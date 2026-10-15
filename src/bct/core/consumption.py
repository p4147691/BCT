"""PR1-only atomic result consumption; not wired into existing chain."""
from __future__ import annotations

import json
from time import time as _current_time
from collections.abc import Sequence
from typing import Any

from .models import ConflictError
from .orchestration import _canonical, _digest
from .store import Store


def commit_consumption_decision(
    store: Store, *, session_id: str, consumer_assignment_id: str,
    manager_epoch: int, decision_id: str, request_digest: str,
    decision: dict[str, Any], results: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    """Commit an immutable consumer-scoped receipt set and its decision together.

    Each result is (message_id, digest). An exact replay is read-only.
    A different digest or decision for an existing id is a conflict.
    """
    if not results or not all((message_id and digest) for message_id, digest in results):
        raise ValueError("RESULTS_REQUIRED")
    if len({message_id for message_id, _ in results}) != len(results):
        raise ValueError("DUPLICATE_RESULT")
    if not all((session_id, consumer_assignment_id, decision_id, request_digest)):
        raise ValueError("IDENTIFIERS_REQUIRED")
    payload = json.dumps(decision, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with store.transaction() as db:
        session = db.execute(
            "SELECT manager_epoch FROM orchestration_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise KeyError("SESSION_NOT_FOUND")
        if session["manager_epoch"] != manager_epoch:
            raise ConflictError("STALE_MANAGER_EPOCH")
        assignment = db.execute(
            "SELECT session_id FROM orchestration_assignments WHERE assignment_id=?",
            (consumer_assignment_id,),
        ).fetchone()
        if assignment is None or assignment["session_id"] != session_id:
            raise ConflictError("CONSUMER_ASSIGNMENT_MISMATCH")

        old = db.execute(
            "SELECT * FROM orchestration_consumption_decisions WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if old is not None and (
            old["session_id"] != session_id
            or old["consumer_assignment_id"] != consumer_assignment_id
            or old["manager_epoch"] != manager_epoch
            or old["request_digest"] != request_digest
            or old["decision_json"] != payload
        ):
            raise ConflictError("DECISION_CONFLICT")

        for message_id, digest in results:
            source = db.execute(
                "SELECT session_id,kind,message_digest,assignment_id,assignment_generation,"
                "sender_node_id,payload_json FROM orchestration_mailbox WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if (source is None or source["session_id"] != session_id
                    or source["kind"] != "RESULT" or source["message_digest"] != digest):
                raise ConflictError("RESULT_NOT_VERIFIED")
            source_id = source["assignment_id"]
            generation = source["assignment_generation"]
            sender = source["sender_node_id"]
            if (not source_id or type(generation) is not int or generation < 1
                    or not sender):
                raise ConflictError("RESULT_PROVENANCE_MISSING")
            origin = db.execute(
                "SELECT session_id,current_generation,state,terminal_result_json "
                "FROM orchestration_assignments WHERE assignment_id=?", (source_id,),
            ).fetchone()
            attempt = db.execute(
                "SELECT worker_node_id,state FROM orchestration_assignment_attempts "
                "WHERE assignment_id=? AND generation=?", (source_id, generation),
            ).fetchone()
            if (origin is None or origin["session_id"] != session_id
                    or origin["current_generation"] != generation
                    or attempt is None or attempt["worker_node_id"] != sender
                    or attempt["state"] not in {"APPLIED", "FAILED", "UNKNOWN", "NOT_APPLIED"}
                    or origin["state"] not in {"APPLIED", "FAILED", "UNKNOWN", "NOT_APPLIED"}):
                raise ConflictError("RESULT_PROVENANCE_MISMATCH")
            try:
                source_payload = json.loads(source["payload_json"])
                valid_digest = _digest(source_payload) == digest
                valid_terminal = _canonical(source_payload) == _canonical(
                    json.loads(origin["terminal_result_json"]))
            except (TypeError, ValueError, OverflowError):
                raise ConflictError("RESULT_PAYLOAD_INVALID") from None
            if not valid_digest or not valid_terminal:
                raise ConflictError("RESULT_INTEGRITY_MISMATCH")
            prior = db.execute(
                "SELECT * FROM orchestration_consumption_receipts "
                "WHERE session_id=? AND consumer_assignment_id=? AND result_message_id=?",
                (session_id, consumer_assignment_id, message_id),
            ).fetchone()
            if prior is not None and (
                prior["result_digest"] != digest or prior["decision_id"] != decision_id
                or prior["manager_epoch"] != manager_epoch
            ):
                raise ConflictError("CONSUMPTION_CONFLICT")
            if old is not None and prior is None:
                raise ConflictError("DECISION_RESULT_SET_CONFLICT")

        if old is not None:
            count = db.execute(
                "SELECT COUNT(*) FROM orchestration_consumption_receipts WHERE decision_id=?",
                (decision_id,),
            ).fetchone()[0]
            if count != len(results):
                raise ConflictError("DECISION_RESULT_SET_CONFLICT")
            return {"decision_id": decision_id, "idempotent": True, "results": count}

        now = _current_time()
        db.execute(
            "INSERT INTO orchestration_consumption_decisions "
            "(decision_id,session_id,consumer_assignment_id,manager_epoch,"
            "request_digest,decision_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (decision_id, session_id, consumer_assignment_id, manager_epoch,
             request_digest, payload, now),
        )
        for message_id, digest in results:
            db.execute(
                "INSERT INTO orchestration_consumption_receipts "
                "(session_id,consumer_assignment_id,result_message_id,result_digest,"
                "manager_epoch,decision_id,created_at) VALUES(?,?,?,?,?,?,?)",
                (session_id, consumer_assignment_id, message_id, digest,
                 manager_epoch, decision_id, now),
            )
        return {"decision_id": decision_id, "idempotent": False, "results": len(results)}
