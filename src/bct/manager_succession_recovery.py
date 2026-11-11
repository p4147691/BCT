"""Fenced, bounded Manager succession recovery.

This is deliberately narrower than an agent scheduler.  It observes exact RCC
endpoints, makes one permanent Manager epoch transition after policy timeout,
and delivers one successor context notice.  It never reads a late predecessor
answer as success, replays an UNKNOWN handoff, or closes a Chrome tab.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from .core.durable_pr2 import acquire_lease
from .core.models import ConflictError, Outcome
from .core.orchestration import OrchestrationService
from .integrations.rcc import RelayClient, RelayEffectUnknown, RelayUnavailable


class ManagerSuccessionRecovery:
    """One fenced observer for permanent Manager succession."""

    _LEASE_NAME = "manager-succession-recovery"

    def __init__(self, service: OrchestrationService, client: RelayClient):
        self.service = service
        self.store = service.store
        self.client = client
        self.owner_id = "manager.succession." + secrets.token_hex(16)
        self.lease_token = secrets.token_hex(32)
        # Iterate all active Manager sessions, not the same first batch forever.
        self._scan_cursor = ""
        self._handoff_scan_cursor = ""

    def _acquire(self, now: float) -> bool:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM orchestration_manager_recovery_leases WHERE lease_name=?",
                (self._LEASE_NAME,),
            ).fetchone()
            expiry = now + 30.0
            if row is None:
                db.execute(
                    "INSERT INTO orchestration_manager_recovery_leases "
                    "(lease_name,owner_id,token,expires_at,updated_at,scan_cursor) "
                    "VALUES(?,?,?,?,?, '')",
                    (self._LEASE_NAME, self.owner_id, self.lease_token, expiry, now),
                )
                return True
            if (str(row["owner_id"]) == self.owner_id
                    and str(row["token"]) == self.lease_token
                    and float(row["expires_at"]) > now):
                db.execute(
                    "UPDATE orchestration_manager_recovery_leases SET expires_at=?,updated_at=? "
                    "WHERE lease_name=? AND owner_id=? AND token=? AND expires_at>?",
                    (expiry, now, self._LEASE_NAME, self.owner_id, self.lease_token, now),
                )
                return True
            if float(row["expires_at"]) <= now:
                return db.execute(
                    "UPDATE orchestration_manager_recovery_leases SET owner_id=?,token=?,"
                    "expires_at=?,updated_at=? WHERE lease_name=? AND owner_id=? "
                    "AND token=? AND expires_at<=?",
                    (self.owner_id, self.lease_token, expiry, now, self._LEASE_NAME,
                     str(row["owner_id"]), str(row["token"]), now),
                ).rowcount == 1
            return False

    @staticmethod
    def _readiness(attachment: dict[str, Any], response: dict[str, Any]) -> str:
        state = response.get("state") if isinstance(response, dict) else None
        if (not isinstance(response, dict) or response.get("ok") is not True
                or not isinstance(state, dict)
                or state.get("instanceId") != attachment["instance_id"]
                or state.get("sessionId") != attachment["external_session_id"]):
            return "UNKNOWN"
        endpoints = state.get("endpoints")
        if not isinstance(endpoints, list):
            return "UNKNOWN"
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            if (endpoint.get("tabId") == attachment["tab_id"]
                    and endpoint.get("conversationKey") == attachment["conversation_key"]):
                if endpoint.get("presence") != "OPEN":
                    return "ORPHANED"
                connection = endpoint.get("connection")
                if (isinstance(connection, dict)
                        and connection.get("disconnected") is True):
                    return "DISCONNECTED"
                return "GENERATING" if endpoint.get("generating") is True else "IDLE"
        return "ORPHANED"

    def _observe(self, attachment: dict[str, Any]) -> str:
        try:
            response = self.client.request(
                instance_id=str(attachment["instance_id"]),
                request_id="manager.liveness." + hashlib.sha256(
                    (str(attachment["attachment_id"]) + ":" + str(time.time_ns())).encode("utf-8")
                ).hexdigest()[:32],
                command="state", timeout_s=5.0,
            )
        except (RelayUnavailable, RelayEffectUnknown):
            # An unavailable sensor cannot prove a failed Chat node.
            return "UNKNOWN"
        return self._readiness(attachment, response)

    def _current(self, *, limit: int) -> list[dict[str, Any]]:
        """Fair bounded scan across every active Manager session."""
        db = self.store._connect()
        try:
            statement = (
                "SELECT s.session_id,s.manager_epoch,s.manager_node_id,s.work_id,"
                "a.attachment_id,a.generation,a.instance_id,a.external_session_id,a.tab_id,"
                "a.window_id,a.conversation_key,a.relay_role,a.binding_receipt_id "
                "FROM orchestration_sessions s JOIN works w ON w.work_id=s.work_id "
                "JOIN orchestration_attachments a ON a.node_id=s.manager_node_id AND a.active=1 "
                "WHERE s.state IN ('ACTIVE','PARTIAL') AND w.state='ACTIVE' "
                "AND w.assignment_epoch=s.work_assignment_epoch "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' AND EXISTS ("
                "SELECT 1 FROM orchestration_session_nodes sn WHERE sn.session_id=s.session_id "
                "AND sn.node_id=a.node_id AND sn.active=1) AND EXISTS ("
                "SELECT 1 FROM orchestration_rcc_instance_sessions rs WHERE rs.instance_id=a.instance_id "
                "AND rs.external_session_id=a.external_session_id) AND a.generation=("
                "SELECT MAX(a2.generation) FROM orchestration_attachments a2 "
                "WHERE a2.node_id=a.node_id AND a2.active=1) "
                "AND s.session_id>? ORDER BY s.session_id LIMIT ?"
            )
            def scan(after: str):
                return db.execute(statement, (after, limit)).fetchall()
            rows = scan(self._scan_cursor)
            if not rows and self._scan_cursor:
                # The next pass wraps to the oldest identity; a stale cursor
                # after Core restart/session removal cannot strand new work.
                self._scan_cursor = ""
                rows = scan("")
            values: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                value = dict(row)
                if value["session_id"] not in seen:
                    seen.add(value["session_id"])
                    values.append(value)
            if rows:
                self._scan_cursor = str(rows[-1]["session_id"])
            return values
        finally:
            db.close()

    def _send_handoff(self, handoff: dict[str, Any], work) -> str:
        payload = json.loads(str(handoff["payload_json"]))
        text = (
            "[BCT_MANAGER_SUCCESSION_V1]" + json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ) + "[/BCT_MANAGER_SUCCESSION_V1]"
        )
        try:
            response = self.client.request(
                instance_id=str(handoff["instance_id"]), request_id=str(handoff["delivery_id"]),
                command="send-wakeback", to=str(handoff["relay_role"]), text=text,
                timeout_s=15.0, extra={
                    "fromNode": "BCT_MANAGER_SUCCESSION",
                    "bindingReceiptId": str(handoff["binding_receipt_id"]),
                    "expectedInstanceId": str(handoff["instance_id"]),
                    "expectedSessionId": str(handoff["external_session_id"]),
                    "expectedTabId": int(handoff["tab_id"]),
                    "expectedConversationKey": str(handoff["conversation_key"]),
                    "attachmentGeneration": int(handoff["attachment_generation"]),
                    "returnTo": "",
                    "returnOnAck": True,
                },
            )
        except RelayEffectUnknown:
            outcome = Outcome.UNKNOWN
        except RelayUnavailable:
            outcome = Outcome.NOT_APPLIED
        else:
            outcome = (
                Outcome.APPLIED if (response.get("type") == "host:ack"
                                    and response.get("ok") is True
                                    and response.get("submitted") is True)
                else Outcome.NOT_APPLIED if (str(response.get("effectState") or "").upper()
                                              in {"NOT_APPLIED", "QUEUED"}
                                              or response.get("deferred") is True)
                else Outcome.UNKNOWN
            )
        self.service.complete_manager_handoff(
            work=work, session_id=str(handoff["session_id"]),
            successor_epoch=int(handoff["successor_epoch"]),
            handoff_id=str(handoff["handoff_id"]), delivery_id=str(handoff["delivery_id"]),
            outcome=outcome,
        )
        return outcome.value

    def _current_pending_handoffs(self, *, limit: int) -> list[dict[str, Any]]:
        """Resume only current-epoch PENDING handoffs after Core restart.

        A takeover may have committed its Manager Epoch before the process
        claimed its first context notice. A later loop must find that exact
        already-created handoff, not elect another Manager or invent new IDs.
        DELIVERING, UNKNOWN, DELIVERED and BLOCKED never appear here.
        """
        with self.store._readonly() as db:
            tables = {
                str(row["name"]) for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required = {
                "orchestration_manager_handoffs",
                "orchestration_sessions",
                "orchestration_attachments",
                "orchestration_session_nodes",
                "works",
            }
            if not required.issubset(tables):
                return []
            statement = (
                "SELECT h.*,s.work_id FROM orchestration_manager_handoffs h "
                "JOIN orchestration_sessions s ON s.session_id=h.session_id "
                "JOIN works w ON w.work_id=s.work_id "
                "JOIN orchestration_attachments a ON a.attachment_id=h.attachment_id "
                "JOIN orchestration_session_nodes n "
                "ON n.session_id=h.session_id AND n.node_id=h.successor_node_id "
                "WHERE h.state IN ('PENDING','NOT_APPLIED') "
                "AND w.state='ACTIVE' AND w.assignment_epoch=s.work_assignment_epoch "
                "AND s.state IN ('ACTIVE','PARTIAL') "
                "AND h.successor_epoch=s.manager_epoch "
                "AND h.successor_node_id=s.manager_node_id "
                "AND n.active=1 AND n.session_role='MANAGER' "
                "AND a.active=1 AND a.node_id=h.successor_node_id "
                "AND a.generation=h.attachment_generation "
                "AND a.generation=(SELECT MAX(a2.generation) "
                "FROM orchestration_attachments a2 "
                "WHERE a2.node_id=a.node_id AND a2.active=1) "
                "AND a.instance_id=h.instance_id "
                "AND a.external_session_id=h.external_session_id "
                "AND a.tab_id=h.tab_id "
                "AND a.conversation_key=h.conversation_key "
                "AND a.binding_receipt_id=h.binding_receipt_id "
                "AND h.handoff_id>? "
                "ORDER BY h.handoff_id LIMIT ?"
            )
            rows = db.execute(
                statement, (self._handoff_scan_cursor, limit),
            ).fetchall()
            if not rows and self._handoff_scan_cursor:
                self._handoff_scan_cursor = ""
                rows = db.execute(statement, ("", limit)).fetchall()
            if rows:
                self._handoff_scan_cursor = str(rows[-1]["handoff_id"])
        return [dict(row) for row in rows]

    def _resume_committed_handoffs(self, *, limit: int) -> dict[str, int]:
        """Claim/complete only previously committed current-Epoch receipts."""
        stats = {"eligible": 0, "delivered": 0, "unknown": 0, "waiting": 0}
        for item in self._current_pending_handoffs(limit=limit):
            stats["eligible"] += 1
            if self._observe(item) != "IDLE":
                stats["waiting"] += 1
                continue
            work = self.store.get_work(str(item["work_id"]))
            # The existing claim checks the current epoch *again* and records
            # the deterministic delivery_id before any RCC external effect.
            # A concurrent Manager takeover fences this claim.
            try:
                claimed = self.service.claim_manager_handoff(
                    work=work, session_id=str(item["session_id"]),
                    successor_epoch=int(item["successor_epoch"]),
                )
            except ConflictError:
                stats["waiting"] += 1
                continue
            if claimed is None:
                continue
            result = self._send_handoff(claimed, work)
            if result == Outcome.APPLIED.value:
                stats["delivered"] += 1
            elif result == Outcome.UNKNOWN.value:
                stats["unknown"] += 1
        return stats

    def run_once(self, *, limit: int = 8, now: float | None = None) -> dict[str, int | bool]:
        if isinstance(limit, bool) or not 1 <= limit <= 32:
            raise ValueError("MANAGER_SUCCESSION_LIMIT_INVALID")
        now = time.time() if now is None else max(float(now), time.time())
        summary: dict[str, int | bool] = {
            "lease_owned": False, "observed": 0, "due": 0, "taken_over": 0,
            "handoffs_delivered": 0, "handoffs_unknown": 0,
            "telemetry_unknown": 0, "needs_successor": 0,
            "handoffs_resumed": 0, "handoffs_resume_unknown": 0,
            "handoffs_resume_waiting": 0,
        }
        if not self._acquire(now):
            return summary
        summary["lease_owned"] = True
        # The Core may have stopped between durable Epoch takeover and its
        # first Manager handoff. Reconcile that exact existing receipt before
        # considering any further recovery election.
        resumed = self._resume_committed_handoffs(limit=limit)
        summary["handoffs_resumed"] = resumed["delivered"]
        summary["handoffs_resume_unknown"] = resumed["unknown"]
        summary["handoffs_resume_waiting"] = resumed["waiting"]
        summary["handoffs_delivered"] += resumed["delivered"]
        summary["handoffs_unknown"] += resumed["unknown"]
        for current in self._current(limit=limit):
            work = self.store.get_work(str(current["work_id"]))
            state = self._observe(current)
            observed = self.service.observe_manager_liveness(
                work=work, session_id=str(current["session_id"]),
                manager_epoch=int(current["manager_epoch"]), state=state,
                evidence={"attachment_id": current["attachment_id"], "source": "rcc-state"},
                observed_at=now,
            )
            summary["observed"] += 1
            if state == "UNKNOWN":
                summary["telemetry_unknown"] += 1
            if not observed["failover_due"]:
                continue
            summary["due"] += 1
            # Confirm the failure again immediately before an epoch transfer.
            final_state = self._observe(current)
            if final_state not in {"ORPHANED", "DISCONNECTED"}:
                self.service.observe_manager_liveness(
                    work=work, session_id=str(current["session_id"]),
                    manager_epoch=int(current["manager_epoch"]),
                    state=final_state, evidence={"source": "rcc-recheck"},
                    observed_at=now,
                )
                continue
            for candidate in self.service.manager_successor_candidates(
                work=work, session_id=str(current["session_id"]),
                expected_epoch=int(current["manager_epoch"]),
            ):
                # An idle ordinary Worker is never an implicit Manager.
                if str(candidate["session_role"]) not in {"STANDBY", "MANAGER"}:
                    continue
                if self._observe(candidate) != "IDLE":
                    continue
                session = self.service.takeover_manager(
                    work=work, session_id=str(current["session_id"]),
                    expected_epoch=int(current["manager_epoch"]),
                    manager_node_id=str(candidate["node_id"]), reason="MANAGER_INACTIVE_TIMEOUT",
                    evidence={"state": state, "elapsed_s": observed["elapsed_s"],
                              "failover_after_s": observed["failover_after_s"]},
                )
                # The successor lease is acquired only after the durable epoch
                # transition.  This cannot revive the predecessor epoch.
                acquire_lease(
                    self.store, session_id=str(current["session_id"]),
                    manager_node_id=str(candidate["node_id"]),
                    expected_epoch=int(session["manager_epoch"]), ttl_s=60.0,
                )
                summary["taken_over"] += 1
                handoff = self.service.claim_manager_handoff(
                    work=work, session_id=str(current["session_id"]),
                    successor_epoch=int(session["manager_epoch"]),
                )
                if handoff is not None:
                    result = self._send_handoff(handoff, work)
                    if result == Outcome.APPLIED.value:
                        summary["handoffs_delivered"] += 1
                    elif result == Outcome.UNKNOWN.value:
                        summary["handoffs_unknown"] += 1
                break
            else:
                # An actual confirmed failure without a safe existing
                # successor is still not permission to promote a Worker.
                # Surface the unresolved automatic-recovery work in status.
                summary["needs_successor"] += 1
        return summary
