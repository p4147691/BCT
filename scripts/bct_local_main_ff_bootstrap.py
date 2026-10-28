"""One-time BCT bootstrap: use its OWN operation/claims, never a raw Git escape.

Entry point is the existing authorized BCT execute capability. This child opens
the existing state DB, validates that exact outer Work/Operation is RUNNING, and
calls the candidate GitCommitFeature through OperationCoordinator, producing a
SECOND, exact durable git_commit operation with its Git resource claim evidence.

This is NOT an independent git implementation and it never relaxes policy.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import re
import sqlite3
import sys
import threading
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bct.core.models import Principal
from bct.core.operations import OperationCoordinator
from bct.core.policy import Policy
from bct.core.store import Store
from bct.features.git import GitCommitFeature
from bct.features.git_authority import require_local_main

_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _opened_store(path: Path) -> Store:
    """Open an existing Store without running startup migrations on LIVE DB."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("BOOTSTRAP_STATE_DB_INVALID")
    store = Store.__new__(Store)
    store.path = str(path)
    store._lock = threading.RLock()
    return store


def verify_outer(store: Store, *, work_id: str, operation_id: str,
                 candidate_root: Path, canonical_root: Path) -> Principal:
    """Require an authorized, actually running execute Operation from BCT."""
    with closing(sqlite3.connect("file:" + store.path.replace("\\", "/") + "?mode=ro",
                                 uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        op = db.execute(
            "SELECT operation_id,work_id,principal_id,capability,target,state,"
            "assignment_epoch FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if (op is None or op["work_id"] != work_id or op["capability"] != "execute"
                or op["state"] != "RUNNING" or
                Path(op["target"]).resolve() != candidate_root):
            raise ValueError("BOOTSTRAP_OUTER_OPERATION_FENCE_INVALID")
        claim = db.execute(
            "SELECT operation_id FROM resource_claims WHERE resource_key=? "
            "AND unresolved=1",
            ("execution:" + str(candidate_root).casefold(),),
        ).fetchone()
        if claim is None or claim["operation_id"] != operation_id:
            raise ValueError("BOOTSTRAP_OUTER_EXECUTION_CLAIM_NOT_CURRENT")
    work = store.get_work(work_id)
    if (work.state != "ACTIVE" or
            work.assignment_epoch != op["assignment_epoch"] or
            work.owner_principal_id != op["principal_id"] or
            not {"execute", "git_commit"}.issubset(work.actions)):
        raise ValueError("BOOTSTRAP_WORK_AUTHORIZATION_INVALID")
    real_roots = {Path(root).resolve() for root in work.roots}
    if canonical_root not in real_roots or candidate_root not in real_roots:
        raise ValueError("BOOTSTRAP_WORK_ROOTS_UNAUTHORIZED")
    return Principal(work.owner_principal_id, "bootstrap-existing-work",
                     frozenset(work.actions))


def run_bootstrap(*, candidate_root: Path, canonical_root: Path,
                  policy_path: Path, state_db: Path, work_id: str,
                  outer_operation_id: str, git_operation_id: str,
                  expected_head: str, expected_remote_head: str) -> dict:
    if (not _ID.fullmatch(work_id) or not _ID.fullmatch(outer_operation_id)
            or not _ID.fullmatch(git_operation_id)
            or outer_operation_id == git_operation_id
            or not _SHA.fullmatch(expected_head)
            or not _SHA.fullmatch(expected_remote_head)):
        raise ValueError("BOOTSTRAP_REQUEST_INVALID")
    candidate_root = candidate_root.resolve()
    canonical_root = canonical_root.resolve()
    policy_path = policy_path.resolve()
    state_db = state_db.resolve()
    if (Path(__file__).resolve().parents[1] != candidate_root
            or not candidate_root.is_dir()
            or not (canonical_root / ".git").is_dir()
            or not (candidate_root / ".git").is_file()):
        raise ValueError("BOOTSTRAP_SOURCE_IDENTITY_INVALID")
    if policy_path.is_symlink() or state_db.is_symlink():
        raise ValueError("BOOTSTRAP_PROTECTED_PATH_INVALID")
    require_local_main(policy_path, canonical_root)
    store = _opened_store(state_db)
    principal = verify_outer(
        store, work_id=work_id, operation_id=outer_operation_id,
        candidate_root=candidate_root, canonical_root=canonical_root,
    )
    coordinator = OperationCoordinator(store=store, policy=Policy(policy_path))
    coordinator.register(GitCommitFeature(policy_path))
    result = coordinator.run(
        principal=principal, work_id=work_id, operation_id=git_operation_id,
        capability="git_commit",
        arguments={
            "operation": "fast_forward_local_main_recovery",
            "path": str(canonical_root),
            "expected_head": expected_head,
            "expected_remote_head": expected_remote_head,
        },
    )
    return {
        "bootstrap": "BCT_EXISTING_EXECUTE_TO_SCOPED_GIT_COMMIT",
        "work_id": work_id, "outer_operation_id": outer_operation_id,
        "git_operation_id": git_operation_id, "operation": result.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    for name in ("candidate-root", "canonical-root", "policy-path", "state-db",
                 "work-id", "outer-operation-id", "git-operation-id",
                 "expected-head", "expected-remote-head"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args(argv)
    try:
        payload = run_bootstrap(
            candidate_root=Path(a.candidate_root),
            canonical_root=Path(a.canonical_root),
            policy_path=Path(a.policy_path), state_db=Path(a.state_db),
            work_id=a.work_id, outer_operation_id=a.outer_operation_id,
            git_operation_id=a.git_operation_id,
            expected_head=a.expected_head.lower(),
            expected_remote_head=a.expected_remote_head.lower(),
        )
    except Exception as exc:
        print(json.dumps({"bootstrap": "REJECTED", "reason": str(exc)},
                         ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["operation"].get("outcome") == "APPLIED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
