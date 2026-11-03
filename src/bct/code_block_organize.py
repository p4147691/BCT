"""Plan and assemble one exact code-block replacement.

This module never writes files.  The public recipe delegates the final full-file
write to BCT's existing hash-fenced, atomic ``write`` primitive.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .code_block_scan import inspect_file


SCHEMA = "bct.code-block-organize-plan.v1"
MAX_REPLACEMENT_CHARS = 512_000
MAX_DIFF_CHARS = 200_000
_HEX64 = re.compile(r"[0-9a-f]{64}")
_BLOCK_ID = re.compile(r"[0-9a-f]{16}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_replacement(replacement: str, old_source: str, file_text: str) -> str:
    if not isinstance(replacement, str) or not replacement.strip():
        raise ValueError("CODE_BLOCK_REPLACEMENT_REQUIRED")
    if len(replacement) > MAX_REPLACEMENT_CHARS or "\x00" in replacement:
        raise ValueError("CODE_BLOCK_REPLACEMENT_INVALID")
    newline = "\r\n" if "\r\n" in file_text else "\n"
    normalized = replacement.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        normalized = normalized.replace("\n", newline)
    old_has_newline = old_source.endswith(("\n", "\r"))
    new_has_newline = normalized.endswith(("\n", "\r"))
    if old_has_newline and not new_has_newline:
        normalized += newline
    elif not old_has_newline and new_has_newline:
        normalized = normalized.rstrip("\r\n")
    return normalized


def _plan_payload(*, path: str, block_id: str, file_sha256: str,
                  block_sha256: str, replacement_sha256: str,
                  after_file_sha256: str) -> dict[str, str]:
    return {
        "schema": SCHEMA,
        "path": path,
        "block_id": block_id,
        "expected_file_sha256": file_sha256,
        "expected_block_sha256": block_sha256,
        "replacement_sha256": replacement_sha256,
        "after_file_sha256": after_file_sha256,
    }


def _plan_sha256(payload: dict[str, str]) -> str:
    return _sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8"))


def _select_block(index: dict[str, Any], block_id: str) -> dict[str, Any]:
    if not isinstance(block_id, str) or not _BLOCK_ID.fullmatch(block_id):
        raise ValueError("CODE_BLOCK_ID_INVALID")
    matches = [card for card in index["blocks"] if card["block_id"] == block_id]
    if len(matches) != 1:
        raise ValueError("CODE_BLOCK_NOT_FOUND_OR_AMBIGUOUS")
    return matches[0]


def _replace_slice(text: str, card: dict[str, Any], replacement: str) -> tuple[str, str, str]:
    lines = text.splitlines(keepends=True)
    start = int(card["line_start"]) - 1
    end = int(card["line_end"])
    old_source = "".join(lines[start:end])
    if _sha256(old_source.encode("utf-8")) != card["source_sha256"]:
        raise ValueError("CODE_BLOCK_SOURCE_CHANGED")
    normalized = _normalize_replacement(replacement, old_source, text)
    return "".join((*lines[:start], normalized, *lines[end:])), old_source, normalized


def plan_block_replacement(
    root: Path,
    *,
    path: str,
    block_id: str,
    replacement: str,
    expected_file_sha256: str = "",
    expected_block_sha256: str = "",
) -> dict[str, Any]:
    """Return a reviewable, hash-bound replacement plan without writing."""
    index = inspect_file(root.resolve(), path)
    if expected_file_sha256 and expected_file_sha256 != index["file_sha256"]:
        raise ValueError("CODE_BLOCK_FILE_SHA_MISMATCH")
    card = _select_block(index, block_id)
    if expected_block_sha256 and expected_block_sha256 != card["source_sha256"]:
        raise ValueError("CODE_BLOCK_SOURCE_SHA_MISMATCH")
    after_text, old_source, normalized = _replace_slice(index["text"], card, replacement)
    after_bytes = after_text.encode("utf-8")
    replacement_sha = _sha256(normalized.encode("utf-8"))
    payload = _plan_payload(
        path=index["path"], block_id=block_id,
        file_sha256=index["file_sha256"], block_sha256=card["source_sha256"],
        replacement_sha256=replacement_sha,
        after_file_sha256=_sha256(after_bytes),
    )
    diff = "".join(difflib.unified_diff(
        old_source.splitlines(keepends=True), normalized.splitlines(keepends=True),
        fromfile=index["path"] + ":before", tofile=index["path"] + ":after",
    ))
    diff_truncated = len(diff) > MAX_DIFF_CHARS
    if diff_truncated:
        diff = diff[:MAX_DIFF_CHARS] + "\n... DIFF_TRUNCATED ...\n"
    return {
        **payload,
        "plan_sha256": _plan_sha256(payload),
        "status": "PLANNED",
        "read_only": True,
        "applied": False,
        "block": {
            "name": card["name"], "kind": card["kind"],
            "line_start": card["line_start"], "line_end": card["line_end"],
            "language": card["language"],
        },
        "replacement": normalized,
        "diff": diff,
        "diff_truncated": diff_truncated,
        "after_bytes": len(after_bytes),
    }


def prepare_block_apply(
    root: Path,
    *,
    path: str,
    block_id: str,
    replacement: str,
    expected_file_sha256: str,
    expected_block_sha256: str,
    expected_after_sha256: str,
    plan_sha256: str,
) -> dict[str, Any]:
    """Rebuild an exact plan and return arguments for the existing write primitive."""
    for value in (expected_file_sha256, expected_block_sha256,
                  expected_after_sha256, plan_sha256):
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise ValueError("CODE_BLOCK_APPLY_HASH_INVALID")
    current = inspect_file(root.resolve(), path)
    if current["file_sha256"] == expected_after_sha256:
        # Exact same-operation replay reaches this branch after the first write.
        # Rebuild the original write request without trying to find an old block
        # that may have been renamed by the replacement.
        payload = _plan_payload(
            path=current["path"], block_id=block_id,
            file_sha256=expected_file_sha256,
            block_sha256=expected_block_sha256,
            replacement_sha256=_sha256(replacement.encode("utf-8")),
            after_file_sha256=expected_after_sha256,
        )
        if _plan_sha256(payload) != plan_sha256:
            raise ValueError("CODE_BLOCK_PLAN_SHA_MISMATCH")
        return {
            "path": str((root / Path(path)).resolve()),
            "content": current["text"],
            "expected_sha256": expected_file_sha256,
            "expected_absent": False,
            "plan": {**payload, "plan_sha256": plan_sha256,
                     "status": "ALREADY_APPLIED", "replacement": replacement},
        }
    if current["file_sha256"] != expected_file_sha256:
        raise ValueError("CODE_BLOCK_FILE_SHA_MISMATCH")
    plan = plan_block_replacement(
        root, path=path, block_id=block_id, replacement=replacement,
        expected_file_sha256=expected_file_sha256,
        expected_block_sha256=expected_block_sha256,
    )
    if plan["after_file_sha256"] != expected_after_sha256:
        raise ValueError("CODE_BLOCK_AFTER_SHA_MISMATCH")
    if plan["plan_sha256"] != plan_sha256:
        raise ValueError("CODE_BLOCK_PLAN_SHA_MISMATCH")
    return {
        "path": str((root / Path(path)).resolve()),
        "content": _assemble_after_text(root, plan),
        "expected_sha256": expected_file_sha256,
        "expected_absent": False,
        "plan": plan,
    }


def _assemble_after_text(root: Path, plan: dict[str, Any]) -> str:
    index = inspect_file(root.resolve(), plan["path"])
    card = _select_block(index, plan["block_id"])
    after_text, _, normalized = _replace_slice(index["text"], card, plan["replacement"])
    if _sha256(normalized.encode("utf-8")) != plan["replacement_sha256"]:
        raise ValueError("CODE_BLOCK_REPLACEMENT_SHA_MISMATCH")
    if _sha256(after_text.encode("utf-8")) != plan["after_file_sha256"]:
        raise ValueError("CODE_BLOCK_AFTER_SHA_MISMATCH")
    return after_text
