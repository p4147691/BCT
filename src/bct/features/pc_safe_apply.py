"""Approval-gated exact file effects: move, reversible quarantine and restore.

One file per operation, no recursion, no overwrite and no permanent delete.
"""
from __future__ import annotations

import os
from pathlib import Path

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
    PreconditionError, UnknownEffectError, Work,
)
from bct.features.common import resolve_in_work, is_reparse_point
from bct.features.pc_safe_plans import (
    _file_fingerprint, _reject_original_reparse,
)


def _protected(path: Path) -> bool:
    """Never alter BCT/OS/app-runtime directories with this P2 capability."""
    fixed = [r"D:\BCT", r"C:\Windows", r"C:\Program Files",
             r"C:\Program Files (x86)", r"C:\ProgramData"]
    fixed += [os.environ.get(key, "") for key in
              ("WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA")]
    target = os.path.normcase(str(path.resolve(strict=False)))
    for raw in fixed:
        if raw:
            protected = os.path.normcase(str(Path(raw).resolve(strict=False)))
            if target == protected or target.startswith(protected + os.sep):
                return True
    return False


class FileActionApplyFeature:
    capability = "file_action_apply"
    _allowed = {"move": "move_preview",
                "recoverable_delete": "quarantine_preview",
                "restore": "move_preview"}

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if set(arguments) != {"operation", "source", "destination", "plan_sha256"}:
            raise PreconditionError("FILE_APPLY_FIELDS_INVALID")
        operation = arguments["operation"]
        if operation not in self._allowed:
            raise PreconditionError("FILE_APPLY_OPERATION_INVALID")
        _reject_original_reparse(arguments["source"])
        _reject_original_reparse(arguments["destination"])
        # Stable request identity even AFTER a successful move: the source may
        # be absent and destination may exist on exact duplicate replay.
        source = resolve_in_work(work, arguments["source"], must_exist=False)
        destination = resolve_in_work(work, arguments["destination"], must_exist=False)
        expected = arguments["plan_sha256"]
        if not isinstance(expected, str) or len(expected) != 64 or any(
            c not in "0123456789abcdef" for c in expected
        ):
            raise PreconditionError("FILE_APPLY_PLAN_HASH_REQUIRED")
        if _protected(source) or _protected(destination):
            raise PreconditionError("FILE_APPLY_PROTECTED_PATH")
        if str(source).casefold() == str(destination).casefold():
            raise PreconditionError("FILE_APPLY_IDENTICAL_PATHS")
        preview = {"operation": self._allowed[operation],
                   "source": str(source), "destination": str(destination)}
        return FeatureRequest(
            self.capability, "apply:" + operation + ":" + str(source).casefold(),
            {"operation": operation, "source": str(source),
             "destination": str(destination), "expected_plan_sha256": expected,
             "preview": preview},
            ("file:" + str(source).casefold(),
             "file:" + str(destination).casefold()),
            {"expected_plan_sha256": expected},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        from bct.core.models import Work
        # Prepared preview was work-scoped. Rebuild only its immutable observed
        # content; never treat the provided plan hash as proof without rechecking.
        values = request.arguments
        src, dst = Path(values["source"]), Path(values["destination"])
        if _protected(src) or _protected(dst):
            raise PreconditionError("FILE_APPLY_PROTECTED_PATH")
        if dst.exists() or dst.is_symlink() or is_reparse_point(dst):
            raise PreconditionError("FILE_APPLY_DESTINATION_OCCUPIED")
        if not dst.parent.is_dir() or is_reparse_point(dst.parent):
            raise PreconditionError("FILE_APPLY_DESTINATION_PARENT_CHANGED")
        from hashlib import sha256
        import json
        before = _file_fingerprint(src, max_bytes=64 * 1024 * 1024)
        if os.stat(dst.parent).st_dev != before["device"]:
            raise PreconditionError("FILE_APPLY_CROSS_DEVICE")
        payload = {"operation": values["preview"]["operation"],
                   "source": str(src), "destination": str(dst),
                   "source_state": before, "destination_absent": True}
        actual_plan_sha = sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()
        if actual_plan_sha != values["expected_plan_sha256"]:
            raise PreconditionError("FILE_APPLY_PLAN_CHANGED")
        # os.rename is NO-OVERWRITE on Windows. This feature is Windows-only;
        # no POSIX fallback where rename can replace the destination.
        if os.name != "nt":
            raise PreconditionError("FILE_APPLY_WINDOWS_ONLY")
        try:
            os.rename(src, dst)
        except OSError as exc:
            if src.is_file() and not dst.exists():
                raise ConfirmedFailure("FILE_APPLY_NOT_APPLIED", release_claims=True) from exc
            raise UnknownEffectError("FILE_APPLY_OUTCOME_UNKNOWN") from exc
        # Post-move source absence and matching destination hash are required.
        try:
            after = _file_fingerprint(dst, max_bytes=64 * 1024 * 1024)
        except (OSError, PreconditionError) as exc:
            raise UnknownEffectError("FILE_APPLY_DESTINATION_UNVERIFIED") from exc
        if src.exists() or after["sha256"] != before["sha256"] or after["bytes"] != before["bytes"]:
            raise UnknownEffectError("FILE_APPLY_POSTCONDITION_UNKNOWN")
        result = {
            "operation": values["operation"], "source": str(src),
            "destination": str(dst), "sha256": after["sha256"],
            "bytes": after["bytes"], "restorable": True,
            "recovery": {"source": str(dst), "destination": str(src),
                         "requires_new_signed_approval": True},
            "applied": True,
        }
        return FeatureResult(Outcome.APPLIED, result, output=result)
