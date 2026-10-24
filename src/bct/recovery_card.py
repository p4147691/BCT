"""Deterministic, side-effect-free successor Recovery Cards.

Collection only reads existing SQLite receipts and local Git. GitHub/CI facts
must come from independently verified, explicitly supplied snapshots.
No claim acquisition, scheduling, dispatch or wake is performed here.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "BCT_RECOVERY_CARD_V1"
FIELDS = ("worktree", "branch", "commit", "pr", "ci", "tests", "pending")
def _canonical(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")

def _git(path: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(path), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                          timeout=8, check=False)
    if proc.returncode:
        raise ValueError("GIT_READ_FAILED")
    return proc.stdout.strip()

def collect_existing(work_id: str, database: str | Path, worktree: str | Path) -> dict[str, Any]:
    """Read-only: never initialize Store (which migrates schema or enables WAL)."""
    p = Path(database)
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        work = con.execute("SELECT work_id,state,request_summary FROM works WHERE work_id=?", (work_id,)).fetchone()
        if work is None: raise ValueError("WORK_NOT_FOUND")
        op_cols = {row[1] for row in con.execute("PRAGMA table_info(operations)")}
        op_select = [col for col in ("operation_id","capability","state","outcome") if col in op_cols]
        ops = [dict(row) for row in con.execute(
            "SELECT "+",".join(op_select)+" FROM operations WHERE work_id=? ORDER BY operation_id", (work_id,)
        )] if op_select else []
    finally:
        con.close()
    w = Path(worktree)
    head = _git(w, "rev-parse", "HEAD")
    branch = _git(w, "branch", "--show-current")
    status = _git(w, "status", "--porcelain")
    return {"predecessor": {"work_id": work_id, "state": work["state"]},
            "facts": {"worktree": str(w), "branch": branch, "commit": head,
                      "git_clean": not bool(status), "operations": ops},
            "unknown": (["UNCOMMITTED_OR_UNTRACKED_FILES"] if status else [])}

def build_card(*, predecessor: dict[str, Any], observations: dict[str, Any],
               protected_resources: list[str], next_minimal_step: str,
               verified_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Only verified evidence entries are promoted to facts; missing data stay UNKNOWN."""
    if not predecessor.get("work_id") or not next_minimal_step.strip():
        raise ValueError("RECOVERY_IDENTITY_AND_NEXT_STEP_REQUIRED")
    verified_evidence = verified_evidence or {}
    facts = {}
    unknown = []
    for key in FIELDS:
        if key in observations and key in verified_evidence and verified_evidence[key]:
            facts[key] = {"value": observations[key], "evidence": str(verified_evidence[key])}
        else:
            unknown.append(key.upper() + "_UNVERIFIED")
    card = {"schema": SCHEMA, "predecessor_identity": predecessor,
            "verified_facts": facts, "UNKNOWN": sorted(unknown),
            "next_minimal_step": next_minimal_step,
            "protected_resources": sorted(set(protected_resources)),
            "successor_assignment": {"state": "PREPARED_ONLY",
              "idempotency_key": hashlib.sha256(_canonical({
                "predecessor": predecessor.get("work_id"),
                "head": facts.get("commit"), "next": next_minimal_step})).hexdigest()},
            "effect": "NONE_READ_ONLY"}
    card["card_sha256"] = hashlib.sha256(_canonical(card)).hexdigest()
    return card

def serialize_card(card: dict[str, Any]) -> bytes:
    return _canonical(card)
