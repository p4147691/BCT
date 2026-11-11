"""Automatic-first, non-destructive recovery of exact Chain Recipe nodes.

BCT's Core owns this cycle, not any A/B/C/S Chat node. It reads existing
Watch/return identities and the same fresh Node Info/RCC status used by
Check/Recheck Node R; it never invents a conversation UUID or replays sends.
The usual Watch and Manager-return loops continue independently.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .node_recovery import NodeRecoveryLedger, observe_node
from .status_views import status_view


def _identity(work_id: str, conversation_key: str, assignment_epoch: int) -> str:
    return "auto-node-" + hashlib.sha256(
        (work_id + "|" + conversation_key + "|" + str(assignment_epoch)).encode("utf-8")
    ).hexdigest()[:32]


def _targets(store: Any) -> list[dict[str, str]]:
    """Read all exact Work-linked identities before choosing a bounded scan."""
    linked: dict[tuple[str, str], dict[str, str]] = {}
    with store._readonly() as db:
        existing = {
            str(r["name"]) for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "delayed_send_watches" in existing:
            for row in db.execute(
                "SELECT d.task_id,d.generation,d.conversation_key,d.state,d.context_json "
                "FROM delayed_send_watches d "
                "WHERE d.state IN ('WATCHING','RESERVED','PAUSED','DISPATCHING',"
                "'UNKNOWN','MANAGER_RECOVERY_PENDING') "
                "ORDER BY d.task_id,d.generation"
            ):
                try:
                    ctx = json.loads(row["context_json"] or "{}")
                except (ValueError, TypeError):
                    continue
                work_id = str(ctx.get("work_id") or "")
                if not work_id:
                    continue
                fields = [
                    ("manager", str(ctx.get("manager_conversation_key") or "")),
                    ("supervisor", str(ctx.get("supervisor_conversation_key") or "")),
                ]
                if str(row["state"]) != "MANAGER_RECOVERY_PENDING":
                    # The B task has *already completed* in this terminal
                    # state. Monitoring its missing tab as broken would cause
                    # pointless replay/replacement pressure.
                    fields.append(("worker", str(row["conversation_key"] or "")))
                for role, key in fields:
                    if not key:
                        continue
                    entry = linked.setdefault((work_id, key), {
                        "work_id": work_id, "conversation_key": key,
                        "role": role, "task_id": "",
                    })
                    # Worker task progress is included in Check/Recheck evidence.
                    if role == "worker":
                        entry["task_id"] = str(row["task_id"])
                    if role == "manager":
                        entry["role"] = "manager"
        if "chain_manager_return_checkpoints" in existing:
            for row in db.execute(
                "SELECT work_id,worker_conversation_key,"
                "active_manager_conversation_key,supervisor_conversation_key "
                "FROM chain_manager_return_checkpoints "
                "WHERE acknowledged_at=0 ORDER BY work_id,task_id,generation"
            ):
                wid = str(row["work_id"])
                for role, name in (
                    ("manager", "active_manager_conversation_key"),
                    ("supervisor", "supervisor_conversation_key"),
                ):
                    # A return checkpoint is evidence B finished its task.
                    # Do not treat the finished Worker tab as a live job.
                    key = str(row[name] or "")
                    if key:
                        linked.setdefault((wid, key), {
                            "work_id": wid, "conversation_key": key,
                            "role": role, "task_id": "",
                        })
        if "chain_directions" in existing:
            # A saved Direction can precede the first Watch. Without these
            # links, a stopped A or S is invisible to automatic Check/Recheck
            # at precisely the boundary where recovery is most useful.
            for row in db.execute(
                "SELECT d.work_id,d.assessment_json,d.chain_state,"
                "d.chain_task_id,d.target_conversation_key "
                "FROM chain_directions d JOIN works w ON w.work_id=d.work_id "
                "WHERE w.state='ACTIVE' AND d.decision='NEW_TASK' "
                "AND d.recipe_state IN ('READY','IN_PROGRESS') "
                "ORDER BY d.work_id,d.created_at,d.direction_id"
            ):
                wid = str(row["work_id"])
                try:
                    assessment = json.loads(row["assessment_json"] or "{}")
                except (ValueError, TypeError):
                    assessment = {}
                if not isinstance(assessment, dict):
                    assessment = {}
                for role, field in (
                    ("manager", "manager_conversation_key"),
                    ("supervisor", "supervisor_conversation_key"),
                ):
                    key = str(assessment.get(field) or "").lower()
                    if not re.fullmatch(
                        r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", key
                    ):
                        continue
                    entry = linked.setdefault((wid, key), {
                        "work_id": wid, "conversation_key": key,
                        "role": role, "task_id": "",
                    })
                    if role == "manager":
                        entry["role"] = "manager"
                # A per-target Direction known to have *started* is another
                # exact Worker source even when Watch registration was lost.
                # Planned-but-unsent Workers are not recovery candidates.
                key = str(row["target_conversation_key"] or "").lower()
                task_id = str(row["chain_task_id"] or "")
                if (row["chain_state"] != "CHAIN_STARTED" or not task_id
                        or not re.fullmatch(
                            r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", key
                        )):
                    continue
                if "chain_manager_return_checkpoints" in existing:
                    completed = db.execute(
                        "SELECT 1 FROM chain_manager_return_checkpoints "
                        "WHERE work_id=? AND task_id=? LIMIT 1", (wid, task_id),
                    ).fetchone()
                    if completed is not None:
                        continue
                if "delayed_send_watches" in existing:
                    prior_watch = db.execute(
                        "SELECT 1 FROM delayed_send_watches "
                        "WHERE task_id=? AND json_extract(context_json,'$.work_id')=? "
                        "AND state NOT IN ('WATCHING','RESERVED','PAUSED',"
                        "'DISPATCHING','UNKNOWN') LIMIT 1",
                        (task_id, wid),
                    ).fetchone()
                    if prior_watch is not None:
                        continue
                linked.setdefault((wid, key), {
                    "work_id": wid, "conversation_key": key,
                    "role": "worker", "task_id": task_id,
                })
        active = {
            str(row["work_id"]): str(row["owner_principal_id"])
            for row in db.execute(
                "SELECT work_id,owner_principal_id FROM works WHERE state='ACTIVE'"
            )
        }
    return [
        {**entry, "owner_principal_id": active[entry["work_id"]]}
        for (wid, _), entry in sorted(linked.items())
        if wid in active
    ]


class AutomaticChainNodeRecovery:
    """Continuous Check/Recheck over original Work identities for A/B/C/S."""

    def __init__(self, *, store: Any, status_provider):
        self.store = store
        self.status_provider = status_provider
        self._cursor = ""
        self.ledger = NodeRecoveryLedger(store)

    def run_once(self, *, limit: int = 16) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("AUTO_NODE_RECOVERY_LIMIT_INVALID")
        targets = _targets(self.store)
        cursor = self._cursor
        after = [
            row for row in targets
            if row["work_id"] + "|" + row["conversation_key"] > cursor
        ]
        if not after and cursor:
            cursor = ""
            after = targets
        selected = after[:limit]
        if selected:
            self._cursor = selected[-1]["work_id"] + "|" + selected[-1]["conversation_key"]
        if not selected:
            return {"status": "IDLE", "observed": 0,
                    "known_nodes": len(targets), "events": []}
        # One RCC/Node Info observation for this complete bounded batch;
        # loss of the sensor is not equivalent to loss of A/B/C/S.
        try:
            snapshot = self.status_provider()
            node_view = status_view(snapshot, "node")
            current = node_view.get("current_nodes") or {}
            if (node_view.get("status") != "OK"
                    or (current.get("observation") or {}).get("state") != "FRESH"):
                return {
                    "status": "SENSOR_UNKNOWN", "observed": 0,
                    "known_nodes": len(targets),
                    "reason": "NODE_OBSERVATION_NOT_FRESH", "events": [],
                }
        except Exception as exc:
            return {"status": "SENSOR_UNKNOWN", "observed": 0,
                    "known_nodes": len(targets),
                    "reason": type(exc).__name__, "events": []}
        events = []
        for row in selected:
            try:
                work = self.store.get_work(row["work_id"])
                evidence = observe_node(node_view, row["conversation_key"])
                case_id = _identity(
                    row["work_id"], row["conversation_key"], work.assignment_epoch
                )
                prior = self.ledger.get(work=work, case_id=case_id)
                if evidence["result"] in {"OK", "WAIT"} and prior is None:
                    continue
                if prior and prior["state"] == "PAUSED" and evidence["result"] == "OK":
                    context = prior.get("context") or {}
                    # A replacement first-submit may already have been sent.
                    # Only its original auto-provision coordinator can inspect
                    # that exact Operation receipt and safely restore the old
                    # node without creating two concurrent Chat leaders.
                    if context.get("automatic_new_chat_intent"):
                        continue
                    if isinstance(context.get("automatic_watch_restore"), list):
                        resumed = self.ledger.restore_automatic_predecessor(
                            work=work, case_id=case_id, evidence=evidence,
                        )
                        events.append({
                            "case_id":case_id, "work_id":row["work_id"],
                            "conversation_key":row["conversation_key"],
                            "status":"RECOVERED_SAME_UUID",
                            "restored_watches":resumed["restored_watches"],
                            "role":row["role"],
                            "next_action":"RESUME_PREVIOUS_WATCH",
                        })
                    continue
                if prior and prior["state"] in {
                    "PAUSED", "REPLACEMENT_PREPARED", "RESETTING", "RESET_UNKNOWN",
                    "REPLACED", "RESET",
                }:
                    # A prepared external replacement must never be undone by
                    # an unrelated Core observation after the replacement send.
                    continue
                # Do not create endless duplicate checks for a stable failed or
                # already recovered state. Fresh evidence changes still reopen
                # the same, scoped automatic recovery case.
                previous = (prior or {}).get("latest_check") or {}
                previous_evidence = previous.get("evidence") or {}
                if (prior and prior["state"] == "RECOVERY_NEEDED"
                        and evidence["result"] == "CHECK"
                        and all(
                            previous_evidence.get(field) == evidence.get(field)
                            for field in ("result", "reason",
                                          "observation_state", "node", "activity")
                        )):
                    events.append({
                        "case_id": case_id, "work_id": row["work_id"],
                        "conversation_key": row["conversation_key"],
                        "role": row["role"],
                        "status": "RECOVERY_EVIDENCE_READY",
                        "reason": evidence["reason"],
                        "next_action": "RECONCILE_EXACT_IDENTITY",
                    })
                    continue
                if (prior and prior["state"] == "RECOVERED"
                        and evidence["result"] == "OK"):
                    continue
                kind = "CHECK" if prior is None else "RECHECK"
                outcome = self.ledger.check(
                    work=work, case_id=case_id,
                    task_id="" if prior is None else str(prior["task_id"]),
                    conversation_key=row["conversation_key"], evidence=evidence,
                    kind=kind,
                )
                # Auto first: BCT's normal Watch/Alarm and return loops handle
                # newly reattached exact UUIDs. Never auto-restart a previously
                # dispatched/UNKNOWN operation or create a guessed Chat.
                state = ("RECOVERED_SAME_UUID" if outcome["result"] == "OK"
                         else "BUSY" if outcome["result"] == "WAIT"
                         else "RECOVERY_EVIDENCE_READY" if outcome["next_action"] == "RESTART"
                         else "RECHECKING")
                if state in {"RECOVERED_SAME_UUID", "RECOVERY_EVIDENCE_READY"}:
                    self.ledger.mark_automatic_observation(
                        work=work, case_id=case_id,
                        state=("RECOVERED" if state == "RECOVERED_SAME_UUID"
                               else "RECOVERY_NEEDED"),
                        reason=outcome["reason"],
                    )
                events.append({
                    "case_id": case_id, "work_id": row["work_id"],
                    "conversation_key": row["conversation_key"],
                    "role": row["role"], "status": state,
                    "reason": outcome["reason"],
                    "next_action": outcome["next_action"],
                })
            except (KeyError, ValueError) as exc:
                events.append({
                    "work_id": row["work_id"],
                    "conversation_key": row["conversation_key"],
                    "status": "RECONCILE_REQUIRED",
                    "reason": type(exc).__name__,
                })
        return {
            "status": "OBSERVED", "observed": len(selected),
            "known_nodes": len(targets), "events": events,
            "scan_cursor": self._cursor,
            "effects": "DURABLE_CHECKS_ONLY_NO_MESSAGE_OR_REPLACE",
        }
