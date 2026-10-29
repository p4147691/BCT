"""Read-only P2 preflight. No mutation, process signal or approval bypass.

These plans preserve Work/Operation authority but are NOT execution grants.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import psutil

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome, PreconditionError, Work,
)
from bct.features.common import is_reparse_point, resolve_in_work
from bct.integrations.native_process import process_fingerprint, process_matches


def _reject_original_reparse(value: Any) -> None:
    """Do not erase symlink/reparse identity before Work path resolution."""
    if not isinstance(value, str) or not value.strip():
        raise PreconditionError("FILE_PLAN_PATH_REQUIRED")
    raw = Path(value)
    if not raw.is_absolute():
        raise PreconditionError("FILE_PLAN_ABSOLUTE_PATH_REQUIRED")
    for candidate in (raw, *raw.parents):
        try:
            if is_reparse_point(candidate):
                raise PreconditionError("FILE_PLAN_REPARSE_PATH_FORBIDDEN")
        except OSError as exc:
            raise PreconditionError("FILE_PLAN_PATH_UNREADABLE") from exc


def _file_fingerprint(path: Path, *, max_bytes: int) -> dict[str, Any]:
    if not path.is_file() or is_reparse_point(path):
        raise PreconditionError("FILE_PLAN_SOURCE_NOT_REGULAR")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise PreconditionError("FILE_PLAN_SOURCE_UNREADABLE") from exc
    try:
        before = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise PreconditionError("FILE_PLAN_SOURCE_TOO_LARGE_OR_CHANGED")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        after = os.fstat(fd)
        try:
            path_info = os.stat(path)
        except OSError as exc:
            raise PreconditionError("FILE_PLAN_SOURCE_CHANGED") from exc
        current = (path_info.st_dev, path_info.st_ino, path_info.st_size, path_info.st_mtime_ns)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity or current != identity:
            raise PreconditionError("FILE_PLAN_SOURCE_CHANGED")
        if is_reparse_point(path):
            raise PreconditionError("FILE_PLAN_SOURCE_CHANGED")
        return {"bytes": before.st_size, "sha256": digest.hexdigest(),
                "device": before.st_dev, "inode": before.st_ino,
                "mtime_ns": before.st_mtime_ns}
    finally:
        os.close(fd)


class FileActionPlanFeature:
    """Plan an exact reversible file move/quarantine. Never performs it."""

    capability = "file_action_plan"
    _operations = frozenset({"move_preview", "quarantine_preview"})

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if set(arguments) != {"operation", "source", "destination"}:
            raise PreconditionError("FILE_PLAN_FIELDS_INVALID")
        kind = arguments["operation"]
        if kind not in self._operations:
            raise PreconditionError("FILE_PLAN_OPERATION_INVALID")
        _reject_original_reparse(arguments["source"])
        _reject_original_reparse(arguments["destination"])
        source = resolve_in_work(work, arguments["source"], must_exist=True)
        destination = resolve_in_work(work, arguments["destination"], must_exist=False)
        if not source.is_file() or is_reparse_point(source):
            raise PreconditionError("FILE_PLAN_SOURCE_NOT_REGULAR")
        if destination.exists() or destination.is_symlink():
            raise PreconditionError("FILE_PLAN_DESTINATION_EXISTS")
        parent = resolve_in_work(work, str(destination.parent), must_exist=True)
        if not parent.is_dir() or is_reparse_point(parent):
            raise PreconditionError("FILE_PLAN_DESTINATION_PARENT_INVALID")
        if source == destination or str(source).casefold() == str(destination).casefold():
            raise PreconditionError("FILE_PLAN_IDENTICAL_PATHS")
        return FeatureRequest(
            self.capability, f"plan:{kind}:{str(source).casefold()}",
            {"operation": kind, "source": str(source), "destination": str(destination)},
            ("file:" + str(source).casefold(),
             "file:" + str(destination).casefold()),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        source = Path(request.arguments["source"])
        destination = Path(request.arguments["destination"])
        if destination.exists() or destination.is_symlink():
            raise PreconditionError("FILE_PLAN_DESTINATION_CHANGED")
        if not destination.parent.is_dir() or is_reparse_point(destination.parent):
            raise PreconditionError("FILE_PLAN_DESTINATION_CHANGED")
        source_state = _file_fingerprint(source, max_bytes=64 * 1024 * 1024)
        parent_state = os.stat(destination.parent)
        if parent_state.st_dev != source_state["device"]:
            raise PreconditionError("FILE_PLAN_CROSS_DEVICE_UNSUPPORTED")
        payload = {"operation": request.arguments["operation"],
                   "source": str(source), "destination": str(destination),
                   "source_state": source_state, "destination_absent": True}
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        result = {**payload, "plan_sha256": digest,
                  "recovery": {"from": str(destination), "to": str(source)},
                  "read_only": True, "applied": False,
                  "apply_available": False,
                  "blocked_by": "APPROVAL_VERIFIER_UNAVAILABLE",
                  "destructive_delete_supported": False}
        return FeatureResult(
            Outcome.APPLIED, {"read_only": True, "applied": False,
                              "plan_sha256": digest, "source_bytes": source_state["bytes"]},
            output=result,
        )


class ProcessStopPlanFeature:
    """Inspect exact process identity; recommend existing owner-scoped stop."""

    capability = "process_stop_plan"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if set(arguments) - {"pid", "expected_created_at", "expected_executable"}:
            raise PreconditionError("PROCESS_STOP_PLAN_FIELDS_INVALID")
        pid = arguments.get("pid")
        if type(pid) is not int or pid <= 0:
            raise PreconditionError("PROCESS_STOP_PLAN_PID_INVALID")
        created = arguments.get("expected_created_at")
        if created is not None and (type(created) not in {int, float} or created <= 0):
            raise PreconditionError("PROCESS_STOP_PLAN_CREATED_INVALID")
        executable = arguments.get("expected_executable")
        if executable is not None and (
            not isinstance(executable, str) or not Path(executable).is_absolute()
            or len(executable) > 1024 or "\x00" in executable
        ):
            raise PreconditionError("PROCESS_STOP_PLAN_EXECUTABLE_INVALID")
        return FeatureRequest(
            self.capability, f"inspect:process:{pid}",
            {"pid": pid, "expected_created_at": created,
             "expected_executable": executable},
            (f"system:process:{pid}",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        pid = request.arguments["pid"]
        try:
            identity = process_fingerprint(pid)
            if not process_matches(identity):
                raise ConfirmedFailure("PROCESS_STOP_PLAN_IDENTITY_CHANGED", release_claims=True)
        except (psutil.Error, OSError, ValueError) as exc:
            if isinstance(exc, ConfirmedFailure):
                raise
            raise ConfirmedFailure("PROCESS_STOP_PLAN_NOT_OBSERVABLE", release_claims=True) from exc
        expected_created = request.arguments["expected_created_at"]
        if expected_created is not None and abs(float(identity["created_at"]) - expected_created) >= .001:
            raise PreconditionError("PROCESS_STOP_PLAN_EXPECTED_IDENTITY_MISMATCH")
        expected_exe = request.arguments["expected_executable"]
        if expected_exe is not None and os.path.normcase(identity["executable"]) != os.path.normcase(expected_exe):
            raise PreconditionError("PROCESS_STOP_PLAN_EXPECTED_IDENTITY_MISMATCH")
        result = {"process": identity, "read_only": True, "stopped": False,
                  "ownership_verified": False, "stop_available": False,
                  "blocked_by": "APPROVAL_VERIFIER_AND_OWNERSHIP_NOT_CONFIRMED",
                  "suggested_existing_operation": "process_session.stop for an exact owned session"}
        return FeatureResult(
            Outcome.APPLIED,
            {"read_only": True, "stopped": False,
             "pid": pid, "created_at": identity["created_at"]},
            output=result,
        )
