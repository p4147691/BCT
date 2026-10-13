from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work

from .common import is_reparse_point, resolve_in_work, sha256_file


class FileReadFeature:
    capability = "read"
    batch_max_items = 20
    batch_max_file_bytes = 512 * 1024
    batch_max_total_bytes = 1024 * 1024
    batch_max_tree_entries = 2000

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "file").strip().casefold()
        if operation not in {"file", "directory_tree", "batch"}:
            raise PreconditionError("READ_OPERATION_INVALID")
        if operation == "batch":
            return self._prepare_batch(work=work, arguments=arguments)
        normalized, resource = self._prepare_item(work=work, arguments=arguments)
        return FeatureRequest(
            self.capability, normalized["path"], normalized, (resource,),
        )

    def _prepare_batch(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        items = arguments.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= self.batch_max_items:
            raise PreconditionError("READ_BATCH_ITEMS_INVALID")
        normalized_items: list[dict[str, Any]] = []
        resources: list[str] = []
        identifiers: set[str] = set()
        targets: set[tuple[str, str]] = set()
        total_file_bytes = 0
        total_tree_entries = 0
        for item in items:
            if not isinstance(item, dict):
                raise PreconditionError("READ_BATCH_ITEM_INVALID")
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier.strip()) > 128:
                raise PreconditionError("READ_BATCH_ITEM_ID_REQUIRED")
            identifier = identifier.strip()
            if identifier in identifiers:
                raise PreconditionError("READ_BATCH_ITEM_ID_DUPLICATE")
            normalized, resource = self._prepare_item(work=work, arguments=item)
            target = (normalized["operation"], normalized["path"].casefold())
            if target in targets:
                raise PreconditionError("READ_BATCH_TARGET_DUPLICATE")
            if normalized["operation"] == "file":
                try:
                    size = Path(normalized["path"]).stat().st_size
                except OSError as exc:
                    raise PreconditionError("READ_TARGET_CHANGED") from exc
                if size > self.batch_max_file_bytes:
                    raise PreconditionError("READ_BATCH_FILE_TOO_LARGE")
                total_file_bytes += size
                if total_file_bytes > self.batch_max_total_bytes:
                    raise PreconditionError("READ_BATCH_TOTAL_BYTES_EXCEEDED")
            else:
                total_tree_entries += normalized["limit"]
                if total_tree_entries > self.batch_max_tree_entries:
                    raise PreconditionError("READ_BATCH_TREE_LIMIT_EXCEEDED")
            identifiers.add(identifier)
            targets.add(target)
            normalized_items.append({"id": identifier, **normalized})
            resources.append(resource)
        return FeatureRequest(
            self.capability,
            "batch:" + str(len(normalized_items)),
            {"operation": "batch", "items": normalized_items},
            tuple(resources),
        )

    @staticmethod
    def _prepare_item(*, work: Work, arguments: dict[str, Any]) -> tuple[dict[str, Any], str]:
        operation = str(arguments.get("operation") or "file").strip().casefold()
        if operation not in {"file", "directory_tree"}:
            raise PreconditionError("READ_BATCH_NESTED_OPERATION_INVALID")
        path = resolve_in_work(work, str(arguments.get("path") or ""), must_exist=True)
        if operation == "file":
            if not path.is_file():
                raise PreconditionError("READ_TARGET_NOT_FILE")
            return {"operation": operation, "path": str(path)}, "file:" + str(path).casefold()
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
        return (
            {"operation": operation, "path": str(path), "depth": depth, "limit": limit},
            "directory:" + str(path).casefold(),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments["operation"] == "batch":
            return self._execute_batch(request.arguments["items"])
        evidence, output = self._execute_item(request.arguments)
        return FeatureResult(
            Outcome.APPLIED,
            evidence,
            output=output,
        )

    def _execute_batch(self, items: list[dict[str, Any]]) -> FeatureResult:
        evidence_items: list[dict[str, Any]] = []
        output_items: list[dict[str, Any]] = []
        total_bytes = 0
        total_entries = 0
        failures = 0
        for item in items:
            base = {"id": item["id"], "operation": item["operation"], "path": item["path"]}
            try:
                evidence, output = self._execute_item(item)
                item_bytes = int(evidence.get("bytes", 0))
                item_entries = int(evidence.get("entries", 0))
                if total_bytes + item_bytes > self.batch_max_total_bytes:
                    raise PreconditionError("READ_BATCH_TOTAL_BYTES_EXCEEDED")
                total_bytes += item_bytes
                total_entries += item_entries
                item_evidence = {**base, "status": "OK", **evidence}
                evidence_items.append(item_evidence)
                output_items.append({**item_evidence, "output": output})
            except (OSError, UnicodeError, PreconditionError) as exc:
                failures += 1
                code = (
                    str(exc) if isinstance(exc, PreconditionError)
                    else "READ_BATCH_ITEM_IO_FAILED:" + type(exc).__name__
                )
                item_evidence = {**base, "status": "ERROR", "code": code, "observed_at": time.time()}
                evidence_items.append(item_evidence)
                output_items.append(item_evidence)
        status = "COMPLETE" if failures == 0 else "PARTIAL_FAILURE"
        return FeatureResult(
            Outcome.APPLIED if failures == 0 else Outcome.FAILED,
            {
                "operation": "batch", "status": status, "items": evidence_items,
                "items_requested": len(items), "items_succeeded": len(items) - failures,
                "items_failed": failures, "total_bytes": total_bytes, "total_entries": total_entries,
            },
            output={"status": status, "items": output_items},
        )

    def _execute_item(self, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        path = Path(item["path"])
        if item["operation"] == "directory_tree":
            if not path.is_dir() or is_reparse_point(path):
                raise PreconditionError("READ_TARGET_CHANGED")
            entries, truncated = self._directory_tree(path, depth=item["depth"], limit=item["limit"])
            observed_at = time.time()
            return (
                {
                    "operation": "directory_tree", "path": str(path), "depth": item["depth"],
                    "entries": len(entries), "truncated": truncated, "observed_at": observed_at,
                },
                {"entries": entries, "truncated": truncated},
            )
        if not path.is_file() or is_reparse_point(path):
            raise PreconditionError("READ_TARGET_CHANGED")
        raw = path.read_bytes()
        if len(raw) > self.batch_max_file_bytes and "id" in item:
            raise PreconditionError("READ_BATCH_FILE_TOO_LARGE")
        # Preserve Path.read_text()'s existing universal-newline response contract while
        # deriving the receipt hash from the exact bytes observed by this same read.
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        observed_at = time.time()
        return (
            {
                "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "characters": len(text), "observed_at": observed_at,
            },
            {"text": text},
        )

    @staticmethod
    def _directory_tree(path: Path, *, depth: int, limit: int) -> tuple[list[dict[str, str]], bool]:
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
                if len(entries) >= limit:
                    truncated = True
                    break
                relative = child.relative_to(path).as_posix()
                if is_reparse_point(child):
                    kind = "symlink"
                elif child.is_dir():
                    kind = "directory"
                    if level < depth:
                        directories.append((child, level + 1))
                elif child.is_file():
                    kind = "file"
                else:
                    kind = "other"
                entries.append({"path": relative, "kind": kind})
            pending.extend(reversed(directories))
        return entries, truncated


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
