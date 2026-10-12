from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work

from .common import resolve_in_work, sha256_file


class FileReadFeature:
    capability = "read"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        path = resolve_in_work(work, str(arguments.get("path") or ""), must_exist=True)
        if not path.is_file():
            raise PreconditionError("READ_TARGET_NOT_FILE")
        return FeatureRequest(self.capability, str(path), {"path": str(path)}, ("file:" + str(path).casefold(),))

    def execute(self, request: FeatureRequest) -> FeatureResult:
        path = Path(request.target)
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
