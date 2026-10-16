"""Isolated PR2 durable manager orchestration. No live dispatch or existing chain wiring."""
from __future__ import annotations
from contextlib import nullcontext

import hashlib
import json
import secrets
import time
from typing import Any

from .models import ConflictError
from .store import Store
from .consumption import commit_consumption_decision


def _require_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("INVALID_ID")
    return value


def _epoch(db, session_id, epoch):
    row = db.execute("SELECT manager_epoch FROM orchestration_sessions WHERE session_id=?", (session_id,)).fetchone()
    if row is None or row["manager_epoch"] != epoch:
        raise ConflictError("STALE_EPOCH")


def _lease(db, session_id, epoch, token, now):
    _epoch(db, session_id, epoch)
    row = db.execute("SELECT * FROM orchestration_durable_leases WHERE session_id=?", (session_id,)).fetchone()
    if row is None or row["epoch"] != epoch or row["token"] != token or row["expires_at"] <= now:
        raise ConflictError("LEASE_FENCED")
    return row


def acquire_lease(store: Store, *, session_id: str, manager_node_id: str,
                  expected_epoch: int, ttl_s: float, now: float | None = None) -> dict[str, Any]:
    _require_id(session_id); _require_id(manager_node_id)
    if not isinstance(expected_epoch, int) or isinstance(expected_epoch, bool) or expected_epoch < 1:
        raise ValueError("INVALID_EPOCH")
    if not 0 < ttl_s <= 3600:
        raise ValueError("INVALID_TTL")
    now = time.time() if now is None else now
    with store.transaction() as db:
        session = db.execute("SELECT manager_epoch,manager_node_id FROM orchestration_sessions WHERE session_id=?", (session_id,)).fetchone()
        if session is None or session["manager_epoch"] != expected_epoch:
            raise ConflictError("STALE_EPOCH")
        node = db.execute("SELECT active,role FROM nodes WHERE node_id=?", (manager_node_id,)).fetchone()
        if node is None or not node["active"] or node["role"] != "MANAGER":
            raise ConflictError("INVALID_MANAGER")
        old = db.execute("SELECT * FROM orchestration_durable_leases WHERE session_id=?", (session_id,)).fetchone()
        # Session epoch is authoritative. A higher epoch is proof that the
        # existing OrchestrationService takeover already committed; its lease
        # must not block the new owner even if it has not expired.
        if old is not None and old["epoch"] >= expected_epoch and old["expires_at"] > now:
            raise ConflictError("LEASE_ALREADY_ACTIVE")
        # Contract B: lease ownership NEVER changes the session epoch.
        # A replacement owner must first complete Orchestrator.takeover_manager(),
        # which atomically records epoch history, fences old wakes, adopts proven
        # unsent assignments and emits its existing takeover event receipts.
        # An expired lease at the SAME epoch is not evidence of a safe takeover.
        if old is not None and expected_epoch <= old["epoch"]:
            raise ConflictError("TAKEOVER_REQUIRED")
        if old is None and session["manager_node_id"] != manager_node_id:
            raise ConflictError("SESSION_MANAGER_MISMATCH")
        if old is not None and session["manager_node_id"] != manager_node_id:
            raise ConflictError("SESSION_MANAGER_MISMATCH")
        epoch = expected_epoch
        token = secrets.token_hex(32)
        if old is None:
            db.execute("INSERT INTO orchestration_durable_leases VALUES(?,?,?,?,?,?)",
                       (session_id, manager_node_id, epoch, token, now + ttl_s, now))
        else:
            if old["epoch"] >= expected_epoch:
                raise ConflictError("TAKEOVER_REQUIRED")
            # Append immutable revocation evidence and replace active lease in
            # the same BEGIN IMMEDIATE transaction. No session epoch mutation.
            db.execute(
                "INSERT INTO orchestration_durable_lease_revocations "
                "(session_id,revoked_epoch,owner_node_id,token_digest,successor_epoch,reason,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (session_id, old["epoch"], old["manager_node_id"],
                 hashlib.sha256(old["token"].encode("utf-8")).hexdigest(),
                 expected_epoch, "SUPERSEDED_BY_SESSION_EPOCH", now))
            changed = db.execute(
                "UPDATE orchestration_durable_leases SET manager_node_id=?,epoch=?,token=?,expires_at=?,updated_at=? "
                "WHERE session_id=? AND epoch=? AND token=?",
                (manager_node_id, epoch, token, now+ttl_s, now, session_id, old["epoch"], old["token"])).rowcount
            if changed != 1:
                raise ConflictError("LEASE_SUPERSEDE_RACE")
        return {"session_id": session_id, "epoch": epoch, "token": token, "expires_at": now + ttl_s}


def renew_lease(store: Store, *, session_id: str, epoch: int, token: str, ttl_s: float,
                now: float | None = None) -> float:
    _require_id(token)
    if not 0 < ttl_s <= 3600:
        raise ValueError("INVALID_TTL")
    now = time.time() if now is None else now
    with store.transaction() as db:
        _lease(db, session_id, epoch, token, now)
        db.execute("UPDATE orchestration_durable_leases SET expires_at=?,updated_at=? WHERE session_id=?",
                   (now + ttl_s, now, session_id))
        return now + ttl_s


def create_wake(store: Store, *, wake_id: str, session_id: str, assignment_id: str,
                generation: int, result_message_id: str, result_digest: str) -> bool:
    for item in (wake_id, session_id, assignment_id, result_message_id, result_digest):
        _require_id(item)
    if type(generation) is not int or generation < 1:
        raise ValueError("INVALID_GENERATION")
    with store.transaction() as db:
        source = db.execute("SELECT * FROM orchestration_mailbox WHERE message_id=?", (result_message_id,)).fetchone()
        assignment = db.execute("SELECT session_id,current_generation FROM orchestration_assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
        if (source is None or assignment is None or assignment["session_id"] != session_id
            or assignment["current_generation"] != generation or source["session_id"] != session_id
            or source["assignment_id"] != assignment_id or source["assignment_generation"] != generation
            or source["kind"] != "RESULT" or source["message_digest"] != result_digest):
            raise ConflictError("WAKE_RESULT_MISMATCH")
        payload = (session_id, assignment_id, generation, result_message_id, result_digest)
        prior = db.execute("SELECT * FROM orchestration_durable_wakes WHERE wake_id=?", (wake_id,)).fetchone()
        if prior is not None:
            if tuple(prior[k] for k in ("session_id","assignment_id","generation","result_message_id","result_digest")) != payload:
                raise ConflictError("WAKE_ID_CONFLICT")
            return False
        db.execute("INSERT INTO orchestration_durable_wakes VALUES(?,?,?,?,?,?,?,?)",
                   (wake_id, *payload, "PENDING", time.time()))
        return True


def commit_and_enqueue(store: Store, *, session_id: str, consumer_assignment_id: str,
                       manager_epoch: int, lease_token: str, decision_id: str,
                       request_digest: str, decision: dict[str, Any],
                       results: list[tuple[str, str]], actions: list[dict[str, Any]],
                       now: float | None = None, _db=None) -> dict[str, Any]:
    if not isinstance(actions, list):
        raise ValueError("ACTIONS_INVALID")
    now = time.time() if now is None else now
    with (store.transaction() if _db is None else nullcontext(_db)) as db:
        _lease(db, session_id, manager_epoch, lease_token, now)
        receipt = commit_consumption_decision(store, session_id=session_id,
                   consumer_assignment_id=consumer_assignment_id, manager_epoch=manager_epoch,
                   decision_id=decision_id, request_digest=request_digest,
                   decision=decision, results=results, _db=db)
        for index, action in enumerate(actions):
            if not isinstance(action, dict) or set(action) != {"delivery_id","target_node_id","attachment_id",
                    "attachment_generation","assignment_id","assignment_generation","payload"}:
                raise ValueError("ACTION_SCHEMA_INVALID")
            for key in ("delivery_id","target_node_id","attachment_id","assignment_id"):
                _require_id(action[key])
            if any(type(action[k]) is not int or action[k] < 1 for k in ("attachment_generation","assignment_generation")):
                raise ValueError("ACTION_GENERATION_INVALID")
            target = db.execute("SELECT node_id,generation,active FROM orchestration_attachments WHERE attachment_id=? AND generation=?",
                                (action["attachment_id"], action["attachment_generation"])).fetchone()
            assignment = db.execute("SELECT session_id,current_generation FROM orchestration_assignments WHERE assignment_id=?",
                                    (action["assignment_id"],)).fetchone()
            if (target is None or target["node_id"] != action["target_node_id"] or not target["active"]
                or assignment is None or assignment["session_id"] != session_id
                or assignment["current_generation"] != action["assignment_generation"]):
                raise ConflictError("TARGET_FENCED")
            serialized = json.dumps(action["payload"],sort_keys=True,separators=(",",":"),allow_nan=False)
            values = (action["delivery_id"], decision_id, index, session_id, manager_epoch,
                      action["target_node_id"],action["attachment_id"],action["attachment_generation"],
                      action["assignment_id"],action["assignment_generation"], serialized)
            old = db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE decision_id=? AND action_index=?",
                             (decision_id, index)).fetchone()
            if old is not None:
                if tuple(old[k] for k in ("delivery_id","decision_id","action_index","session_id","manager_epoch",
                         "target_node_id","attachment_id","attachment_generation","assignment_id",
                         "assignment_generation","payload_json")) != values:
                    raise ConflictError("OUTBOX_CONFLICT")
                continue
            db.execute("INSERT INTO orchestration_dispatch_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?,'PENDING',NULL,NULL,?,NULL)",
                       (*values, now))
        count = db.execute("SELECT COUNT(*) FROM orchestration_dispatch_outbox WHERE decision_id=?", (decision_id,)).fetchone()[0]
        if count != len(actions):
            raise ConflictError("OUTBOX_SET_CONFLICT")
        return {**receipt, "deliveries": count}


def _target_current(db, row):
    target = db.execute(
        "SELECT active,node_id FROM orchestration_attachments WHERE attachment_id=? AND generation=?",
        (row["attachment_id"], row["attachment_generation"])).fetchone()
    assignment = db.execute(
        "SELECT session_id,current_generation FROM orchestration_assignments WHERE assignment_id=?",
        (row["assignment_id"],)).fetchone()
    if (target is None or not target["active"] or target["node_id"] != row["target_node_id"]
        or assignment is None or assignment["session_id"] != row["session_id"]
        or assignment["current_generation"] != row["assignment_generation"]):
        raise ConflictError("TARGET_FENCED")


def reserve_delivery(store: Store, *, delivery_id: str, epoch: int, token: str,
                     now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    with store.transaction() as db:
        row = db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=?", (delivery_id,)).fetchone()
        if row is None:
            raise KeyError("DELIVERY_NOT_FOUND")
        _lease(db,row["session_id"],epoch,token,now)
        if row["manager_epoch"] > epoch or row["state"] != "PENDING":
            raise ConflictError("DELIVERY_NOT_RESERVABLE")
        _target_current(db, row)
        reservation = secrets.token_hex(32)
        db.execute("UPDATE orchestration_dispatch_outbox SET state='RESERVED',reservation_token=? WHERE delivery_id=? AND state='PENDING'",
                   (reservation, delivery_id))
        return {"delivery_id":delivery_id,"reservation_token":reservation,"target_node_id":row["target_node_id"]}


def record_attempt(store: Store, *, delivery_id: str, epoch: int, token: str,
                   reservation_token: str, phase: str, now: float | None = None) -> None:
    if phase not in {"PRE_SEND_ABORT","SEND_STARTED","DELIVERED","UNKNOWN"}:
        raise ValueError("ATTEMPT_PHASE_INVALID")
    now = time.time() if now is None else now
    with store.transaction() as db:
        row = db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=?", (delivery_id,)).fetchone()
        if row is None:
            raise KeyError("DELIVERY_NOT_FOUND")
        _lease(db,row["session_id"],epoch,token,now)
        if row["manager_epoch"] > epoch or row["reservation_token"] != reservation_token:
            raise ConflictError("RESERVATION_FENCED")
        allowed = {"RESERVED":{"PRE_SEND_ABORT":"PENDING","SEND_STARTED":"DISPATCHING"},
                   "DISPATCHING":{"DELIVERED":"DELIVERED","UNKNOWN":"UNKNOWN"}}
        state = allowed.get(row["state"],{}).get(phase)
        if state is None:
            raise ConflictError("INVALID_ATTEMPT_TRANSITION")
        if phase == "SEND_STARTED":
            _target_current(db, row)
        db.execute("UPDATE orchestration_dispatch_outbox SET state=?,reservation_token=? WHERE delivery_id=?",
                   (state,None if state == "PENDING" else reservation_token,delivery_id))
        db.execute("INSERT INTO orchestration_dispatch_attempts(delivery_id,phase,epoch,created_at) VALUES(?,?,?,?)",
                   (delivery_id,phase,epoch,now))


def acknowledge_delivery(store: Store, *, delivery_id: str, target_node_id: str,
                         attachment_id: str, attachment_generation: int,
                         ack_digest: str, epoch: int, token: str,
                         now: float | None = None, _db=None) -> bool:
    for item in (delivery_id,target_node_id,attachment_id,ack_digest):
        _require_id(item)
    now = time.time() if now is None else now
    with (store.transaction() if _db is None else nullcontext(_db)) as db:
        row = db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=?", (delivery_id,)).fetchone()
        if row is None or (row["target_node_id"],row["attachment_id"],row["attachment_generation"]) != (target_node_id,attachment_id,attachment_generation):
            raise ConflictError("ACK_TARGET_MISMATCH")
        _lease(db, row["session_id"], epoch, token, now)
        _target_current(db, row)
        if row["manager_epoch"] > epoch:
            raise ConflictError("STALE_DELIVERY_EPOCH")
        if row["state"] == "ACKNOWLEDGED":
            if row["ack_digest"] != ack_digest:
                raise ConflictError("ACK_CONFLICT")
            return False
        if row["state"] not in {"DELIVERED","UNKNOWN"}:
            raise ConflictError("ACK_NOT_DELIVERED")
        db.execute("UPDATE orchestration_dispatch_outbox SET state='ACKNOWLEDGED',ack_digest=? WHERE delivery_id=?",
                   (ack_digest,delivery_id))
        return True


def recovery_snapshot(store: Store, *, session_id: str) -> dict[str, Any]:
    db=store._connect()
    try:
        lease=db.execute("SELECT * FROM orchestration_durable_leases WHERE session_id=?",(session_id,)).fetchone()
        wakes=[dict(x) for x in db.execute("SELECT * FROM orchestration_durable_wakes WHERE session_id=? ORDER BY created_at,wake_id",(session_id,))]
        rows=[dict(x) for x in db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE session_id=? ORDER BY created_at,delivery_id",(session_id,))]
        return {"lease": None if lease is None else {k:lease[k] for k in ("session_id","manager_node_id","epoch","expires_at")},
                "wakes":wakes,"deliveries":rows,"resendable":[r["delivery_id"] for r in rows if r["state"] == "PENDING"]}
    finally:
        db.close()


def reserve_wake(store: Store, *, wake_id: str, epoch: int, token: str,
                 now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    with store.transaction() as db:
        row = db.execute("SELECT * FROM orchestration_durable_wakes WHERE wake_id=?", (wake_id,)).fetchone()
        if row is None:
            raise KeyError("WAKE_NOT_FOUND")
        lease = _lease(db,row["session_id"],epoch,token,now)
        if row["state"] != "PENDING":
            raise ConflictError("WAKE_NOT_PENDING")
        reservation = secrets.token_hex(32)
        db.execute("UPDATE orchestration_durable_wakes SET state='RESERVED' WHERE wake_id=? AND state='PENDING'",
                   (wake_id,))
        db.execute("INSERT INTO orchestration_durable_wake_attempts VALUES(?,?,?,?,?)",
                   (wake_id,epoch,reservation,"RESERVED",now))
        return {"wake_id":wake_id,"reservation_token":reservation,"result_message_id":row["result_message_id"]}


def record_wake(store: Store, *, wake_id: str, epoch: int, token: str,
                reservation_token: str, outcome: str,
                now: float | None = None) -> bool:
    if outcome not in {"PRE_SEND_ABORT","DELIVERED","UNKNOWN","ACKNOWLEDGED"}:
        raise ValueError("WAKE_OUTCOME_INVALID")
    now=time.time() if now is None else now
    with store.transaction() as db:
        row=db.execute("SELECT * FROM orchestration_durable_wakes WHERE wake_id=?",(wake_id,)).fetchone()
        if row is None:
            raise KeyError("WAKE_NOT_FOUND")
        _lease(db,row["session_id"],epoch,token,now)
        attempt=db.execute("SELECT * FROM orchestration_durable_wake_attempts WHERE wake_id=?",
                           (wake_id,)).fetchone()
        if (attempt is None or attempt["token"] != reservation_token
            or attempt["epoch"] != epoch):
            raise ConflictError("WAKE_RESERVATION_FENCED")
        transitions={"RESERVED":{"PRE_SEND_ABORT":"PENDING","DELIVERED":"DELIVERED",
                                 "UNKNOWN":"UNKNOWN"},
                     "DELIVERED":{"ACKNOWLEDGED":"ACKNOWLEDGED"},
                     "ACKNOWLEDGED":{"ACKNOWLEDGED":"ACKNOWLEDGED"}}
        state=transitions.get(row["state"],{}).get(outcome)
        if state is None:
            raise ConflictError("WAKE_TRANSITION_DENIED")
        if state==row["state"]:
            return False
        db.execute("UPDATE orchestration_durable_wakes SET state=? WHERE wake_id=?",(state,wake_id))
        db.execute("UPDATE orchestration_durable_wake_attempts SET state=? WHERE wake_id=?",
                   (state,wake_id))
        if outcome=="PRE_SEND_ABORT":
            db.execute("DELETE FROM orchestration_durable_wake_attempts WHERE wake_id=?",(wake_id,))
        return True
