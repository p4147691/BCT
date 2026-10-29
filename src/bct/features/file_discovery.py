"""Bounded, work-scoped read-only file discovery and duplicate evidence.

This module never renames, moves, writes or deletes target files.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
import time
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from .common import is_reparse_point, resolve_in_work


def _positive_int(value: Any, code: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise PreconditionError(code)
    return value


def prepare(work: Work, values: dict[str, Any]) -> FeatureRequest:
    operation = values["operation"]
    allowed = {"operation", "path", "depth", "max_entries", "query", "limit",
               "max_hash_bytes", "timeout_seconds"}
    if set(values) - allowed:
        raise PreconditionError("READ_DISCOVERY_FIELDS_INVALID")
    root = resolve_in_work(work, values.get("path"), must_exist=True)
    if not root.is_dir() or is_reparse_point(root):
        raise PreconditionError("READ_DISCOVERY_DIRECTORY_REQUIRED")
    depth = values.get("depth", 3)
    if type(depth) is not int or not 0 <= depth <= 6:
        raise PreconditionError("READ_DISCOVERY_DEPTH_INVALID")
    max_entries = _positive_int(values.get("max_entries", 500),
                                "READ_DISCOVERY_MAX_ENTRIES_INVALID", 2000)
    limit = _positive_int(values.get("limit", 100),
                          "READ_DISCOVERY_LIMIT_INVALID", 500)
    timeout_seconds = _positive_int(values.get("timeout_seconds", 10),
                                    "READ_DISCOVERY_TIMEOUT_INVALID", 25)
    query = values.get("query", "")
    if not isinstance(query, str) or len(query) > 200 or "\x00" in query:
        raise PreconditionError("READ_DISCOVERY_QUERY_INVALID")
    if operation == "search":
        if not query.strip() or "/" in query or "\\" in query:
            raise PreconditionError("READ_DISCOVERY_QUERY_INVALID")
        if "max_hash_bytes" in values:
            raise PreconditionError("READ_DISCOVERY_FIELDS_INVALID")
        max_hash_bytes = 0
    else:
        if query:
            raise PreconditionError("READ_DISCOVERY_FIELDS_INVALID")
        max_hash_bytes = _positive_int(values.get("max_hash_bytes", 256 * 1024 * 1024),
                                      "READ_DUPLICATES_HASH_BUDGET_INVALID",
                                      8 * 1024 * 1024 * 1024)
    normalized = {"operation": operation, "path": str(root), "depth": depth,
                  "max_entries": max_entries, "limit": limit,
                  "query": query.strip(), "timeout_seconds": timeout_seconds,
                  "max_hash_bytes": max_hash_bytes}
    return FeatureRequest("read", str(root), normalized,
                          ("directory:" + str(root).casefold(),))


def _scan(root: Path, depth: int, max_entries: int, deadline: float):
    rows = []
    stack = [(root, 0)]
    truncated = False
    problems = 0
    while stack:
        if len(rows) >= max_entries or time.monotonic() >= deadline:
            truncated = True
            break
        folder, level = stack.pop()
        try:
            with os.scandir(folder) as iterator:
                for child in iterator:
                    if len(rows) >= max_entries or time.monotonic() >= deadline:
                        truncated = True
                        break
                    try:
                        if is_reparse_point(Path(child.path)) or child.is_symlink():
                            problems += 1
                            continue
                        metadata = os.stat(child.path)  # Windows DirEntry.stat may report zero file IDs
                        if stat.S_ISDIR(metadata.st_mode):
                            kind = "directory"
                        elif stat.S_ISREG(metadata.st_mode):
                            kind = "file"
                        else:
                            problems += 1
                            continue
                        path = Path(child.path)
                        rows.append({"path": path, "relative_path": path.relative_to(root).as_posix(),
                                     "name": child.name, "kind": kind,
                                     "bytes": metadata.st_size if kind == "file" else None,
                                     "identity": (metadata.st_dev, metadata.st_ino, metadata.st_size,
                                                  metadata.st_mtime_ns)})
                        if kind == "directory" and level < depth:
                            stack.append((path, level + 1))
                    except OSError:
                        problems += 1
        except OSError:
            problems += 1
    return rows, truncated, problems


def _file_hash(row: dict[str, Any], deadline: float) -> str | None:
    path = row["path"]
    if is_reparse_point(path):
        return None
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if not stat.S_ISREG(before.st_mode) or signature != row["identity"]:
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            while True:
                if time.monotonic() >= deadline:
                    return None
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != signature:
            return None
        try:
            if is_reparse_point(path):
                return None
            current = os.stat(path)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != signature:
                return None
        except OSError:
            return None
        return digest.hexdigest()
    finally:
        os.close(fd)


def execute(request: FeatureRequest) -> FeatureResult:
    args = request.arguments
    root = Path(args["path"])
    if not root.is_dir() or is_reparse_point(root):
        raise PreconditionError("READ_DISCOVERY_TARGET_CHANGED")
    start = time.monotonic()
    deadline = start + args["timeout_seconds"]
    rows, truncated, problems = _scan(root, args["depth"], args["max_entries"], deadline)
    operation = args["operation"]
    output: dict[str, Any]
    if operation == "search":
        query = args["query"].casefold()
        glob = "*" in query or "?" in query or "[" in query
        matches = [
            {"path": row["relative_path"], "kind": row["kind"], "bytes": row["bytes"]}
            for row in rows
            if (fnmatch.fnmatchcase(row["name"].casefold(), query) if glob
                else query in row["name"].casefold())
        ]
        result_truncated = truncated or len(matches) > args["limit"]
        output = {"path": str(root), "query": args["query"], "matches": matches[:args["limit"]],
                  "count": min(len(matches), args["limit"]), "truncated": result_truncated,
                  "scanned_entries": len(rows), "unreadable_or_skipped": problems,
                  "complete": not result_truncated and problems == 0}
    else:
        groups_by_size: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            if row["kind"] == "file":
                groups_by_size.setdefault(row["bytes"], []).append(row)
        candidates = [group for group in groups_by_size.values() if len(group) > 1]
        hashes: dict[tuple[int, str], list[dict[str, Any]]] = {}
        spent = 0
        unverified = 0
        for group in candidates:
            for row in group:
                size = row["bytes"]
                if (spent + size > args["max_hash_bytes"]
                        or time.monotonic() >= deadline):
                    unverified += 1
                    continue
                spent += size
                try:
                    digest = _file_hash(row, deadline)
                except OSError:
                    digest = None
                if digest is None:
                    unverified += 1
                else:
                    hashes.setdefault((size, digest), []).append(row)
        duplicates = [
            {"sha256": digest, "bytes_per_file": size,
             "paths": [row["relative_path"] for row in group], "count": len(group)}
            for (size, digest), group in hashes.items() if len(group) > 1
        ]
        duplicates.sort(key=lambda row: (-row["bytes_per_file"], row["paths"][0].casefold()))
        result_truncated = truncated or unverified > 0 or len(duplicates) > args["limit"]
        output = {"path": str(root), "groups": duplicates[:args["limit"]],
                  "group_count": min(len(duplicates), args["limit"]),
                  "candidate_groups_by_size": len(candidates),
                  "unverified_files": unverified, "hash_bytes": spent,
                  "scanned_entries": len(rows), "unreadable_or_skipped": problems,
                  "truncated": result_truncated,
                  "complete": not result_truncated and problems == 0,
                  "delete_authorized": False}
    evidence = {"operation": operation, "path": str(root),
                "scanned_entries": len(rows), "truncated": output["truncated"],
                "complete": output["complete"], "unreadable_or_skipped": problems,
                "read_only": True}
    return FeatureResult(Outcome.APPLIED, evidence, output=output)


def prepare_compare(work: Work, values: dict[str, Any]) -> FeatureRequest:
    if set(values) - {"operation", "path_a", "path_b", "max_hash_bytes", "timeout_seconds"}:
        raise PreconditionError("READ_COMPARE_FIELDS_INVALID")
    paths = []
    for key in ("path_a", "path_b"):
        path = resolve_in_work(work, values.get(key), must_exist=True)
        if not path.is_file() or is_reparse_point(path):
            raise PreconditionError("READ_COMPARE_REGULAR_FILE_REQUIRED")
        paths.append(path)
    if paths[0] == paths[1]:
        raise PreconditionError("READ_COMPARE_DISTINCT_FILES_REQUIRED")
    max_hash_bytes = _positive_int(values.get("max_hash_bytes", 256 * 1024 * 1024),
                                   "READ_COMPARE_BUDGET_INVALID", 8 * 1024 * 1024 * 1024)
    timeout_seconds = _positive_int(values.get("timeout_seconds", 10),
                                    "READ_COMPARE_TIMEOUT_INVALID", 25)
    return FeatureRequest(
        "read", "compare:" + str(paths[0]) + ":" + str(paths[1]),
        {"operation": "compare", "path_a": str(paths[0]), "path_b": str(paths[1]),
         "max_hash_bytes": max_hash_bytes, "timeout_seconds": timeout_seconds},
        tuple("file:" + str(path).casefold() for path in paths),
    )


def execute_compare(request: FeatureRequest) -> FeatureResult:
    args = request.arguments
    entries = []
    for key in ("path_a", "path_b"):
        path = Path(args[key])
        if not path.is_file() or is_reparse_point(path):
            raise PreconditionError("READ_COMPARE_TARGET_CHANGED")
        meta = os.stat(path)
        if not stat.S_ISREG(meta.st_mode):
            raise PreconditionError("READ_COMPARE_TARGET_CHANGED")
        entries.append({
            "path": path, "identity": (meta.st_dev, meta.st_ino, meta.st_size, meta.st_mtime_ns),
            "bytes": meta.st_size,
        })
    equal_size = entries[0]["bytes"] == entries[1]["bytes"]
    within_budget = sum(row["bytes"] for row in entries) <= args["max_hash_bytes"]
    hashes = [None, None]
    if equal_size and within_budget:
        deadline = time.monotonic() + args["timeout_seconds"]
        for i, row in enumerate(entries):
            try:
                hashes[i] = _file_hash(row, deadline)
            except OSError:
                hashes[i] = None
    verified = not equal_size or all(hashes)
    # Verify both *paths* are still the original files after any hashing.
    if verified:
        for row in entries:
            try:
                if is_reparse_point(row["path"]):
                    verified = False
                    break
                current = os.stat(row["path"])
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != row["identity"]:
                    verified = False
                    break
            except OSError:
                verified = False
                break
    if not verified:
        hashes = [None, None]
    equal = (hashes[0] == hashes[1] if equal_size else False) if verified else None
    output = {
        "path_a": str(entries[0]["path"]), "path_b": str(entries[1]["path"]),
        "bytes_a": entries[0]["bytes"], "bytes_b": entries[1]["bytes"],
        "sha256_a": hashes[0], "sha256_b": hashes[1],
        "equal": equal, "complete": verified, "read_only": True,
        "reason": "VERIFIED" if verified else (
            "HASH_BUDGET_EXCEEDED" if not within_budget else "FILE_CHANGED_OR_TIMEOUT"
        ),
    }
    return FeatureResult(Outcome.APPLIED, {
        "operation": "compare", "read_only": True, "complete": verified,
        "equal": equal,
    }, output=output)
