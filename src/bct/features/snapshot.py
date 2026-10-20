from __future__ import annotations

"""Bounded, work-scoped metadata snapshot; never a second operation authority."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from bct.core.models import ConflictError, PreconditionError
from .common import is_reparse_point

_MAX_FILE_BYTES = 512 * 1024
_MAX_CLAIMS_RETURNED = 32


def _fingerprint_file(item: dict[str, str]) -> dict[str, Any]:
    path = Path(item["path"])
    if not path.is_file() or is_reparse_point(path):
        raise PreconditionError("SNAPSHOT_FILE_CHANGED")
    before = path.stat()
    if before.st_size > _MAX_FILE_BYTES:
        raise PreconditionError("SNAPSHOT_FILE_TOO_LARGE")
    contents = path.read_bytes()
    after = path.stat()
    if (len(contents) != before.st_size or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns or is_reparse_point(path)):
        raise PreconditionError("SNAPSHOT_FILE_CHANGED")
    return {
        "id": item["id"], "path": str(path), "bytes": len(contents),
        "mtime_ns": after.st_mtime_ns,
        "sha256": hashlib.sha256(contents).hexdigest(),
        "observed_at": time.time(),
    }


def capture_work_snapshot(store: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return only this Work's state, file metadata, claims and receipt summaries.

    File and SQLite observations are not one atomic transaction.  The caller
    must check exact SHA and current LIVE state before any later mutation.
    """
    work_id = arguments["work_id"]
    work = store.get_work(work_id)
    if (work.owner_principal_id != arguments["owner_principal_id"]
            or work.assignment_epoch != arguments["assignment_epoch"]):
        raise PreconditionError("SNAPSHOT_WORK_CHANGED")

    # Monitor is read-only; the global projection is filtered before output.
    projection = store.monitor_snapshot()
    own_claims = [
        {"resource_key": row["resource_key"], "operation_id": row["operation_id"],
         "assignment_epoch": row["assignment_epoch"]}
        for row in projection["unresolved_claims"] if row["work_id"] == work_id
    ] if arguments["include_claims"] else []

    receipts = []
    for operation_id in arguments["receipt_ids"]:
        try:
            receipt = store.get_operation_for(
                operation_id=operation_id, work_id=work_id,
                principal_id=work.owner_principal_id,
            )
        except (KeyError, ConflictError) as exc:
            raise PreconditionError("SNAPSHOT_RECEIPT_NOT_ACCESSIBLE") from exc
        receipts.append({
            "operation_id": operation_id, "state": receipt.state.value,
            "outcome": receipt.outcome.value if receipt.outcome else None,
            "evidence_sha256": hashlib.sha256(
                __import__("json").dumps(receipt.evidence, sort_keys=True,
                                        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
        })

    files = arguments["files"]
    if len(files) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(files))) as pool:
            file_results = list(pool.map(_fingerprint_file, files))
    else:
        file_results = [_fingerprint_file(item) for item in files]

    return {
        "schema": 1, "read_only": True, "scope": "work",
        "consistency": "NON_ATOMIC_FILES_AND_STORE",
        "observed_at": time.time(),
        "work": {"work_id": work.work_id, "state": work.state,
                 "assignment_epoch": work.assignment_epoch},
        "files": file_results,
        "claims": {"count": len(own_claims), "items": own_claims[:_MAX_CLAIMS_RETURNED],
                   "truncated": len(own_claims) > _MAX_CLAIMS_RETURNED},
        "receipts": receipts,
        "core_health": "NOT_INCLUDED",
    }
