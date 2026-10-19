from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome, PreconditionError,
    UnknownEffectError, Work,
)
from bct.integrations.desktop_session import (
    DesktopSessionClient, DesktopSessionEffectUnknown, DesktopSessionRequestFailed,
    DesktopSessionUnavailable,
)


def desktop_session_client(policy_path: str | Path, *, data_root: str | Path | None) -> DesktopSessionClient:
    policy_path = Path(policy_path)
    data = tomllib.loads(policy_path.read_text(encoding="utf-8"))
    config = data.get("desktop_session") or {}
    if not isinstance(config, dict):
        raise ValueError("DESKTOP_SESSION_SECTION_INVALID")
    fallback_data = Path(data_root).resolve() if data_root is not None else policy_path.parent / ".desktop-session-data"
    state_root = Path(str(config.get("state_root") or policy_path.parent / ".desktop-session-state"))
    evidence_root = Path(str(config.get("evidence_root") or fallback_data / "desktop-session" / "evidence"))
    if not state_root.is_absolute():
        state_root = policy_path.parent / state_root
    if not evidence_root.is_absolute():
        evidence_root = policy_path.parent / evidence_root
    return DesktopSessionClient(
        endpoint_path=state_root.resolve() / "endpoint.json",
        evidence_root=evidence_root.resolve(),
    )


def _session_evidence(result: dict[str, Any]) -> dict[str, Any]:
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    return {
        "operation": result.get("command"),
        "instance_id": result.get("instanceId"),
        "session": session,
        "monitors": result.get("monitors") if isinstance(result.get("monitors"), list) else [],
    }


class DesktopSessionStatusFeature:
    capability = "desktop_session_status"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if arguments:
            raise PreconditionError("DESKTOP_SESSION_STATUS_ARGUMENTS_INVALID")
        return FeatureRequest(
            self.capability, "interactive-session", {}, ("desktop-session:observe",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.status(request_id=request.operation_id)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            # Status is read-only: transport loss cannot leave an external mutation.
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        evidence = _session_evidence(result)
        return FeatureResult(Outcome.APPLIED, evidence, output=result)


class DesktopCaptureFeature:
    capability = "desktop_capture"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {"target_type", "monitor_index", "hwnd", "max_width", "max_height"}
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_CAPTURE_FIELD_INVALID:" + ",".join(sorted(unknown)))
        target_type = str(arguments.get("target_type") or "virtual_screen").strip().casefold()
        if target_type not in {"virtual_screen", "monitor", "window"}:
            raise PreconditionError("DESKTOP_CAPTURE_TARGET_INVALID")
        monitor_index = arguments.get("monitor_index")
        hwnd = str(arguments.get("hwnd") or "").strip()
        if target_type == "monitor":
            try:
                monitor_index = int(monitor_index)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_CAPTURE_MONITOR_INVALID") from exc
            if not 0 <= monitor_index <= 31:
                raise PreconditionError("DESKTOP_CAPTURE_MONITOR_INVALID")
        else:
            monitor_index = None
        if target_type == "window" and not re.fullmatch(r"[1-9][0-9]{0,18}", hwnd):
            raise PreconditionError("DESKTOP_CAPTURE_HWND_INVALID")
        if target_type != "window":
            hwnd = ""
        try:
            max_width = int(arguments.get("max_width") or 1600)
            max_height = int(arguments.get("max_height") or 1200)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("DESKTOP_CAPTURE_SIZE_INVALID") from exc
        if not 320 <= max_width <= 3840 or not 200 <= max_height <= 2160:
            raise PreconditionError("DESKTOP_CAPTURE_SIZE_INVALID")
        normalized = {
            "target_type": target_type, "monitor_index": monitor_index,
            "hwnd": hwnd, "max_width": max_width, "max_height": max_height,
        }
        if target_type == "window":
            target_suffix = hwnd
        elif target_type == "monitor":
            target_suffix = str(monitor_index)
        else:
            target_suffix = "all"
        target = target_type + ":" + target_suffix
        return FeatureRequest(
            self.capability, target, normalized,
            ("desktop-session:observe", "desktop-capture:" + target.casefold()),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.capture(request_id=request.operation_id, **request.arguments)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        capture = result["capture"]
        evidence = {
            **_session_evidence(result),
            "capture": capture,
        }
        return FeatureResult(Outcome.APPLIED, evidence, output=result)


def _control_result(result: dict[str, Any]) -> FeatureResult:
    control = result.get("control") if isinstance(result.get("control"), dict) else {}
    evidence = {
        **_session_evidence(result),
        "control": control,
    }
    return FeatureResult(Outcome.APPLIED, evidence, output=result)


class DesktopControlLeaseFeature:
    capability = "desktop_control_lease"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {
            "operation", "ttl_seconds", "target_type", "hwnd", "lease_id",
            "expected_stop_generation",
        }
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_CONTROL_LEASE_FIELD_INVALID:" + ",".join(sorted(unknown)))
        owner_id = work.work_id
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner_id):
            raise PreconditionError("DESKTOP_CONTROL_OWNER_INVALID")
        operation = str(arguments.get("operation") or "status").strip().casefold()
        if operation not in {"status", "acquire", "renew", "release", "reset_emergency"}:
            raise PreconditionError("DESKTOP_CONTROL_LEASE_OPERATION_INVALID")
        normalized: dict[str, Any] = {"operation": operation, "owner_id": owner_id}
        target = "interactive-session"
        if operation == "acquire":
            target_type = str(arguments.get("target_type") or "session").strip().casefold()
            hwnd = str(arguments.get("hwnd") or "").strip()
            if target_type not in {"session", "window"}:
                raise PreconditionError("DESKTOP_CONTROL_TARGET_INVALID")
            if target_type == "window" and not re.fullmatch(r"[1-9][0-9]{0,18}", hwnd):
                raise PreconditionError("DESKTOP_CONTROL_HWND_INVALID")
            if target_type == "session" and hwnd:
                raise PreconditionError("DESKTOP_CONTROL_TARGET_INVALID")
            normalized.update({
                "ttl_seconds": self._ttl(arguments), "target_type": target_type,
                "hwnd": hwnd if target_type == "window" else "",
            })
            target = target_type + ":" + (hwnd if hwnd else "current")
        elif operation == "renew":
            normalized.update({
                "lease_id": self._lease_id(arguments),
                "ttl_seconds": self._ttl(arguments),
            })
        elif operation == "release":
            normalized["lease_id"] = self._lease_id(arguments)
        elif operation == "reset_emergency":
            try:
                generation = int(arguments.get("expected_stop_generation"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_EMERGENCY_GENERATION_INVALID") from exc
            if generation <= 0:
                raise PreconditionError("DESKTOP_EMERGENCY_GENERATION_INVALID")
            normalized["expected_stop_generation"] = generation
        resources = (
            ("desktop-control:observe",) if operation == "status"
            else ("desktop-control:interactive-session",)
        )
        return FeatureRequest(self.capability, operation + ":" + target, normalized, resources)

    @staticmethod
    def _ttl(arguments: dict[str, Any]) -> int:
        try:
            value = int(arguments.get("ttl_seconds", 30))
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("DESKTOP_CONTROL_TTL_INVALID") from exc
        if not 2 <= value <= 120:
            raise PreconditionError("DESKTOP_CONTROL_TTL_INVALID")
        return value

    @staticmethod
    def _lease_id(arguments: dict[str, Any]) -> str:
        value = str(arguments.get("lease_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise PreconditionError("DESKTOP_CONTROL_LEASE_ID_INVALID")
        return value

    def execute(self, request: FeatureRequest) -> FeatureResult:
        operation = request.arguments["operation"]
        command = {
            "status": "control_status", "acquire": "lease_acquire",
            "renew": "lease_renew", "release": "lease_release",
            "reset_emergency": "emergency_reset",
        }[operation]
        arguments: dict[str, Any] = {}
        if operation == "acquire":
            arguments = {
                "ownerId": request.arguments["owner_id"],
                "ttlSeconds": request.arguments["ttl_seconds"],
                "targetType": request.arguments["target_type"],
                "hwnd": request.arguments["hwnd"],
            }
        elif operation == "renew":
            arguments = {
                "ownerId": request.arguments["owner_id"],
                "leaseId": request.arguments["lease_id"],
                "ttlSeconds": request.arguments["ttl_seconds"],
            }
        elif operation == "release":
            arguments = {
                "ownerId": request.arguments["owner_id"],
                "leaseId": request.arguments["lease_id"],
            }
        elif operation == "reset_emergency":
            arguments = {"expectedStopGeneration": request.arguments["expected_stop_generation"]}
        try:
            result = self.client.control(
                request_id=request.operation_id, command=command, arguments=arguments,
            )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            if operation == "status":
                raise ConfirmedFailure(str(exc), release_claims=True) from exc
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        return _control_result(result)


class DesktopEmergencyStopFeature:
    capability = "desktop_emergency_stop"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        unknown = set(arguments) - {"reason"}
        if unknown:
            raise PreconditionError("DESKTOP_EMERGENCY_STOP_FIELD_INVALID:" + ",".join(sorted(unknown)))
        reason = str(arguments.get("reason") or "operator-request").strip()
        if not reason or len(reason) > 200:
            raise PreconditionError("DESKTOP_EMERGENCY_STOP_REASON_INVALID")
        # Deliberately separate from the normal control resource: an emergency stop
        # must remain dispatchable even while a control operation is unresolved.
        return FeatureRequest(
            self.capability, "interactive-session", {"reason": reason},
            ("desktop-emergency-stop:interactive-session",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.control(
                request_id=request.operation_id, command="emergency_stop",
                arguments={"reason": request.arguments["reason"]},
            )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        return _control_result(result)


class DesktopInputFeature:
    capability = "desktop_input"
    _KEYS = frozenset({
        "BACKSPACE", "TAB", "ENTER", "ESCAPE", "SPACE", "PAGEUP", "PAGEDOWN",
        "END", "HOME", "LEFT", "UP", "RIGHT", "DOWN", "DELETE",
        *(f"F{index}" for index in range(1, 13)),
        *(chr(value) for value in range(ord("A"), ord("Z") + 1)),
        *(str(value) for value in range(10)),
    })
    _MODIFIERS = frozenset({"ctrl", "shift", "alt", "win"})

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {
            "operation", "lease_id", "x", "y", "button", "click_count",
            "key", "modifiers", "text",
        }
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_INPUT_FIELD_INVALID:" + ",".join(sorted(unknown)))
        owner_id = work.work_id
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner_id):
            raise PreconditionError("DESKTOP_INPUT_OWNER_INVALID")
        lease_id = str(arguments.get("lease_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise PreconditionError("DESKTOP_INPUT_LEASE_ID_INVALID")
        operation = str(arguments.get("operation") or "").strip().casefold()
        if operation not in {"move", "click", "key", "text"}:
            raise PreconditionError("DESKTOP_INPUT_OPERATION_INVALID")
        normalized: dict[str, Any] = {
            "operation": operation, "owner_id": owner_id, "lease_id": lease_id,
        }
        if operation in {"move", "click"}:
            normalized["x"] = self._coordinate(arguments, "x")
            normalized["y"] = self._coordinate(arguments, "y")
        if operation == "move":
            if set(arguments) & {"button", "click_count", "key", "modifiers", "text"}:
                raise PreconditionError("DESKTOP_INPUT_FIELDS_CONFLICT")
        elif operation == "click":
            if set(arguments) & {"key", "modifiers", "text"}:
                raise PreconditionError("DESKTOP_INPUT_FIELDS_CONFLICT")
            button = str(arguments.get("button") or "left").strip().casefold()
            if button not in {"left", "right", "middle"}:
                raise PreconditionError("DESKTOP_INPUT_BUTTON_INVALID")
            try:
                click_count = int(arguments.get("click_count", 1))
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_INPUT_CLICK_COUNT_INVALID") from exc
            if click_count not in {1, 2}:
                raise PreconditionError("DESKTOP_INPUT_CLICK_COUNT_INVALID")
            normalized.update({"button": button, "click_count": click_count})
        elif operation == "key":
            if set(arguments) & {"x", "y", "button", "click_count", "text"}:
                raise PreconditionError("DESKTOP_INPUT_FIELDS_CONFLICT")
            key = str(arguments.get("key") or "").strip().upper()
            modifiers = arguments.get("modifiers", [])
            if key not in self._KEYS:
                raise PreconditionError("DESKTOP_INPUT_KEY_INVALID")
            if (
                not isinstance(modifiers, list) or len(modifiers) > 3
                or any(not isinstance(item, str) for item in modifiers)
            ):
                raise PreconditionError("DESKTOP_INPUT_MODIFIERS_INVALID")
            normalized_modifiers = [item.strip().casefold() for item in modifiers]
            if (
                len(set(normalized_modifiers)) != len(normalized_modifiers)
                or not set(normalized_modifiers).issubset(self._MODIFIERS)
            ):
                raise PreconditionError("DESKTOP_INPUT_MODIFIERS_INVALID")
            normalized.update({"key": key, "modifiers": normalized_modifiers})
        else:
            if set(arguments) & {"x", "y", "button", "click_count", "key", "modifiers"}:
                raise PreconditionError("DESKTOP_INPUT_FIELDS_CONFLICT")
            text = arguments.get("text")
            if (
                not isinstance(text, str) or not 1 <= len(text) <= 256
                or any(ord(character) < 32 or ord(character) == 127 for character in text)
            ):
                raise PreconditionError("DESKTOP_INPUT_TEXT_INVALID")
            normalized["text"] = text
        return FeatureRequest(
            self.capability, operation + ":interactive-session", normalized,
            ("desktop-control:interactive-session",),
        )

    @staticmethod
    def _coordinate(arguments: dict[str, Any], key: str) -> int:
        value = arguments.get(key)
        if isinstance(value, bool):
            raise PreconditionError("DESKTOP_INPUT_COORDINATE_INVALID")
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("DESKTOP_INPUT_COORDINATE_INVALID") from exc
        if not -(2 ** 31) <= result < 2 ** 31:
            raise PreconditionError("DESKTOP_INPUT_COORDINATE_INVALID")
        return result

    def execute(self, request: FeatureRequest) -> FeatureResult:
        operation = request.arguments["operation"]
        command = {
            "move": "input_mouse_move", "click": "input_mouse_click",
            "key": "input_key", "text": "input_text",
        }[operation]
        arguments: dict[str, Any] = {
            "ownerId": request.arguments["owner_id"],
            "leaseId": request.arguments["lease_id"],
        }
        if operation in {"move", "click"}:
            arguments.update({"x": request.arguments["x"], "y": request.arguments["y"]})
        if operation == "move":
            arguments.update({"button": "", "clickCount": 0})
        elif operation == "click":
            arguments.update({
                "button": request.arguments["button"],
                "clickCount": request.arguments["click_count"],
            })
        elif operation == "key":
            arguments.update({
                "key": request.arguments["key"], "modifiers": request.arguments["modifiers"],
            })
        else:
            arguments["text"] = request.arguments["text"]
        try:
            result = self.client.input(
                request_id=request.operation_id, command=command, arguments=arguments,
            )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        evidence = result.get("input") if isinstance(result.get("input"), dict) else {}
        return FeatureResult(
            Outcome.APPLIED, {**_session_evidence(result), "input": evidence}, output=result,
        )


class DesktopWindowListFeature:
    capability = "desktop_window_list"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {"include_minimized", "title_query", "limit"}
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_WINDOW_LIST_FIELD_INVALID:" + ",".join(sorted(unknown)))
        include_minimized = arguments.get("include_minimized", True)
        if not isinstance(include_minimized, bool):
            raise PreconditionError("DESKTOP_WINDOW_LIST_MINIMIZED_INVALID")
        title_query = arguments.get("title_query", "")
        if not isinstance(title_query, str) or len(title_query.strip()) > 200:
            raise PreconditionError("DESKTOP_WINDOW_LIST_QUERY_INVALID")
        try:
            limit = int(arguments.get("limit", 100))
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("DESKTOP_WINDOW_LIST_LIMIT_INVALID") from exc
        if isinstance(arguments.get("limit"), bool) or not 1 <= limit <= 256:
            raise PreconditionError("DESKTOP_WINDOW_LIST_LIMIT_INVALID")
        normalized = {
            "include_minimized": include_minimized,
            "title_query": title_query.strip(),
            "limit": limit,
        }
        return FeatureRequest(
            self.capability, "current-desktop", normalized,
            ("desktop-session:observe",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.windows(request_id=request.operation_id, **request.arguments)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        windows = result["windows"]
        evidence = {
            **_session_evidence(result),
            "window_count": windows["count"],
            "truncated": windows["truncated"],
            "observed_at_utc": windows["observedAtUtc"],
        }
        return FeatureResult(Outcome.APPLIED, evidence, output=result)


class DesktopExploreFeature:
    capability = "desktop_explore"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "").strip().casefold()
        if operation not in {"processes", "paths"}:
            raise PreconditionError("DESKTOP_EXPLORE_OPERATION_INVALID")
        if operation == "paths":
            if set(arguments) != {"operation"}:
                raise PreconditionError("DESKTOP_EXPLORE_FIELDS_CONFLICT")
            normalized = {"operation": operation}
        else:
            allowed = {"operation", "query", "limit", "include_background"}
            unknown = set(arguments) - allowed
            if unknown:
                raise PreconditionError(
                    "DESKTOP_EXPLORE_FIELD_INVALID:" + ",".join(sorted(unknown))
                )
            query = arguments.get("query", "")
            include_background = arguments.get("include_background", True)
            limit_value = arguments.get("limit", 100)
            if not isinstance(query, str) or len(query.strip()) > 200:
                raise PreconditionError("DESKTOP_EXPLORE_QUERY_INVALID")
            if not isinstance(include_background, bool):
                raise PreconditionError("DESKTOP_EXPLORE_BACKGROUND_INVALID")
            if isinstance(limit_value, bool):
                raise PreconditionError("DESKTOP_EXPLORE_LIMIT_INVALID")
            try:
                limit = int(limit_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_EXPLORE_LIMIT_INVALID") from exc
            if not 1 <= limit <= 256:
                raise PreconditionError("DESKTOP_EXPLORE_LIMIT_INVALID")
            normalized = {
                "operation": operation, "query": query.strip(), "limit": limit,
                "include_background": include_background,
            }
        return FeatureRequest(
            self.capability, operation + ":interactive-session", normalized,
            ("desktop-session:observe",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            if request.arguments["operation"] == "paths":
                result = self.client.paths(request_id=request.operation_id)
                paths = result["paths"]
                evidence = {
                    **_session_evidence(result), "known_folder_count": len(paths["knownFolders"]),
                    "drive_count": len(paths["drives"]),
                    "observed_at_utc": paths["observedAtUtc"],
                }
            else:
                result = self.client.processes(
                    request_id=request.operation_id,
                    query=request.arguments["query"], limit=request.arguments["limit"],
                    include_background=request.arguments["include_background"],
                )
                processes = result["processes"]
                evidence = {
                    **_session_evidence(result), "process_count": processes["count"],
                    "truncated": processes["truncated"],
                    "observed_at_utc": processes["observedAtUtc"],
                }
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        return FeatureResult(Outcome.APPLIED, evidence, output=result)


class DesktopApplicationTargetFeature:
    capability = "desktop_application_target"

    _APPLICATIONS = {
        "chrome": ("chrome", frozenset({"chrome_widgetwin_1"})),
        "explorer": ("explorer", frozenset({"cabinetwclass", "explorewclass"})),
    }

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "").strip().casefold()
        if operation not in {"list", "bind"}:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_OPERATION_INVALID")
        application = str(arguments.get("application") or "").strip().casefold()
        if application not in self._APPLICATIONS:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_APPLICATION_INVALID")
        title_query = arguments.get("title_query", "")
        if not isinstance(title_query, str) or len(title_query.strip()) > 200:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_QUERY_INVALID")
        include_minimized = arguments.get("include_minimized", True)
        if not isinstance(include_minimized, bool):
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_MINIMIZED_INVALID")
        if application != "explorer" and "folder_path" in arguments:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_FOLDER_PATH_CONFLICT")
        if application != "chrome" and any(
            field in arguments for field in ("profile_query", "tab_title_query", "tab_scope")
        ):
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_CHROME_SELECTOR_CONFLICT")
        folder_path = arguments.get("folder_path", "")
        if not isinstance(folder_path, str) or "\x00" in folder_path or len(folder_path) > 1024:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_FOLDER_PATH_INVALID")
        folder_path = folder_path.strip()
        if folder_path:
            path = Path(folder_path)
            if not path.is_absolute():
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_FOLDER_PATH_INVALID")
            try:
                path = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_FOLDER_PATH_INVALID") from exc
            if not path.is_dir():
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_FOLDER_PATH_INVALID")
            folder_path = str(path)
        profile_query = arguments.get("profile_query", "")
        if not isinstance(profile_query, str) or len(profile_query.strip()) > 200:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_PROFILE_QUERY_INVALID")
        tab_title_query = arguments.get("tab_title_query", "")
        if not isinstance(tab_title_query, str) or len(tab_title_query.strip()) > 500:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_TAB_QUERY_INVALID")
        tab_scope = str(arguments.get("tab_scope", "active")).strip().casefold()
        if tab_scope not in {"active", "any"}:
            raise PreconditionError("DESKTOP_APPLICATION_TARGET_TAB_SCOPE_INVALID")
        normalized: dict[str, Any] = {
            "operation": operation,
            "application": application,
            "title_query": title_query.strip(),
            "include_minimized": include_minimized,
            "folder_path": folder_path,
            "profile_query": profile_query.strip(),
            "tab_title_query": tab_title_query.strip(),
            "tab_scope": tab_scope,
        }
        if operation == "list":
            unknown = set(arguments) - {
                "operation", "application", "title_query", "include_minimized", "folder_path",
                "profile_query", "tab_title_query", "tab_scope", "limit",
            }
            if unknown:
                raise PreconditionError(
                    "DESKTOP_APPLICATION_TARGET_FIELD_INVALID:" + ",".join(sorted(unknown))
                )
            limit_value = arguments.get("limit", 100)
            if isinstance(limit_value, bool):
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_LIMIT_INVALID")
            try:
                limit = int(limit_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_LIMIT_INVALID") from exc
            if not 1 <= limit <= 256:
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_LIMIT_INVALID")
            normalized["limit"] = limit
            resources = ("desktop-session:observe",)
        else:
            unknown = set(arguments) - {
                "operation", "application", "title_query", "include_minimized", "folder_path",
                "profile_query", "tab_title_query", "tab_scope", "ttl_seconds",
            }
            if unknown:
                raise PreconditionError(
                    "DESKTOP_APPLICATION_TARGET_FIELD_INVALID:" + ",".join(sorted(unknown))
                )
            ttl_value = arguments.get("ttl_seconds", 30)
            if isinstance(ttl_value, bool):
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_TTL_INVALID")
            try:
                ttl_seconds = int(ttl_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_TTL_INVALID") from exc
            if not 5 <= ttl_seconds <= 300:
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_TTL_INVALID")
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", work.work_id):
                raise PreconditionError("DESKTOP_APPLICATION_TARGET_OWNER_INVALID")
            normalized.update({"ttl_seconds": ttl_seconds, "owner_id": work.work_id})
            resources = ("desktop-control:interactive-session",)
        return FeatureRequest(self.capability, operation + ":" + application, normalized, resources)

    @classmethod
    def _candidates(cls, windows: list[dict[str, Any]], *, application: str,
                    title_query: str) -> list[dict[str, Any]]:
        process_name, classes = cls._APPLICATIONS[application]
        query = title_query.casefold()
        candidates = []
        for window in windows:
            if str(window.get("processName") or "").casefold() != process_name:
                continue
            if str(window.get("className") or "").casefold() not in classes:
                continue
            if query and query not in str(window.get("title") or "").casefold():
                continue
            candidates.append(window)
        return candidates

    @staticmethod
    def _same_target(candidate: dict[str, Any], target: dict[str, Any]) -> bool:
        return target.get("type") == "window" and all(
            target.get(key) == candidate.get(key)
            for key in (
                "hwnd", "pid", "processStartTimeUtc", "sessionId", "virtualDesktopId",
            )
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        arguments = request.arguments
        try:
            if arguments["application"] == "explorer":
                observed = self.client.explorer_windows(
                    request_id=request.operation_id,
                    include_minimized=arguments["include_minimized"],
                    title_query="",
                    folder_path=arguments["folder_path"],
                    limit=256,
                )
            else:
                observed = self.client.chrome_windows(
                    request_id=request.operation_id,
                    include_minimized=arguments["include_minimized"],
                    title_query=arguments["title_query"],
                    profile_query=arguments["profile_query"],
                    tab_title_query=arguments["tab_title_query"],
                    tab_scope=arguments["tab_scope"],
                    limit=256,
                )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except (DesktopSessionEffectUnknown, DesktopSessionRequestFailed) as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        windows = observed["windows"]
        candidates = self._candidates(
            windows["items"], application=arguments["application"],
            title_query=arguments["title_query"],
        )
        if arguments["operation"] == "list":
            limit = arguments["limit"]
            items = candidates[:limit]
            application_windows = {
                "application": arguments["application"],
                "titleQuery": arguments["title_query"],
                "folderPath": arguments["folder_path"],
                "profileQuery": arguments["profile_query"],
                "tabTitleQuery": arguments["tab_title_query"],
                "tabScope": arguments["tab_scope"],
                "items": items,
                "count": len(items),
                "truncated": bool(windows["truncated"] or len(candidates) > limit),
                "observedAtUtc": windows["observedAtUtc"],
            }
            output = {**observed, "applicationWindows": application_windows}
            evidence = {
                **_session_evidence(observed),
                "application": arguments["application"],
                "candidate_count": len(items),
                "truncated": application_windows["truncated"],
                "observed_at_utc": windows["observedAtUtc"],
            }
            return FeatureResult(Outcome.APPLIED, evidence, output=output)
        if arguments["application"] == "chrome" and not windows["inspectionAvailable"]:
            raise ConfirmedFailure("DESKTOP_APPLICATION_TARGET_INSPECTION_UNAVAILABLE", release_claims=True)
        if len(candidates) == 0:
            raise ConfirmedFailure("DESKTOP_APPLICATION_TARGET_NOT_FOUND", release_claims=True)
        if len(candidates) != 1 or windows["truncated"]:
            raise ConfirmedFailure("DESKTOP_APPLICATION_TARGET_AMBIGUOUS", release_claims=True)
        candidate = candidates[0]
        try:
            bound = self.client.control(
                request_id=request.operation_id,
                command="lease_acquire",
                arguments={
                    "ownerId": arguments["owner_id"],
                    "ttlSeconds": arguments["ttl_seconds"],
                    "targetType": "window",
                    "hwnd": str(candidate["hwnd"]),
                },
            )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        control = bound.get("control")
        lease = control.get("lease") if isinstance(control, dict) else None
        target = lease.get("target") if isinstance(lease, dict) else None
        if not isinstance(target, dict) or not self._same_target(candidate, target):
            raise UnknownEffectError("DESKTOP_APPLICATION_TARGET_BINDING_MISMATCH")
        application_target = {
            "application": arguments["application"],
            "titleQuery": arguments["title_query"],
            "folderPath": arguments["folder_path"],
            "profileQuery": arguments["profile_query"],
            "tabTitleQuery": arguments["tab_title_query"],
            "tabScope": arguments["tab_scope"],
            "window": candidate,
        }
        output = {**bound, "applicationTarget": application_target}
        evidence = {
            **_session_evidence(bound),
            "application": arguments["application"],
            "candidate_count": 1,
            "application_target": application_target,
            "control": control,
        }
        return FeatureResult(Outcome.APPLIED, evidence, output=output)


class DesktopWindowActivateFeature:
    capability = "desktop_window_activate"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        unknown = set(arguments) - {"lease_id"}
        if unknown:
            raise PreconditionError("DESKTOP_WINDOW_ACTIVATE_FIELD_INVALID:" + ",".join(sorted(unknown)))
        owner_id = work.work_id
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner_id):
            raise PreconditionError("DESKTOP_WINDOW_ACTIVATE_OWNER_INVALID")
        lease_id = str(arguments.get("lease_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise PreconditionError("DESKTOP_WINDOW_ACTIVATE_LEASE_ID_INVALID")
        return FeatureRequest(
            self.capability, "activate:interactive-session",
            {"owner_id": owner_id, "lease_id": lease_id},
            ("desktop-control:interactive-session",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.activate(
                request_id=request.operation_id,
                owner_id=request.arguments["owner_id"],
                lease_id=request.arguments["lease_id"],
            )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        action = result["windowAction"]
        return FeatureResult(
            Outcome.APPLIED, {**_session_evidence(result), "window_action": action}, output=result,
        )


class DesktopChromeTabSelectFeature:
    capability = "desktop_chrome_tab_select"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        unknown = set(arguments) - {"lease_id", "ordinal", "expected_title"}
        if unknown:
            raise PreconditionError("DESKTOP_CHROME_TAB_SELECT_FIELD_INVALID:" + ",".join(sorted(unknown)))
        owner_id = work.work_id
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner_id):
            raise PreconditionError("DESKTOP_CHROME_TAB_SELECT_OWNER_INVALID")
        lease_id = str(arguments.get("lease_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise PreconditionError("DESKTOP_CHROME_TAB_SELECT_LEASE_ID_INVALID")
        ordinal = arguments.get("ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 0 <= ordinal < 100:
            raise PreconditionError("DESKTOP_CHROME_TAB_SELECT_ORDINAL_INVALID")
        expected_title = arguments.get("expected_title")
        if (
            not isinstance(expected_title, str) or not expected_title
            or len(expected_title) > 500 or "\0" in expected_title
        ):
            raise PreconditionError("DESKTOP_CHROME_TAB_SELECT_TITLE_INVALID")
        return FeatureRequest(
            self.capability, "select:chrome-tab", {
                "owner_id": owner_id, "lease_id": lease_id,
                "ordinal": ordinal, "expected_title": expected_title,
            }, ("desktop-control:interactive-session",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.select_chrome_tab(
                request_id=request.operation_id, **request.arguments,
            )
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        action = result["chromeTabAction"]
        return FeatureResult(
            Outcome.APPLIED, {**_session_evidence(result), "chrome_tab_action": action}, output=result,
        )


class DesktopWindowManageFeature:
    capability = "desktop_window_manage"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {"lease_id", "operation", "x", "y", "width", "height"}
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_WINDOW_MANAGE_FIELD_INVALID:" + ",".join(sorted(unknown)))
        owner_id = work.work_id
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner_id):
            raise PreconditionError("DESKTOP_WINDOW_MANAGE_OWNER_INVALID")
        lease_id = str(arguments.get("lease_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise PreconditionError("DESKTOP_WINDOW_MANAGE_LEASE_ID_INVALID")
        operation = str(arguments.get("operation") or "").strip().casefold()
        if operation not in {"restore", "minimize", "maximize", "move_resize"}:
            raise PreconditionError("DESKTOP_WINDOW_MANAGE_OPERATION_INVALID")
        normalized: dict[str, Any] = {
            "owner_id": owner_id, "lease_id": lease_id, "operation": operation,
            "x": None, "y": None, "width": None, "height": None,
        }
        geometry = {"x", "y", "width", "height"}
        if operation == "move_resize":
            if not geometry.issubset(arguments):
                raise PreconditionError("DESKTOP_WINDOW_MANAGE_BOUNDS_REQUIRED")
            for key in geometry:
                value = arguments.get(key)
                if isinstance(value, bool):
                    raise PreconditionError("DESKTOP_WINDOW_MANAGE_BOUNDS_INVALID")
                try:
                    normalized[key] = int(value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise PreconditionError("DESKTOP_WINDOW_MANAGE_BOUNDS_INVALID") from exc
            if (
                not -(2 ** 31) <= normalized["x"] < 2 ** 31
                or not -(2 ** 31) <= normalized["y"] < 2 ** 31
                or not 100 <= normalized["width"] <= 7680
                or not 80 <= normalized["height"] <= 4320
            ):
                raise PreconditionError("DESKTOP_WINDOW_MANAGE_BOUNDS_INVALID")
        elif set(arguments) & geometry:
            raise PreconditionError("DESKTOP_WINDOW_MANAGE_FIELDS_CONFLICT")
        return FeatureRequest(
            self.capability, operation + ":interactive-session", normalized,
            ("desktop-control:interactive-session",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.manage(request_id=request.operation_id, **request.arguments)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        action = result["windowAction"]
        return FeatureResult(
            Outcome.APPLIED, {**_session_evidence(result), "window_action": action}, output=result,
        )


class DesktopProgramLaunchFeature:
    capability = "desktop_program_launch"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {
            "lease_id", "executable", "arguments", "working_directory",
            "window_timeout_ms",
        }
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_FIELD_INVALID:" + ",".join(sorted(unknown)))
        owner_id = work.work_id
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner_id):
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_OWNER_INVALID")
        lease_id = str(arguments.get("lease_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_LEASE_ID_INVALID")
        executable_value = arguments.get("executable")
        if not isinstance(executable_value, str) or "\0" in executable_value:
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_EXECUTABLE_INVALID")
        executable = Path(executable_value)
        if (
            not executable.is_absolute() or executable.suffix.casefold() != ".exe"
            or not executable.is_file() or executable.is_symlink()
        ):
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_EXECUTABLE_INVALID")
        directory_value = arguments.get("working_directory")
        if not isinstance(directory_value, str) or "\0" in directory_value:
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_WORKING_DIRECTORY_INVALID")
        working_directory = Path(directory_value)
        if not working_directory.is_absolute() or not working_directory.is_dir() or working_directory.is_symlink():
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_WORKING_DIRECTORY_INVALID")
        launch_arguments = arguments.get("arguments")
        if (
            not isinstance(launch_arguments, list) or len(launch_arguments) > 32
            or any(
                not isinstance(value, str) or len(value) > 1024 or "\0" in value
                for value in launch_arguments
            )
            or sum(len(value) for value in launch_arguments) > 8192
        ):
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_ARGUMENTS_INVALID")
        timeout_value = arguments.get("window_timeout_ms", 5000)
        if isinstance(timeout_value, bool):
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_TIMEOUT_INVALID")
        try:
            window_timeout_ms = int(timeout_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_TIMEOUT_INVALID") from exc
        if not 100 <= window_timeout_ms <= 10000:
            raise PreconditionError("DESKTOP_PROGRAM_LAUNCH_TIMEOUT_INVALID")
        normalized = {
            "owner_id": owner_id, "lease_id": lease_id,
            "executable": str(executable.resolve()),
            "arguments": list(launch_arguments),
            "working_directory": str(working_directory.resolve()),
            "window_timeout_ms": window_timeout_ms,
        }
        return FeatureRequest(
            self.capability, "launch:interactive-session", normalized,
            ("desktop-control:interactive-session",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.launch(request_id=request.operation_id, **request.arguments)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        launch = result["programLaunch"]
        return FeatureResult(
            Outcome.APPLIED, {**_session_evidence(result), "program_launch": launch}, output=result,
        )
