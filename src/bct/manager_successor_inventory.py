"""Read-only Manager successor recovery inventory with exact Task/Generation receipts.

This is metadata, not a send queue. It never infers successful Worker work from
a message delivery, and never releases an external UNKNOWN operation.
"""
from __future__ import annotations

from typing import Any


def manager_successor_inventory(store: Any, *, work_id: str,
                                session_id: str, expected_epoch: int,
                                limit: int = 50) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("MANAGER_SUCCESSOR_INVENTORY_LIMIT_INVALID")
    with store._readonly() as db:
        # Keep Session/Epoch, original attempts, Watches, returns and counts
        # on ONE SQLite read snapshot. Otherwise a concurrent takeover can
        # mix two manager generations in a single resume inventory.
        db.execute("BEGIN")
        session = db.execute(
            "SELECT session_id,work_id,manager_node_id,manager_epoch,state,"
            "work_assignment_epoch FROM orchestration_sessions "
            "WHERE session_id=? AND work_id=?", (session_id, work_id),
        ).fetchone()
        if session is None:
            raise ValueError("MANAGER_SUCCESSOR_SESSION_NOT_FOUND")
        if (int(session["manager_epoch"]) != expected_epoch or
                str(session["state"]) not in {"ACTIVE", "PARTIAL"}):
            raise ValueError("MANAGER_SUCCESSOR_EPOCH_NOT_CURRENT")
        work = db.execute(
            "SELECT state,assignment_epoch FROM works WHERE work_id=?",
            (work_id,),
        ).fetchone()
        if (work is None or work["state"] != "ACTIVE" or
                int(work["assignment_epoch"]) != int(session["work_assignment_epoch"])):
            raise ValueError("MANAGER_SUCCESSOR_WORK_EPOCH_CHANGED")
        handoff = db.execute(
            "SELECT handoff_id,state,delivery_id,attachment_id,"
            "attachment_generation,conversation_key FROM orchestration_manager_handoffs "
            "WHERE session_id=? AND successor_epoch=?",
            (session_id, expected_epoch),
        ).fetchone()
        succession = db.execute(
            "SELECT successor_node_id,predecessor_epoch,close_state "
            "FROM orchestration_manager_successions WHERE session_id=? "
            "AND successor_epoch=?", (session_id, expected_epoch),
        ).fetchone()
        rows = db.execute(
            "SELECT a.assignment_id,a.state AS assignment_state,"
            "a.current_generation,t.generation,t.manager_epoch AS task_epoch,"
            "t.worker_node_id,t.state AS attempt_state,t.dispatch_operation_id,"
            "t.dispatch_message_id "
            "FROM orchestration_assignments a "
            "LEFT JOIN orchestration_assignment_attempts t "
            "ON t.assignment_id=a.assignment_id "
            "AND t.generation=a.current_generation "
            "WHERE a.session_id=? ORDER BY a.assignment_id LIMIT ?",
            (session_id, limit + 1),
        ).fetchall()
        total = db.execute(
            "SELECT COUNT(*) AS n FROM orchestration_assignments "
            "WHERE session_id=?", (session_id,),
        ).fetchone()["n"]
        tables={
            str(row["name"]) for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        watches=[]
        watch_count=0
        legacy_watch_count=0
        # Invalid historical metadata must not break the whole Manager
        # snapshot. A legacy Work-only Watch is visible for reconciliation,
        # but is NOT proof of membership in this orchestration Session.
        if "delayed_send_watches" in tables:
            safe_work = (
                "CASE WHEN json_valid(d.context_json) "
                "THEN json_extract(d.context_json,'$.work_id') END"
            )
            safe_session = (
                "CASE WHEN json_valid(d.context_json) "
                "THEN json_extract(d.context_json,'$.session_id') END"
            )
            where = (
                f"{safe_work}=? AND ({safe_session}=? "
                f"OR {safe_session} IS NULL)"
            )
            watches = db.execute(
                "SELECT d.task_id,d.generation,d.state,d.conversation_key,"
                "d.source_send_receipt,CASE WHEN "
                f"{safe_session}=? THEN 'EXACT_SESSION' ELSE "
                "'LEGACY_WORK_ONLY_UNVERIFIED' END AS session_scope "
                "FROM delayed_send_watches d WHERE " + where +
                " ORDER BY d.task_id,d.generation LIMIT ?",
                (session_id,work_id,session_id,limit+1),
            ).fetchall()
            watch_count=db.execute(
                "SELECT COUNT(*) AS n FROM delayed_send_watches d WHERE "+where,
                (work_id,session_id),
            ).fetchone()["n"]
            legacy_watch_count=db.execute(
                "SELECT COUNT(*) AS n FROM delayed_send_watches d WHERE "+where+
                f" AND {safe_session} IS NULL",
                (work_id,session_id),
            ).fetchone()["n"]
            # Malformed historic JSON is excluded by guarded extraction.
            # It cannot be attributed to a Work safely. Do not expose a
            # GLOBAL count in this Work-scoped view, or let unrelated Works
            # suppress valid exact-session recovery evidence.
        returns=[]
        return_count=0
        if "chain_manager_return_checkpoints" in tables:
            returns=db.execute(
                "SELECT task_id,generation,delivery_state,delivery_operation_id,"
                "active_manager_conversation_key,acknowledged_at "
                "FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND acknowledged_at=0 "
                "ORDER BY task_id,generation LIMIT ?", (work_id,limit+1),
            ).fetchall()
            return_count=db.execute(
                "SELECT COUNT(*) AS n FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND acknowledged_at=0", (work_id,),
            ).fetchone()["n"]
        pending_wakes = db.execute(
            "SELECT event_id,assignment_id,assignment_generation,manager_epoch,"
            "state,delivery_id,acknowledged_at,decision_id "
            "FROM orchestration_manager_wakes WHERE session_id=? "
            "AND acknowledged_at IS NULL AND state!='STALE' "
            "ORDER BY created_at,event_id LIMIT ?", (session_id, limit + 1),
        ).fetchall()
        wake_count = db.execute(
            "SELECT COUNT(*) AS n FROM orchestration_manager_wakes "
            "WHERE session_id=? AND acknowledged_at IS NULL AND state!='STALE'",
            (session_id,),
        ).fetchone()["n"]
    tasks=[]
    for row in rows[:limit]:
        x=dict(row)
        # This classification is advisory; an AI must inspect the exact
        # existing result/Operation receipts before deciding its next task.
        if str(x["assignment_state"]) in {"APPLIED","FAILED","CANCELLED"}:
            next_step="INSPECT_TERMINAL_RECEIPT_NO_REPLAY"
        elif x["dispatch_operation_id"] or x["dispatch_message_id"]:
            # A durable mailbox message can exist even when a browser
            # Operation ID was not yet persisted. Such a generation is NOT
            # safe to adopt as unsent. Check that exact message/Operation.
            next_step="RECONCILE_EXACT_DISPATCH_OPERATION_NO_REPLAY"
        elif (str(x["assignment_state"]) == "QUEUED"
              and str(x["attempt_state"]) == "QUEUED"):
            next_step="ADOPT_QUEUED_GENERATION_ONLY_IF_NOT_DISPATCHED"
        else:
            next_step="INSPECT_ORIGINAL_TASK_GENERATION"
        tasks.append({
            "assignment_id":x["assignment_id"],
            "generation":x["current_generation"],
            "assignment_state":x["assignment_state"],
            "attempt_state":x["attempt_state"],
            "attempt_manager_epoch":x["task_epoch"],
            "worker_node_id":x["worker_node_id"],
            "dispatch_operation_id":x["dispatch_operation_id"],
            "dispatch_message_id":x["dispatch_message_id"],
            "next_safe_step":next_step,
        })
    return {
        "work_id":work_id, "session_id":session_id,
        "manager_epoch":expected_epoch,
        "manager_node_id":str(session["manager_node_id"] or ""),
        "manager_handoff":dict(handoff) if handoff else None,
        "manager_succession":dict(succession) if succession else None,
        "tasks":tasks, "total_tasks":int(total),
        "tasks_complete_listing":int(total)<=limit,
        "chain_watches":[dict(x) for x in watches[:limit]],
        "total_chain_watches":int(watch_count),
        "watches_complete_listing":int(watch_count)<=limit,
        "legacy_work_only_watches":int(legacy_watch_count),
        "watch_session_membership_verified":int(legacy_watch_count)==0,
        "unattributed_watch_integrity":"NOT_ASSESSED_WORK_SCOPED",
        "unacknowledged_returns":[dict(x) for x in returns[:limit]],
        "total_unacknowledged_returns":int(return_count),
        "returns_complete_listing":int(return_count)<=limit,
        "unresolved_manager_wakes":[dict(x) for x in pending_wakes[:limit]],
        "total_unresolved_wakes":int(wake_count),
        "wakes_complete_listing":int(wake_count)<=limit,
        "effects":"READ_ONLY_NO_SEND_NO_REPLACE",
    }
