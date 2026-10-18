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


_WORK_EVENTS = frozenset(("WORK_CREATED", "WORK_HANDED_OFF"))
_OPERATION_EVENTS = frozenset((
    "OPERATION_STARTED", "OPERATION_FINISHED", "OPERATION_RECONCILED",
    "OPERATION_STEPS_INITIALIZED", "OPERATION_STEP_STARTED",
    "OPERATION_STEP_FINISHED", "OPERATION_STEP_SKIPPED",
    "RCC_RENAME_CLAIM_RECLASSIFIED", "RCC_RENAME_CLAIM_OPERATOR_QUARANTINED",
    "ORCHESTRATION_RECOVERY_TAKEOVER", "ORCHESTRATION_NOT_DISPATCHED_PROVEN",
))
_SESSION_EVENTS = frozenset((
    "ORCHESTRATION_SESSION_STARTED", "ORCHESTRATION_MANAGER_TAKEOVER",
    "ORCHESTRATION_CHAIN_PLAN_RECORDED", "ORCHESTRATION_SESSION_FINISHED",
))
_ASSIGNMENT_EVENTS = frozenset((
    "ORCHESTRATION_ASSIGNMENT_CREATED", "ORCHESTRATION_ASSIGNMENT_FINISHED",
    "ORCHESTRATION_ASSIGNMENT_ADOPTED", "ORCHESTRATION_DISPATCH_RESERVED",
    "ORCHESTRATION_WORKER_REPLACED", "ORCHESTRATION_RESULTS_CONSUMED",
    "ORCHESTRATION_ASSIGNMENT_RECONCILED",
))
_WAKE_EVENTS = frozenset((
    "ORCHESTRATION_MANAGER_WAKE_RECORDED",
    "ORCHESTRATION_MANAGER_WAKE_DISPATCHING",
    "ORCHESTRATION_MANAGER_WAKE_STALE",
    "ORCHESTRATION_MANAGER_WAKE_DELIVERED",
    "ORCHESTRATION_MANAGER_WAKE_PENDING",
    "ORCHESTRATION_MANAGER_WAKE_UNKNOWN",
))
_DECISION_EVENTS = frozenset(("ORCHESTRATION_MANAGER_DECISION_COMMITTED",))
_MAX_SELECTORS = 400  # 800 SQLite bound parameters, below older 999-variable limit.


def _source_links_fingerprint(links: list[dict[str, str]]) -> str:
    """Bind a Manager bookmark to the project Work/Session membership.

    Cross-Work membership remains advisory, never authorization to retrieve
    any unrelated event.
    """
    import hashlib
    import json
    selected = sorted({
        (link["type"], link["id"]) for link in links
        if link["type"] in {"bct_work", "bct_session"}
    })
    encoded = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_project_events(
    conn: sqlite3.Connection, *, project: dict[str, Any],
    work_id: str, session_id: str, limit: int,
) -> dict[str, Any]:
    # Events are not protected by a Work foreign key. A matching subject ID
    # alone is therefore NOT an ownership proof. Query ONLY exact (kind, ID)
    # pairs whose entity belongs to this original Work and Session.
    selectors: set[tuple[str, str]] = set()

    def include(kinds: frozenset[str], identifier: str) -> None:
        for kind in kinds:
            selectors.add((kind, identifier))

    include(_WORK_EVENTS, work_id)
    include(_SESSION_EVENTS, session_id)

    sources = (
        ("SELECT operation_id FROM operations WHERE work_id=? LIMIT 1001",
         (work_id,), _OPERATION_EVENTS),
        ("SELECT assignment_id FROM orchestration_assignments "
         "WHERE session_id=? LIMIT 1001",
         (session_id,), _ASSIGNMENT_EVENTS),
        ("SELECT event_id FROM orchestration_manager_wakes "
         "WHERE session_id=? LIMIT 1001",
         (session_id,), _WAKE_EVENTS),
        ("SELECT decision_id FROM orchestration_consumption_decisions "
         "WHERE session_id=? LIMIT 1001",
         (session_id,), _DECISION_EVENTS),
    )
    source_ids_truncated = False
    for sql, args, kinds in sources:
        rows = conn.execute(sql, args).fetchall()
        if len(rows) > 1000:
            source_ids_truncated = True
        for row in rows[:1000]:
            include(kinds, str(row[0]))

    selectors_truncated = len(selectors) > _MAX_SELECTORS
    selected = sorted(selectors)[:_MAX_SELECTORS]

    record = project["record"]
    cursor = record["checkpoints"].get("bct_event_id")
    cursor = 0 if cursor is None else cursor
    highwater = int(conn.execute(
        "SELECT COALESCE(MAX(event_id),0) FROM events").fetchone()[0])
    if cursor > highwater:
        raise ProjectContextError("PROJECT_CONTEXT_CURSOR_AHEAD_OF_SOURCE")

    # A project can acquire an older Work after the global checkpoint was
    # saved. Without the previous link-set proof, that checkpoint must not
    # hide older events for the newly included source. No cursor is persisted
    # by this reader: the Manager must explicitly reconcile and save a new one.
    links = record["links"]
    fingerprint = _source_links_fingerprint(links)
    checkpoint_fp = record["checkpoints"].get("external", {}).get(
        "bct_source_links_sha256")
    rescan_required = cursor > 0 and checkpoint_fp != fingerprint
    effective_cursor = 0 if rescan_required else cursor

    # An individual Work status never proves completeness of another Work
    # merely because the project ledger links to both.
    foreign_members = any(
        ((link["type"] == "bct_work" and link["id"] != work_id)
         or (link["type"] == "bct_session" and link["id"] != session_id))
        for link in links
    )
    placeholders = ",".join("(?,?)" for _ in selected)
    params = [component for selector in selected for component in selector]
    if not selected:
        return {
            "events": [], "observed_through": effective_cursor,
            "highwater": highwater, "has_more": False,
            "source_complete": False, "reason": "NO_VERIFIED_SOURCE_SELECTORS",
            "source_links_sha256": fingerprint,
            "checkpoint_links_sha256": checkpoint_fp,
            "rescan_required": rescan_required,
            "evidence_scope": "PROVEN_EVENT_KIND_AND_ORIGINAL_ENTITY",
        }
    rows = conn.execute(
        "WITH allowed(kind,subject_id) AS (VALUES " + placeholders + ") "
        "SELECT e.event_id,e.kind,e.subject_id,e.created_at "
        "FROM events e JOIN allowed a "
        "ON e.kind=a.kind AND e.subject_id=a.subject_id "
        "WHERE e.event_id>? AND e.event_id<=? "
        "ORDER BY e.event_id ASC LIMIT ?",
        (*params, effective_cursor, highwater, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    current = rows[:limit]
    next_position = int(current[-1]["event_id"]) if has_more else highwater
    complete = not (
        has_more or selectors_truncated or source_ids_truncated
        or rescan_required or foreign_members
    )
    reason = (
        "SOURCE_LINK_SET_RESCAN_REQUIRED" if rescan_required else
        "MORE_EVENTS" if has_more else
        "PROVEN_SOURCE_SELECTOR_LIMIT" if selectors_truncated or source_ids_truncated else
        "CROSS_WORK_SOURCE_COVERAGE_REQUIRED" if foreign_members else None
    )
    return {
        "events": [dict(row) for row in current],
        "observed_through": next_position,
        "highwater": highwater,
        "has_more": has_more,
        "source_complete": complete,
        "reason": reason,
        "source_links_sha256": fingerprint,
        "checkpoint_links_sha256": checkpoint_fp,
        "rescan_required": rescan_required,
        "evidence_scope": "PROVEN_EVENT_KIND_AND_ORIGINAL_ENTITY",
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
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    except sqlite3.Error as exc:
        # Optional context retrieval must never break the original status.
        raise ProjectContextError("PROJECT_CONTEXT_SQLITE_CONNECT_FAILED") from exc
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
