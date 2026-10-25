from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any

from bct.core.delivery_ledger import DeliveryLedger
from bct.relay_settings import utf16_units
from bct.core.delivery_state import DeliveryEvent, DeliveryState
from bct.core.rcc_result import rcc_result_hash
from bct.core.store import Store
from bct.core.models import (
    ConfirmedFailure,
    ConflictError,
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


_READ_COMMANDS = {
    "state", "presence", "result", "result-of-create-and-send", "target-discover",
}
_RECONCILE_COMMANDS = {
    "reconcile-send-to-created-tab", "reconcile-create-and-send",
    "reconcile-send",
    "reconcile-rename-conversation", "reclassify-rename-claim",
}
_RENAME_INSPECTION_COMMAND = "inspect-rename-receipt"
_OPERATOR_QUARANTINE_COMMAND = "quarantine-legacy-rename-claim"
_MUTATING_COMMANDS = {
    "create-chat-tab", "create-chat-window", "send-to-created-tab", "move-tab",
    "rename-conversation", "reload-extension", "send", "send-to-tab", "create-and-send",
    "simple-relay-bind", "simple-relay-send", "simple-relay-return",
    "delivery-start", "delivery-cancel", "delivery-status", "delivery-return",
    "retire-composer-draft", "retire-recovered-execution",
}
_COMMANDS = _READ_COMMANDS | _MUTATING_COMMANDS | _RECONCILE_COMMANDS | {
    _RENAME_INSPECTION_COMMAND, _OPERATOR_QUARANTINE_COMMAND,
    "delivery-manager-status", "delivery-recovery-inspect", "delivery-response-read", "delivery-preview",
}
_COMMON = {"command", "instance_id", "timeout_s"}
_SENSITIVE_KEYS = {"token", "secret", "password", "authorization"}
_BOOTSTRAP_RESULT_READBACK_TIMEOUT_S = 15.0


def _target_snapshot_fingerprint(tabs: list[dict[str, Any]]) -> str:
    """Return a stable fingerprint for the RCC-visible Chrome target topology."""
    identity = sorted(
        (
            int(tab.get("tabId") or 0), int(tab.get("windowId") or 0),
            str(tab.get("conversationKey") or ""),
        )
        for tab in tabs
        if isinstance(tab, dict)
    )
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8")).hexdigest()


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


def _exact_new_chat_terminal_success(
    result: dict[str, Any], *, operation_id: str, instance_id: str
) -> bool:
    receipt = result.get("result") if isinstance(result.get("result"), dict) else {}
    reply = receipt.get("reply")
    text_sha256 = receipt.get("textSha256")
    supplied_hash = receipt.get("resultHash")
    try:
        tab_id = _positive_int(receipt.get("tabId"), "RCC_NEW_CHAT_TAB_INVALID")
        window_id = _positive_int(receipt.get("windowId"), "RCC_NEW_CHAT_WINDOW_INVALID")
    except PreconditionError:
        return False
    if not (
        result.get("ok") is True
        and str(result.get("relayId") or "") == operation_id
        and result.get("found") is True
        and result.get("completed") is True
        and result.get("pending") is False
        and receipt.get("ok") is True
        and receipt.get("command") == "new-chat-send"
        and str(receipt.get("operationId") or "") == operation_id
        and receipt.get("state") == "RESULT_PERSISTED"
        and receipt.get("effectState") == "APPLIED_CONFIRMED"
        and receipt.get("resultState") == "RESULT_PERSISTED"
        and receipt.get("instanceId") == instance_id
        and bool(str(receipt.get("sessionId") or "").strip())
        and bool(str(receipt.get("conversationKey") or "").strip())
        and isinstance(text_sha256, str)
        and re.fullmatch(r"[a-f0-9]{64}", text_sha256) is not None
        and isinstance(reply, str) and bool(reply.strip())
        and isinstance(supplied_hash, str)
        and re.fullmatch(r"[a-f0-9]{64}", supplied_hash) is not None
    ):
        return False
    expected_hash = hashlib.sha256(json.dumps([
        operation_id, instance_id, receipt["sessionId"], tab_id, window_id,
        receipt["conversationKey"], text_sha256, reply,
    ], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return supplied_hash == expected_hash


class RelayBrowserFeature:
    capability = "relay_browser"

    def __init__(
        self, client: RelayClient | None = None,
        store: Store | None = None,
        *, result_readback_timeout_s: float = _BOOTSTRAP_RESULT_READBACK_TIMEOUT_S,
        recovery_retry_interval_s: float = 0.5,
    ):
        self.client = client or NamedPipeRelayClient()
        self.delivery_ledger = DeliveryLedger(store) if store is not None else None
        self.result_readback_timeout_s = result_readback_timeout_s
        self.recovery_retry_interval_s = max(0.01, recovery_retry_interval_s)
        # Target references deliberately live only in this Core process.  A
        # restart is therefore another safe expiry boundary, never a reason to
        # revive a stale numeric Chrome/RCC identifier.
        self._target_refs: dict[str, dict[str, Any]] = {}
        self._target_epochs: dict[tuple[str, str], str] = {}
        self._target_snapshots: dict[tuple[str, str], str] = {}

    def _read_target_state(self, *, instance_id: str, request_id: str) -> tuple[str, list[dict[str, Any]]]:
        """Read and validate the one RCC state snapshot used for a target ref.

        This is intentionally called from ``prepare`` for a mutating command:
        validation happens before Operations reserves the external-effect
        claim, so an expired/wrong transport reference cannot become UNKNOWN.
        """
        try:
            response = self.client.request(
                instance_id=instance_id, request_id=request_id, command="state",
                timeout_s=2.0,
            )
        except (RelayUnavailable, RelayEffectUnknown) as exc:
            raise PreconditionError("RCC_TARGET_REFERENCE_STATE_UNAVAILABLE") from exc
        state = response.get("state") if isinstance(response, dict) else None
        if not (
            isinstance(response, dict) and response.get("ok") is True
            and isinstance(state, dict) and state.get("instanceId") == instance_id
            and isinstance(state.get("sessionId"), str) and state["sessionId"].strip()
            and isinstance(state.get("tabs"), list)
        ):
            raise PreconditionError("RCC_TARGET_REFERENCE_STATE_INVALID")
        tabs = [tab for tab in state["tabs"] if isinstance(tab, dict)]
        return state["sessionId"].strip(), tabs

    def _refresh_target_epoch(
        self, *, instance_id: str, session_id: str, tabs: list[dict[str, Any]]
    ) -> str:
        identity = (instance_id, session_id)
        snapshot = _target_snapshot_fingerprint(tabs)
        if self._target_snapshots.get(identity) != snapshot:
            self._target_snapshots[identity] = snapshot
            self._target_epochs[identity] = secrets.token_urlsafe(18)
        return self._target_epochs[identity]

    def _issue_target_refs(
        self, *, work_id: str, instance_id: str, session_id: str, tabs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        epoch = self._refresh_target_epoch(
            instance_id=instance_id, session_id=session_id, tabs=tabs,
        )
        targets: list[dict[str, Any]] = []
        windows: set[int] = set()
        for tab in tabs:
            try:
                tab_id = _positive_int(tab.get("tabId"), "RCC_TARGET_DISCOVERY_INVALID")
                window_id = _positive_int(tab.get("windowId"), "RCC_TARGET_DISCOVERY_INVALID")
            except PreconditionError:
                continue
            windows.add(window_id)
            token = "rcc-target-v1." + secrets.token_urlsafe(32)
            self._target_refs[token] = {
                "workId": work_id, "instanceId": instance_id, "sessionId": session_id,
                "windowId": window_id, "tabId": tab_id, "epoch": epoch,
            }
            targets.append({
                "target_ref": token, "target_kind": "tab", "tab_id": tab_id,
                "window_id": window_id,
                "conversation_key": str(tab.get("conversationKey") or ""),
            })
        for window_id in sorted(windows):
            token = "rcc-target-v1." + secrets.token_urlsafe(32)
            self._target_refs[token] = {
                "workId": work_id, "instanceId": instance_id, "sessionId": session_id,
                "windowId": window_id, "tabId": None, "epoch": epoch,
            }
            targets.append({
                "target_ref": token, "target_kind": "window", "window_id": window_id,
            })
        return targets

    def _resolve_target_ref(
        self, *, work: Work, instance_id: str, target_ref: object, require_tab: bool
    ) -> dict[str, Any]:
        token = str(target_ref or "").strip()
        if not token:
            raise PreconditionError("RCC_TARGET_REFERENCE_REQUIRED")
        record = self._target_refs.get(token)
        if record is None:
            raise PreconditionError("RCC_TARGET_REFERENCE_UNKNOWN_OR_EXPIRED")
        if record["workId"] != work.work_id or record["instanceId"] != instance_id:
            raise PreconditionError("RCC_TARGET_REFERENCE_BINDING_MISMATCH")
        request_id = "rcc-target-check-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
        session_id, tabs = self._read_target_state(instance_id=instance_id, request_id=request_id)
        if session_id != record["sessionId"]:
            raise PreconditionError("RCC_TARGET_REFERENCE_SESSION_EXPIRED")
        epoch = self._refresh_target_epoch(
            instance_id=instance_id, session_id=session_id, tabs=tabs,
        )
        if epoch != record["epoch"]:
            raise PreconditionError("RCC_TARGET_REFERENCE_EPOCH_EXPIRED")
        if require_tab and record["tabId"] is None:
            raise PreconditionError("RCC_TARGET_REFERENCE_TAB_REQUIRED")
        matching = [
            tab for tab in tabs
            if int(tab.get("windowId") or 0) == record["windowId"]
            and (record["tabId"] is None or int(tab.get("tabId") or 0) == record["tabId"])
        ]
        if not matching:
            raise PreconditionError("RCC_TARGET_REFERENCE_TARGET_EXPIRED")
        return dict(record)

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
        if (command in {"result", "result-of-create-and-send", _RENAME_INSPECTION_COMMAND,
                        _OPERATOR_QUARANTINE_COMMAND}
                or command in _RECONCILE_COMMANDS):
            allowed.add("relay_id")
            relay_id = str(arguments.get("relay_id") or "").strip()
            if not relay_id or len(relay_id) > 80:
                raise PreconditionError("RCC_RESULT_OPERATION_ID_REQUIRED")
            prepared["text"] = relay_id
            if command == "reconcile-send":
                allowed.update({"original_to", "original_text", "original_timeout_s"})
                original_to = arguments.get("original_to")
                original_text = arguments.get("original_text")
                try:
                    original_timeout = float(arguments.get("original_timeout_s"))
                except (ValueError, TypeError):
                    raise PreconditionError("RCC_RECONCILE_SEND_ORIGINAL_TIMEOUT_INVALID") from None
                if (not isinstance(original_to, str) or not original_to.strip()
                        or not isinstance(original_text, str) or not original_text
                        or not 0.1 <= original_timeout <= 360.0):
                    raise PreconditionError("RCC_RECONCILE_SEND_ORIGINAL_INVALID")
                prepared["extra"] = {
                    "originalTo": original_to.strip(),
                    "originalText": original_text,
                    "originalTimeoutS": original_timeout,
                }
            if command == _RENAME_INSPECTION_COMMAND:
                # This is the first, read-only step for historical rename recovery.
                # The receipt is the durable source of the original session and title,
                # so neither may be required before it is read.
                allowed.update({"tab_id", "conversation_key"})
                conversation_key = str(arguments.get("conversation_key") or "").strip()
                if not conversation_key:
                    raise PreconditionError("RCC_RENAME_INSPECTION_IDENTITY_REQUIRED")
                prepared["extra"].update({
                    "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                    "conversationKey": conversation_key,
                })
            if command == _OPERATOR_QUARANTINE_COMMAND:
                # This is an exceptional, audited containment action for a
                # historical receipt that has already been evicted.  It never
                # decides whether the rename applied and never releases the
                # original UNKNOWN claim.
                allowed.update({"session_id", "tab_id", "conversation_key", "title",
                                "original_timeout_s", "operator_justification",
                                "operator_acknowledgement"})
                session_id = str(arguments.get("session_id") or "").strip()
                conversation_key = str(arguments.get("conversation_key") or "").strip()
                title = str(arguments.get("title") or "").strip()
                justification = str(arguments.get("operator_justification") or "").strip()
                acknowledgement = str(arguments.get("operator_acknowledgement") or "").strip()
                if (not session_id or not conversation_key or not title or len(title) > 100
                        or not justification or not acknowledgement or len(justification) > 500
                        or len(acknowledgement) > 200):
                    raise PreconditionError("RCC_RENAME_OPERATOR_QUARANTINE_ACK_REQUIRED")
                prepared["extra"].update({
                    "sessionId": session_id,
                    "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                    "conversationKey": conversation_key,
                    "title": title,
                    "originalTimeoutS": float(arguments.get("original_timeout_s", 30.0)),
                    "operatorJustification": justification,
                    "operatorAcknowledgement": acknowledgement,
                })
            if command in {"reconcile-rename-conversation", "reclassify-rename-claim"}:
                allowed.update({"relay_id", "session_id", "tab_id", "conversation_key", "title", "original_timeout_s"})
                relay_id = str(arguments.get("relay_id") or "").strip()
                session_id = str(arguments.get("session_id") or "").strip()
                conversation_key = str(arguments.get("conversation_key") or "").strip()
                title = str(arguments.get("title") or "").strip()
                if (not relay_id or len(relay_id) > 80 or not session_id or
                        not conversation_key or not title or len(title) > 100):
                    raise PreconditionError("RCC_RENAME_RECONCILE_EXACT_IDENTITY_REQUIRED")
                prepared["text"] = relay_id
                prepared["extra"].update({
                    "sessionId": session_id,
                    "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                    "conversationKey": conversation_key,
                    "title": title,
                    "originalTimeoutS": float(arguments.get("original_timeout_s", 30.0)),
                })
        elif command in _READ_COMMANDS:
            if command == "target-discover":
                prepared["extra"]["workId"] = work.work_id
        elif command in {"create-chat-window", "reload-extension"}:
            pass
        elif command == "create-and-send":
            # A successor may name one exact historical broad RCC claim that
            # it is prepared to retire after a fresh, read-only RCC proof.
            # These references are never sent to RCC and never authorize a
            # retry of the old operation; they only bind the local handoff.
            if any(key in arguments for key in {"window_id", "tab_id", "session_id"}):
                raise PreconditionError("RCC_LEGACY_NUMERIC_TARGET_REJECTED")
            allowed.update({"mode", "text", "target_ref", "predecessor_work_id",
                            "predecessor_operation_id"})
            mode = str(arguments.get("mode") or "").strip().lower()
            message = str(arguments.get("text") or "")
            if mode != "tab" or not message:
                raise PreconditionError("RCC_COMPOSE_MODE_OR_TEXT_REQUIRED")
            if timeout_s < 30.0:
                raise PreconditionError("RCC_NEW_CHAT_TIMEOUT_TOO_SHORT")
            prepared["text"] = message
            prepared["extra"]["mode"] = mode
            target = self._resolve_target_ref(
                work=work, instance_id=instance_id,
                target_ref=arguments.get("target_ref"), require_tab=False,
            )
            prepared["extra"].update({
                "windowId": target["windowId"], "targetRef": str(arguments["target_ref"]),
                "targetEpoch": target["epoch"],
            })
            predecessor_work = str(arguments.get("predecessor_work_id") or "").strip()
            predecessor_operation = str(arguments.get("predecessor_operation_id") or "").strip()
            if bool(predecessor_work) != bool(predecessor_operation):
                raise PreconditionError("RCC_SUCCESSOR_HANDOFF_REFERENCE_REQUIRED")
            if predecessor_work or predecessor_operation:
                if (len(predecessor_work) > 200 or len(predecessor_operation) > 200
                        or any(ch.isspace() for ch in predecessor_work)
                        or any(ch.isspace() for ch in predecessor_operation)):
                    raise PreconditionError("RCC_SUCCESSOR_HANDOFF_REFERENCE_INVALID")
                prepared["extra"]["successorClaimHandoff"] = {
                    "originalWorkId": predecessor_work,
                    "originalOperationId": predecessor_operation,
                }
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
        elif command == "simple-relay-bind":
            allowed.update({"manager_conversation_key", "worker_conversation_key"})
            manager_key = str(arguments.get("manager_conversation_key") or "").strip().lower()
            worker_key = str(arguments.get("worker_conversation_key") or "").strip().lower()
            key_pattern = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if (not re.fullmatch(key_pattern, manager_key) or not re.fullmatch(key_pattern, worker_key)
                    or manager_key == worker_key):
                raise PreconditionError("RCC_SIMPLE_RELAY_BINDING_INVALID")
            prepared["extra"].update({
                "managerConversationKey": manager_key,
                "workerConversationKey": worker_key,
            })
        elif command == "simple-relay-send":
            allowed.update({"from", "text"})
            source = str(arguments.get("from") or "").strip().lower()
            body = str(arguments.get("text") or "")
            if source not in {"manager", "worker"} or not body or len(body) > 12000:
                raise PreconditionError("RCC_SIMPLE_RELAY_SEND_INVALID")
            prepared["text"] = body
            prepared["extra"]["from"] = source
        elif command == "simple-relay-return":
            allowed.add("source_operation_id")
            source_operation_id = str(arguments.get("source_operation_id") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", source_operation_id):
                raise PreconditionError("RCC_SIMPLE_RELAY_SOURCE_OPERATION_INVALID")
            prepared["extra"]["sourceOperationId"] = source_operation_id
        elif command == "delivery-preview":
            allowed.update({
                "delivery_id", "manager_conversation_key",
                "worker_conversation_key", "text", "scope_id",
                "worker_result_preview",
            })
            delivery_id = str(arguments.get("delivery_id") or "").strip()
            manager_key = str(arguments.get("manager_conversation_key") or "").strip().lower()
            worker_key = str(arguments.get("worker_conversation_key") or "").strip().lower()
            body = str(arguments.get("text") or "")
            scope_id = str(arguments.get("scope_id") or "")
            worker_result_preview = str(arguments.get("worker_result_preview") or "")
            key_pattern = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", delivery_id)
                    or not re.fullmatch(key_pattern, manager_key)
                    or not re.fullmatch(key_pattern, worker_key)
                    or manager_key == worker_key or not body or "\x00" in body
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", scope_id)
                    or not worker_result_preview.strip() or "\x00" in worker_result_preview
                    or utf16_units(worker_result_preview) > 12000):
                raise PreconditionError("RCC_DELIVERY_PREVIEW_INVALID")
            if self.delivery_ledger is None:
                raise PreconditionError("RCC_DELIVERY_COMPOSE_STORE_REQUIRED")
            prepared["text"] = body
            prepared["extra"].update({
                "deliveryId": delivery_id,
                "managerConversationKey": manager_key,
                "workerConversationKey": worker_key,
                "scopeId": scope_id,
                "workerResultPreview": worker_result_preview,
                "workId": work.work_id,
            })
        elif command == "delivery-start":
            allowed.update({
                "delivery_id", "manager_conversation_key",
                "worker_conversation_key", "text", "scope_id",
            })
            delivery_id = str(arguments.get("delivery_id") or "").strip()
            manager_key = str(arguments.get("manager_conversation_key") or "").strip().lower()
            worker_key = str(arguments.get("worker_conversation_key") or "").strip().lower()
            body = str(arguments.get("text") or "")
            key_pattern = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", delivery_id)
                    or not re.fullmatch(key_pattern, manager_key)
                    or not re.fullmatch(key_pattern, worker_key)
                    or manager_key == worker_key or not body or utf16_units(body) > 12000):
                raise PreconditionError("RCC_DELIVERY_START_INVALID")
            original_task = body
            from bct.relay_settings import read_relay_settings
            try:
                delivery_settings = read_relay_settings(
                    str(arguments.get("scope_id") or "")
                )
            except (ValueError, OSError, UnicodeError) as exc:
                raise PreconditionError("RCC_DELIVERY_SETTINGS_INVALID") from exc
            # Opt in to BCT's canonical roster + editable Worker note without
            # changing RCC's native command, return path or Delivery schema.
            # Prepare the exact bytes once BEFORE hashing/fencing the effect.
            if "scope_id" in arguments:
                if self.delivery_ledger is None:
                    raise PreconditionError("RCC_DELIVERY_COMPOSE_STORE_REQUIRED")
                from bct.relay_prompt import compose_worker_delivery
                try:
                    body = compose_worker_delivery(
                        store=self.delivery_ledger.store,
                        scope_id=arguments["scope_id"],
                        manager_conversation_key=manager_key,
                        worker_conversation_key=worker_key,
                        task=body,
                        work_id=work.work_id,
                    )
                except ValueError as exc:
                    raise PreconditionError(str(exc)) from exc
                prepared["extra"]["scopeId"] = arguments["scope_id"]
                prepared["extra"]["originalTask"] = original_task
            prepared["text"] = body
            prepared["extra"].update({
                "deliveryId": delivery_id,
                "managerConversationKey": manager_key,
                "workerConversationKey": worker_key,
                "requestSha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "workId": work.work_id,
                "targetBusyPolicy": delivery_settings["target_busy_policy"],
                "continuationMode": delivery_settings["continuation_mode"],
                "composerWakeMode": delivery_settings["composer_wake_mode"],
                "sendButtonWaitMs": delivery_settings["send_button_wait_ms"],
                "deliverySettingsSha256": delivery_settings["config_sha256"],
            })
        elif command in {"delivery-cancel", "delivery-status", "delivery-return", "delivery-manager-status",
                        "delivery-recovery-inspect"}:
            allowed.add("delivery_id")
            delivery_id = str(arguments.get("delivery_id") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", delivery_id):
                raise PreconditionError("RCC_DELIVERY_ID_INVALID")
            prepared["extra"].update({
                "deliveryId": delivery_id,
                "workId": work.work_id,
            })
        elif command == "retire-composer-draft":
            allowed.update({
                "conversation_key", "expected_draft_sha256", "resume_delivery_id",
                "superseded_work_id", "superseded_delivery_id",
            })
            conversation_key = str(arguments.get("conversation_key") or "").strip().lower()
            expected_sha = str(arguments.get("expected_draft_sha256") or "").strip().lower()
            resume_delivery_id = str(arguments.get("resume_delivery_id") or "").strip()
            superseded_work_id = str(arguments.get("superseded_work_id") or "").strip()
            superseded_delivery_id = str(arguments.get("superseded_delivery_id") or "").strip()
            key_pattern = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if (not re.fullmatch(key_pattern, conversation_key)
                    or not re.fullmatch(r"[a-f0-9]{64}", expected_sha)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", resume_delivery_id)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", superseded_work_id)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", superseded_delivery_id)):
                raise PreconditionError("RCC_DRAFT_RETIRE_ARGUMENT_INVALID")
            if self.delivery_ledger is None:
                raise PreconditionError("RCC_DELIVERY_LEDGER_UNAVAILABLE")
            try:
                superseded_work = self.delivery_ledger.store.get_work(superseded_work_id)
                superseded = self.delivery_ledger.get_for_work(
                    delivery_id=superseded_delivery_id, work_id=superseded_work_id,
                )
            except (KeyError, ConflictError) as exc:
                raise PreconditionError("RCC_DRAFT_RETIRE_SUPERSEDED_NOT_FOUND") from exc
            if (superseded_work.owner_principal_id != work.owner_principal_id
                    or superseded["state"] != DeliveryState.NEEDS_REVIEW.value
                    or superseded["worker_conversation_key"] != conversation_key
                    or superseded["request_sha256"] != expected_sha):
                raise PreconditionError("RCC_DRAFT_RETIRE_SUPERSEDED_IDENTITY_INVALID")
            prepared["extra"].update({
                "conversationKey": conversation_key,
                "expectedDraftSha256": expected_sha,
                "resumeDeliveryId": resume_delivery_id,
                "supersededWorkId": superseded_work_id,
                "supersededDeliveryId": superseded_delivery_id,
                "workId": work.work_id,
            })
        elif command == "retire-recovered-execution":
            allowed.update({
                "conversation_key", "delivery_id", "expected_request_sha256",
                "expected_response_sha256", "expected_response_length",
            })
            conversation_key = str(arguments.get("conversation_key") or "").strip().lower()
            delivery_id = str(arguments.get("delivery_id") or "").strip()
            request_sha = str(arguments.get("expected_request_sha256") or "").strip().lower()
            response_sha = str(arguments.get("expected_response_sha256") or "").strip().lower()
            try:
                response_length = int(arguments.get("expected_response_length"))
            except (TypeError, ValueError) as exc:
                raise PreconditionError("RCC_RECOVERED_RETIRE_ARGUMENT_INVALID") from exc
            key_pattern = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if (not re.fullmatch(key_pattern, conversation_key)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", delivery_id)
                    or not re.fullmatch(r"[a-f0-9]{64}", request_sha)
                    or not re.fullmatch(r"[a-f0-9]{64}", response_sha)
                    or response_length <= 0):
                raise PreconditionError("RCC_RECOVERED_RETIRE_ARGUMENT_INVALID")
            if self.delivery_ledger is None:
                raise PreconditionError("RCC_DELIVERY_LEDGER_UNAVAILABLE")
            try:
                recovered = self.delivery_ledger.get_for_work(
                    delivery_id=delivery_id, work_id=work.work_id,
                )
            except (KeyError, ConflictError) as exc:
                raise PreconditionError("RCC_RECOVERED_RETIRE_DELIVERY_NOT_FOUND") from exc
            if (recovered["state"] != DeliveryState.NEEDS_REVIEW.value
                    or recovered["worker_conversation_key"] != conversation_key
                    or recovered["request_sha256"] != request_sha):
                raise PreconditionError("RCC_RECOVERED_RETIRE_IDENTITY_INVALID")
            prepared["extra"].update({
                "conversationKey": conversation_key, "deliveryId": delivery_id,
                "expectedRequestSha256": request_sha,
                "expectedResponseSha256": response_sha,
                "expectedResponseLength": response_length, "workId": work.work_id,
            })
        elif command == "send-to-tab":
            allowed.update({"session_id", "tab_id", "window_id", "conversation_key", "text"})
            session = str(arguments.get("session_id") or "").strip()
            key = str(arguments.get("conversation_key") or "").strip().lower()
            body = str(arguments.get("text") or "")
            if not session or not re.fullmatch(r"[a-f0-9]{32}", session):
                raise PreconditionError("RCC_DIRECT_TAB_SESSION_ID_REQUIRED")
            if (key and not re.fullmatch(
                    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", key)):
                raise PreconditionError("RCC_DIRECT_TAB_CONVERSATION_KEY_INVALID")
            if not body or len(body) > 12000:
                raise PreconditionError("RCC_DIRECT_TAB_TEXT_INVALID")
            prepared["text"] = body
            prepared["extra"].update({
                "sessionId": session, "workId": work.work_id,
                "tabId": _positive_int(arguments.get("tab_id"), "RCC_TAB_ID_INVALID"),
                "windowId": _positive_int(arguments.get("window_id"), "RCC_WINDOW_ID_INVALID"),
                "conversationKey": key, "instanceId": instance_id,
            })
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
        if command == "reload-extension":
            # Reload is maintenance for the already-running RCC identity, not
            # another browser/message effect.  Keep it mutually exclusive with
            # live RCC-wide execution in Store, while allowing immutable
            # FINISHED/UNKNOWN effect history to remain recorded.
            resource += ":maintenance:reload-extension"
        elif command == "send-to-tab":
            resource += ":direct-tab:" + str(prepared["extra"]["tabId"])
        elif command == "simple-relay-bind":
            resource += ":simple-relay:binding"
        elif command == "simple-relay-send":
            resource += ":simple-relay:" + str(prepared["extra"]["from"])
        elif command == "simple-relay-return":
            resource += ":simple-relay:return:" + str(prepared["extra"]["sourceOperationId"])
        elif command in {"delivery-start", "delivery-cancel", "delivery-status", "delivery-return",
                         "delivery-manager-status"}:
            resource += ":delivery:" + str(prepared["extra"]["deliveryId"])
        elif command == "retire-composer-draft":
            resource += ":composer-draft:" + prepared["extra"]["conversationKey"]
        elif command == "retire-recovered-execution":
            resource += ":recovered-execution:" + prepared["extra"]["deliveryId"]
        if command == "rename-conversation":
            # Cosmetic effects must not claim the entire RCC instance.
            resource += ":rename:" + str(prepared["extra"]["tabId"]) + ":" + str(
                prepared["extra"]["conversationKey"])
        elif (command in _READ_COMMANDS or command in {"delivery-preview", "delivery-response-read"}
              or command in _RECONCILE_COMMANDS
              or command in {_RENAME_INSPECTION_COMMAND, _OPERATOR_QUARANTINE_COMMAND}):
            resource += ":read:" + command
        return FeatureRequest(
            self.capability, instance_id, prepared, (resource,),
            {"command": command, "mutating": command in _MUTATING_COMMANDS},
        )

    def _execute_delivery(self, request: FeatureRequest) -> FeatureResult:
        if self.delivery_ledger is None:
            raise ConfirmedFailure("RCC_DELIVERY_LEDGER_UNAVAILABLE", release_claims=True)
        values = request.arguments
        command = values["command"]
        extra = dict(values["extra"])
        delivery_id = extra["deliveryId"]
        work_id = extra["workId"]

        if command == "delivery-start":
            try:
                _created, delivery = self.delivery_ledger.create_or_get(
                    delivery_id=delivery_id,
                    work_id=work_id,
                    instance_id=values["instance_id"],
                    manager_conversation_key=extra["managerConversationKey"],
                    worker_conversation_key=extra["workerConversationKey"],
                    request_sha256=extra["requestSha256"],
                    scope_id=str(extra.get("scopeId") or ""),
                    original_task=str(extra.get("originalTask") or ""),
                    continuation_mode=str(extra.get("continuationMode") or "manual"),
                )
            except ConflictError as exc:
                if str(exc) != "DELIVERY_ID_REUSE_MISMATCH":
                    raise
                # The immutable ledger identity is checked before the RCC
                # client is called.  A mismatched reuse is therefore a proven
                # pre-dispatch rejection, not an UNKNOWN browser effect.
                raise ConfirmedFailure(
                    "DELIVERY_ID_REUSE_MISMATCH", release_claims=True,
                ) from exc
            if delivery["state"] != DeliveryState.NOT_SENT.value:
                replay_outcome = {
                    DeliveryState.RETURNED.value: Outcome.APPLIED,
                    DeliveryState.NOT_APPLIED.value: Outcome.NOT_APPLIED,
                    DeliveryState.FAILED.value: Outcome.FAILED,
                    DeliveryState.NEEDS_REVIEW.value: Outcome.UNKNOWN,
                }.get(delivery["state"], Outcome.APPLIED)
                return FeatureResult(replay_outcome, {
                    "command": command, "delivery_id": delivery_id,
                    "delivery_state": delivery["state"], "replayed": True,
                }, release_claims=True, output={"delivery": delivery})
        else:
            try:
                delivery = self.delivery_ledger.get_for_work(
                    delivery_id=delivery_id, work_id=work_id,
                )
            except ConflictError as exc:
                raise ConfirmedFailure(
                    "RCC_DELIVERY_ACCESS_DENIED", release_claims=True,
                ) from exc
            except KeyError as exc:
                # Status/cancel/return requests for an ID that was never
                # recorded cannot have produced a browser-side effect.  Keep
                # this a confirmed pre-dispatch failure so the operation does
                # not become UNKNOWN or retain an unnecessary resource claim.
                raise ConfirmedFailure(
                    "RCC_DELIVERY_NOT_FOUND", release_claims=True,
                ) from exc
            if delivery["instance_id"] != values["instance_id"]:
                raise ConfirmedFailure("RCC_DELIVERY_INSTANCE_MISMATCH", release_claims=True)
            extra.update({
                "managerConversationKey": delivery["manager_conversation_key"],
                "workerConversationKey": delivery["worker_conversation_key"],
                "requestSha256": delivery["request_sha256"],
            })
            if command not in {"delivery-cancel", "delivery-manager-status", "delivery-recovery-inspect", "delivery-response-read"} and delivery["state"] in {
                DeliveryState.RETURNED.value, DeliveryState.NOT_APPLIED.value,
                DeliveryState.FAILED.value, DeliveryState.NEEDS_REVIEW.value,
            }:
                replay_outcome = {
                    DeliveryState.RETURNED.value: Outcome.APPLIED,
                    DeliveryState.NOT_APPLIED.value: Outcome.NOT_APPLIED,
                    DeliveryState.FAILED.value: Outcome.FAILED,
                    DeliveryState.NEEDS_REVIEW.value: Outcome.UNKNOWN,
                }[delivery["state"]]
                return FeatureResult(replay_outcome, {
                    "command": command, "delivery_id": delivery_id,
                    "delivery_state": delivery["state"], "replayed": True,
                }, release_claims=True, output={"delivery": delivery})
            if command == "delivery-recovery-inspect" and delivery["state"] != DeliveryState.NEEDS_REVIEW.value:
                raise ConfirmedFailure(
                    "RCC_DELIVERY_RECOVERY_NOT_UNKNOWN", release_claims=True
                )
            if (command == "delivery-manager-status"
                    and delivery["state"] not in {
                        DeliveryState.RETURNED.value,
                        DeliveryState.NEEDS_REVIEW.value,
                    }):
                return FeatureResult(Outcome.APPLIED, {
                    "command": command, "delivery_id": delivery_id,
                    "delivery_state": delivery["state"], "pending": True,
                }, release_claims=True, output={"delivery": delivery})
            if (command == "delivery-manager-status"
                    and delivery["state"] == DeliveryState.RETURNED.value):
                cached = delivery["observation"]
                cached_body = cached.get("manager_response_text")
                cached_digest = cached.get("manager_response_sha256")
                cached_length = cached.get("manager_response_length")
                if (isinstance(cached_body, str) and cached_body
                        and isinstance(cached_digest, str)
                        and hashlib.sha256(cached_body.encode("utf-8")).hexdigest()
                            == cached_digest
                        and cached_length == utf16_units(cached_body)):
                    result = {
                        "ok": True, "pending": False,
                        "deliveryId": delivery_id, "state": delivery["state"],
                        "managerResponseText": cached_body,
                        "managerResponseSha256": cached_digest,
                        "managerResponseLength": cached_length,
                    }
                    return FeatureResult(Outcome.APPLIED, {
                        "command": command, "delivery_id": delivery_id,
                        "delivery_state": delivery["state"], "pending": False,
                        "manager_reply_sha256": cached_digest,
                        "durable_replay": True,
                    }, release_claims=True,
                        output={"delivery": delivery, "result": result})
            if (command == "delivery-cancel"
                    and delivery["state"] not in {
                        DeliveryState.WAITING_TARGET.value,
                        DeliveryState.NOT_APPLIED.value,
                    }):
                raise ConfirmedFailure(
                    "RCC_DELIVERY_CANCEL_STATE_INVALID", release_claims=True,
                )
            if (command == "delivery-status"
                    and delivery["state"] not in {
                        DeliveryState.WAITING_TARGET.value,
                        DeliveryState.SENT_WAITING.value,
                    }):
                raise ConfirmedFailure(
                    "RCC_DELIVERY_STATUS_STATE_INVALID", release_claims=True,
                )
            if (command == "delivery-return"
                    and delivery["state"] != DeliveryState.REPLY_CAPTURED.value):
                raise ConfirmedFailure(
                    "RCC_DELIVERY_RETURN_STATE_INVALID", release_claims=True,
                )

        if command == "delivery-return" and delivery["observation"].get("scope_id"):
            from bct.relay_prompt import compose_manager_return_frame
            context = delivery["observation"]
            try:
                header, footer, settings_sha = compose_manager_return_frame(
                    store=self.delivery_ledger.store, work_id=work_id,
                    delivery_id=delivery_id,
                    manager_conversation_key=delivery["manager_conversation_key"],
                    worker_conversation_key=delivery["worker_conversation_key"],
                    scope_id=context.get("scope_id") or "",
                    original_task=context.get("original_task") or "",
                    worker_result_sha256=delivery.get("response_sha256") or "",
                )
            except (ValueError, OSError, UnicodeError) as exc:
                raise ConfirmedFailure(
                    "RCC_MANAGER_RETURN_SETTINGS_INVALID", release_claims=True
                ) from exc
            if utf16_units(header) + utf16_units(footer) >= 12000:
                raise ConfirmedFailure(
                    "RCC_MANAGER_RETURN_FRAME_TOO_LARGE", release_claims=True
                )
            extra.update({
                "managerReturnHeader": header,
                "managerReturnFooter": footer,
                "managerReturnSettingsSha256": settings_sha,
            })

        try:
            result = self.client.request(
                instance_id=values["instance_id"],
                request_id=request.operation_id,
                command=command,
                text=values["text"],
                extra=extra,
                timeout_s=values["timeout_s"],
            )
        except RelayUnavailable as exc:
            # The named pipe was never written: no Chrome submission happened.
            # Keep captured Worker text returnable, do not mark a false UNKNOWN.
            if command == "delivery-start":
                unchanged = self.delivery_ledger.observe(
                    delivery_id=delivery_id, work_id=work_id,
                    event=DeliveryEvent.PRE_SUBMIT_REJECTED,
                    observation={"error_code": "RCC_PIPE_PRE_SUBMIT_UNAVAILABLE"},
                )
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id,
                    "delivery_state": unchanged["state"], "not_submitted": True,
                }, release_claims=True, output={"delivery": unchanged})
            if command == "delivery-return":
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id,
                    "delivery_state": delivery["state"], "not_submitted": True,
                }, release_claims=True, output={"delivery": delivery})
            if command == "delivery-response-read":
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id, "code": "UNAVAILABLE",
                }, release_claims=True, output={"code": "UNAVAILABLE", "delivery_id": delivery_id})
            if command in {"delivery-cancel", "delivery-status", "delivery-manager-status", "delivery-recovery-inspect"}:
                raise ConfirmedFailure(
                    ("RCC_DELIVERY_MANAGER_STATUS_UNAVAILABLE"
                     if command == "delivery-manager-status"
                     else "RCC_DELIVERY_STATUS_UNAVAILABLE"), release_claims=True,
                ) from exc
            raise UnknownEffectError(
                "RCC_DELIVERY_TRANSPORT_UNKNOWN", release_claims=True,
            ) from exc
        except RelayEffectUnknown as exc:
            if command in {"delivery-start", "delivery-return"}:
                self.delivery_ledger.observe(
                    delivery_id=delivery_id, work_id=work_id,
                    event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
                    observation={"error_code": "RCC_DELIVERY_EFFECT_UNKNOWN"},
                )
            if command == "delivery-response-read":
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id, "code": "UNAVAILABLE",
                }, release_claims=True, output={"code": "UNAVAILABLE", "delivery_id": delivery_id})
            if command in {"delivery-cancel", "delivery-status", "delivery-manager-status", "delivery-recovery-inspect"}:
                raise ConfirmedFailure(
                    ("RCC_DELIVERY_MANAGER_STATUS_UNAVAILABLE"
                     if command == "delivery-manager-status"
                     else "RCC_DELIVERY_STATUS_UNAVAILABLE"), release_claims=True,
                ) from exc
            raise UnknownEffectError(
                "RCC_DELIVERY_EFFECT_UNKNOWN", release_claims=True,
            ) from exc

        if result.get("deliveryId") != delivery_id:
            if command == "delivery-response-read":
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id, "code": "UNAVAILABLE",
                }, release_claims=True, output={"code": "UNAVAILABLE", "delivery_id": delivery_id})
            if command in {"delivery-start", "delivery-return"}:
                self.delivery_ledger.observe(
                    delivery_id=delivery_id, work_id=work_id,
                    event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
                    observation={"error_code": "RCC_DELIVERY_ACK_ID_MISMATCH"},
                )
            if command == "delivery-response-read":
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id, "code": "UNAVAILABLE",
                }, release_claims=True, output={"code": "UNAVAILABLE", "delivery_id": delivery_id})
            if command in {"delivery-cancel", "delivery-status", "delivery-manager-status", "delivery-recovery-inspect"}:
                raise ConfirmedFailure(
                    "RCC_DELIVERY_READ_ID_MISMATCH", release_claims=True,
                )
            raise UnknownEffectError(
                "RCC_DELIVERY_ACK_ID_MISMATCH", release_claims=True,
            )

        state = str(result.get("state") or "")
        if command == "delivery-response-read":
            if result.get("ok") is not True:
                code = str(result.get("code") or "UNAVAILABLE")
                if code not in {"NOT_FOUND", "NOT_RETAINED", "UNAVAILABLE",
                                "ACCESS_DENIED", "INTEGRITY_MISMATCH"}:
                    code = "UNAVAILABLE"
                return FeatureResult(Outcome.NOT_APPLIED, {
                    "command": command, "delivery_id": delivery_id, "code": code,
                }, release_claims=True, output={"code": code, "delivery_id": delivery_id})
            body = result.get("responseText")
            digest = result.get("responseSha256")
            length = result.get("responseLength")
            if (not isinstance(body, str) or not body
                    or len(body.encode("utf-16-le", errors="surrogatepass")) // 2 != length
                    or hashlib.sha256(body.encode("utf-8")).hexdigest() != digest):
                raise ConfirmedFailure("RCC_DELIVERY_READ_INTEGRITY_INVALID", release_claims=True)
            if (digest != delivery["response_sha256"] or length != delivery["response_length"]):
                raise ConfirmedFailure("RCC_DELIVERY_READ_LEDGER_MISMATCH", release_claims=True)
            return FeatureResult(Outcome.APPLIED, {
                "command": command, "delivery_id": delivery_id,
                "response_sha256": digest, "response_length": length,
                "ledger_match": True,
            }, release_claims=True, output={
                "delivery_id": delivery_id, "responseText": body,
                "responseSha256": digest, "responseLength": length, "ledgerMatch": True,
            })
        if command == "delivery-recovery-inspect":
            response = result.get("responseText")
            digest = result.get("responseSha256")
            length = result.get("responseLength")
            turn_key = result.get("originalTurnKey")
            if (result.get("ok") is not True
                    or state != DeliveryState.NEEDS_REVIEW.value
                    or result.get("deliveryId") != delivery_id
                    or result.get("managerConversationKey") != delivery["manager_conversation_key"]
                    or result.get("workerConversationKey") != delivery["worker_conversation_key"]
                    or result.get("requestSha256") != delivery["request_sha256"]
                    or result.get("reconciled") is not False
                    or not isinstance(turn_key, str) or not turn_key or len(turn_key) > 256
                    or result.get("recordPhase") not in
                       {"submit-activated", "submitted", "completed"}
                    or not isinstance(response, str) or not response or len(response) > 12000
                    or hashlib.sha256(response.encode("utf-8")).hexdigest() != digest
                    or length != utf16_units(response)
                    or not isinstance(result.get("workerTabId"), int)
                    or not isinstance(result.get("managerTabId"), int)):
                raise ConfirmedFailure(
                    "RCC_DELIVERY_RECOVERY_PROOF_INSUFFICIENT", release_claims=True
                )
            # This exact operation is the independent durable inspection
            # receipt. The original NEEDS_REVIEW delivery is never updated.
            return FeatureResult(Outcome.APPLIED, {
                "command": command, "delivery_id": delivery_id,
                "delivery_state": state, "reconciled": False,
                "request_sha256": delivery["request_sha256"],
                "response_sha256": digest, "response_length": length,
                "original_turn_key": turn_key,
            }, release_claims=True,
                output={"original_delivery": delivery, "proof": _sanitize(result)})
        if command == "delivery-manager-status":
            if state != DeliveryState.RETURNED.value:
                raise ConfirmedFailure(
                    "RCC_DELIVERY_MANAGER_STATE_MISMATCH", release_claims=True,
                )
            if delivery["state"] == DeliveryState.NEEDS_REVIEW.value:
                if result.get("reconciled") is not True:
                    raise ConfirmedFailure(
                        "RCC_DELIVERY_MANAGER_RECONCILIATION_UNPROVEN",
                        release_claims=True,
                    )
                delivery = self.delivery_ledger.observe(
                    delivery_id=delivery_id, work_id=work_id,
                    event=DeliveryEvent.MANAGER_TURN_RECONCILED,
                    observation={
                        "host_state": state,
                        "manager_return_reconciled": True,
                        "manager_tab_id": result.get("managerTabId"),
                        "manager_window_id": result.get("managerWindowId"),
                        "error_code": "",
                    },
                )
            pending = result.get("pending") is True
            if not pending:
                body = result.get("managerResponseText")
                digest = result.get("managerResponseSha256")
                length = result.get("managerResponseLength")
                if (result.get("ok") is not True or not isinstance(body, str)
                        or not body or len(body) > 12000
                        or hashlib.sha256(body.encode("utf-8")).hexdigest() != digest
                        or length != utf16_units(body)):
                    raise ConfirmedFailure(
                        "RCC_DELIVERY_MANAGER_REPLY_INVALID", release_claims=True,
                    )
                delivery = self.delivery_ledger.observe(
                    delivery_id=delivery_id, work_id=work_id,
                    event=DeliveryEvent.MANAGER_TURN_CONFIRMED,
                    observation={
                        "manager_response_text": body,
                        "manager_response_sha256": digest,
                        "manager_response_length": length,
                    },
                )
            return FeatureResult(Outcome.APPLIED, {
                "command": command, "delivery_id": delivery_id,
                "delivery_state": state, "pending": pending,
                "manager_reply_sha256": str(result.get("managerResponseSha256") or ""),
            }, release_claims=True,
                output={"delivery": delivery, "result": _sanitize(result)})
        if command == "delivery-cancel":
            if (result.get("ok") is not True or result.get("cancelled") is not True
                    or state != DeliveryState.NOT_APPLIED.value
                    or result.get("error") != "DELIVERY_CANCELLED_PRE_SUBMIT"):
                raise ConfirmedFailure(
                    "RCC_DELIVERY_CANCEL_PROOF_INVALID", release_claims=True,
                )
            updated = self.delivery_ledger.observe(
                delivery_id=delivery_id, work_id=work_id,
                event=DeliveryEvent.PRE_SUBMIT_REJECTED,
                observation={
                    "host_state": state,
                    "error_code": "DELIVERY_CANCELLED_PRE_SUBMIT",
                    "rcc_session_id": str(result.get("sessionId") or ""),
                },
            )
            return FeatureResult(Outcome.APPLIED, {
                "command": command, "delivery_id": delivery_id,
                "delivery_state": state, "cancelled": True,
            }, release_claims=True,
                output={"delivery": updated, "result": _sanitize(result)})
        observation = {
            "manager_return_sha256": str(result.get("managerReturnSha256") or ""),
            "manager_return_length": result.get("managerReturnLength"),
            "settings_sha256": str(
                result.get("managerReturnSettingsSha256")
                or result.get("deliverySettingsSha256") or ""
            ),
            "rcc_session_id": str(result.get("sessionId") or ""),
            "worker_tab_id": result.get("workerTabId"),
            "worker_window_id": result.get("workerWindowId"),
            "manager_tab_id": result.get("managerTabId"),
            "manager_window_id": result.get("managerWindowId"),
            "host_state": state,
            "error_code": str(result.get("error") or "")[:128],
        }
        event = None
        if state == DeliveryState.WAITING_TARGET.value:
            event = DeliveryEvent.TARGET_QUEUED
        elif state == DeliveryState.SENT_WAITING.value:
            event = DeliveryEvent.WORKER_TURN_CONFIRMED
        elif state == DeliveryState.REPLY_CAPTURED.value:
            event = DeliveryEvent.WORKER_REPLY_CAPTURED
        elif state == DeliveryState.RETURNED.value:
            event = DeliveryEvent.MANAGER_TURN_CONFIRMED
        elif state == DeliveryState.NOT_APPLIED.value:
            event = DeliveryEvent.PRE_SUBMIT_REJECTED
        elif state == DeliveryState.FAILED.value:
            event = DeliveryEvent.WORKER_TURN_FAILED
        elif state == DeliveryState.NEEDS_REVIEW.value:
            event = DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN
        if event is None:
            raise ConfirmedFailure("RCC_DELIVERY_STATE_INVALID", release_claims=True)

        # RCC can resume a queued target from its browser activity event and
        # capture a very fast reply before BCT performs its next read. Preserve
        # the authoritative ordered ledger by recording the proven submission
        # boundary before the captured-reply boundary.
        if (delivery["state"] == DeliveryState.WAITING_TARGET.value
                and state == DeliveryState.REPLY_CAPTURED.value):
            delivery = self.delivery_ledger.observe(
                delivery_id=delivery_id, work_id=work_id,
                event=DeliveryEvent.WORKER_TURN_CONFIRMED,
                observation=observation,
            )

        response_sha256 = str(result.get("responseSha256") or "") or None
        response_length = result.get("responseLength")
        updated = self.delivery_ledger.observe(
            delivery_id=delivery_id, work_id=work_id, event=event,
            response_sha256=response_sha256,
            response_length=response_length if isinstance(response_length, int) else None,
            observation=observation,
        )
        if state == DeliveryState.NOT_APPLIED.value:
            return FeatureResult(Outcome.NOT_APPLIED, {
                "command": command, "delivery_id": delivery_id,
                "delivery_state": state,
            }, output={"delivery": updated, "result": _sanitize(result)})
        if state == DeliveryState.NEEDS_REVIEW.value:
            return FeatureResult(Outcome.UNKNOWN, {
                "command": command, "delivery_id": delivery_id,
                "delivery_state": state,
            }, release_claims=True,
                output={"delivery": updated, "result": _sanitize(result)})
        if result.get("ok") is not True:
            raise ConfirmedFailure("RCC_DELIVERY_RESULT_INVALID", release_claims=True)
        return FeatureResult(Outcome.APPLIED, {
            "command": command, "delivery_id": delivery_id,
            "delivery_state": state,
            "pending": result.get("pending") is True or state in {
                DeliveryState.WAITING_TARGET.value,
                DeliveryState.SENT_WAITING.value,
            },
            "queued": result.get("queued") is True
                      or state == DeliveryState.WAITING_TARGET.value,
        }, output={"delivery": updated, "result": _sanitize(result)})

    def _execute_create_and_send(self, request: FeatureRequest) -> FeatureResult:
        """Execute one durable RCC new-chat product operation.

        RCC owns the tab-create/first-submit/UUID/result state machine. BCT
        sends one operation ID and never exposes or retries its internal
        browser effects as separate legacy commands.
        """
        values = request.arguments
        instance_id, extra = values["instance_id"], values["extra"]
        began = time.monotonic()
        # The Native Host must return terminal evidence before the outer pipe
        # deadline. Keeping a two-second margin avoids converting an RCC
        # terminal timeout into a transport-level UNKNOWN at the same instant.
        response_timeout_ms = max(15000, int((float(values["timeout_s"]) - 2.0) * 1000))
        try:
            result = self.client.request(
                instance_id=instance_id,
                request_id=request.operation_id,
                command="new-chat-send",
                text=values["text"],
                extra={
                    "operationId": request.operation_id,
                    "instanceId": instance_id,
                    "windowId": extra.get("windowId"),
                    "responseTimeoutMs": response_timeout_ms,
                },
                timeout_s=float(values["timeout_s"]),
            )
        except RelayUnavailable as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except RelayEffectUnknown as exc:
            raise UnknownEffectError("RCC_NEW_CHAT_EFFECT_UNKNOWN:" + str(exc)) from exc
        if (result.get("ok") is False and result.get("effectState") == "NOT_APPLIED"):
            return FeatureResult(
                Outcome.NOT_APPLIED,
                {"command": "create-and-send", "phase": "NOT_APPLIED"},
                output={"result": _sanitize(result)},
            )
        try:
            tab = _positive_int(result.get("tabId"), "RCC_COMPOSE_TAB_INVALID")
            window = _positive_int(result.get("windowId"), "RCC_COMPOSE_WINDOW_INVALID")
        except PreconditionError as exc:
            raise UnknownEffectError("RCC_NEW_CHAT_IDENTITY_UNVERIFIED") from exc
        session = str(result.get("sessionId") or "")
        conversation_key = str(result.get("conversationKey") or "")
        if not (
            result.get("ok") is True
            and result.get("command") == "new-chat-send"
            and result.get("operationId") == request.operation_id
            and result.get("state") == "RESULT_PERSISTED"
            and result.get("resultState") == "RESULT_PERSISTED"
            and result.get("instanceId") == instance_id
            and session
            and conversation_key
            and isinstance(result.get("reply"), str)
            and bool(result["reply"].strip())
            and isinstance(result.get("resultHash"), str)
            and re.fullmatch(r"[a-f0-9]{64}", result["resultHash"])
            and ("windowId" not in extra or extra["windowId"] == window)
        ):
            raise UnknownEffectError("RCC_NEW_CHAT_TERMINAL_EVIDENCE_MISMATCH")
        stage_timing = result.get("stageTiming") if isinstance(
            result.get("stageTiming"), dict) else {}
        return FeatureResult(
            Outcome.APPLIED,
            {
                "command": "create-and-send",
                "rcc_command": "new-chat-send",
                "operation_id": request.operation_id,
                "instance_id": instance_id,
                "session_id": session,
                "tab_id": tab,
                "window_id": window,
                "conversation_key": conversation_key,
                "result_state": "RESULT_PERSISTED",
                "result_hash": result["resultHash"],
                "stage_timing": stage_timing,
                "total_ms": round((time.monotonic() - began) * 1000, 2),
            },
            output={"result": _sanitize(result)},
        )

    def _execute_target_discover(self, request: FeatureRequest) -> FeatureResult:
        """Issue opaque target handles from one exact RCC state snapshot.

        This command is read-only.  The numeric Chrome IDs are returned only as
        observation evidence; later mutations receive the opaque handle, not
        those numbers.
        """
        instance_id = request.arguments["instance_id"]
        request_id = "rcc-target-discover-" + hashlib.sha256(
            request.operation_id.encode("utf-8")
        ).hexdigest()[:24]
        session_id, tabs = self._read_target_state(
            instance_id=instance_id, request_id=request_id,
        )
        targets = self._issue_target_refs(
            work_id=request.arguments["extra"]["workId"], instance_id=instance_id,
            session_id=session_id, tabs=tabs,
        )
        if not targets:
            return FeatureResult(Outcome.NOT_APPLIED, {
                "command": "target-discover", "instance_id": instance_id,
                "session_id": session_id, "reason": "RCC_TARGET_DISCOVERY_EMPTY",
            }, output={"targets": []})
        return FeatureResult(Outcome.APPLIED, {
            "command": "target-discover", "instance_id": instance_id,
            "session_id": session_id, "target_count": len(targets),
        }, output={"targets": targets})

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments["command"] == "delivery-preview":
            if self.delivery_ledger is None:
                raise ConfirmedFailure(
                    "RCC_DELIVERY_LEDGER_UNAVAILABLE", release_claims=True
                )
            from bct.relay_prompt import preview_delivery_messages
            values = request.arguments
            extra = values["extra"]
            try:
                preview = preview_delivery_messages(
                    store=self.delivery_ledger.store,
                    work_id=extra["workId"], delivery_id=extra["deliveryId"],
                    scope_id=extra["scopeId"],
                    manager_conversation_key=extra["managerConversationKey"],
                    worker_conversation_key=extra["workerConversationKey"],
                    task=values["text"],
                    worker_result_preview=extra["workerResultPreview"],
                )
            except (ValueError, OSError, UnicodeError) as exc:
                raise ConfirmedFailure(
                    "RCC_DELIVERY_PREVIEW_INVALID", release_claims=True
                ) from exc
            return FeatureResult(
                Outcome.APPLIED,
                {
                    "command": "delivery-preview",
                    "effect": "NONE_PREVIEW_ONLY",
                    "settings_sha256": preview["settings_sha256"],
                },
                release_claims=True,
                output={"preview": preview},
            )
        if request.arguments["command"] in {
            "delivery-start", "delivery-cancel", "delivery-status", "delivery-return",
            "delivery-manager-status", "delivery-recovery-inspect", "delivery-response-read",
        }:
            return self._execute_delivery(request)
        if request.arguments["command"] == "retire-composer-draft":
            values = request.arguments
            extra = dict(values["extra"])
            if self.delivery_ledger is None:
                raise ConfirmedFailure("RCC_DELIVERY_LEDGER_UNAVAILABLE", release_claims=True)
            queued = self.delivery_ledger.get_for_work(
                delivery_id=extra["resumeDeliveryId"], work_id=extra["workId"],
            )
            if (queued["state"] != DeliveryState.WAITING_TARGET.value
                    or queued["worker_conversation_key"] != extra["conversationKey"]):
                raise ConfirmedFailure(
                    "RCC_DRAFT_RETIRE_RESUME_IDENTITY_INVALID", release_claims=True,
                )
            try:
                current_work = self.delivery_ledger.store.get_work(extra["workId"])
                superseded_work = self.delivery_ledger.store.get_work(extra["supersededWorkId"])
                superseded = self.delivery_ledger.get_for_work(
                    delivery_id=extra["supersededDeliveryId"],
                    work_id=extra["supersededWorkId"],
                )
            except (KeyError, ConflictError) as exc:
                raise ConfirmedFailure(
                    "RCC_DRAFT_RETIRE_SUPERSEDED_NOT_FOUND", release_claims=True,
                ) from exc
            if (current_work.owner_principal_id != superseded_work.owner_principal_id
                    or superseded["state"] != DeliveryState.NEEDS_REVIEW.value
                    or superseded["worker_conversation_key"] != extra["conversationKey"]
                    or superseded["request_sha256"] != extra["expectedDraftSha256"]):
                raise ConfirmedFailure(
                    "RCC_DRAFT_RETIRE_SUPERSEDED_IDENTITY_INVALID", release_claims=True,
                )
            try:
                result = self.client.request(
                    instance_id=values["instance_id"], request_id=request.operation_id,
                    command="retire-composer-draft", extra=extra,
                    timeout_s=values["timeout_s"],
                )
            except RelayUnavailable as exc:
                raise ConfirmedFailure(str(exc), release_claims=True) from exc
            except RelayEffectUnknown as exc:
                raise UnknownEffectError("RCC_DRAFT_RETIRE_EFFECT_UNKNOWN") from exc
            resumed = result.get("resumedDelivery") if isinstance(
                result.get("resumedDelivery"), dict) else {}
            if (result.get("ok") is not True or result.get("retired") is not True
                    or result.get("effectState") != "APPLIED"
                    or result.get("conversationKey") != extra["conversationKey"]
                    or result.get("draftSha256") != extra["expectedDraftSha256"]
                    or str(result.get("supersededDeliveryId") or "")
                       != extra["supersededDeliveryId"]
                    or str(result.get("retiredExecutionId") or "")
                       not in {"", extra["supersededDeliveryId"]}
                    or result.get("composerEmpty") is not True
                    or resumed.get("deliveryId") != extra["resumeDeliveryId"]
                    or resumed.get("state") not in {
                        DeliveryState.WAITING_TARGET.value,
                        DeliveryState.SENT_WAITING.value,
                        DeliveryState.REPLY_CAPTURED.value,
                    }):
                if result.get("effectState") == "NOT_APPLIED":
                    return FeatureResult(Outcome.NOT_APPLIED, {
                        "command": "retire-composer-draft",
                        "conversation_key": extra["conversationKey"],
                        "error": str(result.get("error") or "RCC_DRAFT_RETIRE_NOT_APPLIED")[:128],
                    }, release_claims=True, output={"result": _sanitize(result)})
                raise UnknownEffectError("RCC_DRAFT_RETIRE_ACK_UNVERIFIED")
            return FeatureResult(Outcome.APPLIED, {
                "command": "retire-composer-draft",
                "conversation_key": extra["conversationKey"],
                "retired_draft_sha256": extra["expectedDraftSha256"],
                "retired_draft_length": result.get("draftLength"),
                "retired_execution_id": str(result.get("retiredExecutionId") or ""),
                "superseded_delivery_id": extra["supersededDeliveryId"],
                "resumed_delivery_id": extra["resumeDeliveryId"],
                "resumed_delivery_state": resumed["state"],
            }, output={"result": _sanitize(result)})
        if request.arguments["command"] == "retire-recovered-execution":
            values = request.arguments
            extra = dict(values["extra"])
            if self.delivery_ledger is None:
                raise ConfirmedFailure("RCC_DELIVERY_LEDGER_UNAVAILABLE", release_claims=True)
            recovered = self.delivery_ledger.get_for_work(
                delivery_id=extra["deliveryId"], work_id=extra["workId"],
            )
            if (recovered["state"] != DeliveryState.NEEDS_REVIEW.value
                    or recovered["worker_conversation_key"] != extra["conversationKey"]
                    or recovered["request_sha256"] != extra["expectedRequestSha256"]):
                raise ConfirmedFailure(
                    "RCC_RECOVERED_RETIRE_IDENTITY_INVALID", release_claims=True,
                )
            try:
                result = self.client.request(
                    instance_id=values["instance_id"], request_id=request.operation_id,
                    command="retire-recovered-execution", extra=extra,
                    timeout_s=values["timeout_s"],
                )
            except RelayUnavailable as exc:
                raise ConfirmedFailure(str(exc), release_claims=True) from exc
            except RelayEffectUnknown as exc:
                raise UnknownEffectError("RCC_RECOVERED_RETIRE_EFFECT_UNKNOWN") from exc
            if (result.get("ok") is not True or result.get("retired") is not True
                    or result.get("effectState") != "APPLIED"
                    or result.get("deliveryId") != extra["deliveryId"]
                    or result.get("conversationKey") != extra["conversationKey"]
                    or result.get("requestSha256") != extra["expectedRequestSha256"]
                    or result.get("responseSha256") != extra["expectedResponseSha256"]
                    or result.get("responseLength") != extra["expectedResponseLength"]
                    or result.get("executionAbsent") is not True):
                if result.get("effectState") == "NOT_APPLIED":
                    return FeatureResult(Outcome.NOT_APPLIED, {
                        "command": "retire-recovered-execution",
                        "delivery_id": extra["deliveryId"],
                        "error": str(result.get("error") or "RCC_RECOVERED_RETIRE_NOT_APPLIED")[:128],
                    }, release_claims=True, output={"result": _sanitize(result)})
                raise UnknownEffectError("RCC_RECOVERED_RETIRE_ACK_UNVERIFIED")
            return FeatureResult(Outcome.APPLIED, {
                "command": "retire-recovered-execution",
                "delivery_id": extra["deliveryId"],
                "conversation_key": extra["conversationKey"],
                "response_sha256": extra["expectedResponseSha256"],
                "response_length": extra["expectedResponseLength"],
                "execution_absent": True,
            }, output={"result": _sanitize(result)})
        if request.arguments["command"] == "target-discover":
            return self._execute_target_discover(request)
        if request.arguments["command"] == "create-and-send":
            return self._execute_create_and_send(request)
        values = request.arguments
        extra = dict(values["extra"])
        if values["command"] == "reload-extension":
            # The maintenance claim has already been reserved atomically. Do
            # one final read-only runtime check before the reload side effect.
            # Duplicate operation IDs never reach execute, so neither this
            # probe nor the reload is repeated.
            try:
                state_reply = self.client.request(
                    instance_id=values["instance_id"],
                    request_id="rcc-reload-idle-" + hashlib.sha256(
                        request.operation_id.encode("utf-8")
                    ).hexdigest()[:24],
                    command="state",
                    timeout_s=2.0,
                )
            except (RelayUnavailable, RelayEffectUnknown) as exc:
                raise ConfirmedFailure(
                    "RCC_RELOAD_IDLE_PROOF_UNAVAILABLE", release_claims=True
                ) from exc
            observed_state = (
                state_reply.get("state")
                if isinstance(state_reply, dict)
                and isinstance(state_reply.get("state"), dict)
                else {}
            )
            endpoints = observed_state.get("endpoints")
            if (
                state_reply.get("ok") is not True
                or observed_state.get("instanceId") != values["instance_id"]
                or not str(observed_state.get("sessionId") or "").strip()
                or not isinstance(endpoints, list)
            ):
                raise ConfirmedFailure(
                    "RCC_RELOAD_IDLE_PROOF_INVALID", release_claims=True
                )
            # Ordinary ChatGPT streaming is not an RCC submission.  Only an
            # unfinished *exact* Delivery waiting for its Worker/Manager
            # response may turn a generating page into an RCC reload fence.
            # Store's active-operation/maintenance Claim gate independently
            # protects writes crossing their actual execution boundary.
            if self.delivery_ledger is not None:
                generating_keys = {
                    str(endpoint.get("conversationKey") or "").lower()
                    for endpoint in endpoints if isinstance(endpoint, dict)
                    and endpoint.get("generating") is True
                }
                if generating_keys:
                    db = self.delivery_ledger.store._connect()
                    try:
                        live_rows = db.execute(
                            "SELECT state,worker_conversation_key,"
                            "manager_conversation_key FROM relay_deliveries "
                            "WHERE instance_id=? AND state IN "
                            "('SENT_WAITING','REPLY_CAPTURED')",
                            (values["instance_id"],),
                        ).fetchall()
                    finally:
                        db.close()
                    if any(
                        (row["state"] == "SENT_WAITING"
                         and row["worker_conversation_key"] in generating_keys)
                        or (row["state"] == "REPLY_CAPTURED"
                            and row["manager_conversation_key"] in generating_keys)
                        for row in live_rows
                    ):
                        raise ConfirmedFailure(
                            "RCC_RELOAD_ACTIVE_DELIVERY_GENERATING",
                            release_claims=True,
                        )
        if values["command"] == "send":
            # Transport-only option: do not change the persisted request digest.
            # Legacy UNKNOWN sends must retain their exact original fingerprint
            # for read-only receipt reconciliation after this code upgrade.
            extra["returnOnAck"] = True
        compose_parent_id = ""
        if values["command"] in {
            "result-of-create-and-send", "reconcile-create-and-send",
        }:
            # The coordinator has already authorized this exact original
            # operation under the same work, principal, and RCC instance.
            # Query the durable receipt by that original ID.  Re-keying it to
            # a synthetic child ID makes a successfully persisted new-chat
            # receipt permanently unreachable.
            compose_parent_id = values["text"]
        if request.preconditions["mutating"]:
            extra["operationId"] = request.operation_id
            if values["command"] in {"create-chat-window", "create-chat-tab"}:
                extra["instanceId"] = values["instance_id"]
        try:
            host_command = (
                "rename-receipt" if values["command"] in {
                    _RENAME_INSPECTION_COMMAND, "reconcile-rename-conversation",
                    "reclassify-rename-claim", _OPERATOR_QUARANTINE_COMMAND,
                }
                else "result"
                if values["command"] == "reconcile-create-and-send"
                else "result"
                if values["command"] in
                (_RECONCILE_COMMANDS | {"result-of-create-and-send"})
                else values["command"]
            )
            result = self.client.request(
                instance_id=values["instance_id"], request_id=request.operation_id,
                command=host_command, to=values["to"], text=values["text"],
                extra=({} if values["command"] == "reconcile-send" else extra),
                timeout_s=values["timeout_s"],
            )
        except RelayUnavailable as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except RelayEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        if values["command"] == _RENAME_INSPECTION_COMMAND:
            observed = result.get("observed") if isinstance(result.get("observed"), dict) else {}
            if not (
                result.get("ok") is True
                and result.get("relayId") == values["text"]
                and result.get("instanceId") == values["instance_id"]
                and observed.get("tabId") == extra["tabId"]
                and observed.get("conversationKey") == extra["conversationKey"]
            ):
                raise ConfirmedFailure("RCC_RENAME_INSPECTION_IDENTITY_MISMATCH",
                                       release_claims=True)
            return FeatureResult(Outcome.APPLIED, {
                "command": _RENAME_INSPECTION_COMMAND,
                "original_operation_id": values["text"],
                "instance_id": values["instance_id"],
                "tab_id": extra["tabId"],
                "conversation_key": extra["conversationKey"],
                "receipt_found": isinstance(result.get("receipt"), dict),
            }, output={"result": _sanitize(result)})
        if values["command"] == _OPERATOR_QUARANTINE_COMMAND:
            observed = result.get("observed") if isinstance(result.get("observed"), dict) else {}
            # An absent terminal receipt is the point of this containment path.
            # Treat any other receipt state as evidence that canonical
            # reconciliation, rather than operator quarantine, must be used.
            missing_receipt = (
                result.get("receipt") is None and result.get("receiptState") == "MISSING"
            )
            exact_observation = (
                result.get("ok") is True
                and result.get("relayId") == values["text"]
                and result.get("instanceId") == values["instance_id"]
                and observed.get("tabId") == extra["tabId"]
                and observed.get("conversationKey") == extra["conversationKey"]
                and observed.get("presence") == "OPEN"
            )
            if not (missing_receipt and exact_observation):
                raise ConfirmedFailure("RCC_RENAME_OPERATOR_QUARANTINE_EVIDENCE_INSUFFICIENT",
                                       release_claims=True)
            return FeatureResult(Outcome.APPLIED, {
                "command": _OPERATOR_QUARANTINE_COMMAND,
                "audit_kind": "OPERATOR_QUARANTINE_NOT_RECONCILIATION",
                "original_operation_id": values["text"],
                "expected_original_digest": str(
                    request.preconditions.get("original_request_digest") or ""),
                "instance_id": values["instance_id"],
                "new_resource_key": ("rcc-instance:" + values["instance_id"]
                                     + ":rename:" + str(extra["tabId"])
                                     + ":" + extra["conversationKey"]),
                "observed_tab_id": observed["tabId"],
                "observed_conversation_key": observed["conversationKey"],
                "observed_presence": observed["presence"],
                "receipt_state": "MISSING",
                "operator_justification": extra["operatorJustification"],
                "operator_acknowledgement": extra["operatorAcknowledgement"],
            }, output={"result": _sanitize(result)})
        if values["command"] in {"reconcile-rename-conversation", "reclassify-rename-claim"}:
            expected = extra
            observed = result.get("observed") if isinstance(result.get("observed"), dict) else {}
            receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
            expected_fingerprint = json.dumps(
                [expected["conversationKey"], expected["tabId"],
                 expected["sessionId"], expected["title"]],
                separators=(",", ":"), ensure_ascii=False)
            exact_identity = (
                result.get("ok") is True
                and result.get("relayId") == values["text"]
                and result.get("instanceId") == values["instance_id"]
                and observed.get("tabId") == expected["tabId"]
                and observed.get("conversationKey") == expected["conversationKey"]
                and isinstance(observed.get("currentSessionId"), str)
                and bool(observed.get("currentSessionId"))
                and observed.get("presence") == "OPEN"
            )
            applied = (
                exact_identity
                and receipt.get("command") == "rename-conversation"
                and receipt.get("fingerprint") == expected_fingerprint
                and isinstance(receipt.get("result"), dict)
                and receipt["result"].get("ok") is True
                and receipt["result"].get("operationId") == values["text"]
                and receipt["result"].get("savedTitle") == expected["title"]
                and receipt["result"].get("tabId") == expected["tabId"]
                and receipt["result"].get("conversationKey") == expected["conversationKey"]
                and observed.get("title") == expected["title"]
            )
            if (values["command"] == "reclassify-rename-claim" and exact_identity):
                return FeatureResult(Outcome.APPLIED, {
                    "command": "reclassify-rename-claim",
                    "instance_id": values["instance_id"],
                    "original_operation_id": values["text"],
                    "expected_original_digest": str(
                        request.preconditions.get("original_request_digest") or ""),
                    "new_resource_key": ("rcc-instance:" + values["instance_id"]
                                         + ":rename:" + str(expected["tabId"])
                                         + ":" + expected["conversationKey"]),
                    "observed_conversation_key": observed["conversationKey"],
                    "observed_tab_id": observed["tabId"],
                    "observed_title": observed.get("title"),
                    "observed_session_id": observed["currentSessionId"],
                }, output={"result": _sanitize(result)})
            if not applied:
                # Missing evidence or an old title cannot prove the request was never applied.
                raise ConfirmedFailure("RCC_RENAME_RECONCILIATION_EVIDENCE_INSUFFICIENT",
                                       release_claims=True)
            return FeatureResult(
                Outcome.APPLIED,
                {"command": "reconcile-rename-conversation",
                 "instance_id": values["instance_id"],
                 "reconciled_operation_id": values["text"],
                 "tab_id": expected["tabId"], "conversation_key": expected["conversationKey"],
                 "saved_title": expected["title"]},
                output={"result": _sanitize(result)},
                reconciled_operation_ids=(values["text"],),
            )
        if values["command"] == "reconcile-send":
            # Result-only recovery of a generic RCC send whose BCT response was
            # lost. The coordinator has already fenced the exact original
            # request digest, owner, instance and UNKNOWN error BEFORE this read.
            receipt = result.get("result") if isinstance(result.get("result"), dict) else {}
            try:
                fingerprint = json.loads(str(receipt.get("fingerprint") or ""))
                verified_hash = rcc_result_hash(receipt)
            except (ValueError, TypeError, UnicodeError):
                fingerprint, verified_hash = None, ""
            expected_fingerprint = [
                extra["originalTo"], extra["originalText"], False,
                "", "", "", "", "", 0, "", 0,
            ]
            terminal = (
                result.get("ok") is True
                and result.get("relayId") == values["text"]
                and result.get("found") is True
                and result.get("completed") is True
                and result.get("pending") is False
                and receipt.get("id") == values["text"]
                and receipt.get("ok") is True
                and receipt.get("ambiguous") is False
                and receipt.get("resultState") == "RESULT_PERSISTED"
                and receipt.get("submitState") in {
                    "SUBMITTED_CONFIRMED", "SUBMITTED",
                }
                and isinstance(receipt.get("reply"), str)
                and bool(receipt["reply"].strip())
                and fingerprint == expected_fingerprint
                and receipt.get("messageHash") in {
                    "", receipt.get("fingerprint"),
                }
                and isinstance(receipt.get("tabId"), int)
                and not isinstance(receipt.get("tabId"), bool)
                and receipt["tabId"] > 0
                and isinstance(receipt.get("conversationKey"), str)
                and bool(receipt["conversationKey"])
                and isinstance(receipt.get("resultHash"), str)
                and re.fullmatch(r"[a-f0-9]{64}", receipt["resultHash"]) is not None
                and receipt["resultHash"] == verified_hash
            )
            if not terminal:
                raise ConfirmedFailure(
                    "RCC_GENERIC_SEND_RECEIPT_NOT_PROVEN", release_claims=True,
                )
            return FeatureResult(
                Outcome.APPLIED,
                {"command": "reconcile-send",
                 "original_operation_id": values["text"],
                 "instance_id": values["instance_id"],
                 "result_state": "RESULT_PERSISTED",
                 "result_hash": verified_hash,
                 "tab_id": receipt["tabId"],
                 "conversation_key": receipt["conversationKey"],
                 "original_outcome_preserved": "UNKNOWN",
                 "no_resend": True},
                reconciled_operation_ids=(values["text"],),
            )
        if values["command"] == "reconcile-create-and-send":
            relay_id = compose_parent_id or values["text"]
            if not _exact_new_chat_terminal_success(
                result, operation_id=relay_id, instance_id=values["instance_id"]
            ):
                raise ConfirmedFailure(
                    "RCC_NEW_CHAT_RECEIPT_NOT_PROVEN", release_claims=True,
                )
            receipt = result["result"]
            return FeatureResult(
                Outcome.APPLIED,
                {
                    "instance_id": values["instance_id"],
                    "command": "reconcile-create-and-send",
                    "reconciled_operation_id": relay_id,
                    "result_state": "RESULT_PERSISTED",
                    "result_hash": receipt["resultHash"],
                    "text_sha256": receipt["textSha256"],
                    "tab_id": receipt["tabId"],
                    "window_id": receipt["windowId"],
                    "conversation_key": receipt["conversationKey"],
                    "original_outcome_preserved": "UNKNOWN",
                    "no_resend": True,
                },
                output={"result": _sanitize(result)},
                reconciled_operation_ids=(relay_id,),
            )
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
        # RCC native send failures use effectState, not state. Missing this field
        # erased the original failure (MISSING) and quarantined proven pre-submit
        # NOT_APPLIED failures as UNKNOWN. Never infer NOT_APPLIED from a draft.
        effect_state = str(result.get("effectState") or "").upper()
        if values["command"] == "send" and effect_state:
            state = effect_state
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
        if values["command"] == "send-to-tab" and result.get("ok") is True:
            correct = (
                str(result.get("operationId") or "") == request.operation_id
                and result.get("instanceId") == values["instance_id"]
                and result.get("sessionId") == extra["sessionId"]
                and result.get("tabId") == extra["tabId"]
                and result.get("windowId") == extra["windowId"]
                and result.get("state") == "SUBMITTED"
                and result.get("submitted") is True
            )
            if not correct:
                raise UnknownEffectError("RCC_DIRECT_TAB_ACK_UNVERIFIED")
        if values["command"] == "simple-relay-bind" and result.get("ok") is True:
            binding = result.get("binding") if isinstance(result.get("binding"), dict) else {}
            if not (
                binding.get("managerConversationKey") == extra["managerConversationKey"]
                and binding.get("workerConversationKey") == extra["workerConversationKey"]
            ):
                raise ConfirmedFailure("RCC_SIMPLE_RELAY_BINDING_ACK_UNVERIFIED", release_claims=True)
        if values["command"] == "simple-relay-send" and result.get("ok") is True:
            receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
            if not (
                receipt.get("operationId") == request.operation_id
                and receipt.get("from") == extra["from"]
                and receipt.get("state") == "SUBMITTED"
            ):
                raise UnknownEffectError("RCC_SIMPLE_RELAY_ACK_UNVERIFIED")
        if values["command"] == "simple-relay-return" and result.get("ok") is True:
            receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
            if not (
                receipt.get("operationId") == request.operation_id
                and receipt.get("sourceOperationId") == extra["sourceOperationId"]
                and receipt.get("from") == "worker"
                and receipt.get("to") == "manager"
                and receipt.get("state") == "SUBMITTED"
            ):
                raise UnknownEffectError("RCC_SIMPLE_RELAY_RETURN_ACK_UNVERIFIED")
        if result.get("ok") is True:
            if values["command"] == "send" and result.get("type") == "host:ack":
                if result.get("submitted") is not True or state != "SUBMITTED":
                    raise UnknownEffectError("RCC_SEND_ACK_NOT_SUBMITTED")
            return FeatureResult(Outcome.APPLIED, {
                "instance_id": values["instance_id"], "command": values["command"],
                "host_request_id": request.operation_id, "host_state": state or None,
            }, output={"result": _sanitize(result)})
        host_error = str(result.get("error") or "")
        # Persist only a bounded symbolic error code, never host paths or secrets.
        error_code = host_error if re.fullmatch(r"[A-Z0-9_:-]{1,128}", host_error) else ""
        if state in {"NOT_APPLIED", "NOT_SENT", "FAILED_CONFIRMED"} and result.get("ambiguous") is not True:
            return FeatureResult(Outcome.NOT_APPLIED, {
                "instance_id": values["instance_id"], "command": values["command"],
                "host_request_id": request.operation_id, "host_state": state,
                "error": error_code or "RCC_NOT_APPLIED",
            })
        label = state or "MISSING"
        if error_code:
            label += ":" + error_code
        raise UnknownEffectError("RCC_HOST_OUTCOME_UNVERIFIED:" + label)
