"""PR1-only atomic result consumption; not wired into existing chain."""
from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from time import time as _current_time
from collections.abc import Sequence
from typing import Any

from .models import ConflictError
from .orchestration import _canonical, _digest
from .store import Store


def _verify_reconciled_result(db, *, session, session_id: str, manager_epoch: int,
                              source_id: str, generation: int, message_id: str,
                              digest: str, payload: Any, origin, attempt) -> None:
    """Authorize only an exact, immutable Schema 2 RCC reconciliation.

    A mailbox kind alone is not authority to promote an UNKNOWN delivery:
    the single persisted reconciliation, its original operation, worker
    provenance, terminal state and canonical payload must all agree.
    """
    if (session["wake_receipt_mode"] != "RCC_RESULT_POLL_V1"
            or not isinstance(payload, dict) or payload.get("reconciled") is not True
            or origin["state"] not in {"APPLIED", "FAILED"}
            or attempt["state"] != origin["state"]
            or attempt["manager_epoch"] != manager_epoch):
        raise ConflictError("RECONCILED_RESULT_PROVENANCE_MISMATCH")
    proofs = db.execute(
        "SELECT decision_id,evidence_json FROM orchestration_reconciliations "
        "WHERE session_id=? AND assignment_id=? AND generation=? "
        "AND manager_epoch=? AND decision='IMPORT_EXACT_RCC_RESULT'",
        (session_id, source_id, generation, manager_epoch),
    ).fetchall()
    if len(proofs) != 1:
        raise ConflictError("RECONCILED_RESULT_PROOF_NOT_UNIQUE")
    try:
        evidence = json.loads(proofs[0]["evidence_json"])
    except (TypeError, ValueError, OverflowError):
        raise ConflictError("RECONCILED_RESULT_PROOF_INVALID") from None
    if not isinstance(evidence, dict) or set(evidence) != {
            "original_operation_id", "result_message_id", "result_digest",
    }:
        raise ConflictError("RECONCILED_RESULT_PROOF_INVALID")
    original_id = evidence["original_operation_id"]
    if not isinstance(original_id, str) or not 1 <= len(original_id) <= 96:
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_INVALID")
    expected_proof_id = "result." + hashlib.sha256(
        f"{original_id}:{source_id}:{generation}".encode("utf-8")
    ).hexdigest()[:32]
    if (proofs[0]["decision_id"] != expected_proof_id
            or evidence["result_message_id"] != message_id
            or evidence["result_digest"] != digest):
        raise ConflictError("RECONCILED_RESULT_PROOF_MISMATCH")
    original = db.execute(
        "SELECT work_id,assignment_epoch,capability,target,state,outcome,"
        "evidence_json,error FROM operations WHERE operation_id=?", (original_id,),
    ).fetchone()
    if (original is None or original["work_id"] != session["work_id"]
            or original["assignment_epoch"] != session["work_assignment_epoch"]
            or original["capability"] != "orchestrate"
            or original["target"] != session_id
            or original["state"] != "FINISHED"):
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_FENCED")

    # The exact claim remains in the store even after a proven recovery
    # releases it; do not require unresolved=1 for a historical receipt.
    claim = db.execute(
        "SELECT operation_id,work_id,assignment_epoch FROM resource_claims "
        "WHERE resource_key=?",
        ("orchestration-run:" + session_id + ":" + source_id,),
    ).fetchone()
    if (claim is None or claim["operation_id"] != original_id
            or claim["work_id"] != session["work_id"]
            or claim["assignment_epoch"] != session["work_assignment_epoch"]):
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_CLAIM_MISMATCH")

    # Chains cannot borrow an arbitrary same-session Assignment: the original
    # chain's immutable PLAN must bind that Assignment, even after a resume.
    plan_id = "plan." + hashlib.sha256(
        f"{session_id}:{original_id}".encode("utf-8")
    ).hexdigest()[:32]
    plan_row = db.execute(
        "SELECT message_digest,payload_json FROM orchestration_mailbox "
        "WHERE message_id=? AND session_id=? AND kind='PLAN'",
        (plan_id, session_id),
    ).fetchone()
    if plan_row is not None:
        try:
            plan = json.loads(plan_row["payload_json"])
            included = (
                [task.get("assignment_id") for task in plan["tasks"]]
                + [plan["synthesis"]["assignment_id"]]
            )
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            raise ConflictError("RECONCILED_RESULT_CHAIN_PLAN_INVALID") from None
        if (not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list)
                or not isinstance(plan.get("synthesis"), dict)
                or _digest(plan) != plan_row["message_digest"]
                or included.count(source_id) != 1):
            raise ConflictError("RECONCILED_RESULT_CHAIN_PLAN_MISMATCH")

    try:
        original_evidence = json.loads(original["evidence_json"])
    except (TypeError, ValueError, OverflowError):
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_INVALID") from None
    if not isinstance(original_evidence, dict):
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_INVALID")

    if original_evidence.get("phase") == "ORCHESTRATION_RECOVERED":
        # The atomic resolver legitimately changes an UNKNOWN original to
        # APPLIED/FAILED. Verify the exact resolver and its immutable event,
        # rather than rejecting the successful persisted recovery.
        resolver_id = original_evidence.get("resolver_operation_id")
        recovered = original_evidence.get("recovered_outcome")
        if (not isinstance(resolver_id, str) or not resolver_id
                or recovered not in {"APPLIED", "FAILED"}
                or original["outcome"] != recovered):
            raise ConflictError("RECONCILED_RESULT_RECOVERY_OUTCOME_MISMATCH")
        resolver = db.execute(
            "SELECT work_id,assignment_epoch,capability,target,state,outcome,"
            "evidence_json FROM operations WHERE operation_id=?", (resolver_id,),
        ).fetchone()
        if (resolver is None or resolver["work_id"] != original["work_id"]
                or resolver["assignment_epoch"] != original["assignment_epoch"]
                or resolver["capability"] != "orchestrate"
                or resolver["target"] != session_id
                or resolver["state"] != "FINISHED"
                or resolver["outcome"] != recovered):
            raise ConflictError("RECONCILED_RESULT_RESOLVER_FENCED")
        try:
            resolved = json.loads(resolver["evidence_json"])
        except (TypeError, ValueError, OverflowError):
            raise ConflictError("RECONCILED_RESULT_RESOLVER_INVALID") from None
        if not isinstance(resolved, dict) or resolved.get("session_id") != session_id:
            raise ConflictError("RECONCILED_RESULT_RESOLVER_BINDING_MISMATCH")
        if resolved.get("operation") == "reconcile":
            if (recovered != origin["state"]
                    or resolved.get("assignment_id") != source_id
                    or resolved.get("result_message_id") != message_id
                    or plan_row is not None):
                raise ConflictError("RECONCILED_RESULT_RESOLVER_BINDING_MISMATCH")
        elif resolved.get("operation") == "chain-resume":
            # The chain's aggregate outcome is not necessarily the terminal
            # state of this Worker. The exact PLAN+claim bind the producer.
            # Require the final session state and aggregate verdict as well.
            if (plan_row is None
                    or resolved.get("session_state") not in {"FINISHED", "PARTIAL"}
                    or session["state"] != resolved["session_state"]
                    or recovered != (
                        "APPLIED" if resolved["session_state"] == "FINISHED"
                        else "FAILED"
                    )):
                raise ConflictError("RECONCILED_RESULT_CHAIN_RESUME_MISMATCH")
        else:
            raise ConflictError("RECONCILED_RESULT_RESOLVER_BINDING_MISMATCH")
        events = db.execute(
            "SELECT data_json FROM events WHERE kind='OPERATION_RECONCILED' "
            "AND subject_id=?", (original_id,),
        ).fetchall()
        matched = 0
        for event in events:
            try:
                data = json.loads(event["data_json"])
            except (TypeError, ValueError, OverflowError):
                continue
            if (isinstance(data, dict)
                    and data.get("resolver_operation_id") == resolver_id
                    and data.get("original_outcome") == recovered
                    and data.get("resolved_outcome") == recovered):
                matched += 1
        if matched != 1:
            raise ConflictError("RECONCILED_RESULT_RESOLVER_EVENT_MISMATCH")
        return

    if original["outcome"] != "UNKNOWN":
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_FENCED")
    if original_evidence.get("phase") == "ORCHESTRATION_RECOVERY_TAKEOVER":
        assignments = original_evidence.get("assignment_ids")
        if (original["error"] != "ORCHESTRATION_RECOVERY_TAKEOVER"
                or original_evidence.get("session_id") != session_id
                or not isinstance(assignments, list)
                or any(not isinstance(item, str) for item in assignments)
                or assignments.count(source_id) != 1):
            raise ConflictError("RECONCILED_RESULT_TAKEOVER_MISMATCH")
        takeover_events = db.execute(
            "SELECT data_json FROM events "
            "WHERE kind='ORCHESTRATION_RECOVERY_TAKEOVER' AND subject_id=?",
            (original_id,),
        ).fetchall()
        if len(takeover_events) != 1:
            raise ConflictError("RECONCILED_RESULT_TAKEOVER_EVENT_MISSING")
        try:
            recorded = json.loads(takeover_events[0]["data_json"])
        except (TypeError, ValueError, OverflowError):
            raise ConflictError("RECONCILED_RESULT_TAKEOVER_EVENT_INVALID") from None
        if recorded != {"session_id": session_id, "assignment_ids": assignments}:
            raise ConflictError("RECONCILED_RESULT_TAKEOVER_EVENT_MISMATCH")
        # A takeover does not erase the original PLAN; it still must fence
        # the exact chain membership whenever a chain plan exists.
        return
    operation = original_evidence.get("operation")
    if original_evidence.get("session_id") != session_id:
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_FENCED")
    if operation == "dispatch":
        if original_evidence.get("assignment_id") != source_id:
            raise ConflictError("RECONCILED_RESULT_DISPATCH_ASSIGNMENT_MISMATCH")
        if plan_row is not None:
            raise ConflictError("RECONCILED_RESULT_DISPATCH_PLAN_CONFLICT")
    elif operation in {"chain-run", "chain-resume"}:
        if plan_row is None:
            raise ConflictError("RECONCILED_RESULT_CHAIN_PLAN_MISSING")
        if ("assignment_id" in original_evidence
                and original_evidence["assignment_id"] != source_id):
            raise ConflictError("RECONCILED_RESULT_CHAIN_ASSIGNMENT_MISMATCH")
    else:
        raise ConflictError("RECONCILED_RESULT_ORIGINAL_FENCED")


def commit_consumption_decision(
    store: Store, *, session_id: str, consumer_assignment_id: str,
    manager_epoch: int, decision_id: str, request_digest: str,
    decision: dict[str, Any], results: Sequence[tuple[str, str]], _db=None,
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
    with (store.transaction() if _db is None else nullcontext(_db)) as db:
        session = db.execute(
            "SELECT manager_epoch,work_id,work_assignment_epoch,wake_receipt_mode,state "
            "FROM orchestration_sessions WHERE session_id=?",
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
                    or source["kind"] not in {"RESULT", "RECONCILED_RESULT"}
                    or source["message_digest"] != digest):
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
                "SELECT worker_node_id,state,manager_epoch FROM orchestration_assignment_attempts "
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
            if source["kind"] == "RECONCILED_RESULT":
                _verify_reconciled_result(
                    db, session=session, session_id=session_id,
                    manager_epoch=manager_epoch, source_id=source_id,
                    generation=generation, message_id=message_id,
                    digest=digest, payload=source_payload, origin=origin,
                    attempt=attempt,
                )
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
