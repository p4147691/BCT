from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work

from .common import is_reparse_point, resolve_in_work, sha256_file


class FileReadFeature:
    capability = "read"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "file").strip().casefold()
        if operation not in {"file", "directory_tree"}:
            raise PreconditionError("READ_OPERATION_INVALID")
        path = resolve_in_work(work, str(arguments.get("path") or ""), must_exist=True)
        if operation == "file":
            if not path.is_file():
                raise PreconditionError("READ_TARGET_NOT_FILE")
            return FeatureRequest(
                self.capability, str(path), {"operation": operation, "path": str(path)},
                ("file:" + str(path).casefold(),),
            )
        if not path.is_dir() or path.is_symlink():
            raise PreconditionError("READ_TARGET_NOT_DIRECTORY")
        depth_value = arguments.get("depth", 2)
        limit_value = arguments.get("limit", 200)
        if isinstance(depth_value, bool) or isinstance(limit_value, bool):
            raise PreconditionError("READ_TREE_BOUNDS_INVALID")
        try:
            depth = int(depth_value)
            limit = int(limit_value)
        except (TypeError, ValueError) as exc:
            raise PreconditionError("READ_TREE_BOUNDS_INVALID") from exc
        if not 0 <= depth <= 6 or not 1 <= limit <= 1000:
            raise PreconditionError("READ_TREE_BOUNDS_INVALID")
        return FeatureRequest(
            self.capability, str(path),
            {"operation": operation, "path": str(path), "depth": depth, "limit": limit},
            ("directory:" + str(path).casefold(),),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        path = Path(request.target)
        if request.arguments["operation"] == "directory_tree":
            entries: list[dict[str, str]] = []
            pending: list[tuple[Path, int]] = [(path, 0)]
            truncated = False
            while pending and not truncated:
                current, level = pending.pop()
                try:
                    children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
                except OSError as exc:
                    entries.append({
                        "path": current.relative_to(path).as_posix() or ".",
                        "kind": "unreadable", "error": type(exc).__name__,
                    })
                    continue
                directories: list[tuple[Path, int]] = []
                for child in children:
                    if len(entries) >= request.arguments["limit"]:
                        truncated = True
                        break
                    relative = child.relative_to(path).as_posix()
                    if is_reparse_point(child):
                        kind = "symlink"
                    elif child.is_dir():
                        kind = "directory"
                        if level < request.arguments["depth"]:
                            directories.append((child, level + 1))
                    elif child.is_file():
                        kind = "file"
                    else:
                        kind = "other"
                    entries.append({"path": relative, "kind": kind})
                pending.extend(reversed(directories))
            return FeatureResult(
                Outcome.APPLIED,
                {
                    "operation": "directory_tree", "path": str(path), "depth": request.arguments["depth"],
                    "entries": len(entries), "truncated": truncated,
                },
                output={"entries": entries, "truncated": truncated},
            )
        data = path.read_text(encoding="utf-8")
        return FeatureResult(
            Outcome.APPLIED,
            {"path": str(path), "sha256": sha256_file(path), "characters": len(data)},
            output={"text": data},
        )


class FileWriteFeature:
    capability = "write"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        path = resolve_in_work(work, str(arguments.get("path") or ""), must_exist=False)
        content = arguments.get("content")
        expected_sha = arguments.get("expected_sha256")
        expected_absent = bool(arguments.get("expected_absent", False))
        if not isinstance(content, str):
            raise PreconditionError("CONTENT_MUST_BE_TEXT")
        if expected_absent == bool(expected_sha):
            raise PreconditionError("EXACTLY_ONE_WRITE_PRECONDITION_REQUIRED")
        if expected_sha is not None and (not isinstance(expected_sha, str) or len(expected_sha) != 64):
            raise PreconditionError("BAD_EXPECTED_SHA256")
        return FeatureRequest(
            self.capability, str(path),
            {"path": str(path), "content": content, "expected_sha256": expected_sha,
             "expected_absent": expected_absent},
            ("file:" + str(path).casefold(),),
            {"expected_sha256": expected_sha, "expected_absent": expected_absent},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        path = Path(request.target)
        expected = request.preconditions.get("expected_sha256")
        expected_absent = request.preconditions.get("expected_absent")
        if expected_absent:
            if path.exists():
                raise PreconditionError("WRITE_TARGET_ALREADY_EXISTS")
        else:
            if not path.is_file() or path.is_symlink():
                raise PreconditionError("WRITE_TARGET_NOT_REGULAR_FILE")
            if sha256_file(path) != expected:
                raise PreconditionError("WRITE_SHA_MISMATCH")
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = request.arguments["content"].encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=".bct-write-", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return FeatureResult(Outcome.APPLIED, {"path": str(path), "sha256": sha256_file(path), "bytes": len(encoded)})
