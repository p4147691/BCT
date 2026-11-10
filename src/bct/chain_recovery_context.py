"""Read-only recovery context from existing Chain Recipe ledgers.

Called by any BCT-connected node as an intake helper; never grants Manager role.
No schema creation, sending, replay, Watch reservation or takeover.
"""
from __future__ import annotations

import json
import re
from typing import Any

_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_MAX_ROWS = 1000


def _key(value: str) -> str:
    value = str(value or "").lower()
    if value and not _UUID.fullmatch(value):
        raise ValueError("RECOVERY_CONVERSATION_INVALID")
    return value


def _exists(db: Any, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _collect(
    db: Any, sql: str, params: tuple[Any, ...], limit: int, offset: int = 0,
) -> dict[str, Any]:
    rows = [dict(row) for row in db.execute(
        sql + " LIMIT ? OFFSET ?", (*params, limit + 1, offset),
    ).fetchall()]
    more = len(rows) > limit
    return {"items": rows[:limit], "complete": not more,
            "next_offset": offset + limit if more else None}


def _work_candidates(db: Any, principal_id: str, caller: str, target: str) -> list[dict[str, str]]:
    """Exact conversation links only, no heuristic choice of a Manager."""
    if not caller and not target:
        return []
    candidates = set()
    keys = {caller, target} - {""}
    # The receiving node might not be the task's direct participant.
    # Reuse the existing network directory to discover its siblings rather
    # than requiring the user to supply a Work/Task/UUID.  Multiple matching
    # Work identities remain ambiguous; no automatic manager selection.
    if _exists(db, "conversation_network_memberships"):
        for original in sorted(keys):
            projects = db.execute(
                "SELECT project_id FROM conversation_network_memberships "
                "WHERE conversation_key=? AND activity='ACTIVE'",
                (original,),
            ).fetchall()
            for project in projects:
                members = db.execute(
                    "SELECT conversation_key FROM conversation_network_memberships "
                    "WHERE project_id=? AND activity='ACTIVE'",
                    (project["project_id"],),
                ).fetchall()
                keys.update(str(member["conversation_key"]) for member in members)
    for key in sorted(keys):
        if _exists(db, "delayed_send_watches"):
            for row in db.execute(
                "SELECT DISTINCT json_extract(context_json,'$.work_id') AS work_id "
                "FROM delayed_send_watches WHERE conversation_key=? "
                "OR json_extract(context_json,'$.manager_conversation_key')=? "
                "OR json_extract(context_json,'$.supervisor_conversation_key')=?",
                (key, key, key),
            ):
                if row["work_id"]:
                    candidates.add(str(row["work_id"]))
        if _exists(db, "chain_manager_return_checkpoints"):
            for row in db.execute(
                "SELECT DISTINCT work_id FROM chain_manager_return_checkpoints "
                "WHERE worker_conversation_key=? OR manager_conversation_key=? "
                "OR active_manager_conversation_key=? OR supervisor_conversation_key=?",
                (key, key, key, key),
            ):
                candidates.add(str(row["work_id"]))
        if _exists(db, "chain_directions"):
            columns = {str(col["name"]) for col in db.execute("PRAGMA table_info(chain_directions)")}
            if "target_conversation_key" in columns:
                for row in db.execute(
                    "SELECT DISTINCT work_id FROM chain_directions WHERE target_conversation_key=?",
                    (key,),
                ):
                    candidates.add(str(row["work_id"]))
            if "assessment_json" in columns:
                # Direction assessments already name A, S and the declared
                # per-target workers before a first Watch is recorded.
                for row in db.execute(
                    "SELECT work_id,assessment_json FROM chain_directions "
                    "WHERE assessment_json!='' AND assessment_json!='{}'",
                ):
                    try:
                        assessment = json.loads(row["assessment_json"])
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(assessment, dict):
                        continue
                    relations = {
                        str(assessment.get(field) or "").lower()
                        for field in ("manager_conversation_key", "worker_conversation_key",
                                      "supervisor_conversation_key")
                    }
                    relations.update(
                        str(x.get("conversation_key") or "").lower()
                        for x in assessment.get("targets", [])
                        if isinstance(x, dict)
                    )
                    if key in relations:
                        candidates.add(str(row["work_id"]))
    found = []
    for work_id in sorted(candidates):
        row = db.execute(
            "SELECT work_id,request_summary FROM works WHERE work_id=? "
            "AND owner_principal_id=?",
            (work_id, principal_id),
        ).fetchone()
        if row:
            found.append({"work_id": str(row["work_id"]),
                          "description": str(row["request_summary"])[:200]})
    return found


def read_chain_recovery_context(
    store: Any, *, principal_id: str, work_id: str = "",
    caller_conversation_key: str = "", target_conversation_key: str = "",
    limit: int = _MAX_ROWS,
    cursors: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Inspect the original Work's Chain state without user-supplied internal IDs.

    A Worker, Manager or Supervisor can read this under the same authenticated
    principal; role labels add neither access nor artificial recovery gates.
    """
    caller = _key(caller_conversation_key)
    target = _key(target_conversation_key)
    if type(limit) is not int or not 1 <= limit <= _MAX_ROWS:
        raise ValueError("RECOVERY_READ_LIMIT_INVALID")
    groups = ("watches", "manager_returns", "directions", "uncertain_operations")
    if cursors is None:
        cursors = {}
    if (not isinstance(cursors, dict) or set(cursors) - set(groups)
            or any(type(value) is not int or value < 0 for value in cursors.values())):
        raise ValueError("RECOVERY_READ_CURSOR_INVALID")
    with store._readonly() as db:
        # One consistent read snapshot; no schema, claim, Watch or Work mutation.
        db.execute("BEGIN")
        candidates = _work_candidates(db, principal_id, caller, target)
        if not work_id:
            if len(candidates) == 1:
                work_id = candidates[0]["work_id"]
            else:
                return {
                    "status": "SELECT_ORIGINAL_CONTEXT" if candidates else "NO_BOUND_CONTEXT",
                    "work_candidates": candidates,
                    "reason": "AMBIGUOUS_WORK" if candidates else "NO_EXACT_CONVERSATION_LINK",
                    "read_only": True,
                    "next": "READ_CURRENT_STATE_AND_MATCH_ORIGINAL_WORK",
                }
        owned = db.execute(
            "SELECT work_id,state,request_summary FROM works "
            "WHERE work_id=? AND owner_principal_id=?",
            (work_id, principal_id),
        ).fetchone()
        if owned is None:
            return {"status": "NOT_FOUND", "read_only": True}
        watches = {"items": [], "complete": True, "next_offset": None}
        if _exists(db, "delayed_send_watches"):
            watches = _collect(
                db,
                "SELECT task_id,generation,conversation_key,state,context_json "
                "FROM delayed_send_watches WHERE json_extract(context_json,'$.work_id')=? "
                "ORDER BY task_id,generation",
                (work_id,), limit, cursors.get("watches", 0),
            )
            for row in watches["items"]:
                context = json.loads(row.pop("context_json") or "{}")
                row["direction_id"] = str(context.get("chain_direction_id") or "")
                row["manager_conversation_key"] = str(context.get("manager_conversation_key") or "")
                row["supervisor_conversation_key"] = str(context.get("supervisor_conversation_key") or "")
                row["recovery_needed"] = bool(context.get("recovery_needed"))
        returns = {"items": [], "complete": True, "next_offset": None}
        if _exists(db, "chain_manager_return_checkpoints"):
            returns = _collect(
                db,
                "SELECT task_id,generation,direction_id,worker_conversation_key,"
                "active_manager_conversation_key,delivery_state,acknowledged_at,"
                "response_sha256 FROM chain_manager_return_checkpoints WHERE work_id=? "
                "ORDER BY task_id,generation",
                (work_id,), limit, cursors.get("manager_returns", 0),
            )
        directions = {"items": [], "complete": True, "next_offset": None}
        if _exists(db, "chain_directions"):
            directions = _collect(
                db,
                "SELECT direction_id,decision,chain_state,recipe_state,source_task_id,"
                "source_generation,target_conversation_key FROM chain_directions "
                "WHERE work_id=? ORDER BY created_at,direction_id",
                (work_id,), limit, cursors.get("directions", 0),
            )
        operation_uncertainties = {"items": [], "complete": True, "next_offset": None}
        if _exists(db, "operations"):
            operation_uncertainties = _collect(
                db,
                "SELECT operation_id,capability,state,outcome FROM operations "
                "WHERE work_id=? AND (outcome='UNKNOWN' OR state IN ('RUNNING','CLAIMED')) "
                "ORDER BY operation_id",
                (work_id,), limit, cursors.get("uncertain_operations", 0),
            )
    sources = {
        "watches": watches, "manager_returns": returns,
        "directions": directions, "uncertain_operations": operation_uncertainties,
    }
    complete = all(source["complete"] for source in sources.values())
    # A later page cannot claim that earlier rows have been reviewed.
    entire_work_examined = complete and not any(cursors.values())
    next_cursors = {
        name: source["next_offset"] for name, source in sources.items()
        if source["next_offset"] is not None
    }
    return {
        "status": "READY" if entire_work_examined else "PARTIAL_EVIDENCE",
        "work": {"work_id": str(owned["work_id"]),
                 "state": str(owned["state"]),
                 "description": str(owned["request_summary"])[:200]},
        "caller_conversation_key": caller,
        "target_conversation_key": target,
        "watches": watches,
        "manager_returns": returns,
        "directions": directions,
        "uncertain_operations": operation_uncertainties,
        "all_rows_examined": entire_work_examined,
        "page_complete": complete,
        "next_cursors": next_cursors,
        "read_only": True,
        "authority": "EXISTING_CORE_POLICY_ONLY",
        "next": "CHECK_RECHECK_EXACT_NODE_THEN_RECOVER_AND_RESUME_ORIGINAL_TASK",
        "does_not": [
            "grant_manager_role", "require_new_user_approval", "send_message",
            "replay_unknown", "replace_node", "create_work",
        ],
    }
