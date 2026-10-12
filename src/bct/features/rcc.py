from __future__ import annotations

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


_READ_COMMANDS = {"state", "presence"}
_MUTATING_COMMANDS = {
    "create-chat-tab", "create-chat-window", "send-to-created-tab", "move-tab", "send",
}
_COMMANDS = _READ_COMMANDS | _MUTATING_COMMANDS
_COMMON = {"command", "instance_id", "timeout_s"}
_SENSITIVE_KEYS = {"token", "secret", "password", "authorization"}


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


class RelayBrowserFeature:
    capability = "relay_browser"

    def __init__(self, client: RelayClient | None = None):
        self.client = client or NamedPipeRelayClient()

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
        if command in _READ_COMMANDS:
            pass
        elif command == "create-chat-window":
            pass
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
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("RCC_ARGUMENT_NOT_ALLOWED:" + ",".join(sorted(unknown)))
        resource = "rcc-instance:" + instance_id
        if command in _READ_COMMANDS:
            resource += ":read:" + command
        return FeatureRequest(
            self.capability, instance_id, prepared, (resource,),
            {"command": command, "mutating": command in _MUTATING_COMMANDS},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        extra = dict(values["extra"])
        if request.preconditions["mutating"]:
            extra["operationId"] = request.operation_id
            if values["command"] in {"create-chat-window", "create-chat-tab"}:
                extra["instanceId"] = values["instance_id"]
        try:
            result = self.client.request(
                instance_id=values["instance_id"], request_id=request.operation_id,
                command=values["command"], to=values["to"], text=values["text"],
                extra=extra, timeout_s=values["timeout_s"],
            )
        except RelayUnavailable as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except RelayEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        raw_state = result.get("state")
        state = str(raw_state or "").upper() if not isinstance(raw_state, dict) else "STATE_RETURNED"
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
