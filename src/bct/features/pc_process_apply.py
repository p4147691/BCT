"""Stop an exact owned BCT process-session child, never an arbitrary PID.

Graceful sends WM_CLOSE only to exact owned GUI HWNDs; force is a distinct
signed request digest and allowed only with a new one-shot user grant.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import psutil

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
    PreconditionError, UnknownEffectError, Work,
)
from bct.features.process_session import ProcessSessionFeature
from bct.service_runtime import process_identity
from bct.features.pc_safe_apply import _protected


def _windows_session_id(pid: int) -> int | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    session = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session)):
        raise PreconditionError("PROCESS_STOP_SESSION_UNOBSERVABLE")
    return int(session.value)


def _request_close(pid: int) -> int:
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    seen = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    @callback_type
    def callback(hwnd, extra):
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == pid and user32.IsWindowVisible(hwnd):
            seen.append(hwnd)
        return True

    if not user32.EnumWindows(callback, 0):
        return 0
    for hwnd in seen:
        if not user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE, not process.kill
            raise UnknownEffectError("PROCESS_CLOSE_MESSAGE_UNKNOWN")
    return len(seen)


class ProcessStopApplyFeature:
    capability = "process_stop_apply"

    def __init__(self, sessions: ProcessSessionFeature, store):
        self.sessions = sessions
        self.store = store

    def _proven_start(self, *, operation_id: str, work_id: str,
                      principal_id: str, session_id: str, child: dict) -> None:
        try:
            original = self.store.get_operation_metadata_for(
                operation_id=operation_id, work_id=work_id,
                principal_id=principal_id,
            )
        except (KeyError, ValueError) as exc:
            raise PreconditionError("PROCESS_STOP_START_RECEIPT_NOT_FOUND") from exc
        evidence = original.get("evidence", {})
        observed = evidence.get("session") if isinstance(evidence, dict) else None
        if (original.get("capability") != "process_session"
                or original.get("target") != session_id
                or original.get("state") != "FINISHED"
                or original.get("outcome") != "APPLIED"
                or not isinstance(observed, dict)
                or observed.get("session_id") != session_id
                or observed.get("work_id") != work_id
                or observed.get("process") != child):
            raise PreconditionError("PROCESS_STOP_ORIGIN_NOT_PROVEN")

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if set(arguments) != {
            "session_id", "start_operation_id", "expected_fingerprint", "mode"
        }:
            raise PreconditionError("PROCESS_STOP_APPLY_FIELDS_INVALID")
        mode = arguments["mode"]
        if mode not in {"graceful", "force"}:
            raise PreconditionError("PROCESS_STOP_APPLY_MODE_INVALID")
        session_id = arguments["session_id"]
        if not isinstance(session_id, str):
            raise PreconditionError("PROCESS_STOP_SESSION_ID_INVALID")
        directory, receipt = self.sessions._owned_receipt(work, session_id)
        child = receipt.get("process")
        start_id = arguments["start_operation_id"]
        if (not isinstance(start_id, str) or not start_id
                or len(start_id) > 120):
            raise PreconditionError("PROCESS_STOP_START_OPERATION_INVALID")
        if not isinstance(child, dict):
            raise PreconditionError("PROCESS_STOP_CHILD_NOT_OWNED")
        self._proven_start(
            operation_id=start_id, work_id=work.work_id,
            principal_id=work.owner_principal_id,
            session_id=session_id, child=child,
        )
        expected = arguments["expected_fingerprint"]
        if not isinstance(expected, str) or len(expected) != 64 or expected != child.get("fingerprint"):
            raise PreconditionError("PROCESS_STOP_FINGERPRINT_MISMATCH")
        pid = child.get("pid")
        if type(pid) is not int or pid <= 0:
            raise PreconditionError("PROCESS_STOP_PID_INVALID")
        return FeatureRequest(
            self.capability, f"stop:{mode}:{session_id}:{pid}",
            {"session_id": session_id, "pid": pid, "mode": mode,
             "start_operation_id": start_id,
             "expected_identity": child, "work_id": work.work_id,
             "principal_id": work.owner_principal_id},
            (f"process-session:{session_id.casefold()}",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        pid, session_id = values["pid"], values["session_id"]
        if pid in {os.getpid(), os.getppid()}:
            raise PreconditionError("PROCESS_STOP_CURRENT_OR_PARENT_PROTECTED")
        receipt_dir, receipt = self.sessions._owned_receipt(
            Work(values["work_id"], "verify", (), frozenset(), ""), session_id,
        )
        # Exact persisted identity, including executable and creation marker.
        if receipt.get("process") != values["expected_identity"]:
            raise PreconditionError("PROCESS_STOP_RECEIPT_CHANGED")
        self._proven_start(
            operation_id=values["start_operation_id"],
            work_id=values["work_id"],
            principal_id=values["principal_id"],
            session_id=session_id,
            child=values["expected_identity"],
        )
        live = process_identity(pid)
        if live is None or live.as_dict() != values["expected_identity"]:
            raise PreconditionError("PROCESS_STOP_IDENTITY_CHANGED")
        proc = psutil.Process(pid)
        name = proc.name().casefold()
        if (any(word in name for word in ("bct", "chrome", "rcc", "monitor", "runner", "code"))
                or _protected(Path(live.executable))):
            raise PreconditionError("PROCESS_STOP_OPERATING_PROCESS_PROTECTED")
        if proc.username().casefold() != psutil.Process(os.getpid()).username().casefold():
            raise PreconditionError("PROCESS_STOP_DIFFERENT_USER")
        if os.name == "nt" and _windows_session_id(pid) != _windows_session_id(os.getpid()):
            raise PreconditionError("PROCESS_STOP_DIFFERENT_SESSION")
        if proc.children(recursive=True):
            raise PreconditionError("PROCESS_STOP_DESCENDANTS_PRESENT")
        if os.name != "nt":
            raise PreconditionError("PROCESS_STOP_WINDOWS_ONLY")
        if values["mode"] == "graceful":
            count = _request_close(pid)
            if count == 0:
                raise PreconditionError("PROCESS_STOP_NO_GUI_WINDOW_FOR_GRACEFUL_CLOSE")
        else:
            # This force operation requires a DIFFERENT exact signed approval
            # token (mode is part of the request digest). Never fall back.
            try:
                proc.kill()
            except psutil.Error as exc:
                raise UnknownEffectError("PROCESS_FORCE_STOP_EFFECT_UNKNOWN") from exc
        try:
            proc.wait(timeout=2.5)
        except psutil.TimeoutExpired as exc:
            raise UnknownEffectError("PROCESS_STOP_EFFECT_NOT_CONFIRMED") from exc
        # PID reuse cannot be mistaken for successful stop.
        if process_identity(pid) == live:
            raise UnknownEffectError("PROCESS_STOP_IDENTITY_STILL_PRESENT")
        result = {"pid": pid, "mode": values["mode"], "stopped": True,
                  "session_id": session_id, "birth_fingerprint": live.fingerprint,
                  "descendants_affected": 0, "recovery_possible": False}
        return FeatureResult(Outcome.APPLIED, result, output=result)
