"""Event-first, bounded recovery for PR-B Worker dispatch outboxes.

The SQLite outbox is authoritative.  An in-process event only reduces latency;
the same fenced ``run_once`` path performs periodic crash recovery.  A delivery
that reached the pipe write boundary is never sent again: only its exact RCC
receipt may advance the durable state.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from .core.durable_pr2 import acknowledge_delivery, record_attempt, reserve_delivery
from .core.models import ConflictError, PreconditionError
from .core.node_routing import (
    NodeAffinity, NodeReadiness, RoutingAction, RoutingCandidate,
    RoutingPolicy, decide_route,
)
from .core.orchestration import OrchestrationService, _canonical
from .core.rcc_result import rcc_result_hash
from .features.orchestration import OrchestrationFeature
from .integrations.rcc import RelayClient, RelayEffectUnknown, RelayUnavailable


@dataclass(frozen=True)
class DispatchCandidate:
    delivery_id: str
    session_id: str
    manager_epoch: int
    state: str
    work_id: str
    lease_token: str
    target_node_id: str
    attachment_id: str
    attachment_generation: int
    assignment_id: str
    assignment_generation: int
    instance_id: str
    result_hash: str | None
    routing: dict[str, Any] | None
    routing_state: str | None
    routing_started_at: float | None


@dataclass(frozen=True)
class ManagerWakeCandidate:
    event_id: str
    session_id: str
    manager_epoch: int
    work_id: str
    lease_token: str


class WorkerDispatchRecovery:
    """One fenced dispatcher; duplicate events and pollers converge here."""

    def __init__(self, service: OrchestrationService, client: RelayClient):
        self.service = service
        self.store = service.store
        self.client = client
        self.feature = OrchestrationFeature(service, client)
        self.owner_id = "worker.dispatch." + secrets.token_hex(16)
        self.lease_token = secrets.token_hex(32)
        self._signal = threading.Event()

    def notify(self) -> None:
        self._signal.set()

    def wait(self, timeout: float) -> bool:
        signalled = self._signal.wait(timeout)
        self._signal.clear()
        return signalled

    @staticmethod
    def _scan_cursors(value: Any) -> dict[str, str]:
        raw = str(value or "")
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return {
                        "outbox": str(parsed.get("outbox") or ""),
                        "wake": str(parsed.get("wake") or ""),
                    }
            except json.JSONDecodeError:
                pass
        # Compatibility with the short-lived PR-C plain outbox cursor.
        return {"outbox": raw, "wake": ""}

    def _acquire(self, now: float) -> bool:
        if not self.service.manager_wake_receipt_v2_enabled:
            return False
        expires = now + 30.0
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='worker-dispatcher'"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO orchestration_manager_recovery_leases "
                    "(lease_name,owner_id,token,expires_at,updated_at,scan_cursor) "
                    "VALUES('worker-dispatcher',?,?,?,?, '')",
                    (self.owner_id, self.lease_token, expires, now),
                )
                owned = True
            elif (str(row["owner_id"]), str(row["token"])) == (
                self.owner_id, self.lease_token,
            ) and float(row["expires_at"]) > now:
                owned = db.execute(
                    "UPDATE orchestration_manager_recovery_leases SET "
                    "expires_at=?,updated_at=? WHERE lease_name='worker-dispatcher' "
                    "AND owner_id=? AND token=? AND expires_at>?",
                    (expires, now, self.owner_id, self.lease_token, now),
                ).rowcount == 1
            elif float(row["expires_at"]) <= now:
                owned = db.execute(
                    "UPDATE orchestration_manager_recovery_leases SET owner_id=?,"
                    "token=?,expires_at=?,updated_at=? WHERE lease_name='worker-dispatcher' "
                    "AND owner_id=? AND token=? AND expires_at<=?",
                    (self.owner_id, self.lease_token, expires, now,
                     str(row["owner_id"]), str(row["token"]), now),
                ).rowcount == 1
            else:
                return False
            if not owned:
                return False
            # A restarted Core may inherit an expired Manager lease after the
            # Manager decision itself was already consumed. The dispatcher
            # singleton now fences the old process and rotates only exact
            # current sessions that still own incomplete PR-B outboxes.
            expired = db.execute(
                "SELECT DISTINCT l.session_id,l.manager_node_id,l.epoch,l.token "
                "FROM orchestration_durable_leases l JOIN orchestration_sessions s "
                "ON s.session_id=l.session_id JOIN works w ON w.work_id=s.work_id "
                "WHERE s.state IN ('ACTIVE','PARTIAL') AND w.state='ACTIVE' "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.assignment_epoch=s.work_assignment_epoch "
                "AND l.epoch=s.manager_epoch AND l.manager_node_id=s.manager_node_id "
                "AND l.expires_at<=? AND (EXISTS (SELECT 1 FROM "
                "orchestration_dispatch_outbox o WHERE o.session_id=l.session_id "
                "AND o.manager_epoch=l.epoch AND o.completed_at IS NULL AND o.state IN "
                "('PENDING','RESERVED','DISPATCHING','DELIVERED','UNKNOWN','ACKNOWLEDGED')) "
                "OR EXISTS (SELECT 1 FROM orchestration_manager_wakes mw "
                "WHERE mw.session_id=l.session_id AND mw.manager_epoch=l.epoch "
                "AND mw.envelope_schema=2 AND mw.receipt_mode='RCC_RESULT_POLL_V1' "
                "AND mw.state='PENDING'))",
                (now,),
            ).fetchall()
            for lease in expired:
                replacement = secrets.token_hex(32)
                changed = db.execute(
                    "UPDATE orchestration_durable_leases SET token=?,expires_at=?,"
                    "updated_at=? WHERE session_id=? AND manager_node_id=? AND epoch=? "
                    "AND token=? AND expires_at<=?",
                    (replacement, now + 60.0, now, lease["session_id"],
                     lease["manager_node_id"], lease["epoch"], lease["token"], now),
                ).rowcount
                if changed != 1:
                    raise ConflictError("WORKER_MANAGER_LEASE_ROTATION_RACE")
            db.execute(
                "UPDATE orchestration_durable_leases SET expires_at=?,updated_at=? "
                "WHERE expires_at>? AND expires_at<=? AND EXISTS (SELECT 1 FROM "
                "orchestration_sessions s JOIN works w ON w.work_id=s.work_id "
                "WHERE s.session_id=orchestration_durable_leases.session_id "
                "AND s.state IN ('ACTIVE','PARTIAL') AND w.state='ACTIVE' "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.assignment_epoch=s.work_assignment_epoch "
                "AND s.manager_epoch=orchestration_durable_leases.epoch "
                "AND s.manager_node_id=orchestration_durable_leases.manager_node_id) "
                "AND (EXISTS (SELECT 1 FROM "
                "orchestration_dispatch_outbox o WHERE o.session_id="
                "orchestration_durable_leases.session_id AND o.manager_epoch="
                "orchestration_durable_leases.epoch AND o.completed_at IS NULL AND "
                "o.state IN ('PENDING','RESERVED','DISPATCHING','DELIVERED','UNKNOWN',"
                "'ACKNOWLEDGED')) OR EXISTS (SELECT 1 FROM "
                "orchestration_manager_wakes mw WHERE mw.session_id="
                "orchestration_durable_leases.session_id AND mw.manager_epoch="
                "orchestration_durable_leases.epoch AND mw.envelope_schema=2 AND "
                "mw.receipt_mode='RCC_RESULT_POLL_V1' AND mw.state='PENDING'))",
                (now + 60.0, now, now, now + 20.0),
            )
            return True

    def _assert_fence(self, db, now: float) -> None:
        row = db.execute(
            "SELECT owner_id,token,expires_at FROM orchestration_manager_recovery_leases "
            "WHERE lease_name='worker-dispatcher'"
        ).fetchone()
        if (row is None or str(row["owner_id"]) != self.owner_id
                or str(row["token"]) != self.lease_token
                or float(row["expires_at"]) <= now):
            raise ConflictError("WORKER_DISPATCHER_FENCED")

    @staticmethod
    def _assert_authority(db, candidate: DispatchCandidate) -> list[str]:
        row = db.execute(
            "SELECT s.manager_epoch,s.state,s.work_assignment_epoch,w.assignment_epoch,"
            "w.state AS work_state,a.current_generation,t.worker_node_id,"
            "t.attachment_id,t.attachment_generation,t.manager_epoch AS attempt_epoch,"
            "x.active AS attachment_active,x.node_id,x.generation,x.relay_role,"
            "sn.active AS node_active,a.actions_json FROM orchestration_sessions s "
            "JOIN works w ON w.work_id=s.work_id JOIN orchestration_assignments a "
            "ON a.session_id=s.session_id JOIN orchestration_assignment_attempts t "
            "ON t.assignment_id=a.assignment_id AND t.generation=a.current_generation "
            "JOIN orchestration_attachments x ON x.attachment_id=t.attachment_id "
            "AND x.generation=t.attachment_generation JOIN orchestration_session_nodes sn "
            "ON sn.session_id=s.session_id AND sn.node_id=t.worker_node_id "
            "WHERE s.session_id=? AND a.assignment_id=?",
            (candidate.session_id, candidate.assignment_id),
        ).fetchone()
        if row is None or any((
            int(row["manager_epoch"]) != candidate.manager_epoch,
            str(row["state"]) not in {"ACTIVE", "PARTIAL"},
            int(row["work_assignment_epoch"]) != int(row["assignment_epoch"]),
            str(row["work_state"]) != "ACTIVE",
            int(row["current_generation"]) != candidate.assignment_generation,
            str(row["worker_node_id"]) != candidate.target_node_id,
            str(row["attachment_id"]) != candidate.attachment_id,
            int(row["attachment_generation"]) != candidate.attachment_generation,
            int(row["attempt_epoch"]) != candidate.manager_epoch,
            not bool(row["attachment_active"]), not bool(row["node_active"]),
            str(row["node_id"]) != candidate.target_node_id,
            int(row["generation"]) != candidate.attachment_generation,
            not str(row["relay_role"] or ""),
        )):
            raise ConflictError("WORKER_DISPATCH_AUTHORITY_FENCED")
        actions = json.loads(str(row["actions_json"]))
        if not isinstance(actions, list) or not all(isinstance(x, str) for x in actions):
            raise ConflictError("WORKER_DISPATCH_ACTIONS_INVALID")
        return actions

    def _candidates(self, limit: int, now: float) -> list[DispatchCandidate]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
            raise ValueError("WORKER_DISPATCH_LIMIT_INVALID")
        if not self.service.manager_wake_receipt_v2_enabled:
            return []
        db = self.store._connect()
        try:
            owner = db.execute(
                "SELECT scan_cursor FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='worker-dispatcher' AND owner_id=? AND token=? "
                "AND expires_at>?", (self.owner_id, self.lease_token, now),
            ).fetchone()
            if owner is None:
                return []
            common = (
                "SELECT o.*,s.work_id,l.token,a.instance_id,r.routing_json,r.state AS routing_state,"
                "r.created_at AS routing_started_at FROM "
                "orchestration_dispatch_outbox o JOIN orchestration_sessions s "
                "ON s.session_id=o.session_id JOIN works w ON w.work_id=s.work_id "
                "JOIN orchestration_durable_leases l ON l.session_id=o.session_id "
                "JOIN orchestration_attachments a ON a.attachment_id=o.attachment_id "
                "AND a.generation=o.attachment_generation LEFT JOIN orchestration_dispatch_routes r "
                "ON r.delivery_id=o.delivery_id WHERE o.state IN "
                "('PENDING','RESERVED','DISPATCHING','DELIVERED','UNKNOWN','ACKNOWLEDGED') "
                "AND o.completed_at IS NULL AND s.state IN ('ACTIVE','PARTIAL') "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.state='ACTIVE' AND w.assignment_epoch=s.work_assignment_epoch "
                "AND s.manager_epoch=o.manager_epoch AND l.epoch=o.manager_epoch "
                "AND l.manager_node_id=s.manager_node_id AND l.expires_at>? "
            )
            cursor = self._scan_cursors(owner["scan_cursor"])["outbox"]
            rows = list(db.execute(
                common + "AND o.delivery_id>? ORDER BY o.delivery_id LIMIT ?",
                (now, cursor, limit),
            ).fetchall())
            if len(rows) < limit:
                rows += list(db.execute(
                    common + "AND o.delivery_id<=? ORDER BY o.delivery_id LIMIT ?",
                    (now, cursor, limit - len(rows)),
                ).fetchall())
            return [DispatchCandidate(
                str(r["delivery_id"]), str(r["session_id"]), int(r["manager_epoch"]),
                str(r["state"]), str(r["work_id"]), str(r["token"]),
                str(r["target_node_id"]), str(r["attachment_id"]),
                int(r["attachment_generation"]), str(r["assignment_id"]),
                int(r["assignment_generation"]), str(r["instance_id"]),
                None if r["ack_digest"] is None else str(r["ack_digest"]),
                (json.loads(str(r["routing_json"])) if r["routing_json"] is not None else None),
                None if r["routing_state"] is None else str(r["routing_state"]),
                None if r["routing_started_at"] is None else float(r["routing_started_at"]),
            ) for r in rows]
        finally:
            db.close()

    def _advance(self, delivery_id: str, now: float) -> bool:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT scan_cursor FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='worker-dispatcher' AND owner_id=? AND token=? "
                "AND expires_at>?",
                (self.owner_id, self.lease_token, now),
            ).fetchone()
            if row is None:
                return False
            cursors = self._scan_cursors(row["scan_cursor"])
            cursors["outbox"] = delivery_id
            return db.execute(
                "UPDATE orchestration_manager_recovery_leases SET scan_cursor=? "
                "WHERE lease_name='worker-dispatcher' AND owner_id=? AND token=? "
                "AND expires_at>?",
                (_canonical(cursors), self.owner_id, self.lease_token, now),
            ).rowcount == 1

    def _manager_wake_candidates(
        self, limit: int, now: float,
    ) -> list[ManagerWakeCandidate]:
        """Return a bounded, fair batch of persisted schema-2 wake work."""
        if not self.service.manager_wake_receipt_v2_enabled:
            return []
        db = self.store._connect()
        try:
            owner = db.execute(
                "SELECT scan_cursor FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='worker-dispatcher' AND owner_id=? AND token=? "
                "AND expires_at>?", (self.owner_id, self.lease_token, now),
            ).fetchone()
            if owner is None:
                return []
            common = (
                "SELECT w.event_id,w.session_id,w.manager_epoch,s.work_id,l.token "
                "FROM orchestration_manager_wakes w JOIN orchestration_sessions s "
                "ON s.session_id=w.session_id JOIN works k ON k.work_id=s.work_id "
                "JOIN orchestration_durable_leases l ON l.session_id=w.session_id "
                "WHERE w.envelope_schema=2 AND w.receipt_mode='RCC_RESULT_POLL_V1' "
                "AND s.wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "AND w.state='PENDING' AND s.state IN ('ACTIVE','PARTIAL') "
                "AND k.state='ACTIVE' AND k.assignment_epoch=s.work_assignment_epoch "
                "AND s.manager_epoch=w.manager_epoch AND l.epoch=w.manager_epoch "
                "AND l.manager_node_id=s.manager_node_id AND l.expires_at>? "
            )
            cursor = self._scan_cursors(owner["scan_cursor"])["wake"]
            rows = list(db.execute(
                common + "AND w.event_id>? ORDER BY w.event_id LIMIT ?",
                (now, cursor, limit),
            ).fetchall())
            if len(rows) < limit:
                rows += list(db.execute(
                    common + "AND w.event_id<=? ORDER BY w.event_id LIMIT ?",
                    (now, cursor, limit - len(rows)),
                ).fetchall())
            return [ManagerWakeCandidate(
                str(row["event_id"]), str(row["session_id"]),
                int(row["manager_epoch"]), str(row["work_id"]), str(row["token"]),
            ) for row in rows]
        finally:
            db.close()

    def _advance_manager_wake(self, event_id: str, now: float) -> bool:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT scan_cursor FROM orchestration_manager_recovery_leases "
                "WHERE lease_name='worker-dispatcher' AND owner_id=? AND token=? "
                "AND expires_at>?",
                (self.owner_id, self.lease_token, now),
            ).fetchone()
            if row is None:
                return False
            cursors = self._scan_cursors(row["scan_cursor"])
            cursors["wake"] = event_id
            return db.execute(
                "UPDATE orchestration_manager_recovery_leases SET scan_cursor=? "
                "WHERE lease_name='worker-dispatcher' AND owner_id=? AND token=? "
                "AND expires_at>?",
                (_canonical(cursors), self.owner_id, self.lease_token, now),
            ).rowcount == 1

    def _deliver_manager_wake(self, candidate: ManagerWakeCandidate) -> str:
        work = self.store.get_work(candidate.work_id)
        self.service.assert_manager_wake_receipt_v2_session(candidate.session_id)
        self.service.assert_current_unattended_orchestration_policy(work)
        result = self.feature._wake_manager(
            work=work,
            session_id=candidate.session_id,
            manager_epoch=candidate.manager_epoch,
            event_id=candidate.event_id,
            manager_lease_token=candidate.lease_token,
            recovery_fence=(self.owner_id, self.lease_token),
            claim_at_write=True,
            before_write_fence=lambda: (
                self.service.assert_manager_wake_receipt_v2_session(
                    candidate.session_id
                ),
                self.service.assert_current_unattended_orchestration_policy(
                    self.store.get_work(candidate.work_id)
                ),
            ),
        )
        return "DELIVERED" if result["delivered"] else "DEFERRED"

    def _context(
        self, candidate: DispatchCandidate, *, check_unattended_policy: bool = True,
    ) -> tuple[Any, dict[str, Any], dict[str, Any], str, str]:
        work = self.store.get_work(candidate.work_id)
        self.service.assert_manager_wake_receipt_v2_session(candidate.session_id)
        assignment = self.service.assignment(
            work=work, session_id=candidate.session_id,
            assignment_id=candidate.assignment_id,
        )
        if int(assignment["current_generation"]) != candidate.assignment_generation:
            raise ConflictError("WORKER_DISPATCH_ASSIGNMENT_FENCED")
        attempt = assignment["attempts"][-1]
        if (str(attempt["worker_node_id"]) != candidate.target_node_id
                or str(attempt["attachment_id"]) != candidate.attachment_id
                or int(attempt["attachment_generation"]) != candidate.attachment_generation):
            raise ConflictError("WORKER_DISPATCH_TARGET_FENCED")
        if check_unattended_policy:
            self.service.assert_current_unattended_policy(list(assignment["actions"]))
            self.service.assert_current_unattended_orchestration_policy(work)
        attachment = self.service.attachment(
            work=work, session_id=candidate.session_id,
            attachment_id=candidate.attachment_id,
            generation=candidate.attachment_generation,
        )
        if not attachment["active"] or attachment["node_id"] != candidate.target_node_id:
            raise ConflictError("WORKER_DISPATCH_ATTACHMENT_FENCED")
        result_nonce = hashlib.sha256(_canonical([
            candidate.assignment_id, candidate.assignment_generation,
            assignment["request_digest"],
        ]).encode("utf-8")).hexdigest()[:32]
        prompt = self.feature._result_envelope(
            session_id=candidate.session_id, assignment_id=candidate.assignment_id,
            generation=candidate.assignment_generation,
            manager_epoch=candidate.manager_epoch,
            request_digest=assignment["request_digest"], result_nonce=result_nonce,
            instruction=str(assignment["request"]["instruction"]),
            acceptance=assignment["acceptance"], roots=assignment["roots"],
            actions=assignment["actions"], dependencies=assignment["dependencies"],
        )
        return work, assignment, attachment, result_nonce, prompt

    def _before_write(self, candidate: DispatchCandidate, reservation: str) -> None:
        now = time.time()
        with self.store.transaction() as db:
            self.service.assert_manager_wake_receipt_v2_session(
                candidate.session_id, _db=db,
            )
            self._assert_fence(db, now)
            actions = self._assert_authority(db, candidate)
            # Policy is intentionally re-read at the last local boundary.  The
            # DB fence is rechecked before bytes are written; Policy has no
            # duplicated cached authority in the dispatcher.
            self.service.assert_current_unattended_policy(actions)
            self.service.assert_current_unattended_orchestration_policy(
                self.store.get_work(candidate.work_id)
            )
            record_attempt(
                self.store, delivery_id=candidate.delivery_id,
                epoch=candidate.manager_epoch, token=candidate.lease_token,
                reservation_token=reservation, phase="SEND_STARTED", now=now, _db=db,
            )

    def _set_route_state(
        self, candidate: DispatchCandidate, state: str, detail: dict[str, Any],
    ) -> None:
        """Persist scheduler evidence without changing the delivery receipt."""
        if candidate.routing is None:
            return
        now = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, now)
            changed = db.execute(
                "UPDATE orchestration_dispatch_routes SET state=?,detail_json=?,updated_at=? "
                "WHERE delivery_id=?",
                (state, _canonical(detail), now, candidate.delivery_id),
            ).rowcount
            if changed != 1:
                raise ConflictError("WORKER_DISPATCH_ROUTE_FENCED")

    @staticmethod
    def _endpoint_readiness(attachment: dict[str, Any], state: dict[str, Any]) -> NodeReadiness:
        """Accept only an exact, current endpoint as an idle observation."""
        if (state.get("instanceId") != attachment["instance_id"]
                or state.get("sessionId") != attachment["external_session_id"]):
            return NodeReadiness.DISCONNECTED
        for endpoint in state.get("endpoints", []):
            if not isinstance(endpoint, dict):
                continue
            if (endpoint.get("tabId") == attachment["tab_id"]
                    and endpoint.get("conversationKey") == attachment["conversation_key"]
                    and endpoint.get("presence") == "OPEN"):
                return (NodeReadiness.GENERATING if endpoint.get("generating") is True
                        else NodeReadiness.IDLE)
        return NodeReadiness.ORPHANED

    def _readiness(self, attachment: dict[str, Any]) -> NodeReadiness:
        try:
            response = self.client.request(
                instance_id=str(attachment["instance_id"]),
                request_id="worker.route." + hashlib.sha256(
                    (str(attachment["attachment_id"]) + ":" + str(time.time_ns())).encode("utf-8")
                ).hexdigest()[:32],
                command="state", timeout_s=5.0,
            )
        except (RelayUnavailable, RelayEffectUnknown):
            return NodeReadiness.DISCONNECTED
        state = response.get("state") if isinstance(response.get("state"), dict) else None
        if response.get("ok") is not True or state is None:
            return NodeReadiness.DISCONNECTED
        return self._endpoint_readiness(attachment, state)

    def _route_pending(self, candidate: DispatchCandidate) -> str:
        """Schedule only before reserve_delivery can cross the write boundary."""
        if candidate.routing is None:
            # Pre-routing receipts retain their historical dispatch behavior.
            return "DISPATCH"
        if candidate.routing_state in {"PROVISION_REQUIRED", "ESCALATED"}:
            return "DEFERRED"
        routing = candidate.routing
        try:
            policy = RoutingPolicy(
                affinity=NodeAffinity(str(routing["affinity"])),
                short_wait_s=self.service.worker_reroute_wait_seconds,
                required_wait_s=self.service.required_node_hold_seconds,
                allow_provision=bool(routing["allow_provision"]),
            )
            raw_fallbacks = routing["fallbacks"]
            if not isinstance(raw_fallbacks, list):
                raise ValueError("ROUTING_FALLBACKS_INVALID")
        except (KeyError, TypeError, ValueError) as exc:
            raise PreconditionError("WORKER_DISPATCH_ROUTING_INVALID") from exc
        work, assignment, attachment, _nonce, _prompt = self._context(
            candidate, check_unattended_policy=False,
        )
        preferred = RoutingCandidate(
            node_id=candidate.target_node_id, attachment_id=candidate.attachment_id,
            readiness=self._readiness(attachment),
        )
        fallbacks: list[RoutingCandidate] = []
        for raw in raw_fallbacks:
            if not isinstance(raw, dict):
                raise PreconditionError("WORKER_DISPATCH_ROUTING_INVALID")
            node_id, attachment_id, attachment_generation = (
                raw.get("node_id"), raw.get("attachment_id"), raw.get("attachment_generation"),
            )
            if (not isinstance(node_id, str) or not isinstance(attachment_id, str)
                    or type(attachment_generation) is not int or attachment_generation < 1):
                raise PreconditionError("WORKER_DISPATCH_ROUTING_INVALID")
            fallback = self.service.attachment(
                work=work, session_id=candidate.session_id,
                attachment_id=attachment_id, generation=attachment_generation,
            )
            if fallback["node_id"] != node_id or not fallback["active"]:
                continue
            fallbacks.append(RoutingCandidate(
                node_id=node_id, attachment_id=attachment_id,
                readiness=self._readiness(fallback),
            ))
        elapsed = max(0.0, time.time() - float(candidate.routing_started_at or time.time()))
        decision = decide_route(
            policy=policy, preferred=preferred, fallbacks=fallbacks, elapsed_s=elapsed,
        )
        detail = {
            "reason": decision.reason, "elapsed_s": round(elapsed, 3),
            "preferred": preferred.readiness.value,
            "fallbacks": [{"node_id": item.node_id, "readiness": item.readiness.value}
                          for item in fallbacks],
        }
        if decision.action is RoutingAction.DISPATCH_PREFERRED:
            self._set_route_state(candidate, "PENDING", detail)
            return "DISPATCH"
        if decision.action is RoutingAction.REROUTE_TO_STANDBY:
            assert decision.candidate is not None
            self.service.reroute_undispatched_delivery(
                work=work, session_id=candidate.session_id,
                assignment_id=candidate.assignment_id,
                manager_epoch=candidate.manager_epoch, delivery_id=candidate.delivery_id,
                worker_node_id=decision.candidate.node_id,
                attachment_id=decision.candidate.attachment_id,
                attachment_generation=next(
                    int(item["attachment_generation"]) for item in raw_fallbacks
                    if item["node_id"] == decision.candidate.node_id
                    and item["attachment_id"] == decision.candidate.attachment_id
                ),
                reason=decision.reason, evidence=detail,
            )
            return "REROUTED"
        if decision.action is RoutingAction.PROVISION_NODE:
            self._set_route_state(candidate, "PROVISION_REQUIRED", detail)
            return "DEFERRED"
        if decision.action is RoutingAction.ESCALATE_REQUIRED:
            self._set_route_state(candidate, "ESCALATED", detail)
            return "DEFERRED"
        self._set_route_state(candidate, "WAITING", detail)
        return "DEFERRED"

    def _confirmed_not_applied(
        self, candidate: DispatchCandidate, reservation: str, error: str,
    ) -> None:
        now = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, now)
            self._assert_authority(db, candidate)
            record_attempt(
                self.store, delivery_id=candidate.delivery_id,
                epoch=candidate.manager_epoch, token=candidate.lease_token,
                reservation_token=reservation, phase="CONFIRMED_NOT_APPLIED",
                now=now, _db=db,
            )
            self.service.complete_assignment(
                assignment_id=candidate.assignment_id,
                generation=candidate.assignment_generation,
                outcome="NOT_APPLIED",
                result={"delivery_id": candidate.delivery_id, "error": error,
                        "pre_dispatch": True},
                result_message_id="result." + hashlib.sha256(
                    (candidate.delivery_id + ":not-applied").encode("utf-8")
                ).hexdigest()[:32], _db=db,
            )

    def _reserve_and_send(self, candidate: DispatchCandidate) -> str:
        work, assignment, attachment, result_nonce, prompt = self._context(candidate)
        message_id = "msg." + hashlib.sha256(
            _canonical([candidate.session_id, candidate.assignment_id,
                        candidate.assignment_generation, "dispatch"]).encode("utf-8")
        ).hexdigest()[:32]
        now = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, now)
            actions = self._assert_authority(db, candidate)
            self.service.assert_current_unattended_policy(actions)
            self.service.assert_current_unattended_orchestration_policy(work)
            reserved = reserve_delivery(
                self.store, delivery_id=candidate.delivery_id,
                epoch=candidate.manager_epoch, token=candidate.lease_token,
                now=now, _db=db,
            )
            self.service.reserve_dispatch(
                work=work, session_id=candidate.session_id,
                assignment_id=candidate.assignment_id,
                manager_epoch=candidate.manager_epoch, message_id=message_id,
                dispatch_operation_id=candidate.delivery_id,
                payload={"request_digest": assignment["request_digest"],
                         "result_nonce": result_nonce,
                         "attachment_id": attachment["attachment_id"],
                         "attachment_generation": attachment["generation"]},
                _db=db,
            )
        reservation = str(reserved["reservation_token"])
        try:
            response = self.client.request(
                instance_id=attachment["instance_id"],
                request_id=candidate.delivery_id, command="send",
                to=attachment["relay_role"], text=prompt,
                extra={
                    "fromNode": "BCT_MANAGER",
                    "messageHash": assignment["request_digest"],
                    "bindingReceiptId": attachment["binding_receipt_id"],
                    "expectedInstanceId": attachment["instance_id"],
                    "expectedSessionId": attachment["external_session_id"],
                    "expectedTabId": attachment["tab_id"],
                    "expectedConversationKey": attachment["conversation_key"],
                    "attachmentGeneration": attachment["generation"],
                    "returnOnAck": True,
                }, timeout_s=30.0,
                before_write=lambda: self._before_write(candidate, reservation),
            )
        except RelayUnavailable as exc:
            self._confirmed_not_applied(candidate, reservation, str(exc))
            return "NOT_APPLIED"
        except RelayEffectUnknown:
            self._record_post_send(candidate, reservation, "UNKNOWN")
            return "UNKNOWN"
        if (response.get("type") == "host:ack" and response.get("ok") is True
                and response.get("submitted") is True):
            self._record_post_send(candidate, reservation, "DELIVERED")
            return "DELIVERED"
        effect = str(response.get("effectState") or "").upper()
        if response.get("ok") is False and effect == "NOT_APPLIED":
            self._confirmed_not_applied(
                candidate, reservation,
                str(response.get("error") or "RCC_SUBMIT_NOT_APPLIED"),
            )
            return "NOT_APPLIED"
        self._record_post_send(candidate, reservation, "UNKNOWN")
        return "UNKNOWN"

    def _record_post_send(
        self, candidate: DispatchCandidate, reservation: str, phase: str,
    ) -> None:
        now = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, now)
            record_attempt(
                self.store, delivery_id=candidate.delivery_id,
                epoch=candidate.manager_epoch, token=candidate.lease_token,
                reservation_token=reservation, phase=phase, now=now, _db=db,
            )

    @staticmethod
    def _exact_receipt(
        candidate: DispatchCandidate, assignment: dict[str, Any],
        attachment: dict[str, Any], prompt: str, receipt: dict[str, Any],
    ) -> str:
        expected_fingerprint = _canonical([
            attachment["relay_role"], prompt, False, "",
            attachment["binding_receipt_id"], assignment["request_digest"],
            attachment["instance_id"], attachment["external_session_id"],
            attachment["tab_id"], attachment["conversation_key"],
            attachment["generation"],
        ])
        supplied_hash = str(receipt.get("resultHash") or "")
        if not (
            str(receipt.get("id") or "") == candidate.delivery_id
            and str(receipt.get("fingerprint") or "") == expected_fingerprint
            and receipt.get("ok") is True and receipt.get("ambiguous") is False
            and str(receipt.get("resultState") or "") == "RESULT_PERSISTED"
            and str(receipt.get("from") or "") == attachment["relay_role"]
            and str(receipt.get("messageHash") or "") == assignment["request_digest"]
            and str(receipt.get("targetBindingReceipt") or "")
                == str(attachment["binding_receipt_id"])
            and str(receipt.get("instanceId") or "") == attachment["instance_id"]
            and str(receipt.get("sessionId") or "") == attachment["external_session_id"]
            and isinstance(receipt.get("tabId"), int)
            and not isinstance(receipt.get("tabId"), bool)
            and receipt["tabId"] == attachment["tab_id"]
            and str(receipt.get("conversationKey") or "")
                == attachment["conversation_key"]
            and isinstance(receipt.get("attachmentGeneration"), int)
            and not isinstance(receipt.get("attachmentGeneration"), bool)
            and receipt["attachmentGeneration"] == attachment["generation"]
            and supplied_hash == rcc_result_hash(receipt)
        ):
            raise ConflictError("WORKER_RCC_RECEIPT_MISMATCH")
        return supplied_hash

    def _lookup_result(self, candidate: DispatchCandidate) -> str:
        work, assignment, attachment, result_nonce, prompt = self._context(
            candidate, check_unattended_policy=False,
        )
        self.service.assert_manager_wake_receipt_v2_session(candidate.session_id)
        response = self.client.request(
            instance_id=candidate.instance_id,
            request_id="worker.poll." + hashlib.sha256(
                candidate.delivery_id.encode("utf-8")
            ).hexdigest()[:32],
            command="result", text=candidate.delivery_id, timeout_s=10.0,
        )
        if not (response.get("found") is True and response.get("completed") is True
                and response.get("pending") is False and response.get("ok") is True
                and response.get("relayId") == candidate.delivery_id
                and isinstance(response.get("result"), dict)):
            return "DEFERRED"
        receipt = response["result"]
        result_hash = self._exact_receipt(
            candidate, assignment, attachment, prompt, receipt,
        )
        parsed = self.feature._parse_result(
            str(receipt.get("reply") or ""), session_id=candidate.session_id,
            assignment_id=candidate.assignment_id,
            generation=candidate.assignment_generation,
            request_digest=assignment["request_digest"], result_nonce=result_nonce,
        )
        outcome = "APPLIED" if parsed["status"] == "SUCCEEDED" else "FAILED"
        now = time.time()
        with self.store.transaction() as db:
            self.service.assert_manager_wake_receipt_v2_session(
                candidate.session_id, _db=db,
            )
            self._assert_fence(db, now)
            self._assert_authority(db, candidate)
            row = db.execute(
                "SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=?",
                (candidate.delivery_id,),
            ).fetchone()
            if row is None:
                raise KeyError("DELIVERY_NOT_FOUND")
            if row["state"] == "DISPATCHING":
                record_attempt(
                    self.store, delivery_id=candidate.delivery_id,
                    epoch=candidate.manager_epoch, token=candidate.lease_token,
                    reservation_token=str(row["reservation_token"]),
                    phase="DELIVERED", now=now, _db=db,
                )
            self.service.complete_assignment(
                assignment_id=candidate.assignment_id,
                generation=candidate.assignment_generation, outcome=outcome,
                result={
                    "delivery_id": candidate.delivery_id,
                    "result_digest": hashlib.sha256(
                        _canonical(parsed).encode("utf-8")
                    ).hexdigest(),
                    "envelope": parsed, "rcc_result_hash": result_hash,
                },
                result_message_id="result." + hashlib.sha256(
                    (candidate.delivery_id + ":terminal").encode("utf-8")
                ).hexdigest()[:32], _db=db,
            )
            acknowledge_delivery(
                self.store, delivery_id=candidate.delivery_id,
                target_node_id=candidate.target_node_id,
                attachment_id=candidate.attachment_id,
                attachment_generation=candidate.attachment_generation,
                ack_digest=result_hash, epoch=candidate.manager_epoch,
                token=candidate.lease_token, now=now, _db=db,
            )
        self.notify()
        return self._ack_result(candidate, result_hash)

    def _ack_result(self, candidate: DispatchCandidate, result_hash: str) -> str:
        self.service.assert_manager_wake_receipt_v2_session(candidate.session_id)
        before_ack = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, before_ack)
        response = self.client.request(
            instance_id=candidate.instance_id,
            request_id="worker.ack." + hashlib.sha256(
                candidate.delivery_id.encode("utf-8")
            ).hexdigest()[:32],
            command="result-ack", text=candidate.delivery_id, timeout_s=10.0,
        )
        if (response.get("ok") is not True
                or response.get("relayId") != candidate.delivery_id
                or response.get("resultHash") != result_hash
                or response.get("ackState") != "ACKED"):
            raise ConflictError("WORKER_RESULT_ACK_RESPONSE_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, now)
            row = db.execute(
                "SELECT state,ack_digest,completed_at FROM "
                "orchestration_dispatch_outbox WHERE delivery_id=?",
                (candidate.delivery_id,),
            ).fetchone()
            if row is None or row["state"] != "ACKNOWLEDGED" \
                    or row["ack_digest"] != result_hash:
                raise ConflictError("WORKER_RESULT_ACK_BINDING_MISMATCH")
            if row["completed_at"] is None:
                db.execute(
                    "UPDATE orchestration_dispatch_outbox SET completed_at=? "
                    "WHERE delivery_id=? AND completed_at IS NULL",
                    (now, candidate.delivery_id),
                )
        return "ACKED"

    def _recover_reserved(self, candidate: DispatchCandidate) -> None:
        now = time.time()
        with self.store.transaction() as db:
            self._assert_fence(db, now)
            token = db.execute(
                "SELECT reservation_token FROM orchestration_dispatch_outbox "
                "WHERE delivery_id=? AND state='RESERVED'",
                (candidate.delivery_id,),
            ).fetchone()
            if token is not None:
                record_attempt(
                    self.store, delivery_id=candidate.delivery_id,
                    epoch=candidate.manager_epoch, token=candidate.lease_token,
                    reservation_token=str(token["reservation_token"]),
                    phase="PRE_SEND_ABORT", now=now, _db=db,
                )

    def run_once(self, *, limit: int = 8, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else max(now, time.time())
        summary = {"lease_owned": False, "checked": 0, "sent": 0,
                   "committed": 0, "acked": 0, "deferred": 0,
                   "not_applied": 0, "rerouted": 0, "manager_wakes": 0, "rejected": 0}
        if not self._acquire(now):
            return summary
        summary["lease_owned"] = True
        for candidate in self._candidates(limit, now):
            phase_now = max(now, time.time())
            if not self._acquire(phase_now) or not self._advance(
                candidate.delivery_id, phase_now,
            ):
                summary["lease_owned"] = False
                break
            summary["checked"] += 1
            try:
                if candidate.state == "RESERVED":
                    self._recover_reserved(candidate)
                    summary["deferred"] += 1
                elif candidate.state == "PENDING":
                    route = self._route_pending(candidate)
                    if route == "DEFERRED":
                        summary["deferred"] += 1
                    elif route == "REROUTED":
                        summary["rerouted"] += 1
                    else:
                        outcome = self._reserve_and_send(candidate)
                        if outcome == "NOT_APPLIED":
                            summary["not_applied"] += 1
                        else:
                            summary["sent"] += 1
                elif candidate.state == "ACKNOWLEDGED":
                    self._ack_result(candidate, str(candidate.result_hash))
                    summary["acked"] += 1
                else:
                    outcome = self._lookup_result(candidate)
                    if outcome == "ACKED":
                        summary["committed"] += 1
                        summary["acked"] += 1
                    else:
                        summary["deferred"] += 1
            except (RelayUnavailable, RelayEffectUnknown):
                summary["deferred"] += 1
            except (ConflictError, PreconditionError, KeyError, ValueError,
                    json.JSONDecodeError):
                summary["rejected"] += 1
        # Worker result commit persists a Manager wake before setting the
        # in-process hint.  This bounded phase is therefore both the immediate
        # event target and the crash/restart recovery path.  UNKNOWN wakes are
        # excluded so no ambiguous external effect is ever resent.
        for candidate in self._manager_wake_candidates(limit, max(now, time.time())):
            phase_now = max(now, time.time())
            if not self._acquire(phase_now) or not self._advance_manager_wake(
                candidate.event_id, phase_now,
            ):
                summary["lease_owned"] = False
                break
            try:
                outcome = self._deliver_manager_wake(candidate)
                if outcome == "DELIVERED":
                    summary["manager_wakes"] += 1
                else:
                    summary["deferred"] += 1
            except (RelayUnavailable, RelayEffectUnknown):
                summary["deferred"] += 1
            except (ConflictError, PreconditionError, KeyError, ValueError):
                summary["rejected"] += 1
        return summary
