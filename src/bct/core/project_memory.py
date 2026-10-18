"""Durable, AI-authored project memory; separate from orchestration effects.

The ledger stores manager assessments and evidence references, not copies of
Worker results or arbitrary browser conversations. It never sends or wakes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator

SCHEMA = "BCT_PROJECT_MEMORY_V1"
_PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_MAX_RECORD_BYTES = 256 * 1024


class ProjectMemoryError(ValueError):
    """A failed ledger invariant: no existing record was intentionally changed."""


class ProjectMemoryConflict(ProjectMemoryError):
    """The caller's last observed revision is no longer current."""


class ProjectMemoryCorrupt(ProjectMemoryError):
    """The authoritative pointer or immutable revision cannot be verified."""


def _canonical(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProjectMemoryError("PROJECT_MEMORY_JSON_INVALID") from exc


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _id(value: str) -> str:
    if not isinstance(value, str) or not _PROJECT_ID.fullmatch(value):
        raise ProjectMemoryError("PROJECT_MEMORY_ID_INVALID")
    return value


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _parse_json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, item in pairs:
            if key in obj:
                raise ProjectMemoryCorrupt("PROJECT_MEMORY_DUPLICATE_KEY")
            obj[key] = item
        return obj

    def bad_constant(value: str) -> None:
        raise ProjectMemoryCorrupt("PROJECT_MEMORY_NONFINITE_NUMBER")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=bad_constant)
    except (ValueError, UnicodeError) as exc:
        raise ProjectMemoryCorrupt("PROJECT_MEMORY_JSON_CORRUPT") from exc
    if not isinstance(value, dict):
        raise ProjectMemoryCorrupt("PROJECT_MEMORY_OBJECT_REQUIRED")
    return value


def _validate_references(items: Any) -> None:
    if not isinstance(items, list) or len(items) > 200:
        raise ProjectMemoryError("PROJECT_MEMORY_REFERENCES_INVALID")
    for ref in items:
        if (not isinstance(ref, dict) or set(ref) != {"type", "id"}
                or not isinstance(ref["type"], str)
                or not 1 <= len(ref["type"]) <= 40
                or not re.fullmatch(r"[a-z][a-z0-9_]*", ref["type"])
                or not isinstance(ref["id"], str)
                or not 1 <= len(ref["id"]) <= 512):
            raise ProjectMemoryError("PROJECT_MEMORY_REFERENCE_INVALID")


def _validate_record(record: Any) -> bytes:
    if not isinstance(record, dict) or set(record) != {
        "title", "goal", "scope_note", "summary", "links",
        "items", "decisions", "next_actions", "checkpoints",
    }:
        raise ProjectMemoryError("PROJECT_MEMORY_RECORD_FIELDS_INVALID")
    for key in ("title", "goal", "scope_note", "summary"):
        if not isinstance(record[key], str) or len(record[key]) > 20000:
            raise ProjectMemoryError("PROJECT_MEMORY_TEXT_INVALID:" + key)
    if not record["title"].strip() or not record["goal"].strip():
        raise ProjectMemoryError("PROJECT_MEMORY_GOAL_REQUIRED")
    _validate_references(record["links"])
    for key in ("items", "decisions", "next_actions"):
        values = record[key]
        if not isinstance(values, list) or len(values) > 200:
            raise ProjectMemoryError("PROJECT_MEMORY_LIST_INVALID:" + key)
        for row in values:
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise ProjectMemoryError("PROJECT_MEMORY_ROW_INVALID:" + key)
            if not row["text"].strip() or len(row["text"]) > 8000:
                raise ProjectMemoryError("PROJECT_MEMORY_ROW_TEXT_INVALID")
            _validate_references(row.get("evidence", []))
    checkpoints = record["checkpoints"]
    if not isinstance(checkpoints, dict) or set(checkpoints) - {"bct_event_id", "external"}:
        raise ProjectMemoryError("PROJECT_MEMORY_CHECKPOINTS_INVALID")
    event_id = checkpoints.get("bct_event_id")
    if event_id is not None and (type(event_id) is not int or event_id < 0):
        raise ProjectMemoryError("PROJECT_MEMORY_EVENT_CURSOR_INVALID")
    if "external" in checkpoints and not isinstance(checkpoints["external"], dict):
        raise ProjectMemoryError("PROJECT_MEMORY_EXTERNAL_CURSOR_INVALID")
    raw = _canonical(record)
    if len(raw) > _MAX_RECORD_BYTES:
        raise ProjectMemoryError("PROJECT_MEMORY_RECORD_TOO_LARGE")
    return raw


def _atomic_replace(path: Path, value: bytes) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ledger-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _writer_lock(path: Path) -> Iterator[None]:
    # The same project mutex is used by all writers, including independent
    # manager processes. Unlike a read-then-write hash check, it closes the
    # cross-process race between the check and the pointer replacement.
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ProjectMemoryStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()

    def _project_dir(self, project_id: str, *, create: bool) -> Path:
        project_id = _id(project_id)
        path = self.root / project_id
        if self.root.is_symlink() or path.is_symlink():
            raise ProjectMemoryError("PROJECT_MEMORY_SYMLINK_FORBIDDEN")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if path.exists() and not path.is_dir():
            raise ProjectMemoryError("PROJECT_MEMORY_PATH_INVALID")
        return path

    def get(self, project_id: str) -> dict[str, Any] | None:
        path = self._project_dir(project_id, create=False)
        current = path / "current.json"
        if not current.exists() and not current.is_symlink():
            return None
        if not _regular(current):
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_CURRENT_INVALID")
        pointer = _parse_json(current.read_bytes())
        if set(pointer) != {"schema", "project_id", "revision", "revision_file", "sha256"}:
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_POINTER_FIELDS_INVALID")
        revision = pointer["revision"]
        digest = pointer["sha256"]
        if (pointer["schema"] != SCHEMA or pointer["project_id"] != project_id
                or type(revision) is not int or revision <= 0
                or not isinstance(digest, str)
                or not re.fullmatch("[0-9a-f]{64}", digest)
                or pointer["revision_file"] != f"{revision:08d}-{digest}.json"):
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_POINTER_INVALID")
        file = path / "revisions" / pointer["revision_file"]
        if not _regular(file):
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_REVISION_MISSING")
        raw = file.read_bytes()
        if _digest(raw) != digest:
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_REVISION_HASH_MISMATCH")
        row = _parse_json(raw)
        if (set(row) != {"schema", "project_id", "revision", "previous_sha256",
                         "author", "created_at", "record"}
                or row["schema"] != SCHEMA or row["project_id"] != project_id
                or row["revision"] != revision):
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_REVISION_INVALID")
        if (not isinstance(row["author"], str) or not isinstance(row["created_at"], str)
                or not isinstance(row["record"], dict)):
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_REVISION_INVALID")
        try:
            _validate_record(row["record"])
        except ProjectMemoryError as exc:
            raise ProjectMemoryCorrupt("PROJECT_MEMORY_RECORD_CORRUPT") from exc
        return {**row, "sha256": digest}

    def save(self, project_id: str, *, expected_revision: int, author: str,
             record: dict[str, Any]) -> dict[str, Any]:
        _id(project_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ProjectMemoryError("PROJECT_MEMORY_EXPECTED_REVISION_INVALID")
        if not isinstance(author, str) or not 1 <= len(author) <= 96:
            raise ProjectMemoryError("PROJECT_MEMORY_AUTHOR_INVALID")
        _validate_record(record)
        path = self._project_dir(project_id, create=True)
        with _writer_lock(path / ".ledger.lock"):
            current = self.get(project_id)
            revision = current["revision"] if current else 0
            if current and _canonical(current["record"]) == _canonical(record):
                return {**current, "duplicate": True}
            if revision != expected_revision:
                raise ProjectMemoryConflict("PROJECT_MEMORY_STALE_REVISION")
            previous_cursor = current["record"]["checkpoints"].get("bct_event_id") if current else None
            new_cursor = record["checkpoints"].get("bct_event_id")
            if (previous_cursor is not None and new_cursor is not None
                    and new_cursor < previous_cursor):
                raise ProjectMemoryConflict("PROJECT_MEMORY_EVENT_CURSOR_REGRESSION")
            row = {
                "schema": SCHEMA, "project_id": project_id,
                "revision": revision + 1, "previous_sha256": current["sha256"] if current else None,
                "author": author, "created_at": datetime.now(timezone.utc).isoformat(),
                "record": record,
            }
            data = _canonical(row)
            digest = _digest(data)
            filename = f"{revision + 1:08d}-{digest}.json"
            folder = path / "revisions"
            if folder.is_symlink():
                raise ProjectMemoryError("PROJECT_MEMORY_SYMLINK_FORBIDDEN")
            folder.mkdir(exist_ok=True)
            revision_path = folder / filename
            try:
                with revision_path.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                if (not _regular(revision_path)
                        or revision_path.read_bytes() != data):
                    raise ProjectMemoryCorrupt("PROJECT_MEMORY_REVISION_COLLISION")
            pointer = {
                "schema": SCHEMA, "project_id": project_id,
                "revision": revision + 1, "revision_file": filename, "sha256": digest,
            }
            _atomic_replace(path / "current.json", _canonical(pointer))
            return {**row, "sha256": digest, "duplicate": False}

    def history(self, project_id: str) -> list[dict[str, Any]]:
        # Trace only the verified parent chain: orphan files from interrupted
        # writes must not become committed history.
        current = self.get(project_id)
        if current is None:
            return []
        folder = self._project_dir(project_id, create=False) / "revisions"
        entries = []
        row = current
        while row is not None:
            entries.append(row)
            parent = row["previous_sha256"]
            if row["revision"] == 1:
                if parent is not None:
                    raise ProjectMemoryCorrupt("PROJECT_MEMORY_BAD_GENESIS")
                break
            if not isinstance(parent, str) or not re.fullmatch("[0-9a-f]{64}", parent):
                raise ProjectMemoryCorrupt("PROJECT_MEMORY_PARENT_INVALID")
            path = folder / f"{row['revision'] - 1:08d}-{parent}.json"
            if not _regular(path):
                raise ProjectMemoryCorrupt("PROJECT_MEMORY_PARENT_MISSING")
            raw = path.read_bytes()
            if _digest(raw) != parent:
                raise ProjectMemoryCorrupt("PROJECT_MEMORY_PARENT_HASH_MISMATCH")
            previous = _parse_json(raw)
            if (previous.get("schema") != SCHEMA or previous.get("project_id") != project_id
                    or previous.get("revision") != row["revision"] - 1):
                raise ProjectMemoryCorrupt("PROJECT_MEMORY_PARENT_FIELDS_INVALID")
            row = {**previous, "sha256": parent}
        return list(reversed(entries))

    def projects(self) -> list[str]:
        if not self.root.exists():
            return []
        if self.root.is_symlink() or not self.root.is_dir():
            raise ProjectMemoryError("PROJECT_MEMORY_ROOT_INVALID")
        return [path.name for path in sorted(self.root.iterdir())
                if path.is_dir() and not path.is_symlink()
                and _PROJECT_ID.fullmatch(path.name)
                and (path / "current.json").exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description="BCT Project Memory V1")
    parser.add_argument("--root", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    get = sub.add_parser("get")
    get.add_argument("project_id")
    put = sub.add_parser("put")
    put.add_argument("project_id")
    put.add_argument("--input", required=True)
    put.add_argument("--expected-revision", required=True, type=int)
    put.add_argument("--author", required=True)
    history = sub.add_parser("history")
    history.add_argument("project_id")
    sub.add_parser("list")
    args = parser.parse_args()
    store = ProjectMemoryStore(args.root)
    try:
        if args.action == "get":
            result = store.get(args.project_id)
        elif args.action == "put":
            record = _parse_json(Path(args.input).read_bytes())
            result = store.save(args.project_id, expected_revision=args.expected_revision,
                                author=args.author, record=record)
        elif args.action == "history":
            result = store.history(args.project_id)
        else:
            result = store.projects()
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except ProjectMemoryError as exc:
        # Return only structured error codes. No ledger contents in logs.
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

