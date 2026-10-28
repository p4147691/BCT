"""FIFO integration readiness requests, not execution or permission grants.

Work Manager submission is durable and ordered, with no Chrome, Git, CI, or
deployment effects. The coordinator is a default route only, not an owner role.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from bct.core.models import ConflictError, Work

_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}\Z")
_ALLOWED = frozenset({
    "request_id", "project_id", "repository_root", "expected_main_sha",
    "feature_branch", "feature_head_sha", "changed_files",
    "test_receipts", "candidate_ci_run_id", "target_live_products",
    "acceptance_criteria", "rollback_plan",
    "manager_conversation_uuid", "context_note",
})
_REQUIRED = frozenset({
    "request_id", "project_id", "repository_root", "expected_main_sha",
    "feature_branch", "feature_head_sha", "changed_files",
    "test_receipts", "target_live_products", "acceptance_criteria",
    "rollback_plan",
})


def validate_integration_request(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - _ALLOWED or not _REQUIRED <= set(raw):
        raise ValueError("INTEGRATION_QUEUE_REQUEST_SCHEMA_INVALID")
    request = dict(raw)
    for key in ("request_id", "project_id"):
        if not isinstance(request[key], str) or not _ID.fullmatch(request[key]):
            raise ValueError("INTEGRATION_QUEUE_ID_INVALID:" + key)
    repo = request["repository_root"]
    if (not isinstance(repo, str) or len(repo) > 1024
            or not Path(repo).is_absolute() or "\x00" in repo):
        raise ValueError("INTEGRATION_QUEUE_REPOSITORY_INVALID")
    request["repository_root"] = str(Path(repo).resolve())
    for key in ("expected_main_sha", "feature_head_sha"):
        value = request[key]
        if not isinstance(value, str) or not _SHA.fullmatch(value.lower()):
            raise ValueError("INTEGRATION_QUEUE_SHA_INVALID:" + key)
        request[key] = value.lower()
    branch = request["feature_branch"]
    if (not isinstance(branch, str) or not _BRANCH.fullmatch(branch)
            or branch in {"main", "master"} or ".." in branch
            or branch.endswith(("/", ".", ".lock"))):
        raise ValueError("INTEGRATION_QUEUE_BRANCH_INVALID")
    for key, max_count in (("changed_files", 128), ("test_receipts", 40),
                           ("target_live_products", 20)):
        values = request[key]
        if (not isinstance(values, list) or not 1 <= len(values) <= max_count
                or any(not isinstance(s, str) or not s or len(s) > 1024
                       or "\x00" in s for s in values)
                or len(set(values)) != len(values)):
            # For code-only changes, a caller should use ["NO_LIVE_CHANGE"].
            raise ValueError("INTEGRATION_QUEUE_LIST_INVALID:" + key)
    for name in request["changed_files"]:
        posix = name.replace("\\", "/")
        if (posix.startswith(("/", "-")) or ":" in posix
                or any(component in {"", ".", ".."} for component in posix.split("/"))):
            raise ValueError("INTEGRATION_QUEUE_CHANGED_PATH_INVALID")
    for key, ceiling in (("acceptance_criteria", 4000), ("rollback_plan", 3000)):
        v = request[key]
        if not isinstance(v, str) or not 1 <= len(v.strip()) <= ceiling or "\x00" in v:
            raise ValueError("INTEGRATION_QUEUE_TEXT_INVALID:" + key)
    for key, ceiling in (("manager_conversation_uuid", 128),
                         ("context_note", 2000)):
        value = request.get(key, "")
        if not isinstance(value, str) or len(value) > ceiling or "\x00" in value:
            raise ValueError("INTEGRATION_QUEUE_OPTIONAL_TEXT_INVALID:" + key)
        request[key] = value
    ci = request.get("candidate_ci_run_id")
    if ci is not None and (type(ci) is not int or ci <= 0):
        raise ValueError("INTEGRATION_QUEUE_CI_RUN_INVALID")
    request["candidate_ci_run_id"] = ci
    packed = json.dumps(request, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":"))
    if len(packed.encode("utf-8")) > 32768:
        raise ValueError("INTEGRATION_QUEUE_REQUEST_TOO_LARGE")
    return request


def _published(row: sqlite3.Row, *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "sequence": row["sequence"],
        "request_id": row["request_id"],
        "manager_work_id": row["manager_work_id"],
        "project_id": row["project_id"],
        "repository_root": row["repository_root"],
        "request_digest": row["request_digest"],
        "request": json.loads(row["payload_json"]),
        "state": row["state"],
        "route": "UNASSIGNED_COORDINATOR_PENDING",
        "execution": "NOT_STARTED",
        "created_at": row["created_at"],
        "duplicate": duplicate,
    }


def submit_integration_request(store: Any, *, work: Work,
                               request: dict[str, Any]) -> dict[str, Any]:
    """Atomic append. Same request ID + exact payload/work is idempotent."""
    if work.state != "ACTIVE":
        raise PermissionError("INTEGRATION_QUEUE_WORK_INACTIVE")
    request = validate_integration_request(request)
    serialized = json.dumps(request, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    with store.transaction() as db:
        old = db.execute(
            "SELECT * FROM integration_requests WHERE request_id=?",
            (request["request_id"],),
        ).fetchone()
        if old is not None:
            if old["manager_work_id"] != work.work_id or old["request_digest"] != digest:
                raise ConflictError("INTEGRATION_QUEUE_REQUEST_ID_CONFLICT")
            return _published(old, duplicate=True)
        db.execute(
            "INSERT INTO integration_requests("
            "request_id,manager_work_id,project_id,repository_root,"
            "request_digest,payload_json,state,created_at) "
            "VALUES(?,?,?,?,?,?,'QUEUED',?)",
            (request["request_id"], work.work_id, request["project_id"],
             request["repository_root"], digest, serialized, time.time()),
        )
        row = db.execute(
            "SELECT * FROM integration_requests WHERE request_id=?",
            (request["request_id"],),
        ).fetchone()
        store._event(db, "INTEGRATION_REQUEST_QUEUED", request["request_id"], {
            "sequence": int(row["sequence"]),
            "work_id": work.work_id, "request_digest": digest,
        })
        return _published(row)


def list_integration_requests(
    store: Any, *, repository_root: str = "", limit: int = 50
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("INTEGRATION_QUEUE_LIMIT_INVALID")
    if repository_root:
        if not Path(repository_root).is_absolute():
            raise ValueError("INTEGRATION_QUEUE_REPOSITORY_INVALID")
        repository_root = str(Path(repository_root).resolve())
    db = store._connect()
    try:
        if repository_root:
            rows = db.execute(
                "SELECT * FROM integration_requests WHERE state='QUEUED' "
                "AND repository_root=? ORDER BY sequence ASC LIMIT ?",
                (repository_root, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM integration_requests WHERE state='QUEUED' "
                "ORDER BY sequence ASC LIMIT ?", (limit,),
            ).fetchall()
    finally:
        db.close()
    return {
        "state": "READ_ONLY",
        "order": "FIFO_BY_SQLITE_SEQUENCE",
        "requests": [_published(r) for r in rows],
        "claim_enabled": False,
        "auto_send_enabled": False,
        "effect": "NONE",
    }
