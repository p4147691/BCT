"""Receipt-only Manager decision consumption for Durable Orchestration PR B.

RCC I/O is deliberately outside the authoritative SQLite transaction.  Both a
future trusted event trigger and the bounded recovery poller call the same
``consume_receipt`` boundary below.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from .consumption import verified_finished_chain_wake
from .durable_pr2 import _lease, commit_and_enqueue
from .models import ConflictError, PreconditionError, Work
from .orchestration import OrchestrationService, _canonical, _digest
from .rcc_result import rcc_result_hash


DECISION_SCHEMA = "BCT_ORCHESTRATION_MANAGER_DECISION_V1"
DECISION_START = "[BCT_ORCHESTRATION_MANAGER_DECISION_V1]"
DECISION_END = "[/BCT_ORCHESTRATION_MANAGER_DECISION_V1]"
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_WAKE_STATES_WITH_POSSIBLE_RESULT = ("DELIVERING", "DELIVERED", "UNKNOWN")


def _identifier(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PreconditionError(code)
    return value


def _bounded_string(value: Any, *, code: str, limit: int) -> str:
    if not isinstance(value, str):
        raise PreconditionError(code)
    result = value.strip()
    if not result or len(result) > limit:
        raise PreconditionError(code)
    return result


def _exact_keys(value: dict[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise PreconditionError(code)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError("NON_FINITE_JSON_NUMBER:" + value)


def parse_manager_decision(reply: Any, *, expected: dict[str, Any]) -> dict[str, Any]:
    """Parse one exact, authority-free Manager decision envelope."""
    if not isinstance(reply, str) or len(reply) > 65_536:
        raise PreconditionError("MANAGER_DECISION_REPLY_INVALID")
    stripped = reply.strip()
    if not stripped.startswith(DECISION_START) or not stripped.endswith(DECISION_END):
        raise PreconditionError("MANAGER_DECISION_MARKER_INVALID")
    if stripped.count(DECISION_START) != 1 or stripped.count(DECISION_END) != 1:
        raise PreconditionError("MANAGER_DECISION_MARKER_DUPLICATE")
    raw = stripped[len(DECISION_START):-len(DECISION_END)]
    try:
        value = json.loads(
            raw, object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        raise PreconditionError("MANAGER_DECISION_JSON_INVALID") from None
    if not isinstance(value, dict):
        raise PreconditionError("MANAGER_DECISION_OBJECT_REQUIRED")
    _exact_keys(value, {
        "schema", "event_id", "session_id", "manager_epoch",
        "result_message_id", "result_digest", "kind",
        "summary", "successors",
    }, "MANAGER_DECISION_FIELDS_INVALID")
    if value["schema"] != DECISION_SCHEMA:
        raise PreconditionError("MANAGER_DECISION_SCHEMA_INVALID")
    for field in ("event_id", "session_id", "result_message_id"):
        _identifier(value[field], "MANAGER_DECISION_BINDING_INVALID:" + field)
        if value[field] != expected[field]:
            raise ConflictError("MANAGER_DECISION_BINDING_MISMATCH:" + field)
    if isinstance(value["manager_epoch"], bool) or not isinstance(value["manager_epoch"], int):
        raise PreconditionError("MANAGER_DECISION_EPOCH_INVALID")
    if value["manager_epoch"] != expected["manager_epoch"]:
        raise ConflictError("MANAGER_DECISION_BINDING_MISMATCH:manager_epoch")
    for field in ("result_digest",):
        if not isinstance(value[field], str) or not _HASH.fullmatch(value[field]):
            raise PreconditionError("MANAGER_DECISION_HASH_INVALID:" + field)
        if value[field] != expected[field]:
            raise ConflictError("MANAGER_DECISION_BINDING_MISMATCH:" + field)
    if value["kind"] not in {"COMPLETE", "FOLLOW_UP"}:
        raise PreconditionError("MANAGER_DECISION_KIND_INVALID")
    value["summary"] = _bounded_string(
        value["summary"], code="MANAGER_DECISION_SUMMARY_INVALID", limit=2000,
    )
    successors = value["successors"]
    if not isinstance(successors, list) or len(successors) > 8:
        raise PreconditionError("MANAGER_DECISION_SUCCESSORS_INVALID")
    if value["kind"] == "COMPLETE" and successors:
        raise PreconditionError("MANAGER_DECISION_COMPLETE_HAS_SUCCESSOR")
    if value["kind"] == "FOLLOW_UP" and not successors:
        raise PreconditionError("MANAGER_DECISION_FOLLOW_UP_EMPTY")
    normalized: list[dict[str, Any]] = []
    for successor in successors:
        if not isinstance(successor, dict):
            raise PreconditionError("MANAGER_DECISION_SUCCESSOR_INVALID")
        _exact_keys(successor, {
            "target_node_id", "attachment_id", "instruction", "roots",
            "actions", "acceptance", "dependencies",
        }, "MANAGER_DECISION_SUCCESSOR_FIELDS_INVALID")
        target_node_id = _identifier(
            successor["target_node_id"], "MANAGER_DECISION_TARGET_INVALID",
        )
        attachment_id = _identifier(
            successor["attachment_id"], "MANAGER_DECISION_ATTACHMENT_INVALID",
        )
        instruction = _bounded_string(
            successor["instruction"], code="MANAGER_DECISION_INSTRUCTION_INVALID",
            limit=8000,
        )
        roots = successor["roots"]
        actions = successor["actions"]
        dependencies = successor["dependencies"]
        acceptance = successor["acceptance"]
        if (not isinstance(roots, list) or not 1 <= len(roots) <= 16
                or any(not isinstance(item, str) or not item.strip() or len(item) > 512
                       for item in roots)):
            raise PreconditionError("MANAGER_DECISION_ROOTS_INVALID")
        if (not isinstance(actions, list) or not 1 <= len(actions) <= 16
                or any(not isinstance(item, str) or not _ID.fullmatch(item)
                       for item in actions)):
            raise PreconditionError("MANAGER_DECISION_ACTIONS_INVALID")
        if (not isinstance(dependencies, list) or len(dependencies) > 16
                or any(not isinstance(item, str) or not _ID.fullmatch(item)
                       for item in dependencies)):
            raise PreconditionError("MANAGER_DECISION_DEPENDENCIES_INVALID")
        if not isinstance(acceptance, dict) or len(_canonical(acceptance)) > 8000:
            raise PreconditionError("MANAGER_DECISION_ACCEPTANCE_INVALID")
        normalized.append({
            "target_node_id": target_node_id,
            "attachment_id": attachment_id,
            "instruction": instruction,
            "roots": [item.strip() for item in roots],
            "actions": sorted(set(actions)),
            "acceptance": acceptance,
            "dependencies": sorted(set(dependencies)),
        })
    value["successors"] = normalized
    return value


def _receipt_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "failureEvidence": receipt.get("failureEvidence"),
        "ok": receipt.get("ok") is True,
        "reply": receipt.get("reply"),
        "error": receipt.get("error"),
        "ambiguous": receipt.get("ambiguous") is True,
    }


def _verified_receipt(event: Any, receipt: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(receipt, dict):
        raise PreconditionError("MANAGER_RESULT_RECEIPT_INVALID")
    exact = {
        "id": event["delivery_id"],
        "from": event["relay_role"],
        "messageHash": event["result_digest"],
        "targetBindingReceipt": event["binding_receipt_id"] or "",
        "instanceId": event["instance_id"],
        "sessionId": event["external_session_id"],
        "attachmentGeneration": event["attachment_generation"],
        "tabId": event["tab_id"],
        "conversationKey": event["conversation_key"],
        "resultState": "RESULT_PERSISTED",
    }
    for field, expected in exact.items():
        actual = receipt.get(field)
        if field in {"attachmentGeneration", "tabId"}:
            if isinstance(actual, bool) or not isinstance(actual, int):
                raise ConflictError("MANAGER_RESULT_BINDING_MISMATCH:" + field)
        if actual != expected:
            raise ConflictError("MANAGER_RESULT_BINDING_MISMATCH:" + field)
    if receipt.get("ok") is not True or receipt.get("ambiguous") is True:
        raise PreconditionError("MANAGER_RESULT_NOT_SUCCESSFUL")
    result_hash = receipt.get("resultHash")
    if not isinstance(result_hash, str) or not _HASH.fullmatch(result_hash):
        raise PreconditionError("MANAGER_RESULT_HASH_INVALID")
    if rcc_result_hash(_receipt_payload(receipt)) != result_hash:
        raise ConflictError("MANAGER_RESULT_HASH_MISMATCH")
    return receipt, result_hash


class ManagerDecisionConsumer:
    """The single Core authority used by polling and future event triggers."""

    def __init__(self, service: OrchestrationService):
        self.service = service
        self.store = service.store

    def consume_receipt(
        self, *, work: Work, event_id: str, manager_epoch: int,
        lease_token: str, receipt: dict[str, Any], now: float | None = None,
        recovery_fence: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        db = self.store._connect()
        try:
            event = db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise KeyError("MANAGER_WAKE_NOT_FOUND")
            receipt, result_hash = _verified_receipt(event, receipt)
        finally:
            db.close()
        expected = {
            "event_id": event_id,
            "session_id": str(event["session_id"]),
            "manager_epoch": int(event["manager_epoch"]),
            "result_message_id": str(event["result_message_id"]),
            "result_digest": str(event["result_digest"]),
        }
        decision = parse_manager_decision(receipt["reply"], expected=expected)
        policy_actions = [
            action
            for successor in decision["successors"]
            for action in successor["actions"]
        ]
        decision_id = "mgr.decision." + hashlib.sha256(
            f"{event_id}:{result_hash}".encode("utf-8")
        ).hexdigest()[:40]
        request_digest = _digest({"event_id": event_id, "result_hash": result_hash})
        successor_ids = [
            "mgr.next." + hashlib.sha256(
                f"{decision_id}:{index}".encode("utf-8")
            ).hexdigest()[:32]
            for index in range(len(decision["successors"]))
        ]
        actions: list[dict[str, Any]] = []
        with self.store.transaction() as tx:
            # Do not carry the pre-I/O timestamp into the authoritative write.
            # A supplied future time remains useful for deterministic recovery
            # tests, while wall time always wins after a long RCC lookup.
            commit_now = max(now, time.time())
            if recovery_fence is not None:
                recovery_owner, recovery_token = recovery_fence
                recovery_lease = tx.execute(
                    "SELECT owner_id,token,expires_at FROM "
                    "orchestration_manager_recovery_leases "
                    "WHERE lease_name='manager-decision-poller'",
                ).fetchone()
                if (recovery_lease is None
                        or str(recovery_lease["owner_id"]) != recovery_owner
                        or str(recovery_lease["token"]) != recovery_token
                        or float(recovery_lease["expires_at"]) <= commit_now):
                    raise ConflictError("MANAGER_RECOVERY_POLLER_FENCED")
            current = tx.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if current is None:
                raise KeyError("MANAGER_WAKE_NOT_FOUND")
            if (int(current["envelope_schema"]), str(current["receipt_mode"])) != (
                2, "RCC_RESULT_POLL_V1",
            ):
                raise ConflictError("MANAGER_WAKE_NOT_RECEIPT_V2")
            if current["state"] not in _WAKE_STATES_WITH_POSSIBLE_RESULT:
                raise ConflictError("MANAGER_WAKE_RESULT_NOT_EXPECTED")
            _, current_hash = _verified_receipt(current, receipt)
            current_expected = {
                "event_id": event_id,
                "session_id": str(current["session_id"]),
                "manager_epoch": int(current["manager_epoch"]),
                "result_message_id": str(current["result_message_id"]),
                "result_digest": str(current["result_digest"]),
            }
            current_decision = parse_manager_decision(
                receipt["reply"], expected=current_expected,
            )
            if current_hash != result_hash or _canonical(current_decision) != _canonical(decision):
                raise ConflictError("MANAGER_RESULT_CHANGED_DURING_COMMIT")
            session = self.service._session_row(tx, str(current["session_id"]))
            if session["state"] == "FINISHED":
                if (session["work_id"] != work.work_id
                        or session["work_assignment_epoch"] != work.assignment_epoch
                        or not verified_finished_chain_wake(tx, current)):
                    raise ConflictError("MANAGER_FINISHED_CHAIN_WAKE_NOT_PROVEN")
            else:
                self.service._assert_work(session, work)
            self.service._assert_current_work_assignment(tx, work)
            self.service.assert_manager_wake_receipt_v2_session(
                str(current["session_id"]), _db=tx,
            )
            if int(session["manager_epoch"]) != manager_epoch or int(current["manager_epoch"]) != manager_epoch:
                raise ConflictError("STALE_MANAGER_EPOCH")
            lease = _lease(
                tx, str(current["session_id"]), manager_epoch, lease_token, commit_now,
            )
            if str(lease["manager_node_id"]) != str(session["manager_node_id"] or ""):
                raise ConflictError("MANAGER_LEASE_OWNER_MISMATCH")
            attachment = self.service._manager_attachment_row(
                tx, session_id=str(current["session_id"]),
                manager_node_id=str(session["manager_node_id"] or ""),
            )
            if attachment is None or any((
                str(attachment["attachment_id"]) != str(current["attachment_id"]),
                int(attachment["generation"]) != int(current["attachment_generation"]),
                str(attachment["instance_id"]) != str(current["instance_id"]),
                str(attachment["external_session_id"]) != str(current["external_session_id"]),
                int(attachment["tab_id"]) != int(current["tab_id"]),
                str(attachment["conversation_key"]) != str(current["conversation_key"]),
                str(attachment["binding_receipt_id"] or "")
                != str(current["binding_receipt_id"] or ""),
            )):
                raise ConflictError("MANAGER_ATTACHMENT_FENCED")
            if current["decision_id"] not in {None, decision_id}:
                raise ConflictError("MANAGER_WAKE_DECISION_CONFLICT")
            if current["result_hash"] not in {None, result_hash}:
                raise ConflictError("MANAGER_WAKE_RESULT_CONFLICT")
            if policy_actions and current["decision_id"] is None:
                self.service.assert_current_unattended_policy(policy_actions)
                # A Manager receipt has no Principal of its own. Recheck the
                # current outer grant before it can enqueue autonomous work.
                self.service.assert_current_unattended_orchestration_policy(work)

            for index, successor in enumerate(decision["successors"]):
                assignment_id = successor_ids[index]
                request = {
                    "instruction": successor["instruction"],
                    "source_event_id": event_id,
                    "source_result_hash": result_hash,
                }
                self.service.create_assignment(
                    work=work, session_id=str(current["session_id"]),
                    assignment_id=assignment_id, manager_epoch=manager_epoch,
                    worker_node_id=successor["target_node_id"],
                    attachment_id=successor["attachment_id"], request=request,
                    roots=successor["roots"], actions=successor["actions"],
                    acceptance=successor["acceptance"],
                    dependencies=successor["dependencies"], _db=tx,
                )
                attempt = tx.execute(
                    "SELECT * FROM orchestration_assignment_attempts "
                    "WHERE assignment_id=? AND generation=1", (assignment_id,),
                ).fetchone()
                if attempt is None or str(attempt["worker_node_id"]) != successor["target_node_id"]:
                    raise ConflictError("SUCCESSOR_ASSIGNMENT_MISMATCH")
                delivery_id = "mgr.dispatch." + hashlib.sha256(
                    f"{decision_id}:{index}".encode("utf-8")
                ).hexdigest()[:32]
                actions.append({
                    "delivery_id": delivery_id,
                    "target_node_id": successor["target_node_id"],
                    "attachment_id": successor["attachment_id"],
                    "attachment_generation": int(attempt["attachment_generation"]),
                    "assignment_id": assignment_id,
                    "assignment_generation": 1,
                    "payload": {
                        "schema": "BCT_ORCHESTRATION_DISPATCH_V1",
                        "session_id": str(current["session_id"]),
                        "manager_epoch": manager_epoch,
                        "assignment_id": assignment_id,
                        "instruction": successor["instruction"],
                        "roots": successor["roots"],
                        "actions": successor["actions"],
                        "acceptance": successor["acceptance"],
                        "dependencies": successor["dependencies"],
                    },
                })
            persisted_decision = {
                **decision,
                "successor_assignment_ids": successor_ids,
            }
            result = commit_and_enqueue(
                self.store, session_id=str(current["session_id"]),
                consumer_assignment_id=str(current["assignment_id"]),
                manager_epoch=manager_epoch, lease_token=lease_token,
                decision_id=decision_id, request_digest=request_digest,
                decision=persisted_decision,
                results=[(str(current["result_message_id"]), str(current["result_digest"]))],
                actions=actions, now=commit_now, _db=tx,
            )
            if result["idempotent"]:
                if (current["decision_id"] != decision_id
                        or current["result_hash"] != result_hash
                        or current["acknowledged_at"] is None
                        or current["result_ack_state"] not in {"PENDING", "ACKED"}):
                    raise ConflictError("MANAGER_WAKE_REPLAY_INCOMPLETE")
            else:
                changed = tx.execute(
                    "UPDATE orchestration_manager_wakes SET decision_id=?,result_hash=?,"
                    "acknowledged_at=?,result_ack_state='PENDING',updated_at=? "
                    "WHERE event_id=? AND decision_id IS NULL AND result_hash IS NULL",
                    (decision_id, result_hash, commit_now, commit_now, event_id),
                ).rowcount
                if changed != 1:
                    raise ConflictError("MANAGER_WAKE_COMMIT_CONFLICT")
            committed_wake = tx.execute(
                "SELECT result_ack_state FROM orchestration_manager_wakes WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if not result["idempotent"]:
                self.store._event(tx, "ORCHESTRATION_MANAGER_DECISION_COMMITTED", decision_id, {
                    "event_id": event_id, "kind": decision["kind"],
                    "successors": len(successor_ids), "result_hash": result_hash,
                })
            return {
                **result, "event_id": event_id, "kind": decision["kind"],
                "successor_assignment_ids": successor_ids,
                "result_hash": result_hash,
                "result_ack_state": str(committed_wake["result_ack_state"]),
            }

    def mark_result_acknowledged(
        self, *, event_id: str, result_hash: str, now: float | None = None,
    ) -> bool:
        now = time.time() if now is None else now
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT decision_id,result_hash,result_ack_state FROM "
                "orchestration_manager_wakes WHERE event_id=?", (event_id,),
            ).fetchone()
            if row is None or not row["decision_id"] or row["result_hash"] != result_hash:
                raise ConflictError("MANAGER_RESULT_ACK_BINDING_MISMATCH")
            if row["result_ack_state"] == "ACKED":
                return False
            if row["result_ack_state"] != "PENDING":
                raise ConflictError("MANAGER_RESULT_ACK_NOT_PENDING")
            db.execute(
                "UPDATE orchestration_manager_wakes SET result_ack_state='ACKED',"
                "result_acknowledged_at=?,updated_at=? WHERE event_id=?",
                (now, now, event_id),
            )
            return True
