"""Durable Loop acceptance result and optional exact requester delivery.

The requester is a correlation reference, not implicitly a browser UUID. By
default the result is available for the calling dot to read and report. Only
an explicitly configured, fresh RCC conversation enables a browser send.
Acceptance, transport delivery and user notification are separate facts.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from bct.core.capabilities import capability_matches
from bct.core.models import Principal
from bct.loop_self_dispatch import LoopSelfDispatcher
from bct.loop_store import LoopStateError
from bct.node_recovery import NodeRecoveryLedger
from bct.send_delayed_message import _rcc_submitted_text_sha256

_UUID = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")


class LoopResultLedger:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS loop_result_reports(
                work_id TEXT PRIMARY KEY, requester_ref TEXT NOT NULL DEFAULT '',
                conversation_key TEXT, state TEXT NOT NULL,
                result_json TEXT, message_text TEXT, message_sha256 TEXT,
                operation_id TEXT UNIQUE, route_json TEXT, last_error TEXT,
                updated_at REAL NOT NULL)""")

    @staticmethod
    def _get(db, work_id):
        row = db.execute("SELECT * FROM loop_result_reports WHERE work_id=?", (work_id,)).fetchone()
        return dict(row) if row else None

    def get(self, work_id):
        with self.store._readonly() as db:
            row = self._get(db, work_id)
        if row:
            row["result"] = json.loads(row.pop("result_json") or "null")
            row["delivery_mode"] = "RCC_CONVERSATION" if row["conversation_key"] else "REQUESTER_PULL"
        return row

    @staticmethod
    def _target_allowed(db, work_id, target):
        loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
        if not loop:
            raise LoopStateError("LOOP_NOT_FOUND")
        forbidden = {loop["owner"]}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='loop_review_handoffs'").fetchone():
            review = db.execute("SELECT owner,supervisor FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
            if review:
                forbidden.update(review)
        if target in forbidden:
            raise LoopStateError("LOOP_RESULT_SELF_RETURN_FORBIDDEN")
        return loop

    def configure(self, *, work_id, owner, requester_ref, conversation_key=None, snapshot=None):
        """Bind an explicit requester once; a missing transport stays pull-only.

        This does not infer that requester_ref is an address, or verify an
        external dot's ownership. The caller must supply the actual origin.
        """
        if not isinstance(requester_ref, str) or not requester_ref.strip() or len(requester_ref) > 240:
            raise LoopStateError("LOOP_REQUESTER_REFERENCE_REQUIRED")
        if conversation_key is not None:
            if not _UUID.fullmatch(conversation_key):
                raise LoopStateError("LOOP_REQUESTER_UUID_INVALID")
            LoopSelfDispatcher.exact_route(snapshot or {}, conversation_key, require_idle=False)
        with self.store.transaction() as db:
            loop = self._target_allowed(db, work_id, conversation_key)
            if loop["owner"] != owner:
                raise LoopStateError("LOOP_RESULT_OWNER_CHANGED")
            row = self._get(db, work_id)
            if row and row["requester_ref"]:
                if (row["requester_ref"], row["conversation_key"]) != (requester_ref, conversation_key):
                    raise LoopStateError("LOOP_REQUESTER_BINDING_CONFLICT")
                return self.get(work_id)
            now = time.time()
            if row:
                # A legacy accepted result may be bound once, before any send.
                if row["state"] != "READY_FOR_REQUESTER":
                    raise LoopStateError("LOOP_REQUESTER_BINDING_CONFLICT")
                db.execute("UPDATE loop_result_reports SET requester_ref=?,conversation_key=?,state=?,updated_at=? WHERE work_id=?",
                    (requester_ref, conversation_key, "PENDING" if conversation_key else row["state"], now, work_id))
            else:
                db.execute("INSERT INTO loop_result_reports(work_id,requester_ref,conversation_key,state,updated_at) VALUES(?,?,?,'WAITING_ACCEPTANCE',?)",
                    (work_id, requester_ref, conversation_key, now))
        return self.get(work_id)

    @staticmethod
    def record_acceptance(db, *, loop, review, context, return_operation_id, now):
        """Run atomically inside the independently verified acceptance transition."""
        work_id = loop["work_id"]
        if LoopResultLedger._get(db, work_id) is None:
            db.execute("INSERT INTO loop_result_reports(work_id,state,updated_at) VALUES(?,'WAITING_ACCEPTANCE',?)", (work_id, now))
        row = LoopResultLedger._get(db, work_id)
        result = {
            "acceptance": "ACCEPTED", "work_id": work_id,
            "direction_id": loop["direction_id"], "task_id": loop["task_id"],
            "owner": loop["owner"], "supervisor": review["supervisor"],
            "candidate_sha": review["candidate_sha"],
            "review_task_id": review["task_id"],
            "review_response_sha256": context["decision"]["response_sha256"],
            "return_operation_id": return_operation_id,
            "summary": context["decision"]["payload"],
            "user_notification": "UNVERIFIED",
        }
        raw = json.dumps(result, sort_keys=True, ensure_ascii=False)
        if row["result_json"]:
            if row["result_json"] != raw:
                raise LoopStateError("LOOP_RESULT_ACCEPTANCE_CONFLICT")
            return
        message = ("[LOOP RESULT REPORT]\n"
            f"Work: {work_id}\nCandidate SHA: {review['candidate_sha']}\n"
            f"Independent Supervisor: {review['supervisor']}\n"
            f"Acceptance return Operation: {return_operation_id}\n\n"
            "Independent acceptance was recorded. This is a result report, not a continuation "
            "or authorization to execute further work. Delivery to this conversation does not "
            "prove the original user was notified.\n\n" + result["summary"])
        if len(message) > 12000:
            # Preserve the full pull result even when an RCC message is too large.
            message = message[:1000] + "\nThe full historical result remains in the retained Loop recovery record for work_id='" + work_id + "'."
        operation_id = "loop-result-" + hashlib.sha256((work_id+":"+review["operation_id"]).encode()).hexdigest()[:24]
        db.execute("""UPDATE loop_result_reports SET state=?,result_json=?,message_text=?,
            message_sha256=?,operation_id=?,updated_at=? WHERE work_id=?""",
            ("PENDING" if row["conversation_key"] else "READY_FOR_REQUESTER", raw, message,
             _rcc_submitted_text_sha256(message), operation_id, now, work_id))

    def recover_acceptance(self, work_id):
        """Materialize an older ACCEPTED review from its original proof, never send.

        Do not interpret legacy boolean completion as independent acceptance.
        A missing/changed return receipt leaves the historical result unverified.
        """
        existing = self.get(work_id)
        if existing and existing["result"]:
            return existing
        from bct.loop_supervisor_handoff import LoopReviewLedger
        from bct.send_delayed_message import DurableWatchLedger
        reviews = LoopReviewLedger(self.store)
        row = reviews.get(work_id)
        if not row or row["state"] != "ACCEPTED":
            return existing
        context = json.loads(row["response_json"] or "null")
        if not context:
            raise LoopStateError("LOOP_RESULT_ACCEPTANCE_PROOF_REQUIRED")
        observed = DurableWatchLedger(self.store).read_execution_context(task_id=row["task_id"], generation=context["generation"])
        if observed != context or not reviews._return_applied(row, context):
            raise LoopStateError("LOOP_RESULT_ACCEPTANCE_PROOF_REQUIRED")
        key = hashlib.sha256(f"{row['task_id']}|{context['generation']}|{context['response_turn_id']}".encode()).hexdigest()[:24]
        with self.store.transaction() as db:
            current = db.execute("SELECT * FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
            loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if (not current or dict(current) != row or not loop or loop["state"] != "COMPLETED"
                    or loop["owner"] != row["owner"] or loop["epoch"] != row["epoch"]):
                raise LoopStateError("LOOP_RESULT_ACCEPTANCE_PROOF_REQUIRED")
            self.record_acceptance(db, loop=loop, review=row, context=context,
                return_operation_id="delayed-manager-"+key, now=time.time())
        return self.get(work_id)

    def pending(self, limit=4):
        with self.store._readonly() as db:
            return [dict(row) for row in db.execute("SELECT * FROM loop_result_reports WHERE state IN ('PENDING','DISPATCHING','UNKNOWN') ORDER BY updated_at,work_id LIMIT ?", (limit,))]

    def reserve(self, *, work_id, route):
        with self.store.transaction() as db:
            row = self._get(db, work_id)
            if not row or row["state"] != "PENDING":
                raise LoopStateError("LOOP_RESULT_ALREADY_DISPATCHED")
            self._target_allowed(db, work_id, row["conversation_key"])
            if not row["conversation_key"] or route["conversation_key"] != row["conversation_key"]:
                raise LoopStateError("LOOP_RESULT_ROUTE_CHANGED")
            db.execute("UPDATE loop_result_reports SET state='DISPATCHING',route_json=?,updated_at=? WHERE work_id=?",
                (json.dumps(route, sort_keys=True), time.time(), work_id))
        return self.get(work_id)

    def reconcile(self, work_id):
        row = self.get(work_id)
        if not row or row["state"] not in {"DISPATCHING", "UNKNOWN"}:
            return row
        work = self.store.get_work(work_id)
        try:
            receipt = self.store.get_operation_for(operation_id=row["operation_id"], work_id=work_id, principal_id=work.owner_principal_id)
        except KeyError:
            receipt = None
        state, error = "UNKNOWN", "LOOP_RESULT_ORIGINAL_RECEIPT_REQUIRED"
        if receipt and receipt.state.value == "FINISHED" and receipt.outcome:
            if receipt.outcome.value == "NOT_APPLIED":
                state, error = "NOT_APPLIED", None
            elif receipt.outcome.value == "APPLIED":
                proof = receipt.evidence or {}
                route = json.loads(row["route_json"])
                if (proof.get("conversation_key") == row["conversation_key"]
                        and proof.get("source_message_sha256") == row["message_sha256"]
                        and proof.get("host_request_id") == row["operation_id"]
                        and proof.get("instance_id") == route["instance_id"]
                        and proof.get("command") == "send-to-tab"):
                    state, error = "DELIVERED_TO_CONVERSATION", None
                else:
                    error = "LOOP_RESULT_DELIVERY_PROOF_MISMATCH"
        with self.store.transaction() as db:
            db.execute("UPDATE loop_result_reports SET state=?,last_error=?,updated_at=? WHERE work_id=? AND state IN ('DISPATCHING','UNKNOWN')",
                (state, error, time.time(), work_id))
        return self.get(work_id)


class LoopResultDispatcher:
    def __init__(self, store, operations):
        self.store, self.operations = store, operations
        self.ledger = LoopResultLedger(store)

    def run_once(self, *, snapshot, limit=4):
        outcomes = []
        for row in self.ledger.pending(limit):
            work_id = row["work_id"]
            try:
                if row["state"] == "PENDING":
                    work = self.store.get_work(work_id)
                    if work.state != "ACTIVE" or not any(capability_matches(a, "browser") for a in work.actions):
                        raise LoopStateError("LOOP_RESULT_WORK_NOT_AUTHORIZED")
                    route = LoopSelfDispatcher.exact_route(snapshot, row["conversation_key"])
                    NodeRecoveryLedger(self.store).assert_send_allowed(work_id=work_id, conversation_key=row["conversation_key"])
                    reserved = self.ledger.reserve(work_id=work_id, route=route)
                    self.operations.run(principal=Principal(work.owner_principal_id, "loop-result-existing-work", frozenset({"browser"})),
                        work_id=work_id, operation_id=reserved["operation_id"], capability="browser",
                        arguments={"command":"send-message", **route, "text":reserved["message_text"]})
                result = self.ledger.reconcile(work_id)
                outcomes.append({"work_id":work_id,"state":result["state"],"operation_id":row["operation_id"]})
            except Exception as exc:
                # Rotate held rows so a busy first requester cannot starve other
                # ready reports. Reservation state and Operation ID never reset.
                with self.store.transaction() as db:
                    db.execute("UPDATE loop_result_reports SET last_error=?,updated_at=? WHERE work_id=?",
                        (str(exc)[:180], time.time(), work_id))
                outcomes.append({"work_id":work_id,"state":"HELD","reason":str(exc)[:180],"operation_id":row["operation_id"]})
        return outcomes
