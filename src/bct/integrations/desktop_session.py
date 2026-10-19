from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rcc import RelayUnavailable, _read_line_until, verify_connected_pipe_server


PIPE_ROOT = r"\\.\pipe" + "\\"
PIPE_PREFIX = "bct_desktop_session_v1_s"
_INSTANCE = re.compile(r"^[0-9a-f]{32}$")
_REQUEST = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class DesktopSessionUnavailable(RuntimeError):
    """No request byte reached a verified interactive-session agent."""


class DesktopSessionEffectUnknown(RuntimeError):
    """The request was written but its result could not be proved."""


class DesktopSessionRequestFailed(RuntimeError):
    """The verified Agent returned a terminal non-applied response."""


@dataclass(frozen=True)
class DesktopSessionEndpoint:
    instance_id: str
    pipe_name: str
    pid: int
    session_id: int
    user_sid: str
    logon_sid: str
    agent_version: str


def _current_session_id() -> int:
    if os.name != "nt":
        raise DesktopSessionUnavailable("DESKTOP_SESSION_WINDOWS_REQUIRED")
    try:
        import ctypes
        from ctypes import wintypes

        value = wintypes.DWORD(0)
        fn = ctypes.WinDLL("kernel32", use_last_error=True).ProcessIdToSessionId
        fn.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        fn.restype = wintypes.BOOL
        if not fn(os.getpid(), ctypes.byref(value)) or value.value <= 0:
            raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId failed")
        return int(value.value)
    except (ImportError, OSError, OverflowError) as exc:
        raise DesktopSessionUnavailable("DESKTOP_SESSION_ID_UNAVAILABLE") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class DesktopSessionClient:
    def __init__(self, *, endpoint_path: str | Path, evidence_root: str | Path):
        self.endpoint_path = Path(endpoint_path).resolve()
        self.evidence_root = Path(evidence_root).resolve()

    def _endpoint(self) -> DesktopSessionEndpoint:
        try:
            value = json.loads(self.endpoint_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DesktopSessionUnavailable("DESKTOP_SESSION_ENDPOINT_UNAVAILABLE") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema", "protocol", "instanceId", "pipeName", "pid", "sessionId",
            "userSid", "logonSid", "agentVersion", "heartbeatUtc",
        }:
            raise DesktopSessionUnavailable("DESKTOP_SESSION_ENDPOINT_INVALID")
        try:
            session_id = int(value["sessionId"])
            pid = int(value["pid"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise DesktopSessionUnavailable("DESKTOP_SESSION_ENDPOINT_INVALID") from exc
        expected_pipe = PIPE_PREFIX + str(session_id)
        if (
            value.get("schema") != 1
            or value.get("protocol") != "BCT_DESKTOP_SESSION_V1"
            or not _INSTANCE.fullmatch(str(value.get("instanceId") or ""))
            or str(value.get("pipeName") or "") != expected_pipe
            or pid <= 0
            or session_id != _current_session_id()
            or not str(value.get("userSid") or "").startswith("S-1-5-")
            or not str(value.get("logonSid") or "").startswith("S-1-5-5-")
            or not str(value.get("agentVersion") or "")
        ):
            raise DesktopSessionUnavailable("DESKTOP_SESSION_ENDPOINT_INVALID")
        return DesktopSessionEndpoint(
            instance_id=str(value["instanceId"]), pipe_name=expected_pipe,
            pid=pid, session_id=session_id, user_sid=str(value["userSid"]),
            logon_sid=str(value["logonSid"]), agent_version=str(value["agentVersion"]),
        )

    def request(self, *, request_id: str, command: str,
                arguments: dict[str, Any] | None = None, timeout_s: float = 20.0) -> dict[str, Any]:
        if not _REQUEST.fullmatch(request_id):
            raise ValueError("DESKTOP_SESSION_REQUEST_ID_INVALID")
        if command not in {
            "status", "capture", "control_status", "lease_acquire", "lease_renew",
            "lease_release", "emergency_stop", "emergency_reset",
            "input_mouse_move", "input_mouse_click", "input_mouse_scroll", "input_mouse_drag",
            "input_key", "input_text",
            "clipboard_get", "clipboard_set",
            "windows_list", "window_activate", "window_manage", "program_launch",
            "processes_list", "paths_list", "explorer_windows_list", "chrome_windows_list",
            "chrome_tab_select",
            "chrome_content_list", "chrome_content_action",
            "uia_elements_list", "uia_element_action",
        }:
            raise ValueError("DESKTOP_SESSION_COMMAND_INVALID")
        endpoint = self._endpoint()
        payload: dict[str, Any] = {"requestId": request_id, "command": command}
        if arguments:
            overlap = set(arguments) & {"requestId", "command"}
            if overlap:
                raise ValueError("DESKTOP_SESSION_RESERVED_FIELD_OVERRIDE")
            payload.update(arguments)
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > 65536:
            raise ValueError("DESKTOP_SESSION_REQUEST_TOO_LARGE")
        path = PIPE_ROOT + endpoint.pipe_name
        try:
            pipe = open(path, "r+b", buffering=0)
        except OSError as exc:
            raise DesktopSessionUnavailable("DESKTOP_SESSION_PIPE_UNAVAILABLE") from exc
        write_started = False
        try:
            with pipe:
                try:
                    verify_connected_pipe_server(pipe)
                except RelayUnavailable as exc:
                    raise DesktopSessionUnavailable("DESKTOP_SESSION_PIPE_SERVER_REJECTED") from exc
                write_started = True
                pipe.write(encoded)
                deadline = time.monotonic() + timeout_s
                raw = _read_line_until(pipe, deadline, bytearray())
                if raw is None or not raw:
                    raise DesktopSessionEffectUnknown("DESKTOP_SESSION_RESPONSE_MISSING")
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise DesktopSessionEffectUnknown("DESKTOP_SESSION_RESPONSE_INVALID")
                if result.get("requestId") != request_id:
                    raise DesktopSessionEffectUnknown("DESKTOP_SESSION_REQUEST_MISMATCH")
                if result.get("instanceId") != endpoint.instance_id:
                    raise DesktopSessionEffectUnknown("DESKTOP_SESSION_INSTANCE_MISMATCH")
                if result.get("type") != "desktop-session:result":
                    raise DesktopSessionEffectUnknown("DESKTOP_SESSION_RESPONSE_INVALID")
                if result.get("ok") is not True and result.get("effectState") == "UNKNOWN":
                    raise DesktopSessionEffectUnknown(
                        "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:" + str(result.get("error") or "UNKNOWN")[:200]
                    )
                if result.get("ok") is not True:
                    raise DesktopSessionRequestFailed(
                        "DESKTOP_SESSION_AGENT_ERROR:" + str(result.get("error") or "UNKNOWN")[:200]
                    )
                session = result.get("session")
                if not isinstance(session, dict) or int(session.get("sessionId") or 0) != endpoint.session_id:
                    raise DesktopSessionEffectUnknown("DESKTOP_SESSION_RESPONSE_SESSION_MISMATCH")
                return result
        except DesktopSessionUnavailable:
            raise
        except DesktopSessionEffectUnknown:
            raise
        except DesktopSessionRequestFailed:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            if write_started:
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_TRANSPORT_UNKNOWN") from exc
            raise DesktopSessionUnavailable("DESKTOP_SESSION_TRANSPORT_NOT_STARTED") from exc

    def status(self, *, request_id: str) -> dict[str, Any]:
        return self.request(request_id=request_id, command="status", timeout_s=10.0)

    def capture(self, *, request_id: str, target_type: str,
                monitor_index: int | None, hwnd: str, max_width: int, max_height: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id,
            command="capture",
            arguments={
                "targetType": target_type, "monitorIndex": monitor_index,
                "hwnd": hwnd, "maxWidth": max_width, "maxHeight": max_height,
            },
            timeout_s=30.0,
        )
        capture = result.get("capture")
        if not isinstance(capture, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_SESSION_CAPTURE_MISSING")
        path = Path(str(capture.get("path") or ""))
        expected_sha = str(capture.get("sha256") or "")
        if not path.is_absolute() or not _inside(path, self.evidence_root) or not path.is_file():
            raise DesktopSessionEffectUnknown("DESKTOP_SESSION_CAPTURE_PATH_INVALID")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or actual_sha != expected_sha:
            raise DesktopSessionEffectUnknown("DESKTOP_SESSION_CAPTURE_HASH_MISMATCH")
        return result

    def control(self, *, request_id: str, command: str,
                arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if command not in {
            "control_status", "lease_acquire", "lease_renew", "lease_release",
            "emergency_stop", "emergency_reset",
        }:
            raise ValueError("DESKTOP_CONTROL_COMMAND_INVALID")
        result = self.request(
            request_id=request_id, command=command, arguments=arguments, timeout_s=10.0,
        )
        control = result.get("control")
        if not isinstance(control, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_CONTROL_STATE_MISSING")
        emergency = control.get("emergencyStop")
        if not isinstance(emergency, dict) or not isinstance(emergency.get("active"), bool):
            raise DesktopSessionEffectUnknown("DESKTOP_CONTROL_STATE_INVALID")
        lease = control.get("lease")
        if lease is not None and not isinstance(lease, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_CONTROL_STATE_INVALID")
        return result

    def input(self, *, request_id: str, command: str,
              arguments: dict[str, Any]) -> dict[str, Any]:
        if command not in {
            "input_mouse_move", "input_mouse_click", "input_mouse_scroll", "input_mouse_drag",
            "input_key", "input_text",
        }:
            raise ValueError("DESKTOP_INPUT_COMMAND_INVALID")
        result = self.request(
            request_id=request_id, command=command, arguments=arguments, timeout_s=10.0,
        )
        evidence = result.get("input")
        if not isinstance(evidence, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_INPUT_EVIDENCE_MISSING")
        if evidence.get("operation") not in {"move", "click", "scroll", "drag", "key", "text"}:
            raise DesktopSessionEffectUnknown("DESKTOP_INPUT_EVIDENCE_INVALID")
        return result

    def clipboard(self, *, request_id: str, command: str,
                  arguments: dict[str, Any]) -> dict[str, Any]:
        if command not in {"clipboard_get", "clipboard_set"}:
            raise ValueError("DESKTOP_CLIPBOARD_COMMAND_INVALID")
        result = self.request(
            request_id=request_id, command=command, arguments=arguments, timeout_s=10.0,
        )
        value = result.get("clipboard")
        if (
            not isinstance(value, dict)
            or value.get("operation") != command.removeprefix("clipboard_")
            or value.get("leaseId") != arguments.get("leaseId")
            or not isinstance(value.get("hasText"), bool)
            or isinstance(value.get("textLength"), bool)
            or not isinstance(value.get("textLength"), int)
            or isinstance(value.get("utf8Bytes"), bool)
            or not isinstance(value.get("utf8Bytes"), int)
            or not isinstance(value.get("sha256"), str)
            or not isinstance(value.get("appliedAtUtc"), str)
            or value["textLength"] < 0
            or value["utf8Bytes"] < 0
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CLIPBOARD_EVIDENCE_INVALID")
        if value["hasText"]:
            if not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
                raise DesktopSessionEffectUnknown("DESKTOP_CLIPBOARD_EVIDENCE_INVALID")
            observed = value.get("text") if command == "clipboard_get" else arguments.get("text")
            if not isinstance(observed, str):
                raise DesktopSessionEffectUnknown("DESKTOP_CLIPBOARD_TEXT_MISSING")
            encoded = observed.encode("utf-8")
            if (
                value["textLength"] != len(observed)
                or value["utf8Bytes"] != len(encoded)
                or value["sha256"] != hashlib.sha256(encoded).hexdigest()
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_CLIPBOARD_EVIDENCE_INVALID")
        elif value["textLength"] != 0 or value["utf8Bytes"] != 0 or value["sha256"]:
            raise DesktopSessionEffectUnknown("DESKTOP_CLIPBOARD_EVIDENCE_INVALID")
        elif command == "clipboard_set" and arguments.get("text") != "":
            raise DesktopSessionEffectUnknown("DESKTOP_CLIPBOARD_EVIDENCE_INVALID")
        return result

    def windows(self, *, request_id: str, include_minimized: bool,
                title_query: str, limit: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="windows_list",
            arguments={
                "includeMinimized": include_minimized,
                "titleQuery": title_query,
                "limit": limit,
            },
            timeout_s=10.0,
        )
        return self._validated_windows(result, adapter="generic")

    def explorer_windows(self, *, request_id: str, include_minimized: bool,
                         title_query: str, folder_path: str, limit: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="explorer_windows_list",
            arguments={
                "includeMinimized": include_minimized,
                "titleQuery": title_query,
                "folderPath": folder_path,
                "limit": limit,
            },
            timeout_s=10.0,
        )
        return self._validated_windows(result, adapter="explorer")

    def chrome_windows(self, *, request_id: str, include_minimized: bool,
                       title_query: str, profile_query: str, tab_title_query: str,
                       tab_scope: str, limit: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="chrome_windows_list",
            arguments={
                "includeMinimized": include_minimized,
                "titleQuery": title_query,
                "profileQuery": profile_query,
                "tabTitleQuery": tab_title_query,
                "tabScope": tab_scope,
                "limit": limit,
            },
            timeout_s=10.0,
        )
        validated = self._validated_windows(result, adapter="chrome")
        windows = validated["windows"]
        if (
            windows["profileQuery"] != profile_query
            or windows["tabTitleQuery"] != tab_title_query
            or windows["tabScope"] != tab_scope
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_SELECTOR_MISMATCH")
        return validated

    @staticmethod
    def _validated_windows(result: dict[str, Any], *, adapter: str) -> dict[str, Any]:
        windows = result.get("windows")
        if not isinstance(windows, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_WINDOWS_MISSING")
        items = windows.get("items")
        count = windows.get("count")
        if (
            not isinstance(items, list) or isinstance(count, bool)
            or not isinstance(count, int) or count != len(items)
            or not isinstance(windows.get("truncated"), bool)
            or not isinstance(windows.get("observedAtUtc"), str)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_WINDOWS_INVALID")
        for item in items:
            if (
                not isinstance(item, dict)
                or not re.fullmatch(r"[1-9][0-9]{0,18}", str(item.get("hwnd") or ""))
                or isinstance(item.get("pid"), bool) or not isinstance(item.get("pid"), int)
                or item["pid"] <= 0 or not isinstance(item.get("title"), str)
                or not isinstance(item.get("processName"), str)
                or not isinstance(item.get("className"), str)
                or not isinstance(item.get("processStartTimeUtc"), str)
                or not isinstance(item.get("virtualDesktopId"), str)
                or item.get("sessionId") != result["session"]["sessionId"]
                or not isinstance(item.get("visible"), bool)
                or not isinstance(item.get("minimized"), bool)
                or not isinstance(item.get("foreground"), bool)
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_WINDOWS_INVALID")
            if adapter == "explorer" and (
                str(item.get("processName") or "").casefold() != "explorer"
                or str(item.get("className") or "").casefold()
                not in {"cabinetwclass", "explorewclass"}
                or not isinstance(item.get("locationUrl"), str)
                or not isinstance(item.get("locationName"), str)
                or (
                    item.get("folderPath") is not None
                    and (
                        not isinstance(item.get("folderPath"), str)
                        or not Path(item["folderPath"]).is_absolute()
                    )
                )
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_EXPLORER_WINDOWS_INVALID")
            if adapter == "chrome":
                tabs = item.get("tabs")
                active_tab = item.get("activeTab")
                if (
                    str(item.get("processName") or "").casefold() != "chrome"
                    or str(item.get("className") or "").casefold() != "chrome_widgetwin_1"
                    or not isinstance(item.get("available"), bool)
                    or not isinstance(item.get("profileName"), str)
                    or len(item["profileName"]) > 200
                    or not isinstance(item.get("error"), str)
                    or not isinstance(tabs, list)
                    or isinstance(item.get("tabCount"), bool)
                    or not isinstance(item.get("tabCount"), int)
                    or item["tabCount"] != len(tabs)
                    or item["tabCount"] > 100
                    or active_tab is not None and not isinstance(active_tab, dict)
                ):
                    raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_INVALID")
                selected = []
                for ordinal, tab in enumerate(tabs):
                    if (
                        not isinstance(tab, dict)
                        or isinstance(tab.get("ordinal"), bool)
                        or not isinstance(tab.get("ordinal"), int)
                        or tab["ordinal"] != ordinal
                        or not isinstance(tab.get("title"), str)
                        or len(tab["title"]) > 500
                        or not isinstance(tab.get("selected"), bool)
                    ):
                        raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_INVALID")
                    if tab["selected"]:
                        selected.append(tab)
                if len(selected) > 1 or active_tab != (selected[0] if selected else None):
                    raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_INVALID")
                if not item["available"] and (
                    item["profileName"] or tabs or active_tab is not None or not item["error"]
                ):
                    raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_INVALID")
        if adapter == "explorer" and (
            not isinstance(windows.get("shellAvailable"), bool)
            or not isinstance(windows.get("folderPath"), str)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_EXPLORER_WINDOWS_INVALID")
        if adapter == "chrome" and (
            not isinstance(windows.get("inspectionAvailable"), bool)
            or not isinstance(windows.get("inspectionError"), str)
            or not isinstance(windows.get("profileQuery"), str)
            or not isinstance(windows.get("tabTitleQuery"), str)
            or windows.get("tabScope") not in {"active", "any"}
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_INVALID")
        if adapter == "chrome" and (
            windows["inspectionAvailable"]
            and (windows["inspectionError"] or any(not item["available"] for item in items))
            or not windows["inspectionAvailable"] and not windows["inspectionError"]
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_WINDOWS_INVALID")
        return result

    def activate(self, *, request_id: str, owner_id: str, lease_id: str) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="window_activate",
            arguments={"ownerId": owner_id, "leaseId": lease_id}, timeout_s=10.0,
        )
        action = result.get("windowAction")
        if (
            not isinstance(action, dict) or action.get("operation") != "activate"
            or action.get("leaseId") != lease_id
            or not isinstance(action.get("alreadyForeground"), bool)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_WINDOW_ACTION_INVALID")
        return result

    def select_chrome_tab(self, *, request_id: str, owner_id: str, lease_id: str,
                          ordinal: int, expected_title: str) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="chrome_tab_select",
            arguments={
                "ownerId": owner_id, "leaseId": lease_id,
                "ordinal": ordinal, "expectedTitle": expected_title,
            }, timeout_s=10.0,
        )
        action = result.get("chromeTabAction")
        if (
            not isinstance(action, dict) or action.get("operation") != "select"
            or action.get("leaseId") != lease_id or action.get("ordinal") != ordinal
            or action.get("title") != expected_title
            or action.get("afterOrdinal") != ordinal
            or not isinstance(action.get("alreadySelected"), bool)
            or action.get("foregroundPreserved") is not True
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_TAB_ACTION_INVALID")
        return result

    def chrome_content(self, *, request_id: str, hwnd: str,
                       expected_document_title: str, limit: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="chrome_content_list",
            arguments={
                "hwnd": hwnd, "expectedDocumentTitle": expected_document_title,
                "limit": limit,
            }, timeout_s=10.0,
        )
        content = result.get("chromeContent")
        if not isinstance(content, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_CONTENT_MISSING")
        elements = content.get("elements")
        target = content.get("target")
        if (
            not isinstance(elements, list)
            or isinstance(content.get("count"), bool)
            or not isinstance(content.get("count"), int)
            or content["count"] != len(elements)
            or not isinstance(content.get("truncated"), bool)
            or not isinstance(content.get("documentTitle"), str)
            or len(content["documentTitle"]) > 500
            or isinstance(content.get("tabOrdinal"), bool)
            or not isinstance(content.get("tabOrdinal"), int)
            or not 0 <= content["tabOrdinal"] < 100
            or not isinstance(content.get("tabTitle"), str)
            or not content["tabTitle"] or len(content["tabTitle"]) > 500
            or expected_document_title and content["documentTitle"] != expected_document_title
            or content.get("foregroundPreserved") is not True
            or not isinstance(content.get("observedAtUtc"), str)
            or not isinstance(target, dict)
            or target.get("type") != "window"
            or str(target.get("hwnd") or "") != hwnd
            or isinstance(target.get("pid"), bool)
            or not isinstance(target.get("pid"), int) or target["pid"] <= 0
            or not isinstance(target.get("processStartTimeUtc"), str)
            or not isinstance(target.get("virtualDesktopId"), str)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_CONTENT_INVALID")
        seen: set[str] = set()
        for item in elements:
            bounds = item.get("bounds") if isinstance(item, dict) else None
            element_id = item.get("elementId") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or not isinstance(element_id, str)
                or not re.fullmatch(r"[0-9a-f]{64}", element_id)
                or element_id in seen
                or item.get("role") not in {"edit", "button"}
                or not isinstance(item.get("name"), str) or len(item["name"]) > 500
                or not isinstance(item.get("automationId"), str) or len(item["automationId"]) > 200
                or not isinstance(item.get("className"), str) or len(item["className"]) > 200
                or isinstance(item.get("occurrence"), bool)
                or not isinstance(item.get("occurrence"), int) or item["occurrence"] < 0
                or not all(isinstance(item.get(key), bool) for key in (
                    "enabled", "focusable", "canSetValue", "canInvoke"
                ))
                or not isinstance(bounds, dict)
                or set(bounds) != {"left", "top", "width", "height"}
                or any(isinstance(bounds[key], bool) or not isinstance(bounds[key], int)
                       for key in bounds)
                or bounds["width"] < 0 or bounds["height"] < 0
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_CHROME_CONTENT_INVALID")
            seen.add(element_id)
        return result

    def chrome_content_action(self, *, request_id: str, owner_id: str, lease_id: str,
                              operation: str, element_id: str,
                              expected_document_title: str, expected_tab_ordinal: int,
                              expected_tab_title: str, text: str) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="chrome_content_action",
            arguments={
                "ownerId": owner_id, "leaseId": lease_id, "operation": operation,
                "elementId": element_id, "expectedDocumentTitle": expected_document_title,
                "expectedTabOrdinal": expected_tab_ordinal,
                "expectedTabTitle": expected_tab_title, "text": text,
            }, timeout_s=10.0,
        )
        action = result.get("chromeContentAction")
        expected_bytes = text.encode("utf-8")
        expected_hash = hashlib.sha256(expected_bytes).hexdigest() if operation == "set_value" else ""
        if (
            not isinstance(action, dict)
            or action.get("operation") != operation
            or action.get("leaseId") != lease_id
            or action.get("elementId") != element_id
            or action.get("documentTitle") != expected_document_title
            or action.get("tabOrdinal") != expected_tab_ordinal
            or action.get("tabTitle") != expected_tab_title
            or action.get("foregroundPreserved") is not True
            or not isinstance(action.get("invoked"), bool)
            or not isinstance(action.get("alreadyApplied"), bool)
            or operation == "invoke" and action.get("invokeAcknowledged") is not True
            or operation == "set_value" and (
                action.get("textChars") != len(text)
                or action.get("textBytes") != len(expected_bytes)
                or action.get("textSha256") != expected_hash
                or isinstance(action.get("afterChars"), bool)
                or not isinstance(action.get("afterChars"), int)
                or action.get("afterSha256") != expected_hash
            )
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_CHROME_CONTENT_ACTION_INVALID")
        return result

    def uia_elements(self, *, request_id: str, hwnd: str, limit: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="uia_elements_list",
            arguments={"hwnd": hwnd, "limit": limit}, timeout_s=10.0,
        )
        content = result.get("uiaElements")
        if not isinstance(content, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_UIA_ELEMENTS_MISSING")
        elements = content.get("elements")
        target = content.get("target")
        if (
            not isinstance(elements, list)
            or isinstance(content.get("count"), bool)
            or not isinstance(content.get("count"), int)
            or content["count"] != len(elements)
            or not isinstance(content.get("truncated"), bool)
            or content.get("foregroundPreserved") is not True
            or not isinstance(content.get("observedAtUtc"), str)
            or not isinstance(target, dict)
            or target.get("type") != "window"
            or str(target.get("hwnd") or "") != hwnd
            or isinstance(target.get("pid"), bool)
            or not isinstance(target.get("pid"), int) or target["pid"] <= 0
            or not isinstance(target.get("processStartTimeUtc"), str)
            or not isinstance(target.get("virtualDesktopId"), str)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_UIA_ELEMENTS_INVALID")
        roles = {
            "button", "edit", "checkbox", "radio", "listitem", "treeitem",
            "menuitem", "tabitem", "combobox", "hyperlink", "control",
        }
        seen: set[str] = set()
        for item in elements:
            bounds = item.get("bounds") if isinstance(item, dict) else None
            element_id = item.get("elementId") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or not isinstance(element_id, str)
                or not re.fullmatch(r"[0-9a-f]{64}", element_id)
                or element_id in seen
                or item.get("role") not in roles
                or not isinstance(item.get("name"), str) or len(item["name"]) > 500
                or not isinstance(item.get("automationId"), str) or len(item["automationId"]) > 200
                or not isinstance(item.get("className"), str) or len(item["className"]) > 200
                or isinstance(item.get("occurrence"), bool)
                or not isinstance(item.get("occurrence"), int) or item["occurrence"] < 0
                or not all(isinstance(item.get(key), bool) for key in (
                    "enabled", "focusable", "isPassword", "canSetValue", "canInvoke",
                    "canToggle", "canSelect", "canExpandCollapse",
                ))
                or not isinstance(item.get("toggleState"), str)
                or item["toggleState"] not in {"", "on", "off", "indeterminate"}
                or item.get("selected") is not None and not isinstance(item.get("selected"), bool)
                or not isinstance(item.get("expandCollapseState"), str)
                or item["expandCollapseState"] not in {"", "expanded", "collapsed", "leaf", "partial"}
                or not isinstance(bounds, dict)
                or set(bounds) != {"left", "top", "width", "height"}
                or any(isinstance(bounds[key], bool) or not isinstance(bounds[key], int)
                       for key in bounds)
                or bounds["width"] < 0 or bounds["height"] < 0
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_UIA_ELEMENTS_INVALID")
            seen.add(element_id)
        return result

    def uia_element_action(self, *, request_id: str, owner_id: str, lease_id: str,
                           operation: str, element_id: str, text: str,
                           desired_state: str) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="uia_element_action",
            arguments={
                "ownerId": owner_id, "leaseId": lease_id, "operation": operation,
                "elementId": element_id, "text": text, "desiredState": desired_state,
            }, timeout_s=10.0,
        )
        action = result.get("uiaAction")
        encoded = text.encode("utf-8")
        expected_hash = hashlib.sha256(encoded).hexdigest() if operation == "set_value" else ""
        valid_states = {"", "on", "off", "indeterminate", "selected", "unselected",
                        "expanded", "collapsed", "leaf", "partial"}
        if (
            not isinstance(action, dict)
            or action.get("operation") != operation
            or action.get("leaseId") != lease_id
            or action.get("elementId") != element_id
            or action.get("foregroundPreserved") is not True
            or not isinstance(action.get("invoked"), bool)
            or not isinstance(action.get("alreadyApplied"), bool)
            or not isinstance(action.get("beforeState"), str)
            or action["beforeState"] not in valid_states
            or not isinstance(action.get("afterState"), str)
            or action["afterState"] not in valid_states
            or operation == "set_value" and (
                action.get("textChars") != len(text)
                or action.get("textBytes") != len(encoded)
                or action.get("textSha256") != expected_hash
            )
            or operation != "set_value" and (
                action.get("textChars") != 0
                or action.get("textBytes") != 0
                or action.get("textSha256") != ""
            )
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_UIA_ACTION_INVALID")
        return result

    def processes(self, *, request_id: str, query: str,
                  limit: int, include_background: bool) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="processes_list",
            arguments={
                "query": query, "limit": limit,
                "includeBackground": include_background,
            },
            timeout_s=10.0,
        )
        processes = result.get("processes")
        if not isinstance(processes, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_PROCESSES_MISSING")
        items = processes.get("items")
        count = processes.get("count")
        session_id = result["session"]["sessionId"]
        if (
            not isinstance(items, list) or isinstance(count, bool)
            or not isinstance(count, int) or count != len(items)
            or not isinstance(processes.get("truncated"), bool)
            or not isinstance(processes.get("observedAtUtc"), str)
            or processes.get("sessionId") != session_id
            or processes.get("query") != query
            or processes.get("includeBackground") is not include_background
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_PROCESSES_INVALID")
        for item in items:
            windows = item.get("windows") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or isinstance(item.get("pid"), bool) or not isinstance(item.get("pid"), int)
                or item["pid"] <= 0 or not isinstance(item.get("processName"), str)
                or not item["processName"]
                or item.get("sessionId") != session_id
                or item.get("processStartTimeUtc") is not None
                   and not isinstance(item.get("processStartTimeUtc"), str)
                or item.get("executablePath") is not None
                   and not isinstance(item.get("executablePath"), str)
                or item.get("responding") is not None
                   and not isinstance(item.get("responding"), bool)
                or isinstance(item.get("windowCount"), bool)
                or not isinstance(item.get("windowCount"), int) or item["windowCount"] < 0
                or not isinstance(windows, list) or item["windowCount"] != len(windows)
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_PROCESSES_INVALID")
            for window in windows:
                if (
                    not isinstance(window, dict)
                    or window.get("pid") != item["pid"]
                    or not re.fullmatch(r"[1-9][0-9]{0,18}", str(window.get("hwnd") or ""))
                    or not isinstance(window.get("title"), str)
                    or not isinstance(window.get("virtualDesktopId"), str)
                ):
                    raise DesktopSessionEffectUnknown("DESKTOP_PROCESSES_INVALID")
        return result

    def paths(self, *, request_id: str) -> dict[str, Any]:
        result = self.request(request_id=request_id, command="paths_list", timeout_s=10.0)
        paths = result.get("paths")
        if not isinstance(paths, dict):
            raise DesktopSessionEffectUnknown("DESKTOP_PATHS_MISSING")
        known = paths.get("knownFolders")
        drives = paths.get("drives")
        if (
            not isinstance(known, list) or not isinstance(drives, list)
            or paths.get("sessionId") != result["session"]["sessionId"]
            or not isinstance(paths.get("observedAtUtc"), str)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_PATHS_INVALID")
        for item in known:
            if (
                not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not isinstance(item.get("path"), str) or not item["path"]
                or not Path(item["path"]).is_absolute()
                or not isinstance(item.get("exists"), bool)
                or item.get("kind") != "known-folder"
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_PATHS_INVALID")
        for item in drives:
            if (
                not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or not Path(item["path"]).is_absolute()
                or not isinstance(item.get("driveType"), str)
                or not isinstance(item.get("ready"), bool)
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_PATHS_INVALID")
            for key in ("totalBytes", "freeBytes"):
                if key in item and (
                    isinstance(item[key], bool) or not isinstance(item[key], int)
                    or item[key] < 0
                ):
                    raise DesktopSessionEffectUnknown("DESKTOP_PATHS_INVALID")
        return result

    def manage(self, *, request_id: str, owner_id: str, lease_id: str,
               operation: str, x: int | None, y: int | None,
               width: int | None, height: int | None) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="window_manage",
            arguments={
                "ownerId": owner_id, "leaseId": lease_id, "operation": operation,
                "x": x, "y": y, "width": width, "height": height,
            },
            timeout_s=10.0,
        )
        action = result.get("windowAction")
        if (
            not isinstance(action, dict) or action.get("operation") != operation
            or action.get("leaseId") != lease_id
            or not isinstance(action.get("alreadyApplied"), bool)
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_WINDOW_ACTION_INVALID")
        for key in ("before", "after"):
            state = action.get(key)
            rect = state.get("rect") if isinstance(state, dict) else None
            if (
                not isinstance(state, dict)
                or not re.fullmatch(r"[1-9][0-9]{0,18}", str(state.get("hwnd") or ""))
                or not isinstance(state.get("visible"), bool)
                or not isinstance(state.get("minimized"), bool)
                or not isinstance(state.get("maximized"), bool)
                or not isinstance(rect, dict)
                or any(
                    isinstance(rect.get(name), bool) or not isinstance(rect.get(name), int)
                    for name in ("left", "top", "right", "bottom", "width", "height")
                )
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_WINDOW_ACTION_INVALID")
        after = action["after"]
        if (
            (operation == "restore" and (after["minimized"] or after["maximized"]))
            or (operation == "minimize" and not after["minimized"])
            or (operation == "maximize" and not after["maximized"])
            or (
                operation == "move_resize"
                and (
                    after["rect"]["left"] != x or after["rect"]["top"] != y
                    or after["rect"]["width"] != width or after["rect"]["height"] != height
                )
            )
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_WINDOW_ACTION_POSTCONDITION_INVALID")
        return result

    def launch(self, *, request_id: str, owner_id: str, lease_id: str,
               executable: str, arguments: list[str], working_directory: str,
               window_timeout_ms: int) -> dict[str, Any]:
        result = self.request(
            request_id=request_id, command="program_launch",
            arguments={
                "ownerId": owner_id, "leaseId": lease_id,
                "executable": executable, "arguments": arguments,
                "workingDirectory": working_directory,
                "windowTimeoutMs": window_timeout_ms,
            },
            timeout_s=max(10.0, window_timeout_ms / 1000.0 + 5.0),
        )
        launch = result.get("programLaunch")
        states = {
            "WINDOW_BOUND", "WINDOW_NOT_OBSERVED", "PROCESS_EXITED_NO_WINDOW",
            "LEASE_REVOKED", "EMERGENCY_STOPPED",
        }
        if (
            not isinstance(launch, dict)
            or launch.get("leaseId") != lease_id
            or isinstance(launch.get("pid"), bool)
            or not isinstance(launch.get("pid"), int)
            or launch["pid"] <= 0
            or not isinstance(launch.get("processStartTimeUtc"), str)
            or isinstance(launch.get("sessionId"), bool)
            or not isinstance(launch.get("sessionId"), int)
            or launch["sessionId"] != int(result["session"]["sessionId"])
            or not isinstance(launch.get("startedAtUtc"), str)
            or launch.get("bindingState") not in states
            or launch.get("executable") != executable
            or launch.get("arguments") != arguments
            or launch.get("workingDirectory") != working_directory
        ):
            raise DesktopSessionEffectUnknown("DESKTOP_PROGRAM_LAUNCH_EVIDENCE_INVALID")
        target = launch.get("windowTarget")
        if launch["bindingState"] == "WINDOW_BOUND":
            if (
                not isinstance(target, dict)
                or target.get("type") != "window"
                or target.get("pid") != launch["pid"]
                or target.get("sessionId") != launch["sessionId"]
                or not re.fullmatch(r"[1-9][0-9]{0,18}", str(target.get("hwnd") or ""))
                or target.get("processStartTimeUtc") != launch["processStartTimeUtc"]
            ):
                raise DesktopSessionEffectUnknown("DESKTOP_PROGRAM_WINDOW_BINDING_INVALID")
        elif target is not None:
            raise DesktopSessionEffectUnknown("DESKTOP_PROGRAM_WINDOW_BINDING_INVALID")
        return result
