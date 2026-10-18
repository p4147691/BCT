"""Read-only continuation context built from AI-ledger and existing BCT records.

A context bundle is **evidence for the Manager**, not an instruction, ACK,
permission grant, automated Wake, or an attempt to process a Worker RESULT.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .project_memory import ProjectMemoryStore


class ProjectContextError(ValueError):
    pass


def _read_project_events(
    conn: sqlite3.Connection, *, project: dict[str, Any],
    work_id: str, session_id: str, limit: int,
) -> dict[str, Any]:
    # The project ledger is AI-authored context, never an authorization
    # source. A forged/cross-Work ID in its links must not select events.
    # Resolve only original records proven to belong to the authorized Work
    # and the exact Session. Broader project review requires distinct grants.
    subjects: set[str] = set()
    # Add related durable session/assignment/operation identifiers. The
    # database remains the original truth for any state/result.
    if work_id:
        subjects.add(work_id)
        subjects.update(row[0] for row in conn.execute(
            "SELECT operation_id FROM operations WHERE work_id=? LIMIT 1001",
            (work_id,)).fetchall())
    if session_id:
        subjects.add(session_id)
        subjects.update(row[0] for row in conn.execute(
            "SELECT assignment_id FROM orchestration_assignments "
            "WHERE session_id=? LIMIT 1001", (session_id,)).fetchall())
        subjects.update(row[0] for row in conn.execute(
            "SELECT message_id FROM orchestration_mailbox WHERE session_id=? LIMIT 1001",
            (session_id,)).fetchall())
        subjects.update(row[0] for row in conn.execute(
            "SELECT event_id FROM orchestration_manager_wakes "
            "WHERE session_id=? LIMIT 1001", (session_id,)).fetchall())
        subjects.update(row[0] for row in conn.execute(
            "SELECT decision_id FROM orchestration_consumption_decisions "
            "WHERE session_id=? LIMIT 1001", (session_id,)).fetchall())

    cursor = project["record"]["checkpoints"].get("bct_event_id")
    cursor = 0 if cursor is None else cursor
    highwater = int(conn.execute(
        "SELECT COALESCE(MAX(event_id),0) FROM events").fetchone()[0])
    if cursor > highwater:
        raise ProjectContextError("PROJECT_CONTEXT_CURSOR_AHEAD_OF_SOURCE")
    # Never claim completeness if too many related identifiers were omitted.
    source_complete = len(subjects) <= 1000
    ids = sorted(subjects)[:1000]
    if not ids:
        return {"events": [], "observed_through": cursor,
                "highwater": highwater, "has_more": False,
                "source_complete": False, "reason": "NO_BCT_LINKS"}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT event_id,kind,subject_id,created_at FROM events "
        f"WHERE event_id>? AND event_id<=? AND subject_id IN ({placeholders}) "
        f"ORDER BY event_id ASC LIMIT ?",
        (cursor, highwater, *ids, limit + 1)).fetchall()
    has_more = len(rows) > limit
    current = rows[:limit]
    next_position = (int(current[-1]["event_id"]) if has_more else highwater)
    return {
        "events": [dict(row) for row in current],
        "observed_through": next_position,
        "highwater": highwater,
        "has_more": has_more,
        "source_complete": source_complete and not has_more,
        "reason": ("MORE_EVENTS" if has_more else
                   "RELATED_SUBJECTS_TRUNCATED" if not source_complete else None),
    }


def contexts_for_session(
    *, root: str | Path, sqlite_path: str | Path,
    session_id: str, work_id: str, limit: int = 50,
) -> list[dict[str, Any]]:
    """Reconstruct Manager-readable context without updating any checkpoint.

    Returns only projects explicitly linked to this Work or Session. External
    GitHub/ChatGPT links remain unverifiable here, never auto-acknowledged.
    The source event cursor is a *proposal*, to be committed by Manager later.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ProjectContextError("PROJECT_CONTEXT_LIMIT_INVALID")
    memory = ProjectMemoryStore(root)
    if not memory.root.exists():
        return []
    matches = []
    for project_id in memory.projects():
        item = memory.get(project_id)
        if item is None:
            continue
        links = item["record"]["links"]
        if not any((link["type"] == "bct_session" and link["id"] == session_id)
                   or (link["type"] == "bct_work" and link["id"] == work_id)
                   for link in links):
            continue
        if len(matches) >= 4:
            raise ProjectContextError("PROJECT_CONTEXT_PROJECT_COUNT_LIMIT")
        matches.append((project_id, item))
    if not matches:
        return []

    db_file = Path(sqlite_path).absolute()
    if not db_file.is_file():
        raise ProjectContextError("PROJECT_CONTEXT_SQLITE_MISSING")
    # Query only. Never update Session, result consumed_at, event or Claim.
    uri = "file:" + db_file.as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        present = conn.execute(
            "SELECT s.work_id,s.work_assignment_epoch,s.state,s.plan_revision,"
            "s.manager_node_id,s.manager_epoch,w.assignment_epoch AS current_work_epoch "
            "FROM orchestration_sessions s "
            "JOIN works w ON w.work_id=s.work_id "
            "WHERE s.session_id=?", (session_id,)).fetchone()
        if present is None or present["work_id"] != work_id:
            raise ProjectContextError("PROJECT_CONTEXT_SESSION_NOT_FOUND")
        if present["work_assignment_epoch"] != present["current_work_epoch"]:
            raise ProjectContextError("PROJECT_CONTEXT_WORK_EPOCH_STALE")
        assignment_rows = conn.execute(
            "SELECT assignment_id,state,current_generation,updated_at "
            "FROM orchestration_assignments WHERE session_id=? "
            "ORDER BY updated_at DESC,assignment_id LIMIT 41",
            (session_id,)).fetchall()
        assignments = [dict(row) for row in assignment_rows[:40]]
        assignments_truncated = len(assignment_rows) > 40
        output: list[dict[str, Any]] = []
        for project_id, item in matches:
            evidence = _read_project_events(
                conn, project=item, work_id=work_id, session_id=session_id, limit=limit)
            external = [x for x in item["record"]["links"]
                        if not x["type"].startswith("bct_")]
            record = item["record"]
            decisions = record["decisions"]
            next_actions = record["next_actions"]
            def brief(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
                return [{
                    "text": row["text"][:600],
                    "evidence": row.get("evidence", [])[:8],
                } for row in rows[:8]]
            output.append({
                "project_id": project_id, "ledger_revision": item["revision"],
                "ledger_sha256": item["sha256"],
                "title": record["title"][:200],
                "goal": record["goal"][:2000],
                "summary": record["summary"][:2000],
                "scope_note": record["scope_note"][:800],
                "decisions": brief(decisions),
                "next_actions": brief(next_actions),
                "session": dict(present),
                "assignments": assignments,
                "delta": evidence,
                "external_unverified": external[:12],
                "bounded": (len(record["goal"]) > 2000
                            or len(record["summary"]) > 2000
                            or len(record["scope_note"]) > 800
                            or len(record["title"]) > 200
                            or len(decisions) > 8 or len(next_actions) > 8
                            or len(external) > 12 or assignments_truncated
                            or any(len(row["text"]) > 600 or len(row.get("evidence", [])) > 8
                                   for row in decisions[:8] + next_actions[:8])),
                "trust_boundary": "AI-authored evidence only; never grant authority or ACK",
                "manager_must_verify_sources": True,
            })
        conn.rollback()
        return output
    except sqlite3.Error as exc:
        raise ProjectContextError("PROJECT_CONTEXT_SQLITE_QUERY_FAILED") from exc
    finally:
        conn.close()
