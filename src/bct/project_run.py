"""Bridge a conversation scope to one explicit durable orchestration run.

Conversation scopes remain the single user-facing project/network concept.
Their role tags are intentionally advisory.  A :class:`ProjectRun` records the
separate, time-bounded decision to use one selected conversation as the
manager for one BCT orchestration session.  It never sends an RCC message,
creates a Chrome tab, or treats a ``Manager`` tag as authority by itself.
"""
from __future__ import annotations

import re
import time
from typing import Any

from bct.conversation_network import ConversationNetworkError, project_view
from bct.core.store import Store


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_UUID = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z", re.I
)
_ACTIVE_STATES = frozenset({"PLANNED", "READY", "DEGRADED"})
_TERMINAL_STATES = frozenset({"COMPLETED", "CANCELLED"})


class ProjectRunError(ValueError):
    """A requested project-run transition is not safe or well formed."""


def _identifier(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ProjectRunError(code)
    return text


def _conversation_key(value: object, code: str) -> str:
    text = str(value or "").strip().lower()
    if not _UUID.fullmatch(text):
        raise ProjectRunError(code)
    return text


def _text(value: object, code: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text or len(text) > maximum:
        raise ProjectRunError(code)
    return text


def _members(db, scope_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT m.conversation_key,c.display_name,c.display_order "
        "FROM conversation_network_memberships m "
        "JOIN conversation_network_conversations c ON c.conversation_key=m.conversation_key "
        "WHERE m.project_id=? AND m.activity='ACTIVE' "
        "ORDER BY CASE WHEN c.display_order > 0 THEN c.display_order ELSE 2147483647 END, "
        "c.display_name COLLATE NOCASE, c.conversation_key",
        (scope_id,),
    ).fetchall()
    tags = db.execute(
        "SELECT conversation_key,tag FROM conversation_network_membership_tags "
        "WHERE project_id=? ORDER BY tag COLLATE NOCASE",
        (scope_id,),
    ).fetchall()
    tags_by_key: dict[str, list[str]] = {}
    for row in tags:
        tags_by_key.setdefault(str(row["conversation_key"]), []).append(str(row["tag"]))
    return [
        {
            "conversation_key": str(row["conversation_key"]),
            "display_name": str(row["display_name"]),
            "display_order": int(row["display_order"]),
            "role_tags": tags_by_key.get(str(row["conversation_key"]), []),
        }
        for row in rows
    ]


def _value(row, *, members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": str(row["run_id"]),
        "scope_id": str(row["scope_id"]),
        "objective": str(row["objective"]),
        "state": str(row["state"]),
        "manager_conversation_key": str(row["manager_conversation_key"]),
        "work_id": str(row["work_id"] or ""),
        "orchestration_session_id": str(row["orchestration_session_id"] or ""),
        "manager_node_id": str(row["manager_node_id"] or ""),
        "manager_attachment_id": str(row["manager_attachment_id"] or ""),
        "manager_attachment_generation": row["manager_attachment_generation"],
        "members": members,
    }


def start_project_run(
    store: Store, *, run_id: str, scope_id: str, objective: str,
    manager_conversation_key: str, now: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Create one planned run from an existing active conversation scope.

    The caller must explicitly select a currently tagged Manager.  This allows
    several advisory Managers to coexist without silently electing one.  The
    resulting record is still *PLANNED*: it is not an execution permission and
    has no external side effect.
    """
    run = _identifier(run_id, "PROJECT_RUN_ID_INVALID")
    scope = _identifier(scope_id, "PROJECT_RUN_SCOPE_ID_INVALID")
    objective_text = _text(objective, "PROJECT_RUN_OBJECTIVE_INVALID", 4000)
    manager_key = _conversation_key(
        manager_conversation_key, "PROJECT_RUN_MANAGER_CONVERSATION_INVALID"
    )
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        scope_row = db.execute(
            "SELECT active FROM conversation_network_projects WHERE project_id=?", (scope,)
        ).fetchone()
        if scope_row is None:
            raise ProjectRunError("PROJECT_RUN_SCOPE_NOT_FOUND")
        if not bool(scope_row["active"]):
            raise ProjectRunError("PROJECT_RUN_SCOPE_INACTIVE")
        members = _members(db, scope)
        selected = next((item for item in members if item["conversation_key"] == manager_key), None)
        if selected is None:
            raise ProjectRunError("PROJECT_RUN_MANAGER_NOT_IN_SCOPE")
        if "Manager" not in selected["role_tags"]:
            raise ProjectRunError("PROJECT_RUN_MANAGER_NOT_DESIGNATED")
        existing = db.execute(
            "SELECT * FROM persistent_project_runs WHERE run_id=?", (run,)
        ).fetchone()
        if existing is not None:
            comparable = (
                str(existing["scope_id"]), str(existing["objective"]),
                str(existing["manager_conversation_key"]),
            )
            if comparable != (scope, objective_text, manager_key):
                raise ProjectRunError("PROJECT_RUN_REQUEST_MISMATCH")
            return False, _value(existing, members=members)
        other = db.execute(
            "SELECT run_id FROM persistent_project_runs WHERE scope_id=? "
            "AND state IN ('PLANNED','READY','DEGRADED')", (scope,)
        ).fetchone()
        if other is not None:
            raise ProjectRunError("PROJECT_RUN_SCOPE_ALREADY_ACTIVE")
        db.execute(
            "INSERT INTO persistent_project_runs("
            "run_id,scope_id,objective,manager_conversation_key,state,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?)",
            (run, scope, objective_text, manager_key, "PLANNED", when, when),
        )
        Store._event(db, "PROJECT_RUN_PLANNED", run, {
            "scope_id": scope, "manager_conversation_key": manager_key,
        })
        created = db.execute(
            "SELECT * FROM persistent_project_runs WHERE run_id=?", (run,)
        ).fetchone()
        return True, _value(created, members=members)


def bind_project_run_session(
    store: Store, *, run_id: str, work_id: str, orchestration_session_id: str,
    manager_node_id: str, manager_attachment_id: str,
    manager_attachment_generation: int,
    now: float | None = None,
) -> dict[str, Any]:
    """Bind a planned run to an exact, already-synchronised orchestration path.

    This is the seam missing from the legacy composition: the selected UI
    Manager must be the same conversation as an active attachment in the same
    active orchestration session.  A title, node number, or browser window is
    never accepted as a substitute identity.
    """
    run = _identifier(run_id, "PROJECT_RUN_ID_INVALID")
    work = _identifier(work_id, "PROJECT_RUN_WORK_ID_INVALID")
    session = _identifier(orchestration_session_id, "PROJECT_RUN_SESSION_ID_INVALID")
    node = _identifier(manager_node_id, "PROJECT_RUN_MANAGER_NODE_ID_INVALID")
    attachment = _identifier(manager_attachment_id, "PROJECT_RUN_MANAGER_ATTACHMENT_ID_INVALID")
    if isinstance(manager_attachment_generation, bool) or int(manager_attachment_generation) < 1:
        raise ProjectRunError("PROJECT_RUN_MANAGER_ATTACHMENT_GENERATION_INVALID")
    generation = int(manager_attachment_generation)
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        row = db.execute(
            "SELECT * FROM persistent_project_runs WHERE run_id=?", (run,)
        ).fetchone()
        if row is None:
            raise ProjectRunError("PROJECT_RUN_NOT_FOUND")
        members = _members(db, str(row["scope_id"]))
        if str(row["state"]) not in {"PLANNED", "READY"}:
            raise ProjectRunError("PROJECT_RUN_NOT_BINDABLE")
        session_row = db.execute(
            "SELECT work_id,state,manager_node_id FROM orchestration_sessions WHERE session_id=?", (session,)
        ).fetchone()
        if session_row is None or str(session_row["work_id"]) != work:
            raise ProjectRunError("PROJECT_RUN_SESSION_WORK_MISMATCH")
        if str(session_row["state"]) not in {"ACTIVE", "PARTIAL"}:
            raise ProjectRunError("PROJECT_RUN_SESSION_NOT_ACTIVE")
        attachment_row = db.execute(
            "SELECT node_id,conversation_key,active FROM orchestration_attachments "
            "WHERE attachment_id=? AND generation=?", (attachment, generation),
        ).fetchone()
        if attachment_row is None or not bool(attachment_row["active"]):
            raise ProjectRunError("PROJECT_RUN_MANAGER_ATTACHMENT_NOT_ACTIVE")
        if str(attachment_row["node_id"]) != node:
            raise ProjectRunError("PROJECT_RUN_MANAGER_ATTACHMENT_NODE_MISMATCH")
        if str(attachment_row["conversation_key"]).lower() != str(row["manager_conversation_key"]):
            raise ProjectRunError("PROJECT_RUN_MANAGER_CONVERSATION_MISMATCH")
        session_node = db.execute(
            "SELECT active FROM orchestration_session_nodes WHERE session_id=? AND node_id=?", (session, node),
        ).fetchone()
        if session_node is None or not bool(session_node["active"]):
            raise ProjectRunError("PROJECT_RUN_MANAGER_SESSION_NODE_INACTIVE")
        bound = (str(row["work_id"] or ""), str(row["orchestration_session_id"] or ""))
        requested = (work, session)
        if bound != ("", "") and bound != requested:
            raise ProjectRunError("PROJECT_RUN_ALREADY_BOUND")
        if str(session_row["manager_node_id"] or "") not in {"", node}:
            raise ProjectRunError("PROJECT_RUN_CORE_MANAGER_MISMATCH")
        db.execute(
            "UPDATE persistent_project_runs SET work_id=?,orchestration_session_id=?,"
            "manager_node_id=?,manager_attachment_id=?,manager_attachment_generation=?,"
            "state='READY',updated_at=? WHERE run_id=?",
            (work, session, node, attachment, generation, when, run),
        )
        Store._event(db, "PROJECT_RUN_BOUND", run, {
            "work_id": work, "orchestration_session_id": session,
            "manager_node_id": node, "manager_attachment_id": attachment,
            "manager_attachment_generation": generation,
        })
        updated = db.execute(
            "SELECT * FROM persistent_project_runs WHERE run_id=?", (run,)
        ).fetchone()
        return _value(updated, members=members)


def project_run_view(store: Store, *, run_id: str) -> dict[str, Any]:
    """Read a project run without invoking RCC, Chrome, or Monitor."""
    run = _identifier(run_id, "PROJECT_RUN_ID_INVALID")
    with store.transaction() as db:
        row = db.execute(
            "SELECT * FROM persistent_project_runs WHERE run_id=?", (run,)
        ).fetchone()
        if row is None:
            raise ProjectRunError("PROJECT_RUN_NOT_FOUND")
        return _value(row, members=_members(db, str(row["scope_id"])))


def project_run_scope_view(store: Store, *, scope_id: str) -> dict[str, Any]:
    """Read scope directory plus its single active execution bridge, if any."""
    scope = _identifier(scope_id, "PROJECT_RUN_SCOPE_ID_INVALID")
    try:
        view = project_view(store, project_id=scope)
    except ConversationNetworkError as exc:
        raise ProjectRunError(str(exc)) from exc
    with store.transaction() as db:
        row = db.execute(
            "SELECT * FROM persistent_project_runs WHERE scope_id=? "
            "AND state IN ('PLANNED','READY','DEGRADED')", (scope,)
        ).fetchone()
        run = None if row is None else _value(row, members=_members(db, scope))
    return {"scope": view, "active_run": run}
