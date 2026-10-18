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
