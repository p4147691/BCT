from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Protocol


PIPE_ROOT = r"\\.\pipe" + "\\"
PIPE_PREFIX = "ai_workspace_relay_"


class RelayUnavailable(RuntimeError):
    """No browser mutation was started."""


class RelayEffectUnknown(RuntimeError):
    """The request was written but its browser outcome cannot be proved."""


class RelayClient(Protocol):
    def request(
        self, *, instance_id: str, request_id: str, command: str,
        to: str = "", text: str = "", extra: dict[str, Any] | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]: ...


def validate_instance_id(value: object) -> str:
    instance_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", instance_id):
        raise ValueError("RCC_INSTANCE_ID_INVALID")
    return instance_id


def discover_instance_ids() -> list[str]:
    try:
        names = os.listdir(PIPE_ROOT)
    except OSError:
        return []
    return sorted(
        name[len(PIPE_PREFIX):]
        for name in names
        if name.startswith(PIPE_PREFIX)
        and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", name[len(PIPE_PREFIX):])
    )


def resolve_instance_id(value: object) -> str:
    expected = validate_instance_id(value)
    if expected not in discover_instance_ids():
        raise RelayUnavailable("RCC_INSTANCE_UNAVAILABLE:" + expected)
    return expected


def _read_line_until(pipe, deadline: float, pending: bytearray) -> bytes | None:
    newline = pending.find(b"\n")
    if newline >= 0:
        raw = bytes(pending[:newline + 1])
        del pending[:newline + 1]
        return raw
    if os.name != "nt" or not hasattr(pipe, "fileno"):
        return pipe.readline()
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(pipe.fileno())
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, ImportError, OSError):
        return pipe.readline()
    available = ctypes.c_ulong(0)
    while time.monotonic() < deadline:
        available.value = 0
        if not kernel32.PeekNamedPipe(
            handle, None, 0, None, ctypes.byref(available), None
        ):
            raise OSError(ctypes.get_last_error(), "PeekNamedPipe failed")
        if available.value:
            chunk = pipe.read(min(int(available.value), 65536))
            if not chunk:
                return b""
            pending.extend(chunk)
            newline = pending.find(b"\n")
            if newline >= 0:
                raw = bytes(pending[:newline + 1])
                del pending[:newline + 1]
                return raw
        else:
            time.sleep(0.02)
    return None


class NamedPipeRelayClient:
    """Exact-instance RCC transport; it never falls back to another Chrome."""

    def request(
        self, *, instance_id: str, request_id: str, command: str,
        to: str = "", text: str = "", extra: dict[str, Any] | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        resolved = resolve_instance_id(instance_id)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", request_id):
            raise ValueError("RCC_REQUEST_ID_INVALID")
        payload: dict[str, Any] = {
            "requestId": request_id, "command": command, "to": to, "text": text,
        }
        if extra:
            overlap = {"requestId", "command", "to", "text"}.intersection(extra)
            if overlap:
                raise ValueError("RCC_RESERVED_FIELD_OVERRIDE")
            payload.update(extra)
        path = PIPE_ROOT + PIPE_PREFIX + resolved
        try:
            pipe = open(path, "r+b", buffering=0)
        except OSError as exc:
            raise RelayUnavailable("RCC_PIPE_UNAVAILABLE") from exc
        written = False
        try:
            with pipe:
                pipe.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                written = True
                deadline = time.monotonic() + timeout_s
                pending = bytearray()
                while time.monotonic() < deadline:
                    raw = _read_line_until(pipe, deadline, pending)
                    if raw is None:
                        break
                    if not raw:
                        raise RelayEffectUnknown("RCC_PIPE_CLOSED_AFTER_DISPATCH")
                    message = json.loads(raw.decode("utf-8"))
                    if message.get("type") != "host:result":
                        continue
                    if message.get("requestId") != request_id:
                        continue
                    returned = str(message.get("instanceId") or "").strip()
                    if returned and returned != resolved:
                        raise RelayEffectUnknown("RCC_INSTANCE_RESPONSE_MISMATCH")
                    state = message.get("state")
                    if command == "state" and isinstance(state, dict):
                        state_instance = str(state.get("instanceId") or "").strip()
                        if state_instance != resolved:
                            raise RelayEffectUnknown("RCC_STATE_INSTANCE_MISMATCH")
                    return message
        except (RelayUnavailable, RelayEffectUnknown):
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if written:
                raise RelayEffectUnknown("RCC_TRANSPORT_UNKNOWN_AFTER_DISPATCH") from exc
            raise RelayUnavailable("RCC_TRANSPORT_NOT_STARTED") from exc
        raise RelayEffectUnknown("RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH")
