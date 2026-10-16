from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol


PIPE_ROOT = r"\\.\pipe" + "\\"
PIPE_PREFIX = "ai_workspace_relay_"


class RelayUnavailable(RuntimeError):
    """No browser mutation was started."""


class RelayEffectUnknown(RuntimeError):
    """The request was written but its browser outcome cannot be proved."""


PIPE_FULL_CONTROL = 0x001F019F
LOCAL_SYSTEM_SID = "S-1-5-18"


@dataclass(frozen=True)
class PipeAccessEntry:
    ace_type: int
    ace_flags: int
    access_mask: int
    sid: str


@dataclass(frozen=True)
class PipeServerIdentity:
    server_pid: int
    pipe_server_session_id: int
    process_session_id: int
    current_session_id: int
    server_user_sid: str
    current_user_sid: str
    server_logon_sid: str
    current_logon_sid: str
    pipe_owner_sid: str
    dacl_protected: bool
    dacl_entries: tuple[PipeAccessEntry, ...]


def _reject_server(reason: str) -> None:
    raise RelayUnavailable("RCC_PIPE_SERVER_REJECTED:" + reason)


def validate_pipe_server_identity(identity: PipeServerIdentity) -> None:
    """Validate the approved personal-desktop Core/RCC logon boundary."""
    if identity.server_pid <= 0:
        _reject_server("SERVER_PID")
    if not (
        identity.pipe_server_session_id
        == identity.process_session_id
        == identity.current_session_id
    ):
        _reject_server("SESSION")
    if not identity.server_user_sid or identity.server_user_sid != identity.current_user_sid:
        _reject_server("USER_SID")
    if not identity.server_logon_sid.startswith("S-1-5-5-"):
        _reject_server("SERVER_LOGON_SID")
    if identity.server_logon_sid != identity.current_logon_sid:
        _reject_server("LOGON_SID")
    if identity.pipe_owner_sid != identity.server_user_sid:
        _reject_server("OWNER_SID")
    if not identity.dacl_protected:
        _reject_server("DACL_NOT_PROTECTED")
    if len(identity.dacl_entries) != 2:
        _reject_server("DACL_ACE_COUNT")
    allowed = {
        identity.server_logon_sid: PIPE_FULL_CONTROL,
        LOCAL_SYSTEM_SID: PIPE_FULL_CONTROL,
    }
    observed: dict[str, int] = {}
    for entry in identity.dacl_entries:
        # The protected Host creates only non-inherited ACCESS_ALLOWED ACEs.
        if entry.ace_type != 0 or entry.ace_flags != 0:
            _reject_server("DACL_ACE_TYPE")
        if entry.sid in observed or allowed.get(entry.sid) != entry.access_mask:
            _reject_server("DACL_PRINCIPAL")
        observed[entry.sid] = entry.access_mask
    if observed != allowed:
        _reject_server("DACL_PRINCIPAL")


def _collect_windows_pipe_server_identity(pipe) -> PipeServerIdentity:
    if os.name != "nt" or not hasattr(pipe, "fileno"):
        _reject_server("WINDOWS_HANDLE_REQUIRED")
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle_value = msvcrt.get_osfhandle(pipe.fileno())
        if handle_value in (-1, 0):
            _reject_server("INVALID_HANDLE")
        pipe_handle = wintypes.HANDLE(handle_value)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        class SidAndAttributes(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class TokenUser(ctypes.Structure):
            _fields_ = [("User", SidAndAttributes)]

        class TokenGroupsOne(ctypes.Structure):
            _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", SidAndAttributes * 1)]

        class AceHeader(ctypes.Structure):
            _fields_ = [
                ("AceType", ctypes.c_ubyte),
                ("AceFlags", ctypes.c_ubyte),
                ("AceSize", wintypes.WORD),
            ]

        class AclSizeInformation(ctypes.Structure):
            _fields_ = [
                ("AceCount", wintypes.DWORD),
                ("AclBytesInUse", wintypes.DWORD),
                ("AclBytesFree", wintypes.DWORD),
            ]

        get_server_pid = kernel32.GetNamedPipeServerProcessId
        get_server_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        get_server_pid.restype = wintypes.BOOL
        get_server_session = kernel32.GetNamedPipeServerSessionId
        get_server_session.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        get_server_session.restype = wintypes.BOOL
        process_to_session = kernel32.ProcessIdToSessionId
        process_to_session.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        process_to_session.restype = wintypes.BOOL
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = wintypes.HANDLE
        open_process_token = advapi32.OpenProcessToken
        open_process_token.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        open_process_token.restype = wintypes.BOOL
        get_token_information = advapi32.GetTokenInformation
        get_token_information.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_token_information.restype = wintypes.BOOL
        convert_sid = advapi32.ConvertSidToStringSidW
        convert_sid.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        convert_sid.restype = wintypes.BOOL
        local_free = kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        get_security_info = advapi32.GetSecurityInfo
        get_security_info.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        get_security_info.restype = wintypes.DWORD
        get_sd_control = advapi32.GetSecurityDescriptorControl
        get_sd_control.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
        get_sd_control.restype = wintypes.BOOL
        get_acl_information = advapi32.GetAclInformation
        get_acl_information.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
        get_acl_information.restype = wintypes.BOOL
        get_ace = advapi32.GetAce
        get_ace.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        get_ace.restype = wintypes.BOOL

        def failed(label: str) -> OSError:
            return OSError(ctypes.get_last_error(), label)

        def sid_string(sid_ptr: ctypes.c_void_p) -> str:
            if not sid_ptr:
                raise failed("SID unavailable")
            text_ptr = wintypes.LPWSTR()
            if not convert_sid(sid_ptr, ctypes.byref(text_ptr)):
                raise failed("ConvertSidToStringSidW failed")
            try:
                return str(text_ptr.value or "")
            finally:
                local_free(ctypes.cast(text_ptr, ctypes.c_void_p))

        def token_sid(token: wintypes.HANDLE, information_class: int) -> str:
            required = wintypes.DWORD(0)
            get_token_information(token, information_class, None, 0, ctypes.byref(required))
            if required.value == 0 or required.value > 65536:
                raise failed("GetTokenInformation size failed")
            buffer = ctypes.create_string_buffer(required.value)
            written = wintypes.DWORD(0)
            if not get_token_information(
                token, information_class, buffer, required.value, ctypes.byref(written)
            ) or written.value == 0 or written.value > required.value:
                raise failed("GetTokenInformation failed")
            if information_class == 1:
                sid_ptr = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents.User.Sid
            else:
                groups = ctypes.cast(buffer, ctypes.POINTER(TokenGroupsOne)).contents
                if groups.GroupCount != 1:
                    raise failed("TokenLogonSid count invalid")
                sid_ptr = groups.Groups[0].Sid
            return sid_string(sid_ptr)

        def process_token_sids(process_handle: wintypes.HANDLE) -> tuple[str, str]:
            token = wintypes.HANDLE()
            if not open_process_token(process_handle, 0x0008, ctypes.byref(token)):
                raise failed("OpenProcessToken failed")
            try:
                return token_sid(token, 1), token_sid(token, 28)
            finally:
                close_handle(token)

        server_pid = wintypes.ULONG(0)
        pipe_session = wintypes.ULONG(0)
        if not get_server_pid(pipe_handle, ctypes.byref(server_pid)) or server_pid.value == 0:
            raise failed("GetNamedPipeServerProcessId failed")
        if not get_server_session(pipe_handle, ctypes.byref(pipe_session)):
            raise failed("GetNamedPipeServerSessionId failed")
        process_session = wintypes.DWORD(0)
        current_session = wintypes.DWORD(0)
        if not process_to_session(server_pid.value, ctypes.byref(process_session)):
            raise failed("server ProcessIdToSessionId failed")
        if not process_to_session(os.getpid(), ctypes.byref(current_session)):
            raise failed("current ProcessIdToSessionId failed")

        server_process = open_process(0x1000, False, server_pid.value)
        if not server_process:
            raise failed("OpenProcess server failed")
        try:
            server_user_sid, server_logon_sid = process_token_sids(server_process)
        finally:
            close_handle(server_process)
        current_user_sid, current_logon_sid = process_token_sids(get_current_process())

        owner_sid = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        security_descriptor = ctypes.c_void_p()
        status = get_security_info(
            pipe_handle, 6, 0x00000001 | 0x00000004,
            ctypes.byref(owner_sid), None, ctypes.byref(dacl), None,
            ctypes.byref(security_descriptor),
        )
        if status != 0 or not security_descriptor or not owner_sid or not dacl:
            raise OSError(int(status), "GetSecurityInfo failed")
        try:
            control = wintypes.WORD(0)
            revision = wintypes.DWORD(0)
            if not get_sd_control(security_descriptor, ctypes.byref(control), ctypes.byref(revision)):
                raise failed("GetSecurityDescriptorControl failed")
            acl_info = AclSizeInformation()
            if not get_acl_information(dacl, ctypes.byref(acl_info), ctypes.sizeof(acl_info), 2):
                raise failed("GetAclInformation failed")
            entries: list[PipeAccessEntry] = []
            for index in range(int(acl_info.AceCount)):
                ace_ptr = ctypes.c_void_p()
                if not get_ace(dacl, index, ctypes.byref(ace_ptr)) or not ace_ptr:
                    raise failed("GetAce failed")
                header = ctypes.cast(ace_ptr, ctypes.POINTER(AceHeader)).contents
                if header.AceSize < 12:
                    raise failed("ACE size invalid")
                mask = wintypes.DWORD.from_address(ace_ptr.value + 4).value
                entries.append(PipeAccessEntry(
                    ace_type=int(header.AceType),
                    ace_flags=int(header.AceFlags),
                    access_mask=int(mask),
                    sid=sid_string(ctypes.c_void_p(ace_ptr.value + 8)),
                ))
            pipe_owner_sid = sid_string(owner_sid)
            dacl_protected = bool(control.value & 0x1000)
        finally:
            local_free(security_descriptor)
        return PipeServerIdentity(
            server_pid=int(server_pid.value),
            pipe_server_session_id=int(pipe_session.value),
            process_session_id=int(process_session.value),
            current_session_id=int(current_session.value),
            server_user_sid=server_user_sid,
            current_user_sid=current_user_sid,
            server_logon_sid=server_logon_sid,
            current_logon_sid=current_logon_sid,
            pipe_owner_sid=pipe_owner_sid,
            dacl_protected=dacl_protected,
            dacl_entries=tuple(entries),
        )
    except RelayUnavailable:
        raise
    except (ImportError, OSError, OverflowError, ValueError) as exc:
        raise RelayUnavailable("RCC_PIPE_SERVER_IDENTITY_UNAVAILABLE") from exc


def verify_connected_pipe_server(pipe) -> None:
    validate_pipe_server_identity(_collect_windows_pipe_server_identity(pipe))


class RelayClient(Protocol):
    def request(
        self, *, instance_id: str, request_id: str, command: str,
        to: str = "", text: str = "", extra: dict[str, Any] | None = None,
        timeout_s: float = 30.0, before_write: Callable[[], None] | None = None,
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
        timeout_s: float = 30.0, before_write: Callable[[], None] | None = None,
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
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        path = PIPE_ROOT + PIPE_PREFIX + resolved
        try:
            pipe = open(path, "r+b", buffering=0)
        except OSError as exc:
            raise RelayUnavailable("RCC_PIPE_UNAVAILABLE") from exc
        write_started = False
        invoking_before_write = False
        try:
            with pipe:
                # Authenticate the connected server handle before policy fencing
                # and before the first request byte can leave this process.
                verify_connected_pipe_server(pipe)
                if before_write is not None:
                    invoking_before_write = True
                    before_write()
                    invoking_before_write = False
                # Once the write call begins, an exception cannot prove that
                # the OS accepted zero bytes. Treat every such failure as an
                # ambiguous external effect and recover by exact receipt lookup.
                write_started = True
                pipe.write(encoded)
                deadline = time.monotonic() + timeout_s
                pending = bytearray()
                while time.monotonic() < deadline:
                    raw = _read_line_until(pipe, deadline, pending)
                    if raw is None:
                        break
                    if not raw:
                        raise RelayEffectUnknown("RCC_PIPE_CLOSED_AFTER_DISPATCH")
                    message = json.loads(raw.decode("utf-8"))
                    message_type = message.get("type")
                    if (
                        message_type == "host:ack"
                        and command in {"send", "send-wakeback"}
                        and payload.get("returnOnAck") is True
                    ):
                        if message.get("requestId") != request_id:
                            continue
                        return message
                    if message_type != "host:result":
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
            if invoking_before_write:
                raise
            if write_started:
                raise RelayEffectUnknown("RCC_TRANSPORT_UNKNOWN_AFTER_DISPATCH") from exc
            raise RelayUnavailable("RCC_TRANSPORT_NOT_STARTED") from exc
        raise RelayEffectUnknown("RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH")
