"""Trigger adapter for bounded RCC Manager-result recovery.

The adapter performs no decision logic. Polling and a future trusted event
transport converge on ``ManagerDecisionConsumer.consume_receipt``.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

from .core.manager_decision import ManagerDecisionConsumer
from .core.models import ConflictError, PreconditionError
from .core.orchestration import OrchestrationService
from .integrations.rcc import RelayClient, RelayEffectUnknown, RelayUnavailable


@dataclass(frozen=True)
class PollCandidate:
    event_id: str
    session_id: str
    manager_epoch: int
    instance_id: str
    delivery_id: str
    work_id: str
    lease_token: str
    result_hash: str | None
    ack_only: bool


class ManagerDecisionRecovery:
    """Bounded receipt recovery; it never sends or retries a Manager wake."""

    def __init__(
        self, service: OrchestrationService, client: RelayClient,
        *, on_deliveries: Callable[[], None] | None = None,
    ):
        self.service = service
        self.store = service.store
        self.client = client
        self.consumer = ManagerDecisionConsumer(service)
        self.owner_id = "mgr.recovery." + secrets.token_hex(16)
        self.lease_token = secrets.token_hex(32)
        self.on_deliveries = on_deliveries

    def _acquire_recovery_lease(self, *, now: float) -> bool:
        """Own one fenced poller and recover only its current Manager leases."""
        if not self.service.manager_wake_receipt_v2_enabled:
            return False
        expires_at = now + 30.0
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='manager-decision-poller'",
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO orchestration_manager_recovery_leases "
                    "(lease_name,owner_id,token,expires_at,updated_at,scan_cursor) "
                    "VALUES('manager-decision-poller',?,?,?,?, '')",
                    (self.owner_id, self.lease_token, expires_at, now),
                )
            elif (str(row["owner_id"]) == self.owner_id
                  and str(row["token"]) == self.lease_token
                  and float(row["expires_at"]) > now):
                db.execute(
                    "UPDATE orchestration_manager_recovery_leases "
                    "SET expires_at=?,updated_at=? WHERE lease_name=? "
                    "AND owner_id=? AND token=? AND expires_at>?",
                    (expires_at, now, "manager-decision-poller",
                     self.owner_id, self.lease_token, now),
                )
            elif float(row["expires_at"]) <= now:
                changed = db.execute(
                    "UPDATE orchestration_manager_recovery_leases SET "
                    "owner_id=?,token=?,expires_at=?,updated_at=? "
                    "WHERE lease_name=? AND owner_id=? AND token=? AND expires_at<=?",
                    (self.owner_id, self.lease_token, expires_at, now,
                     "manager-decision-poller", str(row["owner_id"]),
                     str(row["token"]), now),
                ).rowcount
                if changed != 1:
                    return False
            else:
                return False

            # A crashed Core may leave the internal Manager lease expired.  The
            # poller lease fences the old process first; only the exact current
            # session owner/epoch may then receive a rotated token.  This is not
            # a Manager takeover and cannot revive a stale epoch.
            expired = db.execute(
                "SELECT DISTINCT l.session_id,l.manager_node_id,l.epoch,l.token "
                "FROM orchestration_durable_leases l "
                "JOIN orchestration_sessions s ON s.session_id=l.session_id "
                "JOIN works k ON k.work_id=s.work_id "
                "JOIN orchestration_manager_wakes w ON w.session_id=l.session_id "
                "WHERE w.envelope_schema=2 AND w.receipt_mode='RCC_RESULT_POLL_V1' "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.state IN ('DELIVERING','DELIVERED','UNKNOWN') "
                "AND (w.decision_id IS NULL OR w.result_ack_state='PENDING') "
                "AND s.state IN ('ACTIVE','PARTIAL') AND k.state='ACTIVE' "
                "AND k.assignment_epoch=s.work_assignment_epoch "
                "AND s.manager_epoch=w.manager_epoch AND l.epoch=s.manager_epoch "
                "AND l.manager_node_id=s.manager_node_id AND l.expires_at<=?",
                (now,),
            ).fetchall()
            for lease in expired:
                successor_token = secrets.token_hex(32)
                changed = db.execute(
                    "UPDATE orchestration_durable_leases SET token=?,expires_at=?,"
                    "updated_at=? WHERE session_id=? AND manager_node_id=? AND "
                    "epoch=? AND token=? AND expires_at<=?",
                    (successor_token, now + 60.0, now, lease["session_id"],
                     lease["manager_node_id"], lease["epoch"], lease["token"], now),
                ).rowcount
                if changed != 1:
                    raise ConflictError("MANAGER_RECOVERY_LEASE_ROTATION_RACE")
                self.store._event(db, "ORCHESTRATION_MANAGER_LEASE_RECOVERED", str(
                    lease["session_id"]), {
                        "manager_node_id": str(lease["manager_node_id"]),
                        "manager_epoch": int(lease["epoch"]),
                        "prior_token_digest": hashlib.sha256(
                            str(lease["token"]).encode("utf-8")
                        ).hexdigest(),
                    })
            return True

    def _candidates(self, *, limit: int, now: float) -> list[PollCandidate]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
            raise ValueError("MANAGER_POLL_LIMIT_INVALID")
        if not self.service.manager_wake_receipt_v2_enabled:
            return []
        db = self.store._connect()
        try:
            owner = db.execute(
                "SELECT scan_cursor FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='manager-decision-poller' AND owner_id=? "
                "AND token=? AND expires_at>?",
                (self.owner_id, self.lease_token, now),
            ).fetchone()
            if owner is None:
                return []
            common = (
                "SELECT w.event_id,w.session_id,w.manager_epoch,w.instance_id,"
                "w.delivery_id,s.work_id,l.token,w.result_hash,w.result_ack_state "
                "FROM orchestration_manager_wakes w "
                "JOIN orchestration_sessions s ON s.session_id=w.session_id "
                "JOIN works k ON k.work_id=s.work_id "
                "JOIN orchestration_durable_leases l ON l.session_id=w.session_id "
                "WHERE w.envelope_schema=2 AND w.receipt_mode='RCC_RESULT_POLL_V1' "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.state IN ('DELIVERING','DELIVERED','UNKNOWN') "
                "AND w.delivery_id IS NOT NULL AND s.manager_epoch=w.manager_epoch "
                "AND s.state IN ('ACTIVE','PARTIAL') AND k.state='ACTIVE' "
                "AND k.assignment_epoch=s.work_assignment_epoch "
                "AND l.epoch=w.manager_epoch AND l.manager_node_id=s.manager_node_id "
                "AND l.expires_at>? "
            )
            cursor = str(owner["scan_cursor"] or "")
            rows = list(db.execute(
                common + "AND (w.decision_id IS NULL OR "
                "w.result_ack_state='PENDING') AND w.event_id>? "
                "ORDER BY w.event_id LIMIT ?", (now, cursor, limit),
            ).fetchall())
            remaining = limit - len(rows)
            if remaining:
                rows.extend(db.execute(
                    common + "AND (w.decision_id IS NULL OR "
                    "w.result_ack_state='PENDING') AND w.event_id<=? "
                    "ORDER BY w.event_id LIMIT ?", (now, cursor, remaining),
                ).fetchall())
            return [PollCandidate(
                str(row["event_id"]), str(row["session_id"]),
                int(row["manager_epoch"]), str(row["instance_id"]),
                str(row["delivery_id"]), str(row["work_id"]), str(row["token"]),
                None if row["result_hash"] is None else str(row["result_hash"]),
                str(row["result_ack_state"]) == "PENDING",
            ) for row in rows]
        finally:
            db.close()

    def _advance_cursor(self, *, event_id: str, now: float) -> bool:
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE orchestration_manager_recovery_leases SET scan_cursor=? "
                "WHERE lease_name='manager-decision-poller' AND owner_id=? "
                "AND token=? AND expires_at>?",
                (event_id, self.owner_id, self.lease_token, now),
            ).rowcount
            return changed == 1

    def _renew_live_recovery_leases(self, *, now: float) -> None:
        """Renew only near-expiry leases that have relevant receipt work."""
        if not self.service.manager_wake_receipt_v2_enabled:
            return
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT l.session_id,l.epoch,l.token FROM "
                "orchestration_durable_leases l JOIN orchestration_sessions s "
                "ON s.session_id=l.session_id JOIN works k ON k.work_id=s.work_id "
                "WHERE s.state IN ('ACTIVE','PARTIAL') AND k.state='ACTIVE' "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND k.assignment_epoch=s.work_assignment_epoch "
                "AND l.epoch=s.manager_epoch AND l.manager_node_id=s.manager_node_id "
                "AND l.expires_at>? AND l.expires_at<=? AND EXISTS ("
                "SELECT 1 FROM orchestration_manager_wakes w "
                "WHERE w.session_id=l.session_id AND w.manager_epoch=l.epoch "
                "AND w.envelope_schema=2 AND w.receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.state IN ('DELIVERING','DELIVERED','UNKNOWN') "
                "AND (w.decision_id IS NULL OR w.result_ack_state='PENDING'))",
                (now, now + 20.0),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE orchestration_durable_leases SET expires_at=?,updated_at=? "
                    "WHERE session_id=? AND epoch=? AND token=? AND expires_at>?",
                    (now + 60.0, now, row["session_id"], row["epoch"],
                     row["token"], now),
                )

    def _ack(self, candidate: PollCandidate) -> str:
        assert candidate.result_hash is not None
        self.service.assert_manager_wake_receipt_v2_session(candidate.session_id)
        response = self.client.request(
            instance_id=candidate.instance_id,
            request_id="mgr.ack." + hashlib.sha256(
                candidate.event_id.encode("utf-8")
            ).hexdigest()[:32],
            command="result-ack", text=candidate.delivery_id, timeout_s=10.0,
        )
        if (response.get("ok") is not True
                or response.get("relayId") != candidate.delivery_id
                or response.get("resultHash") != candidate.result_hash
                or response.get("ackState") != "ACKED"):
            raise ConflictError("MANAGER_RESULT_ACK_RESPONSE_INVALID")
        self.consumer.mark_result_acknowledged(
            event_id=candidate.event_id, result_hash=candidate.result_hash,
        )
        return "ACKED"

    def handle_receipt(
        self, *, event_id: str, receipt: dict[str, Any], now: float | None = None,
    ) -> dict[str, Any]:
        """Shared entry point for polling and a future trusted event trigger."""
        now = time.time() if now is None else max(now, time.time())
        db = self.store._connect()
        try:
            row = db.execute(
                "SELECT w.session_id,w.manager_epoch,s.work_id,l.token,l.expires_at "
                "FROM orchestration_manager_wakes w "
                "JOIN orchestration_sessions s ON s.session_id=w.session_id "
                "JOIN orchestration_durable_leases l ON l.session_id=w.session_id "
                "WHERE w.event_id=? AND s.manager_epoch=w.manager_epoch "
                "AND l.epoch=w.manager_epoch AND l.manager_node_id=s.manager_node_id",
                (event_id,),
            ).fetchone()
        finally:
            db.close()
        if row is None or float(row["expires_at"]) <= now:
            raise ConflictError("MANAGER_RESULT_TRIGGER_NOT_CURRENT")
        self.service.assert_manager_wake_receipt_v2_session(
            str(row["session_id"])
        )
        result = self.consumer.consume_receipt(
            work=self.store.get_work(str(row["work_id"])), event_id=event_id,
            manager_epoch=int(row["manager_epoch"]), lease_token=str(row["token"]),
            receipt=receipt, now=now,
            recovery_fence=(self.owner_id, self.lease_token),
        )
        if int(result.get("deliveries", 0)) > 0 and self.on_deliveries is not None:
            # The consumer has returned only after its SQLite transaction
            # committed. A lost signal is harmless because bounded polling
            # reads the same durable outbox.
            self.on_deliveries()
        return result

    def run_once(self, *, limit: int = 8, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        summary: dict[str, Any] = {
            "checked": 0, "committed": 0, "acked": 0,
            "deferred": 0, "rejected": 0, "lease_owned": False,
        }
        phase_now = max(now, time.time())
        if not self._acquire_recovery_lease(now=phase_now):
            return summary
        summary["lease_owned"] = True
        self._renew_live_recovery_leases(now=phase_now)
        for candidate in self._candidates(limit=limit, now=phase_now):
            phase_now = max(now, time.time())
            if not self._acquire_recovery_lease(now=phase_now):
                summary["lease_owned"] = False
                break
            if not self._advance_cursor(
                event_id=candidate.event_id, now=phase_now,
            ):
                summary["lease_owned"] = False
                break
            summary["checked"] += 1
            try:
                if candidate.ack_only:
                    self._ack(candidate)
                    summary["acked"] += 1
                    continue
                self.service.assert_manager_wake_receipt_v2_session(
                    candidate.session_id
                )
                response = self.client.request(
                    instance_id=candidate.instance_id,
                    request_id="mgr.poll." + hashlib.sha256(
                        candidate.event_id.encode("utf-8")
                    ).hexdigest()[:32],
                    command="result", text=candidate.delivery_id, timeout_s=10.0,
                )
                receipt = response.get("result")
                if (response.get("ok") is not True
                        or response.get("relayId") != candidate.delivery_id
                        or response.get("found") is not True
                        or response.get("completed") is not True
                        or not isinstance(receipt, dict)):
                    summary["deferred"] += 1
                    continue
                committed = self.handle_receipt(
                    event_id=candidate.event_id, receipt=receipt,
                    now=max(now, time.time()),
                )
                summary["committed"] += 1
                self._ack(PollCandidate(
                    **{**candidate.__dict__, "result_hash": committed["result_hash"],
                       "ack_only": True}
                ))
                summary["acked"] += 1
            except (RelayUnavailable, RelayEffectUnknown):
                summary["deferred"] += 1
            except (ConflictError, PreconditionError, ValueError, KeyError):
                summary["rejected"] += 1
        return summary
