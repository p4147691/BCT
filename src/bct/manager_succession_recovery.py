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
        if (response.get("ok") is not True or not isinstance(state, dict)
                or state.get("instanceId") != attachment["instance_id"]
                or state.get("sessionId") != attachment["external_session_id"]):
            return "DISCONNECTED"
        for endpoint in state.get("endpoints", []):
            if not isinstance(endpoint, dict):
                continue
            if (endpoint.get("tabId") == attachment["tab_id"]
                    and endpoint.get("conversationKey") == attachment["conversation_key"]):
                if endpoint.get("presence") != "OPEN":
                    return "ORPHANED"
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
            return "DISCONNECTED"
        return self._readiness(attachment, response)

    def _current(self, *, limit: int) -> list[dict[str, Any]]:
        db = self.store._connect()
        try:
            rows = db.execute(
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
                "ORDER BY s.updated_at,s.session_id LIMIT ?", (limit,),
            ).fetchall()
            # One active attachment is expected; duplicate stale observations
            # are not a choice of authority, so leave them untouched.
            values: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                value = dict(row)
                if value["session_id"] not in seen:
                    seen.add(value["session_id"])
                    values.append(value)
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

    def run_once(self, *, limit: int = 8, now: float | None = None) -> dict[str, int | bool]:
        if isinstance(limit, bool) or not 1 <= limit <= 32:
            raise ValueError("MANAGER_SUCCESSION_LIMIT_INVALID")
        now = time.time() if now is None else max(float(now), time.time())
        summary: dict[str, int | bool] = {
            "lease_owned": False, "observed": 0, "due": 0, "taken_over": 0,
            "handoffs_delivered": 0, "handoffs_unknown": 0,
        }
        if not self._acquire(now):
            return summary
        summary["lease_owned"] = True
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
            if not observed["failover_due"]:
                continue
            summary["due"] += 1
            for candidate in self.service.manager_successor_candidates(
                work=work, session_id=str(current["session_id"]),
                expected_epoch=int(current["manager_epoch"]),
            ):
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
        return summary
