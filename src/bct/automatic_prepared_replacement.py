"""Automatically finalize already prepared Node Recovery replacements.

This stage never creates a Chat, resends a Worker task or invents a UUID.
Only a predecessor with a durable REPLACEMENT_PREPARED case and a positively
verified successor with a completed first inheritance turn is finalized.
Manager A remains owned by Manager Epoch and atomic Watch/return succession.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .node_recovery import NodeRecoveryLedger, observe_node
from .status_views import status_view


_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z")


def _exact_successor_attachment(snapshot: dict, conversation_key: str) -> dict | None:
    """Require one real OPEN RCC instance/session/tab for the observed UUID."""
    rcc = status_view(snapshot, "rcc").get("rcc") or {}
    matches = []
    for instance in rcc.get("instances", []):
        if (not isinstance(instance, dict) or instance.get("state") != "OPEN"
                or instance.get("cached") is True):
            continue
        instance_id = str(instance.get("instance_id") or "")
        session_id = str(instance.get("session_id") or "")
        if not instance_id or not re.fullmatch("[a-f0-9]{32}", session_id):
            continue
        for tab in instance.get("tabs", []):
            if (not isinstance(tab, dict)
                    or str(tab.get("conversation_key") or "").lower() != conversation_key
                    or type(tab.get("tab_id")) is not int
                    or tab["tab_id"] <= 0
                    or type(tab.get("window_id")) is not int
                    or tab["window_id"] <= 0
                    or tab.get("presence") != "OPEN"):
                continue
            connection = tab.get("connection")
            if isinstance(connection, dict) and connection.get("disconnected") is True:
                continue
            matches.append({
                "instance_id": instance_id, "session_id": session_id,
                "tab_id": tab["tab_id"], "window_id": tab["window_id"],
            })
    return matches[0] if len(matches) == 1 else None


class AutomaticPreparedReplacement:
    """Crash-resumable, exact-identity finalization of an existing replacement."""

    def __init__(self, *, store: Any, status_provider):
        self.store = store
        self.status_provider = status_provider
        self.ledger = NodeRecoveryLedger(store)
        self._cursor = ""

    def _pending(self) -> list[dict]:
        with self.store._readonly() as db:
            rows = db.execute(
                "SELECT c.case_id,c.work_id,c.conversation_key,"
                "c.replacement_conversation_key,c.inheritance_task_id,"
                "c.assignment_epoch,c.principal_id,c.task_id "
                "FROM node_recovery_cases c JOIN works w ON w.work_id=c.work_id "
                "WHERE c.state='REPLACEMENT_PREPARED' AND w.state='ACTIVE' "
                "AND w.assignment_epoch=c.assignment_epoch "
                "AND w.owner_principal_id=c.principal_id "
                "ORDER BY c.case_id",
            ).fetchall()
            return [dict(row) for row in rows]

    def _inheritance_confirmed(self, item: dict) -> bool:
        # A Watch reservation is not evidence of an external send. A terminal
        # response with a durable observed-response hash proves the new Chat
        # actually received and processed its inheritance instruction.
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT state,conversation_key,context_json FROM delayed_send_watches "
                "WHERE task_id=? ORDER BY generation DESC LIMIT 1",
                (item["inheritance_task_id"],),
            ).fetchone()
            if row is None or row["conversation_key"] != item["replacement_conversation_key"]:
                return False
            try:
                context = json.loads(row["context_json"] or "{}")
            except (TypeError, ValueError):
                return False
            if context.get("work_id") != item["work_id"]:
                return False
            return (str(row["state"]) in {
                "SELF_SENT", "RETURNED_TO_MANAGER", "MANAGER_DECISION_REQUIRED"
            } and bool(context.get("observed_response_sha")
                       or context.get("observed_response_turn_key")))

    def _manager_original(self, item: dict) -> bool:
        """Do not bypass the Work's separate Manager Epoch/return handoff."""
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT 1 FROM conversation_network_membership_tags "
                "WHERE conversation_key=? AND lower(tag)='manager' LIMIT 1",
                (item["conversation_key"],),
            ).fetchone()
            if row is not None:
                return True
            unassigned = db.execute(
                "SELECT unassigned_role_tags FROM conversation_network_conversations "
                "WHERE conversation_key=?", (item["conversation_key"],),
            ).fetchone()
            if unassigned:
                try:
                    tags = json.loads(unassigned["unassigned_role_tags"] or "[]")
                except (TypeError, ValueError):
                    tags = []
                if isinstance(tags, list) and any(
                        str(tag).casefold() == "manager" for tag in tags):
                    return True
            row = db.execute(
                "SELECT 1 FROM delayed_send_watches "
                "WHERE json_extract(context_json,'$.work_id')=? "
                "AND json_extract(context_json,'$.manager_conversation_key')=? "
                "LIMIT 1",
                (item["work_id"], item["conversation_key"]),
            ).fetchone()
            if row is not None:
                return True
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='chain_manager_return_checkpoints'",
            ).fetchone()
            if exists is None:
                return False
            row = db.execute(
                "SELECT 1 FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND active_manager_conversation_key=? "
                "LIMIT 1",
                (item["work_id"], item["conversation_key"]),
            ).fetchone()
            return row is not None

    def _uncertain_original(self, item: dict) -> bool:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT 1 FROM delayed_send_watches "
                "WHERE conversation_key=? AND state IN ('UNKNOWN','DISPATCHING') "
                "AND json_extract(context_json,'$.work_id')=? LIMIT 1",
                (item["conversation_key"], item["work_id"]),
            ).fetchone()
            return row is not None

    def run_once(self, *, limit: int = 8) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("AUTO_PREPARED_REPLACE_LIMIT_INVALID")
        candidates = self._pending()
        selected = [x for x in candidates if x["case_id"] > self._cursor][:limit]
        if not selected and self._cursor:
            self._cursor = ""
            selected = candidates[:limit]
        if selected:
            self._cursor = str(selected[-1]["case_id"])
        if not selected:
            return {"status": "IDLE", "examined": 0, "pending": 0, "events": []}
        try:
            snapshot = self.status_provider()
            node_view = status_view(snapshot, "node")
            current = node_view.get("current_nodes") or {}
            if (node_view.get("status") != "OK"
                    or (current.get("observation") or {}).get("state") != "FRESH"):
                return {"status": "SENSOR_UNKNOWN", "examined": 0,
                        "pending": len(candidates), "events": []}
        except Exception as exc:
            return {"status": "SENSOR_UNKNOWN", "examined": 0,
                    "pending": len(candidates), "reason": type(exc).__name__,
                    "events": []}
        events = []
        for item in selected:
            work_id = str(item["work_id"])
            successor = str(item["replacement_conversation_key"] or "").lower()
            old = str(item["conversation_key"] or "").lower()
            if not _UUID.fullmatch(successor) or successor == old:
                events.append({"case_id": item["case_id"], "status": "RECONCILE_IDENTITY"})
                continue
            try:
                work = self.store.get_work(work_id)
                old_evidence = observe_node(node_view, old)
                if old_evidence["result"] in {"OK", "WAIT"}:
                    events.append({"case_id": item["case_id"], "status": "OLD_NODE_RECOVERED"})
                    continue
                new_evidence = observe_node(node_view, successor)
                if new_evidence["result"] != "OK":
                    events.append({"case_id": item["case_id"], "status": "AWAIT_SUCCESSOR"})
                    continue
                attachment = _exact_successor_attachment(snapshot, successor)
                if attachment is None:
                    events.append({"case_id": item["case_id"],
                                   "status": "AWAIT_EXACT_RCC_BINDING"})
                    continue
                new_evidence["verified_rcc_attachment"] = attachment
                if self._manager_original(item):
                    events.append({"case_id": item["case_id"], "status": "MANAGER_EPOCH_REBIND_REQUIRED"})
                    continue
                if self._uncertain_original(item):
                    events.append({"case_id": item["case_id"], "status": "UNKNOWN_RECONCILIATION_REQUIRED"})
                    continue
                if not self._inheritance_confirmed(item):
                    events.append({"case_id": item["case_id"], "status": "AWAIT_INHERITANCE_PROOF"})
                    continue
                done = self.ledger.commit_replace(
                    work=work, case_id=str(item["case_id"]),
                    successor_evidence=new_evidence,
                )
                events.append({"case_id": item["case_id"], "status": "REPLACED",
                               "successor_conversation_key": successor,
                               "duplicate": bool(done["duplicate"])})
            except (ValueError, KeyError) as exc:
                events.append({"case_id": item["case_id"], "status": "RECONCILE_REQUIRED",
                               "reason": str(exc)[:160]})
        return {"status": "OBSERVED", "examined": len(selected),
                "pending": len(candidates), "events": events,
                "effects": "EXISTING_PREPARED_REPLACEMENT_ONLY"}
