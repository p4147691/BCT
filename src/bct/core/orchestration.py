from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .models import ConflictError, Outcome, PreconditionError, Work
from .store import Store


_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_ROLE = re.compile(r"^[A-Z0-9_-]{1,24}$")
_TERMINAL = frozenset({
    "APPLIED", "NOT_APPLIED", "FAILED", "UNKNOWN", "CANCELLED", "SKIPPED"
})
_NODE_EVIDENCE_ACTIONS = frozenset({"read"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _load(value: str) -> Any:
    return json.loads(value)


def _bounded_text(value: object, *, code: str, limit: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > limit:
        raise PreconditionError(code)
    return result


def _identifier(value: object, code: str) -> str:
    result = str(value or "").strip()
    if not _ID.fullmatch(result):
        raise PreconditionError(code)
    return result


def _within(root: str, candidate: str) -> bool:
    root_path = Path(root).resolve()
    candidate_path = Path(candidate).resolve()
    try:
        candidate_path.relative_to(root_path)
        return True
    except ValueError:
        return candidate_path == root_path


class OrchestrationService:
    """Durable manager/worker metadata with independent failover fencing."""

    def __init__(
        self, store: Store, *, manager_wake_receipt_v2_enabled: bool = False,
    ):
        self.store = store
        self.manager_wake_receipt_v2_enabled = manager_wake_receipt_v2_enabled

    @staticmethod
    def _assert_outer_operation_running(db, *, work: Work,
                                        request: dict[str, Any]) -> None:
        outer_id = str(request.get("_outer_operation_id") or "").strip()
        if not outer_id:
            # Direct service-level callers used by bounded unit helpers have no
            # outer operation. Public feature-created assignments always do.
            return
        _identifier(outer_id, "ORCHESTRATION_OUTER_OPERATION_ID_INVALID")
        row = db.execute(
            "SELECT state FROM operations WHERE operation_id=? AND work_id=? "
            "AND capability='orchestrate'",
            (outer_id, work.work_id),
        ).fetchone()
        if row is None or row["state"] != "RUNNING":
            raise ConflictError("ORCHESTRATION_OUTER_OPERATION_NOT_RUNNING")

    def _session_row(self, db, session_id: str):
        row = db.execute(
            "SELECT * FROM orchestration_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError("ORCHESTRATION_SESSION_NOT_FOUND")
        return row

    @staticmethod
    def _session_value(row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "work_id": row["work_id"],
            "work_assignment_epoch": row["work_assignment_epoch"],
            "objective": row["objective"],
            "roots": _load(row["roots_json"]),
            "actions": _load(row["actions_json"]),
            "acceptance": _load(row["acceptance_json"]),
            "plan_revision": row["plan_revision"],
            "manager_node_id": row["manager_node_id"],
            "manager_epoch": row["manager_epoch"],
            "state": row["state"],
            "terminal_summary": _load(row["terminal_summary_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _assert_work(row, work: Work) -> None:
        if row["work_id"] != work.work_id:
            raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
        if row["work_assignment_epoch"] != work.assignment_epoch:
            raise ConflictError("ORCHESTRATION_WORK_ASSIGNMENT_CHANGED")
        if row["state"] not in {"ACTIVE", "PARTIAL"}:
            raise PreconditionError("ORCHESTRATION_SESSION_NOT_ACTIVE")

    @staticmethod
    def _assert_current_work_assignment(db, work: Work) -> None:
        current = db.execute(
            "SELECT owner_principal_id,assignment_epoch,state FROM works "
            "WHERE work_id=?", (work.work_id,),
        ).fetchone()
        if current is None or (
            str(current["owner_principal_id"]) != work.owner_principal_id
            or int(current["assignment_epoch"]) != int(work.assignment_epoch)
        ):
            raise ConflictError("ORCHESTRATION_WORK_ASSIGNMENT_CHANGED")
        if current["state"] != "ACTIVE" or work.state != "ACTIVE":
            raise PreconditionError("ORCHESTRATION_WORK_NOT_ACTIVE")

    def start_session(
        self, *, work: Work, session_id: str, objective: str,
        acceptance: dict[str, Any], roots: list[str] | None = None,
        actions: list[str] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        session_id = _identifier(session_id, "ORCHESTRATION_SESSION_ID_INVALID")
        objective = _bounded_text(
            objective, code="ORCHESTRATION_OBJECTIVE_INVALID", limit=4000
        )
        if not isinstance(acceptance, dict) or len(_canonical(acceptance)) > 12000:
            raise PreconditionError("ORCHESTRATION_ACCEPTANCE_INVALID")
        delegated_roots = [str(Path(item).resolve()) for item in (roots or list(work.roots))]
        delegated_actions = sorted(set(actions or work.actions))
        if not delegated_roots or any(
            not any(_within(parent, child) for parent in work.roots)
            for child in delegated_roots
        ):
            raise PreconditionError("ORCHESTRATION_ROOT_OUTSIDE_WORK")
        if not set(delegated_actions).issubset(work.actions):
            raise PreconditionError("ORCHESTRATION_ACTION_OUTSIDE_WORK")
        expected = {
            "work_id": work.work_id,
            "work_assignment_epoch": work.assignment_epoch,
            "objective": objective,
            "roots": delegated_roots,
            "actions": delegated_actions,
            "acceptance": acceptance,
        }
        now = time.time()
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT * FROM orchestration_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if current is not None:
                value = self._session_value(current)
                comparable = {
                    key: value[key]
                    for key in (
                        "work_id", "work_assignment_epoch", "objective",
                        "roots", "actions", "acceptance",
                    )
                }
                if comparable != expected:
                    raise ConflictError("ORCHESTRATION_SESSION_REQUEST_MISMATCH")
                return False, value
            db.execute(
                "INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id, work.work_id, work.assignment_epoch, objective,
                    _canonical(delegated_roots), _canonical(delegated_actions),
                    _canonical(acceptance), 1, None, 0, "ACTIVE", "{}", now, now,
                ),
            )
            self.store._event(db, "ORCHESTRATION_SESSION_STARTED", session_id, {
                "work_id": work.work_id, "work_assignment_epoch": work.assignment_epoch,
            })
            row = self._session_row(db, session_id)
            return True, self._session_value(row)

    def validate_sync_targets(
        self, *, work: Work, session_id: str, instance_id: str,
        targets: list[dict[str, str]],
    ) -> None:
        """Reject conversation ownership conflicts before any RCC mutation."""
        instance_id = _bounded_text(
            instance_id, code="ORCHESTRATION_INSTANCE_ID_INVALID", limit=64
        )
        normalized: list[tuple[str, str]] = []
        for target in targets:
            normalized.append((
                _bounded_text(
                    target.get("conversation_key"),
                    code="ORCHESTRATION_CONVERSATION_INVALID", limit=96,
                ),
                _identifier(
                    target.get("node_id"), "ORCHESTRATION_NODE_ID_INVALID"
                ),
            ))
        db = self.store._connect()
        try:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            for conversation_key, node_id in normalized:
                other = db.execute(
                    "SELECT node_id FROM orchestration_attachments "
                    "WHERE instance_id=? AND conversation_key=? AND active=1",
                    (instance_id, conversation_key),
                ).fetchone()
                if other is not None and other["node_id"] != node_id:
                    raise ConflictError(
                        "ORCHESTRATION_CONVERSATION_ALREADY_ATTACHED"
                    )
        finally:
            db.close()

    @staticmethod
    def _node_sync_expected_bindings(db, *, instance_id: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT attachment_id,generation,node_id,tab_id,conversation_key,"
            "relay_role,binding_receipt_id FROM orchestration_attachments "
            "WHERE instance_id=? AND active=1 AND relay_role IS NOT NULL "
            "AND relay_role!='' AND binding_receipt_id IS NOT NULL "
            "AND binding_receipt_id!='' ORDER BY relay_role",
            (instance_id,),
        ).fetchall()
        if not rows:
            raise ConflictError("ORCHESTRATION_NODE_SYNC_BINDINGS_MISSING")
        return [dict(row) for row in rows]

    def _validate_node_sync_recovery(
        self, db, *, work: Work, session_id: str,
        original_operation_id: str, instance_id: str,
    ) -> list[dict[str, Any]]:
        session = self._session_row(db, session_id)
        self._assert_work(session, work)
        original = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND work_id=? "
            "AND capability='orchestrate'",
            (original_operation_id, work.work_id),
        ).fetchone()
        if original is None or not (
            original["target"] == session_id
            and original["state"] == "FINISHED"
            and original["outcome"] == "UNKNOWN"
            and original["error"] == "ORCHESTRATION_CONVERSATION_ALREADY_ATTACHED"
        ):
            raise ConflictError("ORCHESTRATION_NODE_SYNC_ORIGINAL_INVALID")
        claims = [row[0] for row in db.execute(
            "SELECT resource_key FROM resource_claims WHERE operation_id=? "
            "AND unresolved=1 ORDER BY resource_key",
            (original_operation_id,),
        ).fetchall()]
        if claims != ["rcc-instance:" + instance_id]:
            raise ConflictError("ORCHESTRATION_NODE_SYNC_CLAIM_MISMATCH")
        if db.execute(
            "SELECT 1 FROM orchestration_assignments WHERE session_id=? LIMIT 1",
            (session_id,),
        ).fetchone() is not None or db.execute(
            "SELECT 1 FROM orchestration_mailbox WHERE session_id=? LIMIT 1",
            (session_id,),
        ).fetchone() is not None:
            raise ConflictError("ORCHESTRATION_NODE_SYNC_EXTERNAL_EFFECT_NOT_EXCLUDED")
        return self._node_sync_expected_bindings(db, instance_id=instance_id)

    def node_sync_recovery_plan(
        self, *, work: Work, session_id: str,
        original_operation_id: str, instance_id: str,
    ) -> dict[str, Any]:
        db = self.store._connect()
        try:
            expected = self._validate_node_sync_recovery(
                db, work=work, session_id=session_id,
                original_operation_id=original_operation_id,
                instance_id=instance_id,
            )
            return {
                "instance_id": instance_id,
                "bindings": expected,
                "bindings_digest": _digest(expected),
            }
        finally:
            db.close()

    def finish_node_sync_recovery(
        self, *, work: Work, session_id: str,
        original_operation_id: str, resolver_operation_id: str,
        instance_id: str, bindings_digest: str,
        external_session_id: str, verified_bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self.store.transaction() as db:
            expected = self._validate_node_sync_recovery(
                db, work=work, session_id=session_id,
                original_operation_id=original_operation_id,
                instance_id=instance_id,
            )
            if _digest(expected) != bindings_digest:
                raise ConflictError("ORCHESTRATION_NODE_SYNC_BINDINGS_CHANGED")
            expected_verified = [{
                "relay_role": row["relay_role"],
                "tab_id": row["tab_id"],
                "conversation_key": row["conversation_key"],
                "binding_receipt_id": row["binding_receipt_id"],
                "external_session_id": external_session_id,
            } for row in expected]
            normalized_verified = sorted(
                verified_bindings, key=lambda item: str(item.get("relay_role") or "")
            )
            if normalized_verified != expected_verified:
                raise ConflictError("ORCHESTRATION_NODE_SYNC_RESTORE_UNVERIFIED")
            evidence = {
                "operation": "recover-node-sync",
                "session_id": session_id,
                "original_operation_id": original_operation_id,
                "instance_id": instance_id,
                "external_session_id": external_session_id,
                "bindings_digest": bindings_digest,
                "restored_roles": [row["relay_role"] for row in expected],
                "message_effect_excluded": True,
                "binding_effect_reconciled": True,
            }
            self.store.finish_orchestration_recovery_in_transaction(
                db, resolver_operation_id=resolver_operation_id,
                original_operation_id=original_operation_id,
                resolver_outcome=Outcome.APPLIED,
                original_outcome=Outcome.FAILED,
                evidence=evidence, release_original=True,
                expected_original_error="ORCHESTRATION_CONVERSATION_ALREADY_ATTACHED",
            )
            return evidence

    def sync_attachment(
        self, *, work: Work, session_id: str, node_id: str, name: str,
        role: str, attachment_id: str, instance_id: str,
        external_session_id: str, tab_id: int, window_id: int,
        conversation_key: str, endpoint: str, relay_role: str,
        binding_receipt_id: str, observed_at: float | None = None,
    ) -> dict[str, Any]:
        node_id = _identifier(node_id, "ORCHESTRATION_NODE_ID_INVALID")
        attachment_id = _identifier(
            attachment_id, "ORCHESTRATION_ATTACHMENT_ID_INVALID"
        )
        name = _bounded_text(name, code="ORCHESTRATION_NODE_NAME_INVALID", limit=120)
        role = _bounded_text(role, code="ORCHESTRATION_NODE_ROLE_INVALID", limit=32)
        relay_role = str(relay_role or "").strip().upper()
        if relay_role and not _ROLE.fullmatch(relay_role):
            raise PreconditionError("ORCHESTRATION_RELAY_ROLE_INVALID")
        if not isinstance(tab_id, int) or tab_id <= 0:
            raise PreconditionError("ORCHESTRATION_TAB_ID_INVALID")
        if not isinstance(window_id, int) or window_id <= 0:
            raise PreconditionError("ORCHESTRATION_WINDOW_ID_INVALID")
        conversation_key = _bounded_text(
            conversation_key, code="ORCHESTRATION_CONVERSATION_INVALID", limit=96
        )
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            other = db.execute(
                "SELECT node_id FROM orchestration_attachments "
                "WHERE instance_id=? AND conversation_key=? AND active=1",
                (instance_id, conversation_key),
            ).fetchone()
            if other is not None and other["node_id"] != node_id:
                raise ConflictError("ORCHESTRATION_CONVERSATION_ALREADY_ATTACHED")
            node = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if node is None:
                db.execute(
                    "INSERT INTO nodes(node_id,name,role,group_name,revision,active) "
                    "VALUES(?,?,?,?,1,1)",
                    (node_id, name, role, "ORCHESTRATION"),
                )
            else:
                db.execute(
                    "UPDATE nodes SET name=?,role=?,group_name=?,active=1,revision=revision+1 "
                    "WHERE node_id=?",
                    (name, role, "ORCHESTRATION", node_id),
                )
            db.execute(
                "INSERT INTO orchestration_session_nodes VALUES(?,?,?,1) "
                "ON CONFLICT(session_id,node_id) DO UPDATE SET "
                "session_role=excluded.session_role,active=1",
                (session_id, node_id, role),
            )
            prior = db.execute(
                "SELECT * FROM orchestration_attachments WHERE attachment_id=? "
                "ORDER BY generation DESC LIMIT 1",
                (attachment_id,),
            ).fetchone()
            fingerprint = (
                instance_id, external_session_id, tab_id, window_id,
                conversation_key, endpoint, relay_role, binding_receipt_id,
            )
            if prior is not None:
                prior_fingerprint = (
                    prior["instance_id"], prior["external_session_id"],
                    prior["tab_id"], prior["window_id"], prior["conversation_key"],
                    prior["endpoint"], prior["relay_role"],
                    prior["binding_receipt_id"],
                )
                if prior_fingerprint == fingerprint and prior["active"]:
                    return dict(prior)
                generation = prior["generation"] + 1
                db.execute(
                    "UPDATE orchestration_attachments SET active=0 "
                    "WHERE attachment_id=? AND active=1", (attachment_id,)
                )
            else:
                generation = 1
            stale = db.execute(
                "SELECT attachment_id FROM orchestration_attachments "
                "WHERE active=1 AND instance_id=? AND (tab_id=? OR "
                "(?!='' AND relay_role=?)) AND NOT (attachment_id=? AND generation=?)",
                (
                    instance_id, tab_id, relay_role, relay_role,
                    attachment_id, generation,
                ),
            ).fetchall()
            for item in stale:
                db.execute(
                    "UPDATE orchestration_attachments SET active=0 "
                    "WHERE attachment_id=? AND active=1",
                    (item["attachment_id"],),
                )
                db.execute(
                    "UPDATE connections SET active=0 WHERE connection_id=?",
                    ("orch:" + item["attachment_id"],),
                )
            db.execute(
                "INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attachment_id, generation, node_id, "rcc", instance_id,
                    external_session_id, tab_id, window_id, conversation_key,
                    endpoint, relay_role or None, binding_receipt_id or None, 1,
                    float(observed_at or now),
                ),
            )
            connection_id = "orch:" + attachment_id
            connection = db.execute(
                "SELECT * FROM connections WHERE connection_id=?", (connection_id,)
            ).fetchone()
            instance = _canonical({
                "instance_id": instance_id, "session_id": external_session_id,
                "tab_id": tab_id, "window_id": window_id,
            })
            if connection is None:
                db.execute(
                    "INSERT INTO connections VALUES(?,?,?,?,?,?,1)",
                    (connection_id, node_id, "rcc", instance, conversation_key, generation),
                )
            else:
                db.execute(
                    "UPDATE connections SET node_id=?,kind='rcc',instance=?,endpoint=?,"
                    "generation=?,active=1 WHERE connection_id=?",
                    (node_id, instance, conversation_key, generation, connection_id),
                )
            self.store._event(db, "ORCHESTRATION_ATTACHMENT_SYNCED", attachment_id, {
                "node_id": node_id, "generation": generation,
                "conversation_key": conversation_key,
            })
            row = db.execute(
                "SELECT * FROM orchestration_attachments "
                "WHERE attachment_id=? AND generation=?",
                (attachment_id, generation),
            ).fetchone()
            return dict(row)

    def reconcile_observed_attachments(
        self, *, work: Work, session_id: str, instance_id: str,
        active_attachment_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Deactivate session attachments omitted from one complete RCC observation.

        ``sync_attachment`` records each selected endpoint independently.  The caller
        must invoke this method once after every selected endpoint from the same RCC
        state response has been stored.  Keeping this as a separate finalization
        transaction prevents a partial observation from deactivating endpoints that
        have not been processed yet.
        """
        instance_id = _bounded_text(
            instance_id, code="ORCHESTRATION_INSTANCE_ID_INVALID", limit=64
        )
        selected = sorted(set(
            _identifier(item, "ORCHESTRATION_ATTACHMENT_ID_INVALID")
            for item in active_attachment_ids
        ))
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            rows = db.execute(
                "SELECT a.* FROM orchestration_attachments a "
                "WHERE a.instance_id=? AND a.active=1 AND EXISTS ("
                "SELECT 1 FROM orchestration_session_nodes sn "
                "WHERE sn.session_id=? AND sn.node_id=a.node_id AND sn.active=1)",
                (instance_id, session_id),
            ).fetchall()
            stale = [row for row in rows if row["attachment_id"] not in selected]
            for row in stale:
                db.execute(
                    "UPDATE orchestration_attachments SET active=0 "
                    "WHERE attachment_id=? AND generation=? AND active=1",
                    (row["attachment_id"], row["generation"]),
                )
                db.execute(
                    "UPDATE connections SET active=0 "
                    "WHERE connection_id=? AND generation=? AND active=1",
                    ("orch:" + row["attachment_id"], row["generation"]),
                )
                self.store._event(
                    db, "ORCHESTRATION_ATTACHMENT_INACTIVE", row["attachment_id"],
                    {
                        "session_id": session_id,
                        "instance_id": instance_id,
                        "generation": row["generation"],
                        "reason": "OMITTED_FROM_COMPLETE_OBSERVATION",
                    },
                )
            return [dict(row) for row in stale]

    def takeover_manager(
        self, *, work: Work, session_id: str, expected_epoch: int,
        manager_node_id: str, reason: str, evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manager_node_id = _identifier(
            manager_node_id, "ORCHESTRATION_MANAGER_NODE_INVALID"
        )
        reason = _bounded_text(
            reason, code="ORCHESTRATION_TAKEOVER_REASON_INVALID", limit=500
        )
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            if session["manager_epoch"] != expected_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            node = db.execute(
                "SELECT active FROM nodes WHERE node_id=?", (manager_node_id,)
            ).fetchone()
            if node is None or not node["active"]:
                raise ConflictError("ORCHESTRATION_MANAGER_NODE_NOT_ACTIVE")
            attachment = db.execute(
                "SELECT 1 FROM orchestration_attachments a "
                "WHERE a.node_id=? AND a.active=1 AND EXISTS ("
                "SELECT 1 FROM orchestration_session_nodes sn "
                "WHERE sn.session_id=? AND sn.node_id=a.node_id AND sn.active=1)",
                (manager_node_id, session_id),
            ).fetchone()
            if attachment is None:
                raise ConflictError("ORCHESTRATION_MANAGER_ATTACHMENT_MISSING")
            next_epoch = expected_epoch + 1
            db.execute(
                "UPDATE orchestration_manager_epochs SET ended_at=? "
                "WHERE session_id=? AND ended_at IS NULL",
                (now, session_id),
            )
            db.execute(
                "INSERT INTO orchestration_manager_epochs VALUES(?,?,?,?,?,?,NULL)",
                (
                    session_id, next_epoch, manager_node_id, reason,
                    _canonical(evidence or {}), now,
                ),
            )
            changed = db.execute(
                "UPDATE orchestration_sessions SET manager_node_id=?,manager_epoch=?,"
                "plan_revision=plan_revision+1,updated_at=? "
                "WHERE session_id=? AND manager_epoch=?",
                (manager_node_id, next_epoch, now, session_id, expected_epoch),
            ).rowcount
            if changed != 1:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            # A pending notification belongs to the old manager attachment and
            # must never be redirected.  Once takeover has atomically proved
            # the replacement manager, preserve the old record as STALE and
            # create a separately fenced event for the same immutable result.
            # DELIVERING/UNKNOWN remain untouched: their external effect is not
            # known and therefore cannot safely be re-notified automatically.
            pending_wakes = db.execute(
                "SELECT w.*,a.* FROM orchestration_manager_wakes w "
                "JOIN orchestration_assignments a ON a.assignment_id=w.assignment_id "
                "WHERE w.session_id=? AND w.manager_epoch=? AND w.state='PENDING' "
                "AND a.session_id=? AND a.state IN ('APPLIED','FAILED') "
                "ORDER BY w.created_at,w.event_id",
                (session_id, expected_epoch, session_id),
            ).fetchall()
            requeued_wakes = 0
            for wake in pending_wakes:
                db.execute(
                    "UPDATE orchestration_manager_wakes SET state='STALE',updated_at=? "
                    "WHERE event_id=? AND state='PENDING'", (now, wake["event_id"]),
                )
                self.store._event(db, "ORCHESTRATION_MANAGER_WAKE_STALE", wake["event_id"], {
                    "manager_epoch": expected_epoch,
                    "reason": "MANAGER_TAKEOVER",
                })
                self._record_manager_wake(
                    db, session_id=session_id, assignment=wake,
                    generation=int(wake["assignment_generation"]),
                    result_message_id=str(wake["result_message_id"]),
                    result_digest=str(wake["result_digest"]), now=now,
                )
                requeued_wakes += 1
            queued = db.execute(
                "SELECT a.assignment_id,a.current_generation FROM orchestration_assignments a "
                "JOIN orchestration_assignment_attempts t ON "
                "t.assignment_id=a.assignment_id AND t.generation=a.current_generation "
                "WHERE a.session_id=? AND a.state='QUEUED' AND t.state='QUEUED' "
                "AND t.dispatch_operation_id IS NULL",
                (session_id,),
            ).fetchall()
            for item in queued:
                db.execute(
                    "UPDATE orchestration_assignment_attempts SET manager_epoch=?,updated_at=? "
                    "WHERE assignment_id=? AND generation=? AND state='QUEUED' "
                    "AND dispatch_operation_id IS NULL",
                    (
                        next_epoch, now, item["assignment_id"],
                        item["current_generation"],
                    ),
                )
                decision_id = "adopt." + hashlib.sha256(
                    f"{item['assignment_id']}:{item['current_generation']}:{next_epoch}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:32]
                db.execute(
                    "INSERT INTO orchestration_reconciliations VALUES(?,?,?,?,?,?,?,?)",
                    (
                        decision_id, session_id, item["assignment_id"],
                        item["current_generation"], next_epoch,
                        "ADOPT_QUEUED_NOT_DISPATCHED",
                        _canonical({"prior_manager_epoch": expected_epoch}), now,
                    ),
                )
            self.store._event(db, "ORCHESTRATION_MANAGER_TAKEOVER", session_id, {
                "manager_node_id": manager_node_id, "manager_epoch": next_epoch,
                "prior_epoch": expected_epoch,
                "adopted_queued_assignments": len(queued),
                "requeued_manager_wakes": requeued_wakes,
            })
            return self._session_value(self._session_row(db, session_id))

    def _scope(self, session, roots: list[str], actions: list[str]) -> tuple[list[str], list[str]]:
        session_roots = _load(session["roots_json"])
        session_actions = set(_load(session["actions_json"]))
        normalized_roots = [str(Path(item).resolve()) for item in roots]
        normalized_actions = sorted(set(actions))
        if not normalized_roots or any(
            not any(_within(parent, child) for parent in session_roots)
            for child in normalized_roots
        ):
            raise PreconditionError("ORCHESTRATION_ASSIGNMENT_ROOT_OUTSIDE_SESSION")
        if not set(normalized_actions).issubset(session_actions):
            raise PreconditionError("ORCHESTRATION_ASSIGNMENT_ACTION_OUTSIDE_SESSION")
        if not set(normalized_actions).issubset(_NODE_EVIDENCE_ACTIONS):
            raise PreconditionError("ORCHESTRATION_NODE_SIDE_EFFECT_ACTION_FORBIDDEN")
        return normalized_roots, normalized_actions

    def create_assignment(
        self, *, work: Work, session_id: str, assignment_id: str,
        manager_epoch: int, worker_node_id: str, attachment_id: str,
        request: dict[str, Any], roots: list[str], actions: list[str],
        acceptance: dict[str, Any], dependencies: list[str], _db=None,
    ) -> tuple[bool, dict[str, Any]]:
        assignment_id = _identifier(
            assignment_id, "ORCHESTRATION_ASSIGNMENT_ID_INVALID"
        )
        worker_node_id = _identifier(
            worker_node_id, "ORCHESTRATION_WORKER_NODE_INVALID"
        )
        attachment_id = _identifier(
            attachment_id, "ORCHESTRATION_ATTACHMENT_ID_INVALID"
        )
        if not isinstance(request, dict) or len(_canonical(request)) > 16000:
            raise PreconditionError("ORCHESTRATION_ASSIGNMENT_REQUEST_INVALID")
        if not isinstance(acceptance, dict) or len(_canonical(acceptance)) > 8000:
            raise PreconditionError("ORCHESTRATION_ASSIGNMENT_ACCEPTANCE_INVALID")
        dependencies = sorted(set(
            _identifier(item, "ORCHESTRATION_DEPENDENCY_ID_INVALID")
            for item in dependencies
        ))
        if assignment_id in dependencies or len(dependencies) > 16:
            raise PreconditionError("ORCHESTRATION_DEPENDENCY_INVALID")
        public_request = {
            key: value for key, value in request.items()
            if key != "_outer_operation_id"
        }
        now = time.time()
        with (self.store.transaction() if _db is None else nullcontext(_db)) as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            self._assert_outer_operation_running(db, work=work, request=request)
            # Identity must be derived from the same canonical scope persisted
            # below.  Windows runner temp roots can use an 8.3 alias while
            # ``Work.roots`` contains the resolved long path; hashing the raw
            # spelling made an otherwise exact queued assignment look different.
            normalized_roots, normalized_actions = self._scope(
                session, roots, actions
            )
            digest_value = {
                "session_id": session_id, "request": public_request,
                "roots": normalized_roots, "actions": normalized_actions,
                "acceptance": acceptance, "dependencies": dependencies,
                "worker_node_id": worker_node_id,
                "attachment_id": attachment_id,
            }
            request_digest = _digest(digest_value)
            existing = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["session_id"] != session_id
                    or existing["request_digest"] != request_digest
                ):
                    raise ConflictError("ORCHESTRATION_ASSIGNMENT_REQUEST_MISMATCH")
                return False, self._assignment_value(db, existing)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            attachment = db.execute(
                "SELECT * FROM orchestration_attachments "
                "WHERE attachment_id=? AND node_id=? AND active=1 "
                "AND EXISTS (SELECT 1 FROM orchestration_session_nodes sn "
                "WHERE sn.session_id=? AND sn.node_id=orchestration_attachments.node_id "
                "AND sn.active=1) "
                "ORDER BY generation DESC LIMIT 1",
                (attachment_id, worker_node_id, session_id),
            ).fetchone()
            if attachment is None:
                raise ConflictError("ORCHESTRATION_WORKER_ATTACHMENT_MISMATCH")
            busy = db.execute(
                "SELECT a.assignment_id,a.state FROM orchestration_assignments a "
                "JOIN orchestration_assignment_attempts t ON "
                "t.assignment_id=a.assignment_id AND t.generation=a.current_generation "
                "JOIN orchestration_attachments x ON x.attachment_id=t.attachment_id "
                "AND x.generation=t.attachment_generation "
                "WHERE x.conversation_key=? "
                "AND a.state IN ('QUEUED','DISPATCHING','ACKNOWLEDGED',"
                "'DISPATCH_UNKNOWN','UNKNOWN') LIMIT 1",
                (attachment["conversation_key"],),
            ).fetchone()
            if busy is not None:
                raise ConflictError(
                    "ORCHESTRATION_CONVERSATION_QUARANTINED:"
                    + str(busy["state"])
                )
            for dependency in dependencies:
                row = db.execute(
                    "SELECT session_id FROM orchestration_assignments "
                    "WHERE assignment_id=?", (dependency,)
                ).fetchone()
                if row is None or row["session_id"] != session_id:
                    raise ConflictError("ORCHESTRATION_DEPENDENCY_NOT_FOUND")
            db.execute(
                "INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    assignment_id, session_id, manager_epoch, request_digest,
                    _canonical(request), _canonical(normalized_roots),
                    _canonical(normalized_actions), _canonical(acceptance),
                    "QUEUED", 1, "{}", now, now,
                ),
            )
            for dependency in dependencies:
                db.execute(
                    "INSERT INTO orchestration_dependencies VALUES(?,?)",
                    (assignment_id, dependency),
                )
            db.execute(
                "INSERT INTO orchestration_assignment_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    assignment_id, 1, manager_epoch, worker_node_id,
                    attachment_id, attachment["generation"], "QUEUED",
                    None, None, now, now,
                ),
            )
            self.store._event(db, "ORCHESTRATION_ASSIGNMENT_CREATED", assignment_id, {
                "session_id": session_id, "manager_epoch": manager_epoch,
                "worker_node_id": worker_node_id,
            })
            row = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            return True, self._assignment_value(db, row)

    @staticmethod
    def _assignment_value(db, row) -> dict[str, Any]:
        dependencies = [
            item[0] for item in db.execute(
                "SELECT depends_on_assignment_id FROM orchestration_dependencies "
                "WHERE assignment_id=? ORDER BY depends_on_assignment_id",
                (row["assignment_id"],),
            ).fetchall()
        ]
        attempts = [dict(item) for item in reversed(db.execute(
            "SELECT * FROM orchestration_assignment_attempts "
            "WHERE assignment_id=? ORDER BY generation DESC LIMIT 20",
            (row["assignment_id"],),
        ).fetchall())]
        return {
            "assignment_id": row["assignment_id"],
            "session_id": row["session_id"],
            "created_manager_epoch": row["created_manager_epoch"],
            "request_digest": row["request_digest"],
            "request": _load(row["request_json"]),
            "roots": _load(row["roots_json"]),
            "actions": _load(row["actions_json"]),
            "acceptance": _load(row["acceptance_json"]),
            "state": row["state"],
            "current_generation": row["current_generation"],
            "terminal_result": _load(row["terminal_result_json"]),
            "dependencies": dependencies,
            "attempts": attempts,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _dispatch_attachment_row(db, *, session_id: str, attempt):
        return db.execute(
            "SELECT a.* FROM orchestration_attachments a "
            "WHERE a.attachment_id=? AND a.generation=? AND a.node_id=? "
            "AND a.active=1 AND a.relay_role IS NOT NULL AND a.relay_role!='' "
            "AND EXISTS (SELECT 1 FROM orchestration_session_nodes sn "
            "WHERE sn.session_id=? AND sn.node_id=a.node_id AND sn.active=1) "
            "AND EXISTS (SELECT 1 FROM connections c "
            "WHERE c.connection_id=? AND c.node_id=a.node_id "
            "AND c.generation=a.generation AND c.active=1)",
            (
                attempt["attachment_id"], attempt["attachment_generation"],
                attempt["worker_node_id"], session_id,
                "orch:" + attempt["attachment_id"],
            ),
        ).fetchone()

    def _finish_pre_dispatch_not_applied(
        self, db, *, session_id: str, assignment, attempt, now: float,
    ):
        assignment_id = assignment["assignment_id"]
        generation = int(assignment["current_generation"])
        result = {
            "error": "ORCHESTRATION_ATTACHMENT_NOT_ROUTABLE",
            "pre_dispatch": True,
            "attachment_id": attempt["attachment_id"],
            "attachment_generation": attempt["attachment_generation"],
        }
        bounded = _canonical(result)
        result_message_id = "result." + hashlib.sha256(
            f"{assignment_id}:{generation}:attachment-not-routable".encode("utf-8")
        ).hexdigest()[:32]
        digest = _digest(result)
        attempt_changed = db.execute(
            "UPDATE orchestration_assignment_attempts "
            "SET state='NOT_APPLIED',updated_at=? "
            "WHERE assignment_id=? AND generation=? AND state='QUEUED' "
            "AND dispatch_operation_id IS NULL",
            (now, assignment_id, generation),
        ).rowcount
        assignment_changed = db.execute(
            "UPDATE orchestration_assignments SET state='NOT_APPLIED',"
            "terminal_result_json=?,updated_at=? "
            "WHERE assignment_id=? AND current_generation=? AND state='QUEUED'",
            (bounded, now, assignment_id, generation),
        ).rowcount
        if attempt_changed != 1 or assignment_changed != 1:
            raise ConflictError("ORCHESTRATION_PRE_DISPATCH_STATE_CHANGED")
        db.execute(
            "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                result_message_id, session_id, assignment_id, generation,
                "RESULT", attempt["worker_node_id"], None, digest, bounded,
                now, now, None,
            ),
        )
        self.store._event(
            db, "ORCHESTRATION_ASSIGNMENT_FINISHED", assignment_id,
            {
                "generation": generation,
                "outcome": "NOT_APPLIED",
                "result_message_id": result_message_id,
                "pre_dispatch": True,
            },
        )
        return db.execute(
            "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
            (assignment_id,),
        ).fetchone()

    def resolve_dispatch_attachment(
        self, *, work: Work, session_id: str, assignment_id: str,
        manager_epoch: int,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Resolve the exact current attachment or terminally fence pre-dispatch.

        No transport call may occur before this transaction succeeds.  If the exact
        immutable attachment generation is no longer routable, both the attempt and
        logical assignment become terminal ``NOT_APPLIED`` with evidence that permits
        a same-identity worker replacement.
        """
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments "
                "WHERE assignment_id=? AND session_id=?",
                (assignment_id, session_id),
            ).fetchone()
            if assignment is None:
                raise KeyError("ORCHESTRATION_ASSIGNMENT_NOT_FOUND")
            self._assert_outer_operation_running(
                db, work=work, request=_load(assignment["request_json"])
            )
            generation = int(assignment["current_generation"])
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, generation),
            ).fetchone()
            if attempt is None:
                raise ConflictError("ORCHESTRATION_ATTEMPT_MISSING")
            if attempt["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_ATTEMPT_MANAGER_STALE")
            if assignment["state"] == "NOT_APPLIED":
                result = _load(assignment["terminal_result_json"])
                if result.get("pre_dispatch") is True:
                    return None, self._assignment_value(db, assignment)
            if assignment["state"] != "QUEUED" or attempt["state"] != "QUEUED":
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_NOT_QUEUED")
            if attempt["dispatch_operation_id"] is not None:
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_ALREADY_DISPATCHED")
            attachment = self._dispatch_attachment_row(
                db, session_id=session_id, attempt=attempt
            )
            if attachment is not None:
                return dict(attachment), self._assignment_value(db, assignment)
            updated = self._finish_pre_dispatch_not_applied(
                db, session_id=session_id, assignment=assignment,
                attempt=attempt, now=now,
            )
            return None, self._assignment_value(db, updated)

    def adopt_pre_dispatch_assignment(
        self, *, work: Work, session_id: str, assignment_id: str,
        manager_epoch: int, outer_operation_id: str,
    ) -> dict[str, Any]:
        """Move only a proven-unsent assignment under the current resolver fence."""
        outer_operation_id = _identifier(
            outer_operation_id, "ORCHESTRATION_OUTER_OPERATION_ID_INVALID"
        )
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            operation = db.execute(
                "SELECT state FROM operations WHERE operation_id=? AND work_id=? "
                "AND capability='orchestrate'",
                (outer_operation_id, work.work_id),
            ).fetchone()
            if operation is None or operation["state"] != "RUNNING":
                raise ConflictError("ORCHESTRATION_OUTER_OPERATION_NOT_RUNNING")
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=? "
                "AND session_id=?", (assignment_id, session_id),
            ).fetchone()
            if assignment is None or assignment["state"] != "QUEUED":
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_NOT_QUEUED")
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, assignment["current_generation"]),
            ).fetchone()
            if attempt is None or attempt["dispatch_operation_id"] is not None \
                    or attempt["dispatch_message_id"] is not None:
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_ALREADY_DISPATCHED")
            request = _load(assignment["request_json"])
            request["_outer_operation_id"] = outer_operation_id
            db.execute(
                "UPDATE orchestration_assignments SET request_json=?,updated_at=? "
                "WHERE assignment_id=? AND state='QUEUED'",
                (_canonical(request), time.time(), assignment_id),
            )
            self.store._event(db, "ORCHESTRATION_ASSIGNMENT_ADOPTED", assignment_id, {
                "outer_operation_id": outer_operation_id,
                "manager_epoch": manager_epoch,
            })
            updated = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            return self._assignment_value(db, updated)

    def reserve_dispatch(
        self, *, work: Work, session_id: str, assignment_id: str,
        manager_epoch: int, message_id: str, dispatch_operation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        message_id = _identifier(message_id, "ORCHESTRATION_MESSAGE_ID_INVALID")
        dispatch_operation_id = _identifier(
            dispatch_operation_id, "ORCHESTRATION_DISPATCH_ID_INVALID"
        )
        payload_digest = _digest(payload)
        now = time.time()
        pre_dispatch_failed = False
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if assignment is None or assignment["session_id"] != session_id:
                raise KeyError("ORCHESTRATION_ASSIGNMENT_NOT_FOUND")
            self._assert_outer_operation_running(
                db, work=work, request=_load(assignment["request_json"])
            )
            prior_message = db.execute(
                "SELECT * FROM orchestration_mailbox WHERE message_id=?", (message_id,)
            ).fetchone()
            if prior_message is not None:
                if (
                    prior_message["message_digest"] != payload_digest
                    or prior_message["assignment_id"] != assignment_id
                ):
                    raise ConflictError("ORCHESTRATION_MESSAGE_REQUEST_MISMATCH")
                return self._assignment_value(db, assignment)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            if assignment["state"] in _TERMINAL:
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_TERMINAL")
            for dependency in db.execute(
                "SELECT depends_on_assignment_id FROM orchestration_dependencies "
                "WHERE assignment_id=?", (assignment_id,)
            ).fetchall():
                state = db.execute(
                    "SELECT state FROM orchestration_assignments WHERE assignment_id=?",
                    (dependency[0],),
                ).fetchone()
                if state is None or state["state"] != "APPLIED":
                    raise ConflictError("ORCHESTRATION_DEPENDENCY_NOT_APPLIED")
            generation = assignment["current_generation"]
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, generation),
            ).fetchone()
            if attempt is None:
                raise ConflictError("ORCHESTRATION_ATTEMPT_MISSING")
            if attempt["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_ATTEMPT_MANAGER_STALE")
            attachment = self._dispatch_attachment_row(
                db, session_id=session_id, attempt=attempt
            )
            if attachment is None:
                updated = self._finish_pre_dispatch_not_applied(
                    db, session_id=session_id, assignment=assignment,
                    attempt=attempt, now=now,
                )
                result = self._assignment_value(db, updated)
                pre_dispatch_failed = True
            elif attempt["dispatch_operation_id"] is not None:
                if (
                    attempt["dispatch_operation_id"] == dispatch_operation_id
                    and attempt["dispatch_message_id"] == message_id
                ):
                    return self._assignment_value(db, assignment)
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_ALREADY_DISPATCHED")
            else:
                db.execute(
                    "UPDATE orchestration_assignment_attempts "
                    "SET state='DISPATCHING',dispatch_message_id=?,dispatch_operation_id=?,updated_at=? "
                    "WHERE assignment_id=? AND generation=?",
                    (message_id, dispatch_operation_id, now, assignment_id, generation),
                )
                db.execute(
                    "UPDATE orchestration_assignments SET state='DISPATCHING',updated_at=? "
                    "WHERE assignment_id=?", (now, assignment_id)
                )
                db.execute(
                    "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        message_id, session_id, assignment_id, generation, "DISPATCH",
                        session["manager_node_id"], attempt["worker_node_id"],
                        payload_digest, _canonical(payload), now, None, None,
                    ),
                )
                self.store._event(db, "ORCHESTRATION_DISPATCH_RESERVED", assignment_id, {
                    "generation": generation, "message_id": message_id,
                    "dispatch_operation_id": dispatch_operation_id,
                })
                updated = db.execute(
                    "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                    (assignment_id,),
                ).fetchone()
                result = self._assignment_value(db, updated)
        if pre_dispatch_failed:
            # Raise only after the NOT_APPLIED receipt commits.  The feature's
            # existing precondition path then returns a NOT_APPLIED operation and
            # never reaches the external transport call.
            raise PreconditionError("ORCHESTRATION_ATTACHMENT_NOT_ROUTABLE")
        return result

    def record_delivery(
        self, *, assignment_id: str, generation: int, state: str,
        evidence: dict[str, Any],
    ) -> None:
        if state not in {"ACKNOWLEDGED", "UNKNOWN", "NOT_APPLIED"}:
            raise ValueError("ORCHESTRATION_DELIVERY_STATE_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, generation),
            ).fetchone()
            if attempt is None:
                raise KeyError("ORCHESTRATION_ATTEMPT_NOT_FOUND")
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if generation != assignment["current_generation"]:
                message_id = "delivery." + hashlib.sha256(
                    f"{assignment_id}:{generation}:{state}".encode("utf-8")
                ).hexdigest()[:32]
                payload = {"state": state, "evidence": evidence, "late": True}
                digest = _digest(payload)
                prior = db.execute(
                    "SELECT message_digest FROM orchestration_mailbox WHERE message_id=?",
                    (message_id,),
                ).fetchone()
                if prior is None:
                    db.execute(
                        "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            message_id, assignment["session_id"], assignment_id,
                            generation, "LATE_DELIVERY", attempt["worker_node_id"],
                            None, digest, _canonical(payload), now, now, None,
                        ),
                    )
                elif prior["message_digest"] != digest:
                    raise ConflictError("ORCHESTRATION_MESSAGE_REQUEST_MISMATCH")
                return
            if assignment["state"] in _TERMINAL:
                return
            projected_state = "DISPATCH_UNKNOWN" if state == "UNKNOWN" else state
            db.execute(
                "UPDATE orchestration_assignment_attempts SET state=?,updated_at=? "
                "WHERE assignment_id=? AND generation=?",
                (state, now, assignment_id, generation),
            )
            db.execute(
                "UPDATE orchestration_assignments SET state=?,terminal_result_json=?,updated_at=? "
                "WHERE assignment_id=?",
                (
                    projected_state,
                    _canonical(evidence if state != "ACKNOWLEDGED" else {}),
                    now, assignment_id,
                ),
            )
            dispatch_message_id = attempt["dispatch_message_id"]
            if dispatch_message_id and state == "ACKNOWLEDGED":
                db.execute(
                    "UPDATE orchestration_mailbox SET delivered_at=? "
                    "WHERE message_id=? AND delivered_at IS NULL",
                    (now, dispatch_message_id),
                )
            message_id = "delivery." + hashlib.sha256(
                f"{assignment_id}:{generation}:{state}".encode("utf-8")
            ).hexdigest()[:32]
            payload = {"state": state, "evidence": evidence}
            digest = _digest(payload)
            prior = db.execute(
                "SELECT message_digest FROM orchestration_mailbox WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if prior is None:
                db.execute(
                    "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        message_id, assignment["session_id"], assignment_id,
                        generation, "ACK" if state == "ACKNOWLEDGED" else state,
                        attempt["worker_node_id"], None, digest, _canonical(payload),
                        now, now, None,
                    ),
                )
            elif prior["message_digest"] != digest:
                raise ConflictError("ORCHESTRATION_MESSAGE_REQUEST_MISMATCH")

    def replace_worker(
        self, *, work: Work, session_id: str, assignment_id: str,
        manager_epoch: int, worker_node_id: str, attachment_id: str,
        reason: str, evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new attempt only after the prior one is proven not applied.

        The logical assignment and its request digest stay unchanged.  A new
        generation fences late results from the old attachment and gives the
        replacement delivery a distinct, deterministic identity.
        """
        worker_node_id = _identifier(
            worker_node_id, "ORCHESTRATION_WORKER_NODE_INVALID"
        )
        attachment_id = _identifier(
            attachment_id, "ORCHESTRATION_ATTACHMENT_ID_INVALID"
        )
        reason = _bounded_text(
            reason, code="ORCHESTRATION_REPLACEMENT_REASON_INVALID", limit=500
        )
        evidence = dict(evidence or {})
        if len(_canonical(evidence)) > 8000:
            raise PreconditionError("ORCHESTRATION_REPLACEMENT_EVIDENCE_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if assignment is None or assignment["session_id"] != session_id:
                raise KeyError("ORCHESTRATION_ASSIGNMENT_NOT_FOUND")
            generation = int(assignment["current_generation"])
            prior_attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, generation),
            ).fetchone()
            prior_result = _load(assignment["terminal_result_json"])
            proven_not_applied = (
                prior_attempt is not None
                and prior_attempt["state"] == "NOT_APPLIED"
                and assignment["state"] == "NOT_APPLIED"
                and isinstance(prior_result, dict)
                and prior_result.get("pre_dispatch") is True
            )
            if not proven_not_applied:
                raise ConflictError("ORCHESTRATION_REPLACEMENT_NOT_PROVEN_SAFE")
            attachment = db.execute(
                "SELECT * FROM orchestration_attachments "
                "WHERE attachment_id=? AND node_id=? AND active=1 "
                "AND EXISTS (SELECT 1 FROM orchestration_session_nodes sn "
                "WHERE sn.session_id=? AND sn.node_id=orchestration_attachments.node_id "
                "AND sn.active=1) "
                "ORDER BY generation DESC LIMIT 1",
                (attachment_id, worker_node_id, session_id),
            ).fetchone()
            if attachment is None or not attachment["relay_role"]:
                raise ConflictError("ORCHESTRATION_REPLACEMENT_ATTACHMENT_MISMATCH")
            next_generation = generation + 1
            decision_id = "replace." + hashlib.sha256(
                f"{assignment_id}:{next_generation}".encode("utf-8")
            ).hexdigest()[:32]
            decision_payload = {
                "reason": reason,
                "evidence": evidence,
                "prior_generation": generation,
                "prior_result_digest": _digest(prior_result),
                "replacement_worker_node_id": worker_node_id,
                "replacement_attachment_id": attachment_id,
            }
            prior_decision = db.execute(
                "SELECT * FROM orchestration_reconciliations WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if prior_decision is not None:
                return self._assignment_value(db, assignment)
            db.execute(
                "INSERT INTO orchestration_reconciliations VALUES(?,?,?,?,?,?,?,?)",
                (
                    decision_id, session_id, assignment_id, generation,
                    manager_epoch, "REPLACE_PROVEN_NOT_APPLIED",
                    _canonical(decision_payload), now,
                ),
            )
            db.execute(
                "INSERT INTO orchestration_assignment_attempts "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    assignment_id, next_generation, manager_epoch,
                    worker_node_id, attachment_id, attachment["generation"],
                    "QUEUED", None, None, now, now,
                ),
            )
            db.execute(
                "UPDATE orchestration_assignments SET state='QUEUED',"
                "current_generation=?,terminal_result_json='{}',updated_at=? "
                "WHERE assignment_id=? AND current_generation=?",
                (next_generation, now, assignment_id, generation),
            )
            self.store._event(db, "ORCHESTRATION_WORKER_REPLACED", assignment_id, {
                "prior_generation": generation,
                "generation": next_generation,
                "worker_node_id": worker_node_id,
                "decision_id": decision_id,
            })
            updated = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            return self._assignment_value(db, updated)

    def complete_assignment(
        self, *, assignment_id: str, generation: int, outcome: str,
        result: dict[str, Any], result_message_id: str,
    ) -> dict[str, Any]:
        if outcome not in {"APPLIED", "FAILED", "UNKNOWN", "NOT_APPLIED"}:
            raise ValueError("ORCHESTRATION_OUTCOME_INVALID")
        result_message_id = _identifier(
            result_message_id, "ORCHESTRATION_RESULT_MESSAGE_ID_INVALID"
        )
        bounded = _canonical(result)
        if len(bounded) > 64000:
            result = {
                "truncated": True,
                "sha256": hashlib.sha256(bounded.encode("utf-8")).hexdigest(),
                "summary": str(result.get("summary") or result.get("error") or "")[:4000],
            }
            bounded = _canonical(result)
        now = time.time()
        with self.store.transaction() as db:
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if assignment is None:
                raise KeyError("ORCHESTRATION_ASSIGNMENT_NOT_FOUND")
            prior = db.execute(
                "SELECT * FROM orchestration_mailbox WHERE message_id=?",
                (result_message_id,),
            ).fetchone()
            digest = _digest(result)
            if prior is not None:
                if prior["message_digest"] != digest:
                    raise ConflictError("ORCHESTRATION_MESSAGE_REQUEST_MISMATCH")
                return self._assignment_value(db, assignment)
            if generation != assignment["current_generation"]:
                # Late evidence is retained but can never become the new attempt result.
                attempt = db.execute(
                    "SELECT worker_node_id FROM orchestration_assignment_attempts "
                    "WHERE assignment_id=? AND generation=?",
                    (assignment_id, generation),
                ).fetchone()
                if attempt is None:
                    raise KeyError("ORCHESTRATION_ATTEMPT_NOT_FOUND")
                db.execute(
                    "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        result_message_id, assignment["session_id"], assignment_id,
                        generation, "LATE_RESULT", attempt["worker_node_id"], None,
                        digest, bounded, now, now, None,
                    ),
                )
                return self._assignment_value(db, assignment)
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, generation),
            ).fetchone()
            terminal = outcome
            if assignment["state"] in _TERMINAL:
                if (
                    assignment["state"] != terminal
                    or _load(assignment["terminal_result_json"]) != result
                ):
                    raise ConflictError("ORCHESTRATION_TERMINAL_RESULT_MISMATCH")
                return self._assignment_value(db, assignment)
            db.execute(
                "UPDATE orchestration_assignment_attempts SET state=?,updated_at=? "
                "WHERE assignment_id=? AND generation=?",
                (terminal, now, assignment_id, generation),
            )
            db.execute(
                "UPDATE orchestration_assignments "
                "SET state=?,terminal_result_json=?,updated_at=? WHERE assignment_id=?",
                (terminal, bounded, now, assignment_id),
            )
            db.execute(
                "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result_message_id, assignment["session_id"], assignment_id,
                    generation, "RESULT", attempt["worker_node_id"], None,
                    digest, bounded, now, now, None,
                ),
            )
            # A known terminal worker result is durable before any manager
            # notification is attempted.  The event snapshots the *current*
            # manager attachment; a later manager epoch or attachment change
            # makes that event stale rather than redirecting it.
            if outcome in {"APPLIED", "FAILED"}:
                self._record_manager_wake(
                    db, session_id=assignment["session_id"], assignment=assignment,
                    generation=generation, result_message_id=result_message_id,
                    result_digest=digest, now=now,
                )
            self.store._event(db, "ORCHESTRATION_ASSIGNMENT_FINISHED", assignment_id, {
                "generation": generation, "outcome": terminal,
                "result_message_id": result_message_id,
            })
            updated = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            return self._assignment_value(db, updated)

    @staticmethod
    def _manager_attachment_row(db, *, session_id: str, manager_node_id: str):
        return db.execute(
            "SELECT a.* FROM orchestration_attachments a "
            "WHERE a.node_id=? AND a.active=1 AND a.relay_role IS NOT NULL "
            "AND a.relay_role!='' AND EXISTS (SELECT 1 FROM "
            "orchestration_session_nodes sn WHERE sn.session_id=? "
            "AND sn.node_id=a.node_id AND sn.active=1) AND EXISTS "
            "(SELECT 1 FROM connections c WHERE c.connection_id='orch:' || a.attachment_id "
            "AND c.node_id=a.node_id AND c.generation=a.generation "
            "AND c.active=1) ORDER BY a.generation DESC LIMIT 1",
            (manager_node_id, session_id),
        ).fetchone()

    def _record_manager_wake(
        self, db, *, session_id: str, assignment, generation: int,
        result_message_id: str, result_digest: str, now: float,
    ) -> dict[str, Any]:
        session = self._session_row(db, session_id)
        manager_epoch = int(session["manager_epoch"])
        manager_node_id = str(session["manager_node_id"] or "")
        attachment = (
            self._manager_attachment_row(
                db, session_id=session_id, manager_node_id=manager_node_id,
            ) if manager_node_id else None
        )
        event_id = "wake." + hashlib.sha256(
            f"{session_id}:{manager_epoch}:{assignment['assignment_id']}:"
            f"{generation}:{result_message_id}".encode("utf-8")
        ).hexdigest()[:32]
        state = "PENDING" if attachment is not None else "BLOCKED"
        envelope_schema, receipt_mode = (
            (2, "RCC_RESULT_POLL_V1")
            if self.manager_wake_receipt_v2_enabled
            else (1, "LEGACY_RETURN_V1")
        )
        if envelope_schema == 2 and manager_node_id:
            lease = db.execute(
                "SELECT * FROM orchestration_durable_leases WHERE session_id=?",
                (session_id,),
            ).fetchone()
            lease_token = secrets.token_hex(32)
            if lease is None:
                db.execute(
                    "INSERT INTO orchestration_durable_leases VALUES(?,?,?,?,?,?)",
                    (session_id, manager_node_id, manager_epoch, lease_token,
                     now + 60.0, now),
                )
            elif int(lease["epoch"]) < manager_epoch:
                db.execute(
                    "INSERT INTO orchestration_durable_lease_revocations "
                    "(session_id,revoked_epoch,owner_node_id,token_digest,"
                    "successor_epoch,reason,created_at) VALUES(?,?,?,?,?,?,?)",
                    (session_id, int(lease["epoch"]), str(lease["manager_node_id"]),
                     hashlib.sha256(str(lease["token"]).encode("utf-8")).hexdigest(),
                     manager_epoch, "SUPERSEDED_BY_MANAGER_WAKE_EPOCH", now),
                )
                changed = db.execute(
                    "UPDATE orchestration_durable_leases SET manager_node_id=?,"
                    "epoch=?,token=?,expires_at=?,updated_at=? WHERE session_id=? "
                    "AND epoch=? AND token=?",
                    (manager_node_id, manager_epoch, lease_token, now + 60.0, now,
                     session_id, int(lease["epoch"]), str(lease["token"])),
                ).rowcount
                if changed != 1:
                    raise ConflictError("ORCHESTRATION_MANAGER_LEASE_RACE")
            elif (int(lease["epoch"]) == manager_epoch
                  and str(lease["manager_node_id"]) != manager_node_id):
                raise ConflictError("ORCHESTRATION_MANAGER_LEASE_OWNER_MISMATCH")
        values = (
            event_id, session_id, manager_epoch, assignment["assignment_id"],
            generation, result_message_id, result_digest, manager_node_id or None,
            attachment["attachment_id"] if attachment is not None else None,
            int(attachment["generation"]) if attachment is not None else None,
            attachment["instance_id"] if attachment is not None else None,
            attachment["external_session_id"] if attachment is not None else None,
            int(attachment["tab_id"]) if attachment is not None else None,
            attachment["conversation_key"] if attachment is not None else None,
            attachment["relay_role"] if attachment is not None else None,
            attachment["binding_receipt_id"] if attachment is not None else None,
            state, None, now, now, None, None, envelope_schema, receipt_mode,
            None, None, "NOT_REQUESTED", None,
        )
        db.execute(
            "INSERT OR IGNORE INTO orchestration_manager_wakes "
            "(event_id,session_id,manager_epoch,assignment_id,"
            "assignment_generation,result_message_id,result_digest,manager_node_id,"
            "attachment_id,attachment_generation,instance_id,external_session_id,"
            "tab_id,conversation_key,relay_role,binding_receipt_id,state,delivery_id,"
            "created_at,updated_at,delivered_at,acknowledged_at,envelope_schema,"
            "receipt_mode,decision_id,result_hash,result_ack_state,"
            "result_acknowledged_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        row = db.execute(
            "SELECT * FROM orchestration_manager_wakes WHERE event_id=?", (event_id,)
        ).fetchone()
        self.store._event(db, "ORCHESTRATION_MANAGER_WAKE_RECORDED", event_id, {
            "assignment_id": assignment["assignment_id"],
            "generation": generation, "manager_epoch": manager_epoch,
            "state": row["state"],
            "receipt_mode": receipt_mode,
        })
        return dict(row)

    def claim_manager_wake(
        self, *, work: Work, session_id: str, event_id: str,
        manager_epoch: int, delivery_id: str,
    ) -> dict[str, Any] | None:
        event_id = _identifier(event_id, "ORCHESTRATION_WAKE_EVENT_ID_INVALID")
        delivery_id = _identifier(delivery_id, "ORCHESTRATION_WAKE_DELIVERY_ID_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            self._assert_current_work_assignment(db, work)
            event = db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=? AND session_id=?",
                (event_id, session_id),
            ).fetchone()
            if event is None:
                raise KeyError("ORCHESTRATION_WAKE_EVENT_NOT_FOUND")
            envelope_schema = event["envelope_schema"]
            receipt_mode = str(event["receipt_mode"] or "")
            if isinstance(envelope_schema, bool) or not isinstance(envelope_schema, int):
                raise ConflictError("ORCHESTRATION_WAKE_ENVELOPE_SCHEMA_INVALID")
            if (envelope_schema, receipt_mode) not in {
                (1, "LEGACY_RETURN_V1"), (2, "RCC_RESULT_POLL_V1"),
            }:
                raise ConflictError("ORCHESTRATION_WAKE_ENVELOPE_SCHEMA_UNSUPPORTED")
            if int(session["manager_epoch"]) != manager_epoch or int(event["manager_epoch"]) != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            if event["state"] == "DELIVERED":
                return dict(event)
            if event["state"] != "PENDING":
                return None
            attachment = self._manager_attachment_row(
                db, session_id=session_id, manager_node_id=str(session["manager_node_id"] or ""),
            )
            exact = attachment is not None and all((
                str(attachment["attachment_id"]) == str(event["attachment_id"]),
                int(attachment["generation"]) == int(event["attachment_generation"]),
                str(attachment["instance_id"]) == str(event["instance_id"]),
                str(attachment["external_session_id"]) == str(event["external_session_id"]),
                int(attachment["tab_id"]) == int(event["tab_id"]),
                str(attachment["conversation_key"]) == str(event["conversation_key"]),
                str(attachment["relay_role"]) == str(event["relay_role"]),
                str(attachment["binding_receipt_id"]) == str(event["binding_receipt_id"]),
            ))
            if not exact:
                db.execute(
                    "UPDATE orchestration_manager_wakes SET state='STALE',updated_at=? "
                    "WHERE event_id=? AND state='PENDING'", (now, event_id),
                )
                self.store._event(db, "ORCHESTRATION_MANAGER_WAKE_STALE", event_id, {
                    "manager_epoch": manager_epoch,
                })
                return None
            changed = db.execute(
                "UPDATE orchestration_manager_wakes SET state='DELIVERING',delivery_id=?,"
                "updated_at=? WHERE event_id=? AND state='PENDING'",
                (delivery_id, now, event_id),
            ).rowcount
            if changed != 1:
                raise ConflictError("ORCHESTRATION_WAKE_STATE_CHANGED")
            claimed = db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?", (event_id,)
            ).fetchone()
            self.store._event(db, "ORCHESTRATION_MANAGER_WAKE_DISPATCHING", event_id, {
                "delivery_id": delivery_id, "manager_epoch": manager_epoch,
                "wake_envelope_schema": envelope_schema,
                "receipt_mode": receipt_mode,
            })
            result = dict(claimed)
            result["wake_envelope_schema"] = envelope_schema
            result["receipt_mode"] = receipt_mode
            return result

    def complete_manager_wake(
        self, *, work: Work, session_id: str, event_id: str,
        manager_epoch: int, delivery_id: str, outcome: str,
    ) -> dict[str, Any]:
        if outcome not in {"DELIVERED", "PENDING", "UNKNOWN"}:
            raise ValueError("ORCHESTRATION_WAKE_OUTCOME_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            self._assert_current_work_assignment(db, work)
            event = db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=? AND session_id=?",
                (event_id, session_id),
            ).fetchone()
            if event is None:
                raise KeyError("ORCHESTRATION_WAKE_EVENT_NOT_FOUND")
            envelope_schema = event["envelope_schema"]
            receipt_mode = str(event["receipt_mode"] or "")
            if isinstance(envelope_schema, bool) or not isinstance(envelope_schema, int):
                raise ConflictError("ORCHESTRATION_WAKE_ENVELOPE_SCHEMA_INVALID")
            if (envelope_schema, receipt_mode) not in {
                (1, "LEGACY_RETURN_V1"), (2, "RCC_RESULT_POLL_V1"),
            }:
                raise ConflictError("ORCHESTRATION_WAKE_ENVELOPE_SCHEMA_UNSUPPORTED")
            if int(session["manager_epoch"]) != manager_epoch or int(event["manager_epoch"]) != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            if str(event["delivery_id"] or "") != delivery_id:
                raise ConflictError("ORCHESTRATION_WAKE_DELIVERY_MISMATCH")
            if event["state"] == "DELIVERED":
                return dict(event)
            if event["state"] != "DELIVERING":
                raise ConflictError("ORCHESTRATION_WAKE_STATE_CHANGED")
            delivered_at = now if outcome == "DELIVERED" else None
            db.execute(
                "UPDATE orchestration_manager_wakes SET state=?,updated_at=?,"
                "delivered_at=? WHERE event_id=?",
                (outcome, now, delivered_at, event_id),
            )
            updated = db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?", (event_id,)
            ).fetchone()
            self.store._event(db, "ORCHESTRATION_MANAGER_WAKE_" + outcome, event_id, {
                "delivery_id": delivery_id, "manager_epoch": manager_epoch,
            })
            return dict(updated)

    def consume_results(
        self, *, work: Work, session_id: str, manager_epoch: int,
        consumer_assignment_id: str, producer_assignment_ids: list[str],
    ) -> list[str]:
        consumer_assignment_id = _identifier(
            consumer_assignment_id, "ORCHESTRATION_ASSIGNMENT_ID_INVALID"
        )
        producer_assignment_ids = sorted(set(
            _identifier(item, "ORCHESTRATION_DEPENDENCY_ID_INVALID")
            for item in producer_assignment_ids
        ))
        now = time.time()
        consumed: list[str] = []
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            consumer = db.execute(
                "SELECT state FROM orchestration_assignments "
                "WHERE assignment_id=? AND session_id=?",
                (consumer_assignment_id, session_id),
            ).fetchone()
            if consumer is None or consumer["state"] != "QUEUED":
                raise ConflictError("ORCHESTRATION_CONSUMER_NOT_QUEUED")
            for producer_id in producer_assignment_ids:
                dependency = db.execute(
                    "SELECT 1 FROM orchestration_dependencies "
                    "WHERE assignment_id=? AND depends_on_assignment_id=?",
                    (consumer_assignment_id, producer_id),
                ).fetchone()
                producer = db.execute(
                    "SELECT state,current_generation FROM orchestration_assignments "
                    "WHERE assignment_id=? AND session_id=?",
                    (producer_id, session_id),
                ).fetchone()
                if dependency is None or producer is None or producer["state"] != "APPLIED":
                    raise ConflictError("ORCHESTRATION_RESULT_NOT_CONSUMABLE")
                message = db.execute(
                    "SELECT message_id FROM orchestration_mailbox "
                    "WHERE assignment_id=? AND assignment_generation=? AND kind='RESULT' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (producer_id, producer["current_generation"]),
                ).fetchone()
                if message is None:
                    raise ConflictError("ORCHESTRATION_RESULT_MESSAGE_MISSING")
                db.execute(
                    "UPDATE orchestration_mailbox SET consumed_at=COALESCE(consumed_at,?) "
                    "WHERE message_id=?",
                    (now, message["message_id"]),
                )
                consumed.append(message["message_id"])
            self.store._event(db, "ORCHESTRATION_RESULTS_CONSUMED", consumer_assignment_id, {
                "producer_assignment_ids": producer_assignment_ids,
                "message_ids": consumed,
                "manager_epoch": manager_epoch,
            })
        return consumed

    def record_chain_plan(
        self, *, work: Work, session_id: str, operation_id: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        operation_id = _identifier(operation_id, "ORCHESTRATION_OPERATION_ID_INVALID")
        payload = _canonical(plan)
        if len(payload) > 64000:
            raise PreconditionError("ORCHESTRATION_CHAIN_PLAN_TOO_LARGE")
        message_id = "plan." + hashlib.sha256(
            f"{session_id}:{operation_id}".encode("utf-8")
        ).hexdigest()[:32]
        digest = _digest(plan)
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            prior = db.execute(
                "SELECT * FROM orchestration_mailbox WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if prior is not None:
                if prior["message_digest"] != digest:
                    raise ConflictError("ORCHESTRATION_CHAIN_PLAN_MISMATCH")
                return _load(prior["payload_json"])
            db.execute(
                "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    message_id, session_id, None, None, "PLAN", None, None,
                    digest, payload, now, now, None,
                ),
            )
            self.store._event(db, "ORCHESTRATION_CHAIN_PLAN_RECORDED", session_id, {
                "operation_id": operation_id, "plan_digest": digest,
            })
        return plan

    def chain_plan(
        self, *, work: Work, session_id: str, original_operation_id: str
    ) -> dict[str, Any]:
        message_id = "plan." + hashlib.sha256(
            f"{session_id}:{original_operation_id}".encode("utf-8")
        ).hexdigest()[:32]
        db = self.store._connect()
        try:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            row = db.execute(
                "SELECT payload_json FROM orchestration_mailbox "
                "WHERE message_id=? AND session_id=? AND kind='PLAN'",
                (message_id, session_id),
            ).fetchone()
            if row is None:
                raise KeyError("ORCHESTRATION_CHAIN_PLAN_NOT_FOUND")
            return _load(row["payload_json"])
        finally:
            db.close()

    def fence_recovery_original(
        self, *, work: Work, session_id: str, original_operation_id: str,
        assignment_ids: list[str],
    ) -> None:
        """Stop the crashed worker and fence recovery to its exact claims.

        A RUNNING outer operation is durably converted to a transitional UNKNOWN
        receipt before a resolver observes RCC or adopts queued work.  All worker
        paths re-check that outer receipt, so no late worker can race the resolver.
        """
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            original = db.execute(
                "SELECT state,outcome FROM operations WHERE operation_id=? "
                "AND work_id=? AND capability='orchestrate'",
                (original_operation_id, work.work_id),
            ).fetchone()
            if original is None or not (
                original["state"] == "RUNNING"
                or (original["state"] == "FINISHED" and original["outcome"] == "UNKNOWN")
            ):
                raise ConflictError("ORCHESTRATION_RECOVERY_ORIGINAL_INVALID")
            for assignment_id in sorted(set(assignment_ids)):
                exact = "orchestration-run:" + session_id + ":" + _identifier(
                    assignment_id, "ORCHESTRATION_ASSIGNMENT_ID_INVALID"
                )
                claim = db.execute(
                    "SELECT 1 FROM resource_claims WHERE operation_id=? "
                    "AND resource_key=? AND unresolved=1",
                    (original_operation_id, exact),
                ).fetchone()
                if claim is None:
                    raise ConflictError("ORCHESTRATION_RECOVERY_CLAIM_MISSING")
            if original["state"] == "RUNNING":
                now = time.time()
                db.execute(
                    "UPDATE operations SET state='FINISHED',outcome='UNKNOWN',"
                    "evidence_json=?,error=?,updated_at=? WHERE operation_id=? "
                    "AND state='RUNNING'",
                    (
                        _canonical({
                            "phase": "ORCHESTRATION_RECOVERY_TAKEOVER",
                            "session_id": session_id,
                            "assignment_ids": sorted(set(assignment_ids)),
                        }),
                        "ORCHESTRATION_RECOVERY_TAKEOVER", now,
                        original_operation_id,
                    ),
                )
                self.store._event(
                    db, "ORCHESTRATION_RECOVERY_TAKEOVER", original_operation_id,
                    {"session_id": session_id,
                     "assignment_ids": sorted(set(assignment_ids))},
                )

    @staticmethod
    def _chain_plan_row(db, session_id: str, original_operation_id: str):
        message_id = "plan." + hashlib.sha256(
            f"{session_id}:{original_operation_id}".encode("utf-8")
        ).hexdigest()[:32]
        return db.execute(
            "SELECT * FROM orchestration_mailbox WHERE message_id=? "
            "AND session_id=? AND kind='PLAN'",
            (message_id, session_id),
        ).fetchone()

    @staticmethod
    def _original_claim(db, *, work: Work, session_id: str,
                        assignment_id: str, original_operation_id: str):
        exact_claim = "orchestration-run:" + session_id + ":" + assignment_id
        original = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND work_id=? "
            "AND capability='orchestrate'",
            (original_operation_id, work.work_id),
        ).fetchone()
        claim = db.execute(
            "SELECT 1 FROM resource_claims WHERE operation_id=? "
            "AND resource_key=? AND unresolved=1",
            (original_operation_id, exact_claim),
        ).fetchone()
        if original is None or claim is None:
            raise ConflictError("ORCHESTRATION_RECONCILE_ORIGINAL_MISMATCH")
        return original

    def recover_terminal_assignment(
        self, *, work: Work, session_id: str, assignment_id: str,
        original_operation_id: str, allow_chain: bool = False,
        resolver_operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Prove a terminal exact assignment after the outer receipt was lost."""
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=? "
                "AND session_id=?", (assignment_id, session_id),
            ).fetchone()
            if assignment is None or assignment["state"] not in {
                "APPLIED", "FAILED", "NOT_APPLIED"
            }:
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_NOT_TERMINAL")
            self._original_claim(
                db, work=work, session_id=session_id,
                assignment_id=assignment_id,
                original_operation_id=original_operation_id,
            )
            if (
                self._chain_plan_row(db, session_id, original_operation_id) is not None
                and not allow_chain
            ):
                raise ConflictError("ORCHESTRATION_CHAIN_REQUIRES_RESUME")
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, assignment["current_generation"]),
            ).fetchone()
            terminal = _load(assignment["terminal_result_json"])
            delivery_id = str(terminal.get("delivery_id") or "")
            if (
                attempt is None or not delivery_id
                or delivery_id != str(attempt["dispatch_operation_id"] or "")
            ):
                raise ConflictError("ORCHESTRATION_TERMINAL_DELIVERY_UNPROVEN")
            value = self._assignment_value(db, assignment)
            if not allow_chain and resolver_operation_id:
                mapped = Outcome(str(assignment["state"]))
                self.store.finish_orchestration_recovery_in_transaction(
                    db, resolver_operation_id=resolver_operation_id,
                    original_operation_id=original_operation_id,
                    resolver_outcome=mapped, original_outcome=mapped,
                    evidence={
                        "operation": "reconcile", "session_id": session_id,
                        "assignment_id": assignment_id,
                        "terminal_recovery": True,
                    },
                    release_original=True,
                )
            return value

    def prove_not_dispatched(
        self, *, work: Work, session_id: str, original_operation_id: str,
        resolver_operation_id: str,
    ) -> dict[str, Any]:
        """Prove a crashed outer operation had no possible browser effect."""
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            original = db.execute(
                "SELECT * FROM operations WHERE operation_id=? AND work_id=? "
                "AND capability='orchestrate'",
                (original_operation_id, work.work_id),
            ).fetchone()
            if original is None or not (
                original["state"] == "RUNNING"
                or (original["state"] == "FINISHED" and original["outcome"] == "UNKNOWN")
            ):
                raise ConflictError("ORCHESTRATION_RECOVERY_ORIGINAL_INVALID")
            claims = [row[0] for row in db.execute(
                "SELECT resource_key FROM resource_claims WHERE operation_id=? "
                "AND unresolved=1 ORDER BY resource_key", (original_operation_id,),
            ).fetchall()]
            prefix = "orchestration-run:" + session_id + ":"
            claimed_ids = [item[len(prefix):] for item in claims if item.startswith(prefix)]
            if not claimed_ids:
                raise ConflictError("ORCHESTRATION_RECOVERY_CLAIM_MISSING")
            plan_row = self._chain_plan_row(db, session_id, original_operation_id)
            if plan_row is not None:
                plan = _load(plan_row["payload_json"])
                planned_ids = [str(item["assignment_id"]) for item in plan["tasks"]]
                planned_ids.append(str(plan["synthesis"]["assignment_id"]))
            else:
                planned_ids = claimed_ids
            observed: list[str] = []
            for assignment_id in planned_ids:
                assignment = db.execute(
                    "SELECT * FROM orchestration_assignments WHERE assignment_id=? "
                    "AND session_id=?", (assignment_id, session_id),
                ).fetchone()
                if assignment is None:
                    continue
                observed.append(assignment_id)
                request = _load(assignment["request_json"])
                outer_owner = str(request.get("_outer_operation_id") or "")
                if outer_owner and outer_owner != original_operation_id:
                    raise ConflictError("ORCHESTRATION_ASSIGNMENT_ADOPTED_BY_RESOLVER")
                terminal = _load(assignment["terminal_result_json"])
                safe_pre_dispatch_terminal = (
                    assignment["state"] == "NOT_APPLIED"
                    and terminal.get("pre_dispatch") is True
                )
                if assignment["state"] != "QUEUED" and not safe_pre_dispatch_terminal:
                    raise ConflictError("ORCHESTRATION_EXTERNAL_EFFECT_NOT_EXCLUDED")
                attempt = db.execute(
                    "SELECT * FROM orchestration_assignment_attempts "
                    "WHERE assignment_id=? AND generation=?",
                    (assignment_id, assignment["current_generation"]),
                ).fetchone()
                if attempt is None or attempt["dispatch_operation_id"] is not None \
                        or attempt["dispatch_message_id"] is not None:
                    raise ConflictError("ORCHESTRATION_EXTERNAL_EFFECT_NOT_EXCLUDED")
                dispatched = db.execute(
                    "SELECT 1 FROM orchestration_mailbox WHERE assignment_id=? "
                    "AND kind='DISPATCH' LIMIT 1", (assignment_id,),
                ).fetchone()
                if dispatched is not None:
                    raise ConflictError("ORCHESTRATION_EXTERNAL_EFFECT_NOT_EXCLUDED")
            recovery_evidence = {
                "operation": "recover-not-dispatched",
                "session_id": session_id,
                "original_operation_id": original_operation_id,
                "external_effect_excluded": True,
            }
            self.store.finish_orchestration_recovery_in_transaction(
                db, resolver_operation_id=resolver_operation_id,
                original_operation_id=original_operation_id,
                resolver_outcome=Outcome.APPLIED,
                original_outcome=Outcome.NOT_APPLIED,
                evidence=recovery_evidence, release_original=True,
            )
            self.store._event(db, "ORCHESTRATION_NOT_DISPATCHED_PROVEN", original_operation_id, {
                "session_id": session_id,
                "plan_present": plan_row is not None,
                "observed_queued_assignments": observed,
                "original_finalized": original["state"] == "RUNNING",
            })
            return {
                "original_operation_id": original_operation_id,
                "plan_present": plan_row is not None,
                "observed_queued_assignments": observed,
                "claim_count": len(claims),
                "original_finalized": original["state"] == "RUNNING",
            }

    def reconcile_assignment(
        self, *, work: Work, session_id: str, assignment_id: str,
        manager_epoch: int, generation: int, outcome: str,
        result: dict[str, Any], result_message_id: str,
        original_operation_id: str, allow_chain: bool = False,
        resolver_operation_id: str | None = None,
    ) -> dict[str, Any]:
        if outcome not in {"APPLIED", "FAILED"}:
            raise ValueError("ORCHESTRATION_RECONCILE_OUTCOME_INVALID")
        result_message_id = _identifier(
            result_message_id, "ORCHESTRATION_RESULT_MESSAGE_ID_INVALID"
        )
        now = time.time()
        bounded = _canonical(result)
        if len(bounded) > 64000:
            raise PreconditionError("ORCHESTRATION_RESULT_TOO_LARGE")
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            self._assert_work(session, work)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=? "
                "AND session_id=?",
                (assignment_id, session_id),
            ).fetchone()
            if assignment is None or generation != assignment["current_generation"]:
                raise ConflictError("ORCHESTRATION_RECONCILE_GENERATION_MISMATCH")
            if assignment["state"] not in {
                "DISPATCHING", "ACKNOWLEDGED", "DISPATCH_UNKNOWN", "UNKNOWN"
            }:
                raise ConflictError("ORCHESTRATION_ASSIGNMENT_NOT_RECONCILABLE")
            self._original_claim(
                db, work=work, session_id=session_id,
                assignment_id=assignment_id,
                original_operation_id=original_operation_id,
            )
            if (
                self._chain_plan_row(db, session_id, original_operation_id) is not None
                and not allow_chain
            ):
                raise ConflictError("ORCHESTRATION_CHAIN_REQUIRES_RESUME")
            attempt = db.execute(
                "SELECT * FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?",
                (assignment_id, generation),
            ).fetchone()
            decision_id = "result." + hashlib.sha256(
                f"{original_operation_id}:{assignment_id}:{generation}".encode("utf-8")
            ).hexdigest()[:32]
            prior = db.execute(
                "SELECT * FROM orchestration_reconciliations WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if prior is not None:
                return self._assignment_value(db, assignment)
            digest = _digest(result)
            prior_message = db.execute(
                "SELECT message_digest FROM orchestration_mailbox WHERE message_id=?",
                (result_message_id,),
            ).fetchone()
            if prior_message is not None and prior_message["message_digest"] != digest:
                raise ConflictError("ORCHESTRATION_MESSAGE_REQUEST_MISMATCH")
            if prior_message is None:
                db.execute(
                    "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        result_message_id, session_id, assignment_id, generation,
                        "RECONCILED_RESULT", attempt["worker_node_id"], None,
                        digest, bounded, now, now, None,
                    ),
                )
            db.execute(
                "UPDATE orchestration_assignment_attempts SET state=?,updated_at=? "
                "WHERE assignment_id=? AND generation=?",
                (outcome, now, assignment_id, generation),
            )
            db.execute(
                "UPDATE orchestration_assignments SET state=?,terminal_result_json=?,"
                "updated_at=? WHERE assignment_id=?",
                (outcome, bounded, now, assignment_id),
            )
            db.execute(
                "INSERT INTO orchestration_reconciliations VALUES(?,?,?,?,?,?,?,?)",
                (
                    decision_id, session_id, assignment_id, generation,
                    manager_epoch, "IMPORT_EXACT_RCC_RESULT",
                    _canonical({
                        "original_operation_id": original_operation_id,
                        "result_message_id": result_message_id,
                        "result_digest": digest,
                    }), now,
                ),
            )
            self.store._event(db, "ORCHESTRATION_ASSIGNMENT_RECONCILED", assignment_id, {
                "generation": generation, "outcome": outcome,
                "original_operation_id": original_operation_id,
            })
            updated = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if not allow_chain and resolver_operation_id:
                mapped = Outcome(outcome)
                self.store.finish_orchestration_recovery_in_transaction(
                    db, resolver_operation_id=resolver_operation_id,
                    original_operation_id=original_operation_id,
                    resolver_outcome=mapped, original_outcome=mapped,
                    evidence={
                        "operation": "reconcile", "session_id": session_id,
                        "assignment_id": assignment_id,
                        "result_message_id": result_message_id,
                    },
                    release_original=True,
                )
            return self._assignment_value(db, updated)

    def finish_session(
        self, *, work: Work, session_id: str, manager_epoch: int,
        state: str, summary: dict[str, Any],
        resolver_operation_id: str | None = None,
        original_operation_id: str | None = None,
        resolver_outcome: Outcome | None = None,
        original_outcome: Outcome | None = None,
        release_original: bool = False,
        required_terminal_assignment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if state not in {"FINISHED", "PARTIAL", "BLOCKED", "CANCELLED"}:
            raise ValueError("ORCHESTRATION_SESSION_STATE_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            session = self._session_row(db, session_id)
            terminal_recovery = (
                resolver_operation_id is not None and session["state"] == state
                and state in {"FINISHED", "PARTIAL", "BLOCKED", "CANCELLED"}
            )
            if terminal_recovery:
                if session["work_id"] != work.work_id:
                    raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
                if session["work_assignment_epoch"] != work.assignment_epoch:
                    raise ConflictError("ORCHESTRATION_WORK_ASSIGNMENT_CHANGED")
            else:
                self._assert_work(session, work)
            if session["manager_epoch"] != manager_epoch:
                raise ConflictError("ORCHESTRATION_MANAGER_EPOCH_MISMATCH")
            for assignment_id in required_terminal_assignment_ids or []:
                assignment = db.execute(
                    "SELECT * FROM orchestration_assignments WHERE assignment_id=? "
                    "AND session_id=?", (assignment_id, session_id),
                ).fetchone()
                if assignment is None or assignment["state"] not in {
                    "APPLIED", "FAILED", "NOT_APPLIED"
                }:
                    raise ConflictError("ORCHESTRATION_ASSIGNMENT_NOT_TERMINAL")
                attempt = db.execute(
                    "SELECT * FROM orchestration_assignment_attempts "
                    "WHERE assignment_id=? AND generation=?",
                    (assignment_id, assignment["current_generation"]),
                ).fetchone()
                delivery_id = str(
                    _load(assignment["terminal_result_json"]).get("delivery_id") or ""
                )
                if (
                    attempt is None or not delivery_id
                    or delivery_id != str(attempt["dispatch_operation_id"] or "")
                ):
                    raise ConflictError("ORCHESTRATION_TERMINAL_DELIVERY_UNPROVEN")
            db.execute(
                "UPDATE orchestration_sessions SET state=?,terminal_summary_json=?,"
                "updated_at=? WHERE session_id=?",
                (state, _canonical(summary), now, session_id),
            )
            self.store._event(db, "ORCHESTRATION_SESSION_FINISHED", session_id, {
                "state": state, "manager_epoch": manager_epoch,
            })
            if resolver_operation_id is not None:
                if original_operation_id is None or resolver_outcome is None:
                    raise ValueError("ORCHESTRATION_RECOVERY_FINALIZATION_INVALID")
                self.store.finish_orchestration_recovery_in_transaction(
                    db, resolver_operation_id=resolver_operation_id,
                    original_operation_id=original_operation_id,
                    resolver_outcome=resolver_outcome,
                    original_outcome=original_outcome,
                    evidence={
                        "operation": "chain-resume", "session_id": session_id,
                        "session_state": state,
                    },
                    release_original=release_original,
                )
            return self._session_value(self._session_row(db, session_id))

    def snapshot(self, *, work: Work, session_id: str) -> dict[str, Any]:
        db = self.store._connect()
        try:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            assignments = [
                self._assignment_value(db, row)
                for row in db.execute(
                    "SELECT * FROM orchestration_assignments WHERE session_id=? "
                    "ORDER BY created_at DESC,assignment_id DESC LIMIT 100", (session_id,)
                ).fetchall()
            ]
            attachments = [dict(row) for row in db.execute(
                "SELECT * FROM orchestration_attachments WHERE node_id IN "
                "(SELECT node_id FROM orchestration_session_nodes "
                "WHERE session_id=? AND active=1) "
                "ORDER BY observed_at DESC,node_id,generation DESC LIMIT 100", (session_id,)
            ).fetchall()]
            mailbox = [dict(row) for row in db.execute(
                "SELECT message_id,assignment_id,assignment_generation,kind,"
                "sender_node_id,recipient_node_id,message_digest,created_at,"
                "delivered_at,consumed_at FROM orchestration_mailbox "
                "WHERE session_id=? ORDER BY created_at,message_id LIMIT 200",
                (session_id,),
            ).fetchall()]
            wakes = [dict(row) for row in db.execute(
                "SELECT event_id,manager_epoch,assignment_id,assignment_generation,"
                "result_message_id,result_digest,manager_node_id,attachment_id,"
                "attachment_generation,instance_id,external_session_id,tab_id,"
                "conversation_key,relay_role,state,delivery_id,created_at,updated_at,"
                "delivered_at,acknowledged_at,envelope_schema,receipt_mode,"
                "decision_id,result_hash,result_ack_state,result_acknowledged_at "
                "FROM orchestration_manager_wakes "
                "WHERE session_id=? ORDER BY created_at,event_id LIMIT 200",
                (session_id,),
            ).fetchall()]
            epochs = [dict(row) for row in db.execute(
                "SELECT session_id,epoch,manager_node_id,reason,started_at,ended_at "
                "FROM orchestration_manager_epochs WHERE session_id=? "
                "ORDER BY epoch DESC LIMIT 50",
                (session_id,),
            ).fetchall()]
            counts = {
                "assignments": db.execute(
                    "SELECT COUNT(*) FROM orchestration_assignments WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0],
                "attachments": db.execute(
                    "SELECT COUNT(*) FROM orchestration_attachments WHERE node_id IN "
                    "(SELECT node_id FROM orchestration_session_nodes WHERE session_id=?)",
                    (session_id,),
                ).fetchone()[0],
                "mailbox": db.execute(
                    "SELECT COUNT(*) FROM orchestration_mailbox WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0],
                "manager_epochs": db.execute(
                    "SELECT COUNT(*) FROM orchestration_manager_epochs WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0],
                "manager_wakes": len(wakes),
            }
        finally:
            db.close()
        return {
            "session": self._session_value(session),
            "assignments": assignments,
            "attachments": attachments,
            "mailbox": mailbox,
            "manager_wakes": wakes,
            "manager_epochs": epochs,
            "counts": counts,
        }

    def assignment(
        self, *, work: Work, session_id: str, assignment_id: str
    ) -> dict[str, Any]:
        db = self.store._connect()
        try:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            row = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id=? "
                "AND session_id=?",
                (assignment_id, session_id),
            ).fetchone()
            if row is None:
                raise KeyError("ORCHESTRATION_ASSIGNMENT_NOT_FOUND")
            return self._assignment_value(db, row)
        finally:
            db.close()

    def attachment(
        self, *, work: Work, session_id: str, attachment_id: str, generation: int
    ) -> dict[str, Any]:
        db = self.store._connect()
        try:
            session = self._session_row(db, session_id)
            if session["work_id"] != work.work_id:
                raise ConflictError("ORCHESTRATION_SESSION_ACCESS_DENIED")
            row = db.execute(
                "SELECT a.* FROM orchestration_attachments a "
                "JOIN orchestration_session_nodes sn ON sn.node_id=a.node_id "
                "WHERE sn.session_id=? AND sn.active=1 AND a.attachment_id=? "
                "AND a.generation=?",
                (session_id, attachment_id, generation),
            ).fetchone()
            if row is None:
                raise KeyError("ORCHESTRATION_ATTACHMENT_NOT_FOUND")
            return dict(row)
        finally:
            db.close()
