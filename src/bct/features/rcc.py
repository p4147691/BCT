from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from bct.core.models import (
    ConfirmedFailure,
    FeatureRequest,
    FeatureResult,
    Outcome,
    PreconditionError,
    UnknownEffectError,
    Work,
)
from bct.integrations.rcc import (
    NamedPipeRelayClient,
    RelayClient,
    RelayEffectUnknown,
    RelayUnavailable,
    validate_instance_id,
)


_READ_COMMANDS = {"state", "presence", "result", "result-of-create-and-send"}
_RECONCILE_COMMANDS = {
    "reconcile-send-to-created-tab", "reconcile-create-and-send",
}
_MUTATING_COMMANDS = {
    "create-chat-tab", "create-chat-window", "send-to-created-tab", "move-tab",
    "rename-conversation", "reload-extension", "send", "create-and-send",
}
_COMMANDS = _READ_COMMANDS | _MUTATING_COMMANDS | _RECONCILE_COMMANDS
_COMMON = {"command", "instance_id", "timeout_s"}
_SENSITIVE_KEYS = {"token", "secret", "password", "authorization"}
_BOOTSTRAP_RESULT_READBACK_TIMEOUT_S = 15.0


def _positive_int(value: object, code: str) -> int:
    if isinstance(value, bool):
        raise PreconditionError(code)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PreconditionError(code) from exc
    if parsed <= 0:
        raise PreconditionError(code)
    return parsed


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _readback_request_id(operation_id: str) -> str:
    digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:16]
    return operation_id[:55] + ".rb." + digest


def _exact_bootstrap_terminal_success(
    result: dict[str, Any], *, operation_id: str, values: dict[str, Any]
) -> bool:
    receipt = result.get("result") if isinstance(result.get("result"), dict) else {}
    try:
        fingerprint = json.loads(str(receipt.get("fingerprint") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    extra = values["extra"]
    expected = [
        extra.get("createOperationId"), values["instance_id"], extra.get("sessionId"),
        extra.get("tabId"), extra.get("windowId"), values["text"],
    ]
    return (
        result.get("ok") is True
        and str(result.get("relayId") or "") == operation_id
        and result.get("found") is True
        and result.get("completed") is True
        and result.get("pending") is False
        and str(receipt.get("id") or "") == operation_id
        and receipt.get("ok") is True
        and receipt.get("ambiguous") is False
        and str(receipt.get("resultState") or "") == "RESULT_PERSISTED"
        and bool(str(receipt.get("conversationKey") or "").strip())
        and bool(str(receipt.get("resultHash") or "").strip())
        and bool(str(receipt.get("reply") or "").strip())
        and fingerprint == expected
        and int(receipt.get("tabId") or 0) == int(extra.get("tabId") or 0)
    )


class RelayBrowserFeature:
    capability = "relay_browser"

    def __init__(
        self, client: RelayClient | None = None,
        *, result_readback_timeout_s: float = _BOOTSTRAP_RESULT_READBACK_TIMEOUT_S,
    ):
        self.client = client or NamedPipeRelayClient()
        self.result_readback_timeout_s = result_readback_timeout_s

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        command = str(arguments.get("command") or "").strip().lower()
        if command not in _COMMANDS:
            raise PreconditionError("RCC_COMMAND_NOT_ALLOWED")
        try:
            instance_id = validate_instance_id(arguments.get("instance_id"))
        except ValueError as exc:
            raise PreconditionError(str(exc)) from exc
        try:
            timeout_s = float(arguments.get("timeout_s", 30.0))
        except (TypeError, ValueError) as exc:
            raise PreconditionError("RCC_TIMEOUT_INVALID") from exc
        if not 0.1 <= timeout_s <= 360.0:
            raise PreconditionError("RCC_TIMEOUT_INVALID")

        allowed = set(_COMMON)
        prepared: dict[str, Any] = {
            "command": command, "instance_id": instance_id,
            "timeout_s": timeout_s, "to": "", "text": "", "extra": {},
        }
        if command in {"result", "result-of-create-and-send"} or command in _RECONCILE_COMMANDS:
            allowed.add("relay_id")
            relay_id = str(arguments.get("relay_id") or "").strip()
            if not relay_id or len(relay_id) > 80:
                raise PreconditionError("RCC_RESULT_OPERATION_ID_REQUIRED")
            prepared["text"] = relay_id
        elif command in _READ_COMMANDS:
            pass
        elif command in {"create-chat-window", "reload-extension"}:
            pass
        elif command == "create-and-send":
            allowed.update({"mode", "text", "window_id"})
            mode = str(arguments.get("mode") or "").strip().lower()
            message = str(arguments.get("text") or "")
            if mode not in {"tab", "window"} or not message:
                raise PreconditionError("RCC_COMPOSE_MODE_OR_TEXT_REQUIRED")
            if mode == "window" and arguments.get("window_id") is not None:
                raise PreconditionError("RCC_COMPOSE_WINDOW_ID_FORBIDDEN")
            prepared["text"] = message
            prepared["extra"]["mode"] = mode
            if arguments.get("window_id") is not None:
                prepared["extra"]["windowId"] = _positive_int(
                    arguments["window_id"], "RCC_WINDOW_ID_INVALID")
        elif command == "create-chat-tab":
            allowed.add("window_id")
            if arguments.get("window_id") is not None:
                prepared["extra"]["windowId"] = _positive_int(
                    arguments["window_id"], "RCC_WINDOW_ID_INVALID"
                )
        elif command == "send":
            allowed.update({"to", "text"})
            prepared["to"] = str(arguments.get("to") or "").strip()
            prepared["text"] = str(arguments.get("text") or "")
            if not prepared["to"] or not prepared["text"]:
                raise PreconditionError("RCC_SEND_TARGET_AND_TEXT_REQUIRED")
        elif command == "send-to-created-tab":
            allowed.update({
                "session_id", "tab_id", "window_id", "create_operation_id", "text",
            })
            session_id = str(arguments.get("session_id") or "").strip()
            create_id = str(arguments.get("create_operation_id") or "").strip()
            text = str(arguments.get("text") or "")
            if not session_id or not create_id or not text:
                raise PreconditionError("RCC_BOOTSTRAP_IDENTITY_REQUIRED")
            prepared["text"] = text
            prepared["extra"].update({
                "instanceId": instance_id, "sessionId": session_id,
                "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                "windowId": _positive_int(arguments.get("window_id"), "RCC_WINDOW_ID_INVALID"),
                "createOperationId": create_id,
            })
        elif command == "move-tab":
            allowed.update({
                "session_id", "tab_id", "window_id", "index",
                "conversation_key", "create_operation_id",
            })
            session_id = str(arguments.get("session_id") or "").strip()
            conversation_key = str(arguments.get("conversation_key") or "").strip()
            create_id = str(arguments.get("create_operation_id") or "").strip()
            try:
                index = int(arguments.get("index"))
            except (TypeError, ValueError) as exc:
                raise PreconditionError("RCC_TAB_INDEX_INVALID") from exc
            if not session_id or index < -1 or not (conversation_key or create_id):
                raise PreconditionError("RCC_MOVE_IDENTITY_REQUIRED")
            prepared["extra"].update({
                "instanceId": instance_id, "sessionId": session_id,
                "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                "windowId": _positive_int(arguments.get("window_id"), "RCC_WINDOW_ID_INVALID"),
                "index": index, "conversationKey": conversation_key,
                "createOperationId": create_id,
            })
        elif command == "rename-conversation":
            allowed.update({"session_id", "tab_id", "conversation_key", "title"})
            session_id = str(arguments.get("session_id") or "").strip()
            conversation_key = str(arguments.get("conversation_key") or "").strip()
            title = str(arguments.get("title") or "").strip()
            if not session_id or not conversation_key or not title or len(title) > 100:
                raise PreconditionError("RCC_RENAME_IDENTITY_REQUIRED")
            prepared["extra"].update({
                "sessionId": session_id,
                "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                "conversationKey": conversation_key,
                "title": title,
            })
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("RCC_ARGUMENT_NOT_ALLOWED:" + ",".join(sorted(unknown)))
        resource = "rcc-instance:" + instance_id
        if command in _READ_COMMANDS or command in _RECONCILE_COMMANDS:
            resource += ":read:" + command
        return FeatureRequest(
            self.capability, instance_id, prepared, (resource,),
            {"command": command, "mutating": command in _MUTATING_COMMANDS},
        )

    def _execute_create_and_send(self, request: FeatureRequest) -> FeatureResult:
        """One BCT parent, two separately fenced durable RCC child operations."""
        values = request.arguments
        instance_id, extra = values["instance_id"], values["extra"]
        digest = hashlib.sha256(request.operation_id.encode("utf-8")).hexdigest()[:24]
        create_id, send_id = "bct-compose-c-" + digest, "bct-compose-s-" + digest
        began = time.monotonic()

        def remaining() -> float:
            return max(0.1, float(values["timeout_s"]) - (time.monotonic() - began))

        try:
            created = self.client.request(
                instance_id=instance_id, request_id=create_id,
                command="create-chat-window" if extra["mode"] == "window" else "create-chat-tab",
                extra={"operationId": create_id, "instanceId": instance_id,
                       **({"windowId": extra["windowId"]} if "windowId" in extra else {})},
                timeout_s=remaining())
        except RelayUnavailable as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except RelayEffectUnknown as exc:
            raise UnknownEffectError("RCC_COMPOSE_CREATE_UNKNOWN:" + str(exc)) from exc
        create_ms = round((time.monotonic() - began)*1000,2)
        receipt = created.get("creationReceipt")
        if not isinstance(receipt,dict):
            if created.get("ok") is False and created.get("state") in {
                "NOT_APPLIED","NOT_SENT","FAILED_CONFIRMED",
            }:
                return FeatureResult(Outcome.NOT_APPLIED, {"command":"create-and-send",
                    "create_operation_id":create_id,"phase":"CREATE_NOT_APPLIED"},
                    output={"result":_sanitize(created)})
            raise UnknownEffectError("RCC_COMPOSE_CREATE_RECEIPT_UNVERIFIED")
        try:
            tab = _positive_int(created.get("tabId"),"RCC_COMPOSE_TAB_INVALID")
            window = _positive_int(created.get("windowId"),"RCC_COMPOSE_WINDOW_INVALID")
        except PreconditionError as exc:
            raise UnknownEffectError("RCC_COMPOSE_CREATED_IDENTITY_UNVERIFIED") from exc
        session = str(created.get("sessionId") or "")
        if not (created.get("ok") is True and created.get("created") is True
                and created.get("state") == "PENDING_UNBOUND"
                and created.get("instanceId") == instance_id and session
                and receipt.get("tabId")==tab and receipt.get("windowId")==window
                and receipt.get("instanceId")==instance_id and receipt.get("sessionId")==session
                and receipt.get("bindingState")=="PENDING_UNBOUND"
                and ("windowId" not in extra or extra["windowId"] == window)):
            raise UnknownEffectError("RCC_COMPOSE_CREATED_IDENTITY_UNVERIFIED")
        identity={"instanceId":instance_id,"sessionId":session,"tabId":tab,
                  "windowId":window,"createOperationId":create_id}
        send_at=time.monotonic()
        try:
            send=self.client.request(instance_id=instance_id,request_id=send_id,
                command="send-to-created-tab",text=values["text"],
                extra={"operationId":send_id,**identity},timeout_s=remaining())
        except (RelayUnavailable,RelayEffectUnknown) as exc:
            raise UnknownEffectError("RCC_COMPOSE_SEND_UNKNOWN:"+str(exc)) from exc
        send_ms=round((time.monotonic()-send_at)*1000,2)
        initial_confirmed = (
            send.get("ok") is True
            and send.get("state") in {
                "SUBMITTED", "SUBMITTED_RECOVERED_AFTER_NAVIGATION"}
            and send.get("operationId") == send_id
            and send.get("createOperationId") == create_id
            and send.get("tabId") == tab
            and send.get("windowId") == window)
        if not initial_confirmed and send.get("state") != "SUBMIT_UNKNOWN":
            raise UnknownEffectError("RCC_COMPOSE_SEND_ACK_UNVERIFIED")
        proof_at=time.monotonic()
        deadline=began+float(values["timeout_s"])
        proof={"instance_id":instance_id,"extra":identity,"text":values["text"]}
        recovery_attempted = False
        while time.monotonic()<deadline:
            remaining=deadline-time.monotonic()
            try:
                done=self.client.request(instance_id=instance_id,
                    request_id=_readback_request_id(send_id),
                    command="result",text=send_id,
                    timeout_s=max(0.1,min(2.0,remaining)))
            except (RelayUnavailable,RelayEffectUnknown):
                done={}
            pending_status = done.get("pendingStatus") if isinstance(
                done.get("pendingStatus"), dict) else {}
            if (
                done.get("pending") is True
                and pending_status.get("networkCompletedAt")
                and not recovery_attempted
            ):
                recovery_attempted = True
                try:
                    done = self.client.request(
                        instance_id=instance_id,
                        request_id=_readback_request_id(send_id) + ".recover",
                        command="recover-created-result", text=send_id,
                        timeout_s=max(0.1, min(10.0, deadline-time.monotonic())),
                    )
                except (RelayUnavailable, RelayEffectUnknown):
                    done = {}
            if _exact_bootstrap_terminal_success(done,operation_id=send_id,values=proof):
                return FeatureResult(Outcome.APPLIED,{
                    "command":"create-and-send","create_operation_id":create_id,
                    "send_operation_id":send_id,"instance_id":instance_id,
                    "session_id":session,"tab_id":tab,"window_id":window,
                    "conversation_key":str(done["result"]["conversationKey"]),
                    "host_state":("SUBMITTED" if initial_confirmed else "SUBMIT_UNKNOWN"),
                    "result_state":"RESULT_PERSISTED",
                    "create_ms":create_ms,"send_ms":send_ms,
                    "readback_ms":round((time.monotonic()-proof_at)*1000,2),
                    "total_ms":round((time.monotonic()-began)*1000,2)},
                    output={"creation":_sanitize(created),"submission":_sanitize(send),
                            "result":_sanitize(done)})
            if done.get("found") is True and done.get("completed") is True and done.get("pending") is False:
                raise UnknownEffectError("RCC_COMPOSE_TERMINAL_EVIDENCE_MISMATCH")
            time.sleep(min(0.1,max(0.0,deadline-time.monotonic())))
        raise UnknownEffectError("RCC_COMPOSE_TERMINAL_NOT_CONFIRMED")

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments["command"] == "create-and-send":
            return self._execute_create_and_send(request)
        values = request.arguments
        extra = dict(values["extra"])
        compose_parent_id = ""
        if values["command"] in {
            "result-of-create-and-send", "reconcile-create-and-send",
        }:
            # The coordinator has already authorized the exact parent work,
            # principal and instance; no arbitrary RCC child ID is accepted.
            compose_parent_id = values["text"]
            digest = hashlib.sha256(compose_parent_id.encode("utf-8")).hexdigest()[:24]
            values = dict(values)
            values["text"] = "bct-compose-s-" + digest
        if request.preconditions["mutating"]:
            extra["operationId"] = request.operation_id
            if values["command"] in {"create-chat-window", "create-chat-tab"}:
                extra["instanceId"] = values["instance_id"]
        try:
            host_command = (
                "recover-created-result"
                if values["command"] == "reconcile-create-and-send"
                else "result"
                if values["command"] in
                (_RECONCILE_COMMANDS | {"result-of-create-and-send"})
                else values["command"]
            )
            result = self.client.request(
                instance_id=values["instance_id"], request_id=request.operation_id,
                command=host_command, to=values["to"], text=values["text"],
                extra=extra, timeout_s=values["timeout_s"],
            )
        except RelayUnavailable as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except RelayEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        if values["command"] in _RECONCILE_COMMANDS:
            relay_id = values["text"]
            receipt = result.get("result") if isinstance(result.get("result"), dict) else {}
            try:
                fingerprint = json.loads(str(receipt.get("fingerprint") or ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                fingerprint = None
            expected_create_id = (
                "bct-compose-c-" + hashlib.sha256(
                    compose_parent_id.encode("utf-8")
                ).hexdigest()[:24]
                if compose_parent_id else ""
            )
            bootstrap_fingerprint = (
                isinstance(fingerprint, list)
                and len(fingerprint) == 6
                and bool(str(fingerprint[0] or "").strip())
                and str(fingerprint[1] or "") == values["instance_id"]
                and bool(str(fingerprint[2] or "").strip())
                and isinstance(fingerprint[3], int) and fingerprint[3] > 0
                and isinstance(fingerprint[4], int) and fingerprint[4] > 0
                and bool(str(fingerprint[5] or ""))
                and int(receipt.get("tabId") or 0) == fingerprint[3]
                and (not expected_create_id or fingerprint[0] == expected_create_id)
            )
            submit_state = str(receipt.get("submitState") or "")
            # RCC 1.0.1 persisted this field but did not expose it from the
            # read-only result projection. The coordinator has already proved
            # that the exact original BCT operation ended in SUBMIT_UNKNOWN;
            # all other terminal/bootstrap fences below still apply.
            submit_state_compatible = submit_state in {"", "SUBMIT_UNKNOWN"}
            terminal = (
                result.get("ok") is True
                and str(result.get("relayId") or "") == relay_id
                and result.get("found") is True
                and result.get("completed") is True
                and result.get("pending") is False
                and str(receipt.get("id") or "") == relay_id
                and submit_state_compatible
                and str(receipt.get("resultState") or "") == "RESULT_PERSISTED"
                and bool(str(receipt.get("conversationKey") or "").strip())
                and bootstrap_fingerprint
            )
            if not terminal:
                raise ConfirmedFailure(
                    "RCC_RECONCILIATION_EVIDENCE_INSUFFICIENT",
                    release_claims=True,
                )
            return FeatureResult(
                Outcome.APPLIED,
                {
                    "instance_id": values["instance_id"],
                    "command": values["command"],
                    "reconciled_operation_id": compose_parent_id or relay_id,
                    "terminal_relay_id": relay_id,
                    "result_state": "RESULT_PERSISTED",
                    "submit_state": submit_state or "LEGACY_OMITTED_VERIFIED_BY_ORIGINAL",
                    "pending": False,
                    "conversation_key": str(receipt["conversationKey"]),
                },
                output={"result": _sanitize(result)},
                reconciled_operation_ids=(compose_parent_id or relay_id,),
            )
        raw_state = result.get("state")
        state = str(raw_state or "").upper() if not isinstance(raw_state, dict) else "STATE_RETURNED"
        if values["command"] == "send-to-created-tab" and state == "SUBMIT_UNKNOWN":
            deadline = time.monotonic() + min(
                self.result_readback_timeout_s, float(values["timeout_s"])
            )
            readback_id = _readback_request_id(request.operation_id)
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    terminal = self.client.request(
                        instance_id=values["instance_id"], request_id=readback_id,
                        command="result", text=request.operation_id,
                        timeout_s=max(0.1, min(2.0, remaining)),
                    )
                except (RelayUnavailable, RelayEffectUnknown):
                    terminal = {}
                if _exact_bootstrap_terminal_success(
                    terminal, operation_id=request.operation_id, values=values
                ):
                    receipt = terminal["result"]
                    return FeatureResult(Outcome.APPLIED, {
                        "instance_id": values["instance_id"],
                        "command": values["command"],
                        "host_request_id": request.operation_id,
                        "host_state": "SUBMITTED_CONFIRMED_BY_TERMINAL_RESULT",
                        "conversation_key": str(receipt["conversationKey"]),
                        "result_state": "RESULT_PERSISTED",
                    }, output={"result": _sanitize(terminal)})
                if (
                    terminal.get("found") is True
                    and terminal.get("completed") is True
                    and terminal.get("pending") is False
                ):
                    break
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if result.get("ok") is True:
            return FeatureResult(Outcome.APPLIED, {
                "instance_id": values["instance_id"], "command": values["command"],
                "host_request_id": request.operation_id, "host_state": state or None,
            }, output={"result": _sanitize(result)})
        if state in {"NOT_APPLIED", "NOT_SENT", "FAILED_CONFIRMED"}:
            return FeatureResult(Outcome.NOT_APPLIED, {
                "instance_id": values["instance_id"], "command": values["command"],
                "host_request_id": request.operation_id, "host_state": state,
                "error": str(result.get("error") or "RCC_NOT_APPLIED"),
            })
        raise UnknownEffectError("RCC_HOST_OUTCOME_UNVERIFIED:" + (state or "MISSING"))
