"""Normal local PC actions that reuse exact P2 effects and BCT Work receipts.

Move and rename require explicit Work authority and exact source/destination.
Recoverable deletion requires a visible Windows YES/NO prompt; fail closed
without an interactive desktop. Protected files and permanent delete excluded.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from bct.core.models import FeatureRequest, FeatureResult, PreconditionError, Work
from bct.features.common import resolve_in_work
from bct.features.pc_safe_apply import FileActionApplyFeature, _protected
from bct.features.pc_safe_plans import (
    FileActionPlanFeature, _reject_original_reparse,
)
from bct.features.pc_process_apply import ProcessStopApplyFeature


def _confirm_recoverable_delete(*, source: str, destination: str,
                                sha256: str, bytes_count: int) -> bool:
    """Bounded interaction in the invoking process's own visible user desktop.

    There is no unattended approval flag or command-line 'yes' shortcut.
    A headless Core/session-0 execution returns NOT_APPLIED, never approval.
    """
    if os.name != "nt":
        raise PreconditionError("LOCAL_DELETE_WINDOWS_INTERACTIVE_REQUIRED")
    # subprocess return code is only a human GUI answer, never an effect.
    child_code = r'''
import ctypes
import sys
from ctypes import wintypes
u = ctypes.WinDLL("user32", use_last_error=True)
u.GetProcessWindowStation.restype = wintypes.HANDLE
w = u.GetProcessWindowStation()
class USEROBJECTFLAGS(ctypes.Structure):
    _fields_ = [("fInherit", wintypes.BOOL), ("fReserved", wintypes.BOOL),
                ("dwFlags", wintypes.DWORD)]
flags = USEROBJECTFLAGS()
length = wintypes.DWORD(0)
if not w or not u.GetUserObjectInformationW(w, 1, ctypes.byref(flags),
                                             ctypes.sizeof(flags), ctypes.byref(length)):
    sys.exit(3)
if not flags.dwFlags & 1:
    sys.exit(3)
title = "BCT — 복구 가능한 삭제 확인"
details = sys.stdin.read(8192)
u.MessageBoxW.argtypes = [wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.UINT]
u.MessageBoxW.restype = ctypes.c_int
reply = u.MessageBoxW(None, details, title, 0x00000004 | 0x00000100 | 0x00040000)
sys.exit(0 if reply == 6 else 2)
'''
    message = (
        "다음 파일을 복구 보관함으로 이동합니다.\n\n"
        f"원본:\n{source}\n\n"
        f"복구 위치:\n{destination}\n\n"
        f"크기: {bytes_count} bytes\nSHA-256: {sha256}\n\n"
        "삭제하시겠습니까? (영구 삭제 아님)\n"
        "취소/닫기/시간 초과는 변경하지 않습니다."
    )
    if len(message) > 8192:
        raise PreconditionError("LOCAL_DELETE_CONFIRMATION_TOO_LARGE")
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-c", child_code],
            input=message, text=True, capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise PreconditionError("LOCAL_DELETE_CONFIRMATION_UNAVAILABLE") from exc
    if process.returncode == 0:
        return True
    if process.returncode == 2:
        return False
    raise PreconditionError("LOCAL_DELETE_INTERACTIVE_SESSION_UNAVAILABLE")


class LocalFileActionFeature:
    capability = "file_local_action"
    _allowed = frozenset({"move", "rename", "restore", "recoverable_delete"})

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        op = arguments.get("operation")
        if op not in self._allowed:
            raise PreconditionError("LOCAL_FILE_OPERATION_INVALID")
        expected = {"operation", "source"} if op == "recoverable_delete" else {
            "operation", "source", "destination",
        }
        if set(arguments) != expected:
            raise PreconditionError("LOCAL_FILE_FIELDS_INVALID")
        _reject_original_reparse(arguments["source"])
        source = resolve_in_work(work, arguments["source"], must_exist=False)
        if op == "recoverable_delete":
            destination = source.parent / ".bct-recovery" / source.name
            # Same Work and same volume. No free-form trash destination.
            destination = resolve_in_work(work, str(destination), must_exist=False)
        else:
            _reject_original_reparse(arguments["destination"])
            destination = resolve_in_work(work, arguments["destination"], must_exist=False)
        if _protected(source) or _protected(destination):
            raise PreconditionError("LOCAL_FILE_PROTECTED_PATH")
        if source == destination or str(source).casefold() == str(destination).casefold():
            raise PreconditionError("LOCAL_FILE_IDENTICAL_TARGET")
        if op == "rename" and source.parent != destination.parent:
            raise PreconditionError("LOCAL_RENAME_MUST_STAY_IN_DIRECTORY")
        return FeatureRequest(
            self.capability, f"local:{op}:{str(source).casefold()}",
            {"operation": op, "source": str(source), "destination": str(destination),
             "work_id": work.work_id},
            ("file:" + str(source).casefold(), "file:" + str(destination).casefold()),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        args = request.arguments
        op = args["operation"]
        source, destination = Path(args["source"]), Path(args["destination"])
        if _protected(source) or _protected(destination):
            raise PreconditionError("LOCAL_FILE_PROTECTED_PATH")
        if op == "recoverable_delete":
            if (destination.parent != source.parent / ".bct-recovery"
                    or destination.name != source.name):
                raise PreconditionError("LOCAL_DELETE_RECOVERY_PATH_INVALID")
            if destination.parent.exists() and not destination.parent.is_dir():
                raise PreconditionError("LOCAL_DELETE_RECOVERY_PARENT_OCCUPIED")
        # FileActionPlanFeature enforces same Work paths, file identity, no
        # overwrite, no symlinks, same-volume, and SHA-256 preflight.
        # No effect occurs before the confirmation.
        if not source.is_file():
            raise PreconditionError("LOCAL_FILE_SOURCE_NOT_FOUND")
        if destination.exists() or destination.is_symlink():
            raise PreconditionError("LOCAL_FILE_DESTINATION_OCCUPIED")
        if destination.parent.exists():
            plan = FileActionPlanFeature()
            pseudo = Work(args["work_id"], "local-apply", (str(source.parent), str(destination.parent)),
                          frozenset({"file_action_plan"}), "local")
            preview = plan.execute(plan.prepare(work=pseudo, arguments={
                "operation": "quarantine_preview" if op == "recoverable_delete" else "move_preview",
                "source": str(source), "destination": str(destination),
            })).output
        else:
            # A new recovery folder is permitted only for the fixed
            # recoverable-delete destination. Do not create it before YES.
            if op != "recoverable_delete":
                raise PreconditionError("LOCAL_FILE_DESTINATION_PARENT_MISSING")
            from bct.features.pc_safe_plans import _file_fingerprint
            preview = {"source_state": _file_fingerprint(source, max_bytes=64*1024*1024)}
            source_stat = os.stat(source)
            if source_stat.st_dev != os.stat(source.parent).st_dev:
                raise PreconditionError("LOCAL_FILE_CROSS_DEVICE")
        if op == "recoverable_delete":
            state = preview["source_state"]
            if not _confirm_recoverable_delete(
                    source=str(source), destination=str(destination),
                    sha256=state["sha256"], bytes_count=state["bytes"]):
                raise PreconditionError("LOCAL_DELETE_USER_DECLINED")
            if not destination.parent.exists():
                destination.parent.mkdir(mode=0o700)
        # Recompute a fresh exact plan AFTER approval, protecting races.
        planner = FileActionPlanFeature()
        pseudo = Work(args["work_id"], "local-apply", (str(source.parent), str(destination.parent)),
                      frozenset({"file_action_plan"}), "local")
        plan_result = planner.execute(planner.prepare(work=pseudo, arguments={
            "operation": "quarantine_preview" if op == "recoverable_delete" else "move_preview",
            "source": str(source), "destination": str(destination),
        }))
        if op == "recoverable_delete" and plan_result.output["source_state"] != preview["source_state"]:
            raise PreconditionError("LOCAL_DELETE_SOURCE_CHANGED_DURING_CONFIRMATION")
        apply = FileActionApplyFeature()
        actual_mode = "recoverable_delete" if op == "recoverable_delete" else "restore" if op == "restore" else "move"
        prepared = apply.prepare(work=pseudo, arguments={
            "operation": actual_mode, "source": str(source),
            "destination": str(destination),
            "plan_sha256": plan_result.output["plan_sha256"],
        })
        result = apply.execute(prepared)
        result.evidence["local_mode"] = True
        result.evidence["user_confirmation"] = ("YES" if op == "recoverable_delete" else "NOT_REQUIRED")
        return result


class LocalProcessStopFeature:
    capability = "process_local_stop"

    def __init__(self, strict: ProcessStopApplyFeature):
        self.strict = strict

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if set(arguments) != {"session_id", "start_operation_id", "expected_fingerprint"}:
            raise PreconditionError("LOCAL_PROCESS_FIELDS_INVALID")
        strict = self.strict.prepare(work=work, arguments={**arguments, "mode": "graceful"})
        return FeatureRequest(
            self.capability, strict.target,
            strict.arguments, strict.resources, strict.preconditions,
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments.get("mode") != "graceful":
            raise PreconditionError("LOCAL_PROCESS_FORCE_NOT_ALLOWED")
        return self.strict.execute(request)
