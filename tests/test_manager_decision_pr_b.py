from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from bct.core.manager_decision import (
    DECISION_END,
    DECISION_SCHEMA,
    DECISION_START,
    ManagerDecisionConsumer,
    parse_manager_decision,
)
from bct.manager_decision_recovery import ManagerDecisionRecovery
from bct.core.models import ConflictError, PreconditionError, Work
from bct.core.orchestration import OrchestrationService, _canonical, _digest
from bct.core.policy import Policy
from bct.core.rcc_result import rcc_result_hash
from bct.core.store import Store
from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable


class FakeRelay:
    def __init__(self, receipt=None):
        self.receipt = receipt
        self.calls = []
        self.result_missing = False
        self.unavailable = False
        self.ack_unknown_once = False
        self.result_missing_ids = set()
        self.on_result = None
        self.receipts = {}

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.unavailable:
            raise RelayUnavailable("offline")
        if kwargs["command"] == "result":
            if self.on_result is not None:
                self.on_result(kwargs)
            if self.result_missing or kwargs["text"] in self.result_missing_ids:
                return {"ok": True, "relayId": kwargs["text"], "found": False,
                        "completed": False, "result": None}
            return {"ok": True, "relayId": kwargs["text"], "found": True,
                    "completed": True,
                    "result": self.receipts.get(kwargs["text"], self.receipt)}
        if kwargs["command"] == "result-ack":
            if self.ack_unknown_once:
                self.ack_unknown_once = False
                raise RelayEffectUnknown("lost ack response")
            receipt = self.receipts.get(kwargs["text"], self.receipt)
            return {"ok": True, "relayId": kwargs["text"], "ackState": "ACKED",
                    "resultHash": receipt["resultHash"], "duplicate": False}
        raise AssertionError(kwargs["command"])


class ManagerDecisionPRBTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name).resolve())
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.policy_path = Path(self.temp.name) / "bct.toml"
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["read"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.policy = Policy(self.policy_path)
        self.work = Work("work", "fixture", (self.root,), frozenset({"read"}), "owner")
        self.store.create_work(self.work)
        self.service = OrchestrationService(
            self.store, manager_wake_receipt_v2_enabled=True,
            policy=self.policy,
        )
        payload = {"status": "done"}
        with self.store.transaction() as db:
            for node, role in (("manager", "MANAGER"), ("worker", "WORKER"),
                               ("next-worker", "WORKER")):
                db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                           (node, node, role, "fixture", 1, 1))
            db.execute("INSERT INTO orchestration_sessions "
                       "(session_id,work_id,work_assignment_epoch,objective,roots_json,actions_json,"
                       "acceptance_json,plan_revision,manager_node_id,manager_epoch,state,"
                       "terminal_summary_json,wake_receipt_mode,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "session", "work", 1, "fixture", _canonical([self.root]),
                _canonical(["read"]), "{}", 1, "manager", 1, "ACTIVE", "{}",
                "RCC_RESULT_POLL_V1", 1.0, 1.0,
            ))
            for node, role in (("manager", "MANAGER"), ("worker", "WORKER"),
                               ("next-worker", "WORKER")):
                db.execute("INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                           ("session", node, role, 1))
            db.execute("INSERT INTO orchestration_manager_epochs VALUES(?,?,?,?,?,?,?)",
                       ("session", 1, "manager", "fixture", "{}", 1.0, None))
            attachments = (
                ("manager-att", "manager", "manager-instance", "manager-session", 11,
                 "manager-conversation", "MANAGER", "manager-binding"),
                ("worker-att", "worker", "worker-instance", "worker-session", 12,
                 "worker-conversation", "WORKER", "worker-binding"),
                ("next-att", "next-worker", "next-instance", "next-session", 13,
                 "next-conversation", "NEXT", "next-binding"),
            )
            for attachment_id, node, instance, external, tab, conversation, role, binding in attachments:
                db.execute("INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    attachment_id, 1, node, "rcc", instance, external, tab, 21,
                    conversation, "endpoint", role, binding, 1, 1.0,
                ))
                db.execute("INSERT INTO connections VALUES(?,?,?,?,?,?,?)", (
                    "orch:" + attachment_id, node, "rcc", "{}", "endpoint", 1, 1,
                ))
            db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "producer", "session", 1, "request", "{}", _canonical([self.root]),
                _canonical(["read"]), "{}", "APPLIED", 1, _canonical(payload), 1.0, 1.0,
            ))
            db.execute("INSERT INTO orchestration_assignment_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                "producer", 1, 1, "worker", "worker-att", 1, "APPLIED", None, None, 1.0, 1.0,
            ))
            db.execute("INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                "result-message", "session", "producer", 1, "RESULT", "worker", None,
                _digest(payload), _canonical(payload), 1.0, None, None,
            ))
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id='producer'"
            ).fetchone()
            self.now = time.time()
            self.event = self.service._record_manager_wake(
                db, session_id="session", assignment=assignment, generation=1,
                result_message_id="result-message", result_digest=_digest(payload), now=self.now,
            )
            self.delivery_id = "orch.wake.fixture"
            db.execute(
                "UPDATE orchestration_manager_wakes SET state='DELIVERED',delivery_id=?,"
                "delivered_at=3.0 WHERE event_id=?",
                (self.delivery_id, self.event["event_id"]),
            )
        db = self.store._connect()
        try:
            self.lease = dict(db.execute(
                "SELECT * FROM orchestration_durable_leases WHERE session_id='session'"
            ).fetchone())
        finally:
            db.close()

    def decision(self, kind="COMPLETE"):
        successors = []
        if kind == "FOLLOW_UP":
            successors = [{
                "target_node_id": "next-worker", "attachment_id": "next-att",
                "instruction": "Read the exact remaining evidence.",
                "roots": [self.root], "actions": ["read"],
                "acceptance": {"reported": True}, "dependencies": ["producer"],
            }]
        return {
            "schema": DECISION_SCHEMA,
            "event_id": self.event["event_id"], "session_id": "session",
            "manager_epoch": 1, "result_message_id": "result-message",
            "result_digest": self.event["result_digest"], "kind": kind,
            "summary": "Fixture decision.", "successors": successors,
        }

    def receipt(self, kind="COMPLETE"):
        reply = DECISION_START + _canonical(self.decision(kind)) + DECISION_END
        payload = {"failureEvidence": None, "ok": True, "reply": reply,
                   "error": "", "ambiguous": False}
        return {
            "id": self.delivery_id, "from": "MANAGER",
            "messageHash": self.event["result_digest"],
            "targetBindingReceipt": "manager-binding",
            "instanceId": "manager-instance", "sessionId": "manager-session",
            "attachmentGeneration": 1, "tabId": 11,
            "conversationKey": "manager-conversation",
            "resultState": "RESULT_PERSISTED", "ackState": "UNACKED",
            "resultHash": rcc_result_hash(payload), **payload,
        }

    def consumer(self):
        return ManagerDecisionConsumer(self.service)

    def consume(self, receipt=None):
        return self.consumer().consume_receipt(
            work=self.work, event_id=self.event["event_id"], manager_epoch=1,
            lease_token=self.lease["token"], receipt=receipt or self.receipt(), now=self.now + 1,
        )

    def count(self, table):
        db = self.store._connect()
        try:
            return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        finally:
            db.close()


    def use_proven_reconciled_result(self):
        # Clone the exact provenance shape of Worker B's stored
        # RECONCILED_RESULT, but keep the entire test in temporary SQLite.
        payload = {"status": "done", "reconciled": True}
        digest = _digest(payload)
        original_id = "manager-original-dispatch"
        proof_id = "result." + hashlib.sha256(
            f"{original_id}:producer:1".encode("utf-8")
        ).hexdigest()[:32]
        evidence = {
            "original_operation_id": original_id,
            "result_message_id": "result-message",
            "result_digest": digest,
        }
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_mailbox SET kind='RECONCILED_RESULT', "
                       "message_digest=?,payload_json=? WHERE message_id='result-message'",
                       (digest, _canonical(payload)))
            db.execute("UPDATE orchestration_assignments SET terminal_result_json=? "
                       "WHERE assignment_id='producer'", (_canonical(payload),))
            db.execute("UPDATE orchestration_manager_wakes SET result_digest=? "
                       "WHERE event_id=?", (digest, self.event["event_id"]))
            db.execute("INSERT INTO operations "
                       "(operation_id,work_id,principal_id,request_digest,capability,"
                       "target,state,outcome,evidence_json,error,assignment_epoch,"
                       "policy_revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (original_id, "work", "owner", "original-request", "orchestrate",
                        "session", "FINISHED", "UNKNOWN",
                        _canonical({"operation": "dispatch", "session_id": "session",
                                    "assignment_id": "producer"}), None, 1,
                        "fixture", 1.0, 1.0))
            db.execute("INSERT INTO resource_claims "
                       "(resource_key,operation_id,work_id,assignment_epoch,unresolved) "
                       "VALUES(?,?,?,?,?)",
                       ("orchestration-run:session:producer", original_id,
                        "work", 1, 0))
            db.execute("INSERT INTO orchestration_reconciliations "
                       "(decision_id,session_id,assignment_id,generation,manager_epoch,"
                       "decision,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (proof_id, "session", "producer", 1, 1,
                        "IMPORT_EXACT_RCC_RESULT", _canonical(evidence), 1.0))
            self.event = dict(db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?",
                (self.event["event_id"],)
            ).fetchone())

    def test_shared_fixture_and_exact_parser_contract(self):
        fixture = json.loads((Path(__file__).parents[1] / "modules" / "rcc" / "extension" /
                              "fixtures" / "manager_decision_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(DECISION_SCHEMA, fixture["schema"])
        self.assertEqual(DECISION_START, fixture["startMarker"])
        self.assertEqual(DECISION_END, fixture["endMarker"])
        expected = {key: fixture["complete"][key] for key in (
            "event_id", "session_id", "manager_epoch", "result_message_id", "result_digest"
        )}
        parsed = parse_manager_decision(
            DECISION_START + _canonical(fixture["complete"]) + DECISION_END,
            expected=expected,
        )
        self.assertEqual("COMPLETE", parsed["kind"])
        bad = dict(fixture["complete"], unexpected=True)
        with self.assertRaises(PreconditionError):
            parse_manager_decision(DECISION_START + _canonical(bad) + DECISION_END,
                                   expected=expected)

    def test_parser_rejects_duplicate_nonfinite_and_wrong_types(self):
        expected = {key: self.decision()[key] for key in (
            "event_id", "session_id", "manager_epoch", "result_message_id",
            "result_digest",
        )}
        raw = _canonical(self.decision()).replace(
            '"schema":', f'"schema":"{DECISION_SCHEMA}","schema":', 1,
        )
        invalid = [
            raw,
            _canonical(self.decision()).replace(
                '"summary":"Fixture decision."', '"summary":NaN', 1,
            ),
            _canonical(self.decision()).replace(
                '"summary":"Fixture decision."', '"summary":Infinity', 1,
            ),
            _canonical(dict(self.decision(), manager_epoch=1.0)),
        ]
        for payload in invalid:
            with self.subTest(payload=payload[:80]):
                with self.assertRaises(PreconditionError):
                    parse_manager_decision(
                        DECISION_START + payload + DECISION_END, expected=expected,
                    )


    def test_reconciled_result_manager_complete_consumption_and_result_ack(self):
        self.use_proven_reconciled_result()
        relay = FakeRelay(self.receipt("COMPLETE"))
        result = ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        self.assertEqual(1, result["checked"])
        self.assertEqual(1, result["committed"])
        self.assertEqual(1, result["acked"])
        self.assertEqual(0, result["rejected"])
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_dispatch_outbox"))
        self.assertTrue(self.consume()["idempotent"])
        with self.store.transaction() as db:
            wake = db.execute(
                "SELECT state,decision_id,result_ack_state,result_acknowledged_at "
                "FROM orchestration_manager_wakes WHERE event_id=?",
                (self.event["event_id"],),
            ).fetchone()
            self.assertEqual("DELIVERED", wake["state"])
            self.assertIsNotNone(wake["decision_id"])
            self.assertEqual("ACKED", wake["result_ack_state"])
            self.assertIsNotNone(wake["result_acknowledged_at"])
            self.assertEqual("RECONCILED_RESULT", db.execute(
                "SELECT kind FROM orchestration_mailbox WHERE message_id='result-message'"
            ).fetchone()[0])
        commands = [call["command"] for call in relay.calls]
        self.assertEqual(["result", "result-ack"], commands)
        self.assertNotIn("send-wakeback", commands)

    def test_manager_complete_ack_finalizes_idle_session(self):
        relay = FakeRelay(self.receipt("COMPLETE"))
        summary = ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        self.assertEqual(1, summary["acked"])
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT state,terminal_summary_json FROM orchestration_sessions "
                "WHERE session_id='session'"
            ).fetchone()
            self.assertEqual("FINISHED", row["state"])
            self.assertEqual("COMPLETE", json.loads(row["terminal_summary_json"])["manager_decision"])
        self.assertTrue(self.consume()["idempotent"])

    def test_deferred_complete_finishes_after_other_assignment_settles(self):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("pending-extra", "session", 1, "extra", "{}",
                 _canonical([self.root]), _canonical(["read"]), "{}",
                 "QUEUED", 1, "{}", 1.0, 1.0),
            )
        relay = FakeRelay(self.receipt("COMPLETE"))
        recovery = ManagerDecisionRecovery(self.service, relay)
        result = recovery.run_once(now=self.now + 1)
        self.assertEqual(1, result["acked"])
        with self.store.transaction() as db:
            self.assertEqual("ACTIVE", db.execute(
                "SELECT state FROM orchestration_sessions WHERE session_id='session'"
            ).fetchone()[0])
            db.execute(
                "UPDATE orchestration_assignments SET state='APPLIED' "
                "WHERE assignment_id='pending-extra'"
            )
        next_tick = recovery.run_once(now=self.now + 3)
        with self.store.transaction() as db:
            self.assertEqual("FINISHED", db.execute(
                "SELECT state FROM orchestration_sessions WHERE session_id='session'"
            ).fetchone()[0])
            self.assertEqual(1, db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='ORCHESTRATION_SESSION_FINISHED'"
            ).fetchone()[0])
        recovery.run_once(now=self.now + 5)
        with self.store.transaction() as db:
            self.assertEqual(1, db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='ORCHESTRATION_SESSION_FINISHED'"
            ).fetchone()[0])

    def test_concurrent_deferred_complete_recovery_exactly_once(self):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("concurrent-extra", "session", 1, "extra-concurrent", "{}",
                 _canonical([self.root]), _canonical(["read"]), "{}",
                 "QUEUED", 1, "{}", 1.0, 1.0),
            )
        relay = FakeRelay(self.receipt("COMPLETE"))
        self.assertEqual(1, ManagerDecisionRecovery(
            self.service, relay).run_once(now=self.now + 1)["acked"])
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_assignments SET state='APPLIED' "
                       "WHERE assignment_id='concurrent-extra'")
        results, failures = [], []
        def attempt():
            try:
                results.append(self.consumer().reconcile_acked_completes(
                    now=self.now + 5))
            except Exception as exc:
                failures.append(exc)
        jobs = [threading.Thread(target=attempt) for _ in range(2)]
        for job in jobs:
            job.start()
        for job in jobs:
            job.join()
        self.assertFalse(failures)
        self.assertEqual([0, 1], sorted(results))
        with self.store.transaction() as db:
            self.assertEqual("FINISHED", db.execute(
                "SELECT state FROM orchestration_sessions WHERE session_id='session'"
            ).fetchone()[0])
            self.assertEqual(1, db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='ORCHESTRATION_SESSION_FINISHED'"
            ).fetchone()[0])

    def test_followup_ack_keeps_session_open(self):
        relay = FakeRelay(self.receipt("FOLLOW_UP"))
        summary = ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        self.assertEqual(1, summary["acked"])
        with self.store.transaction() as db:
            state = db.execute(
                "SELECT state FROM orchestration_sessions WHERE session_id='session'"
            ).fetchone()["state"]
        self.assertEqual("ACTIVE", state)
        self.assertEqual(1, self.count("orchestration_dispatch_outbox"))

    def test_complete_ack_keeps_session_open_with_other_active_assignment(self):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("still-running", "session", 1, "request-extra", "{}",
                 _canonical([self.root]), _canonical(["read"]), "{}",
                 "QUEUED", 1, "{}", 1.0, 1.0),
            )
        relay = FakeRelay(self.receipt("COMPLETE"))
        summary = ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        self.assertEqual(1, summary["acked"])
        with self.store.transaction() as db:
            state = db.execute(
                "SELECT state FROM orchestration_sessions WHERE session_id='session'"
            ).fetchone()["state"]
        self.assertEqual("ACTIVE", state)

    def test_reconciled_result_followup_atomic_and_exact_replay(self):
        self.use_proven_reconciled_result()
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_followup BEFORE INSERT ON "
                       "orchestration_dispatch_outbox BEGIN "
                       "SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(Exception):
            self.consume(self.receipt("FOLLOW_UP"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_dispatch_outbox"))
        with self.store.transaction() as db:
            db.execute("DROP TRIGGER reject_followup")
        first = self.consume(self.receipt("FOLLOW_UP"))
        second = self.consume(self.receipt("FOLLOW_UP"))
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(1, self.count("orchestration_dispatch_outbox"))

    def test_reconciled_result_stale_epoch_does_not_commit_or_ack(self):
        self.use_proven_reconciled_result()
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=2 "
                       "WHERE session_id='session'")
        relay = FakeRelay(self.receipt())
        summary = ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        self.assertEqual(0, summary["committed"])
        self.assertEqual(0, summary["acked"])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def use_finished_chain_reconciliation(self):
        self.use_proven_reconciled_result()
        origin = "manager-original-dispatch"
        plan = {
            "tasks": [
                {"assignment_id": "producer", "worker_node_id": "worker",
                 "attachment_id": "worker-att", "instruction": "Read source",
                 "acceptance": {"verified": True}, "roots": [self.root],
                 "actions": ["read"], "dependencies": []},
                {"assignment_id": "next-check", "worker_node_id": "next-worker",
                 "attachment_id": "next-att", "instruction": "Check independently",
                 "acceptance": {"verified": True}, "roots": [self.root],
                 "actions": ["read"], "dependencies": []},
            ],
            "synthesis": {"assignment_id": "final-manager",
                          "manager_node_id": "manager",
                          "attachment_id": "manager-att",
                          "instruction": "Summarize", "acceptance": {},
                          "roots": [self.root], "actions": ["read"]},
            "takeover": None, "timeout_s": 600.0,
        }
        plan_id = "plan." + hashlib.sha256(
            f"session:{origin}".encode("utf-8")
        ).hexdigest()[:32]
        resolver_id = "manager-chain-resume-proven"
        with self.store.transaction() as db:
            db.execute("INSERT INTO resource_claims "
                       "(resource_key,operation_id,work_id,assignment_epoch,unresolved) "
                       "VALUES(?,?,?,?,?)",
                       ("orchestration-run:session:next-check", origin, "work", 1, 0))
            db.execute("INSERT INTO orchestration_mailbox "
                       "(message_id,session_id,kind,message_digest,payload_json,created_at) "
                       "VALUES(?,?,?,?,?,?)",
                       (plan_id, "session", "PLAN", _digest(plan), _canonical(plan), 1.0))
            db.execute("INSERT INTO events (kind,subject_id,data_json,created_at) "
                       "VALUES(?,?,?,?)",
                       ("ORCHESTRATION_CHAIN_PLAN_RECORDED","session",
                        _canonical({"operation_id":origin,"plan_digest":_digest(plan)}), 1.0))
            db.execute("UPDATE operations SET outcome='APPLIED',error=NULL,"
                       "evidence_json=? WHERE operation_id=?", (
                _canonical({"phase":"ORCHESTRATION_RECOVERED",
                            "resolver_operation_id":resolver_id,
                            "recovered_outcome":"APPLIED"}), origin))
            db.execute("INSERT INTO operations "
                       "(operation_id,work_id,principal_id,request_digest,capability,"
                       "target,state,outcome,evidence_json,error,assignment_epoch,"
                       "policy_revision,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (resolver_id,"work","owner","existing","orchestrate","session",
                        "FINISHED","APPLIED",_canonical({
                            "operation":"chain-resume","session_id":"session",
                            "session_state":"FINISHED"
                        }),None,1,"fixture",1.0,1.0))
            db.execute("INSERT INTO events(kind,subject_id,data_json,created_at) "
                       "VALUES(?,?,?,?)",
                       ("OPERATION_RECONCILED",origin,_canonical({
                           "resolver_operation_id":resolver_id,
                           "original_outcome":"APPLIED",
                           "resolved_outcome":"APPLIED",
                           "claims_released":True,
                       }),1.0))
            db.execute("UPDATE orchestration_sessions SET state='FINISHED' "
                       "WHERE session_id='session'")
        return plan_id

    def test_finished_chain_is_polled_once_and_result_acked(self):
        self.use_finished_chain_reconciliation()
        relay = FakeRelay(self.receipt())
        recovery = ManagerDecisionRecovery(self.service, relay)
        summary = recovery.run_once(now=self.now+1)
        self.assertEqual(1, summary["committed"])
        self.assertEqual(1, summary["acked"])
        self.assertEqual(0, summary["rejected"])
        self.assertEqual(1,self.count("orchestration_consumption_decisions"))
        self.assertEqual(1,self.count("orchestration_consumption_receipts"))
        self.assertEqual(["result","result-ack"],
                         [call["command"] for call in relay.calls])
        db=self.store._connect()
        try:
            row=db.execute("SELECT result_ack_state,decision_id FROM "
                           "orchestration_manager_wakes WHERE event_id=?",
                           (self.event["event_id"],)).fetchone()
            self.assertEqual("ACKED",row["result_ack_state"])
            self.assertIsNotNone(row["decision_id"])
        finally: db.close()

    def test_finished_chain_missing_plan_is_not_polled_or_consumed(self):
        plan_id = self.use_finished_chain_reconciliation()
        with self.store.transaction() as db:
            db.execute("DELETE FROM orchestration_mailbox WHERE message_id=?", (plan_id,))
        relay=FakeRelay(self.receipt())
        result=ManagerDecisionRecovery(self.service,relay).run_once(now=self.now+1)
        self.assertEqual(0,result["committed"])
        self.assertEqual(0,result["acked"])
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))
        self.assertEqual([],relay.calls)
        with self.assertRaises(ConflictError):
            self.consume()

    def test_finished_non_chain_and_inactive_work_are_fenced(self):
        self.use_proven_reconciled_result()
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET state='FINISHED' "
                       "WHERE session_id='session'")
        with self.assertRaises(ConflictError):
            self.consume()
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))

    def test_finished_chain_stale_epoch_is_not_revived(self):
        self.use_finished_chain_reconciliation()
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=2 "
                       "WHERE session_id='session'")
        relay=FakeRelay(self.receipt())
        summary=ManagerDecisionRecovery(self.service,relay).run_once(now=self.now+1)
        self.assertEqual(0,summary["committed"])
        self.assertEqual([],relay.calls)
        self.assertEqual(0,self.count("orchestration_consumption_receipts"))

    def test_complete_commits_without_successor_and_is_idempotent(self):
        first = self.consume()
        second = self.consume()
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual([], first["successor_assignment_ids"])
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_dispatch_outbox"))

    def test_legacy_session_pin_blocks_decision_and_poller_without_commit(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_sessions SET wake_receipt_mode="
                "'LEGACY_RETURN_V1' WHERE session_id='session'"
            )
        blocked = OrchestrationService(
            Store(self.store.path), manager_wake_receipt_v2_enabled=True,
            policy=self.policy,
        )
        with self.assertRaisesRegex(
            ConflictError, "MANAGER_WAKE_RECEIPT_V2_SESSION_NOT_ALLOWED",
        ):
            ManagerDecisionConsumer(blocked).consume_receipt(
                work=self.work, event_id=self.event["event_id"], manager_epoch=1,
                lease_token=self.lease["token"], receipt=self.receipt(), now=self.now + 1,
            )
        recovery = ManagerDecisionRecovery(blocked, FakeRelay())
        summary = recovery.run_once(now=self.now + 1)
        self.assertTrue(summary["lease_owned"])
        self.assertEqual(0, summary["checked"])
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_follow_up_assignment_receipt_decision_and_outbox_are_atomic(self):
        result = self.consume(self.receipt("FOLLOW_UP"))
        self.assertEqual(1, len(result["successor_assignment_ids"]))
        self.assertEqual(2, self.count("orchestration_assignments"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        self.assertEqual(1, self.count("orchestration_dispatch_outbox"))
        self.policy_path.write_text(
            '[policy]\nnormal_actions=[]\napproval_actions=["read"]\n',
            encoding="utf-8",
        )
        replay = self.consume(self.receipt("FOLLOW_UP"))
        self.assertTrue(replay["idempotent"])
        self.assertEqual(1, self.count("orchestration_dispatch_outbox"))

    def test_follow_up_revalidates_current_policy(self):
        self.policy_path.write_text(
            '[policy]\nnormal_actions=[]\napproval_actions=["read"]\n',
            encoding="utf-8",
        )
        with self.assertRaises(PreconditionError):
            self.consume(self.receipt("FOLLOW_UP"))
        self.assertEqual(1, self.count("orchestration_assignments"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_dispatch_outbox"))

    def test_outbox_failure_rolls_back_successor_and_decision(self):
        with self.store.transaction() as db:
            db.execute(
                "CREATE TRIGGER abort_manager_outbox BEFORE INSERT ON "
                "orchestration_dispatch_outbox BEGIN SELECT RAISE(ABORT,'fixture'); END"
            )
        with self.assertRaises(Exception):
            self.consume(self.receipt("FOLLOW_UP"))
        self.assertEqual(1, self.count("orchestration_assignments"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_dispatch_outbox"))

    def test_duplicate_consumers_converge_on_one_decision(self):
        outcomes = []
        gate = threading.Barrier(2)

        def consume():
            gate.wait()
            outcomes.append(self.consume())

        left = threading.Thread(target=consume)
        right = threading.Thread(target=consume)
        left.start(); right.start(); left.join(); right.join()
        self.assertEqual([False, True], sorted(item["idempotent"] for item in outcomes))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_bad_hash_binding_and_attachment_rotation_fail_without_commit(self):
        bad = self.receipt()
        bad["resultHash"] = "0" * 64
        with self.assertRaises(ConflictError):
            self.consume(bad)
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='manager-att'")
        with self.assertRaises(ConflictError):
            self.consume()
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_takeover_and_stale_work_fail_closed(self):
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=2 WHERE session_id='session'")
        with self.assertRaises(ConflictError):
            self.consume()
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=1 WHERE session_id='session'")
            db.execute("UPDATE works SET assignment_epoch=2 WHERE work_id='work'")
        with self.assertRaises(ConflictError):
            self.consume()

    def test_delayed_result_restart_ack_loss_and_unknown_never_resend(self):
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_manager_wakes SET state='UNKNOWN' WHERE event_id=?",
                       (self.event["event_id"],))
        relay = FakeRelay(self.receipt())
        recovery = ManagerDecisionRecovery(self.service, relay)
        relay.result_missing = True
        delayed = recovery.run_once(now=self.now + 1)
        self.assertEqual(1, delayed["deferred"])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        relay.result_missing = False
        relay.ack_unknown_once = True
        first = recovery.run_once(now=self.now + 2)
        self.assertEqual(1, first["committed"])
        self.assertEqual(1, first["deferred"])
        restarted = ManagerDecisionRecovery(OrchestrationService(
            Store(self.store.path), manager_wake_receipt_v2_enabled=True,
            policy=self.policy,
        ), relay)
        # A crash-safe replacement waits for the short singleton poller lease
        # instead of assuming the old Core process is gone immediately.
        second = restarted.run_once(now=self.now + 40)
        self.assertEqual(1, second["acked"])
        commands = [call["command"] for call in relay.calls]
        self.assertNotIn("send", commands)
        self.assertNotIn("send-wakeback", commands)
        db = self.store._connect()
        try:
            wake = db.execute("SELECT * FROM orchestration_manager_wakes WHERE event_id=?",
                              (self.event["event_id"],)).fetchone()
            self.assertEqual("UNKNOWN", wake["state"])
            self.assertEqual("ACKED", wake["result_ack_state"])
        finally:
            db.close()

    def test_rcc_outage_is_read_only(self):
        relay = FakeRelay(self.receipt())
        relay.unavailable = True
        result = ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        self.assertEqual(1, result["deferred"])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_result_lookup_cannot_commit_after_poller_replacement(self):
        relay = FakeRelay(self.receipt())
        recovery = ManagerDecisionRecovery(self.service, relay)

        def replace_poller(_request):
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE orchestration_manager_recovery_leases SET "
                    "owner_id='replacement',token='replacement-token',expires_at=?",
                    (time.time() + 60.0,),
                )

        relay.on_result = replace_poller
        result = recovery.run_once(now=self.now + 1)
        self.assertEqual(1, result["rejected"])
        self.assertEqual(0, result["committed"])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_result_lookup_cannot_commit_after_manager_lease_expiry(self):
        relay = FakeRelay(self.receipt())
        recovery = ManagerDecisionRecovery(self.service, relay)

        def expire_manager_lease(_request):
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE orchestration_durable_leases SET expires_at=? "
                    "WHERE session_id='session'", (time.time() - 1.0,),
                )

        relay.on_result = expire_manager_lease
        result = recovery.run_once(now=self.now + 1)
        self.assertEqual(1, result["rejected"])
        self.assertEqual(0, result["committed"])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_keyset_cursor_prevents_missing_result_starvation_after_restart(self):
        with self.store.transaction() as db:
            original = dict(db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?",
                (self.event["event_id"],),
            ).fetchone())
            db.execute(
                "UPDATE orchestration_manager_wakes SET state='STALE' WHERE event_id=?",
                (self.event["event_id"],),
            )
            columns = list(original)
            mailbox = dict(db.execute(
                "SELECT * FROM orchestration_mailbox WHERE message_id='result-message'"
            ).fetchone())
            mailbox_columns = list(mailbox)
            for index in range(10):
                message = dict(mailbox)
                message["message_id"] = f"result-message-{index:02d}"
                db.execute(
                    f"INSERT INTO orchestration_mailbox "
                    f"({','.join(mailbox_columns)}) VALUES("
                    f"{','.join('?' for _ in mailbox_columns)})",
                    tuple(message[column] for column in mailbox_columns),
                )
                clone = dict(original)
                clone.update({
                    "event_id": f"wake.{index:02d}",
                    "result_message_id": f"result-message-{index:02d}",
                    "delivery_id": f"relay.{index:02d}",
                    "state": "DELIVERED",
                    "decision_id": None,
                    "result_hash": None,
                    "result_ack_state": "NOT_REQUESTED",
                    "acknowledged_at": None,
                    "result_acknowledged_at": None,
                })
                placeholders = ",".join("?" for _ in columns)
                db.execute(
                    f"INSERT INTO orchestration_manager_wakes "
                    f"({','.join(columns)}) VALUES({placeholders})",
                    tuple(clone[column] for column in columns),
                )
        relay = FakeRelay(self.receipt())
        relay.result_missing_ids = {f"relay.{index:02d}" for index in range(9)}
        final_decision = self.decision()
        final_decision.update({
            "event_id": "wake.09", "result_message_id": "result-message-09",
        })
        reply = DECISION_START + _canonical(final_decision) + DECISION_END
        payload = {"failureEvidence": None, "ok": True, "reply": reply,
                   "error": "", "ambiguous": False}
        final_receipt = dict(self.receipt())
        final_receipt.update({
            "id": "relay.09", "reply": reply,
            "resultHash": rcc_result_hash(payload),
        })
        relay.receipts["relay.09"] = final_receipt
        first = ManagerDecisionRecovery(self.service, relay)
        one = first.run_once(limit=8, now=self.now + 1)
        self.assertEqual(8, one["checked"])
        self.assertNotIn("relay.09", [call["text"] for call in relay.calls])
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_manager_recovery_leases SET expires_at=?",
                (self.now + 2,),
            )
        second = ManagerDecisionRecovery(self.service, relay)
        two = second.run_once(limit=8, now=self.now + 40)
        self.assertTrue(two["lease_owned"])
        self.assertIn("relay.09", [call["text"] for call in relay.calls])
        self.assertEqual(1, two["committed"])
        self.assertEqual(1, two["acked"])

    def test_lease_renewal_is_relevant_and_rate_limited(self):
        unrelated = Work("other-work", "fixture", (self.root,),
                         frozenset({"read"}), "owner")
        self.store.create_work(unrelated)
        with self.store.transaction() as db:
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                       ("other-manager", "other", "MANAGER", "fixture", 1, 1))
            db.execute("INSERT INTO orchestration_sessions "
                       "(session_id,work_id,work_assignment_epoch,objective,roots_json,actions_json,"
                       "acceptance_json,plan_revision,manager_node_id,manager_epoch,state,"
                       "terminal_summary_json,wake_receipt_mode,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "other-session", "other-work", 1, "fixture", _canonical([self.root]),
                _canonical(["read"]), "{}", 1, "other-manager", 1, "ACTIVE", "{}",
                "RCC_RESULT_POLL_V1", 1.0, 1.0,
            ))
            db.execute(
                "INSERT INTO orchestration_durable_leases VALUES(?,?,?,?,?,?)",
                ("other-session", "other-manager", 1, "other-token", self.now + 5,
                 self.now),
            )
            db.execute(
                "UPDATE orchestration_durable_leases SET expires_at=?,updated_at=? "
                "WHERE session_id='session'", (self.now + 50, self.now),
            )
        relay = FakeRelay(self.receipt())
        relay.result_missing = True
        ManagerDecisionRecovery(self.service, relay).run_once(now=self.now + 1)
        db = self.store._connect()
        try:
            relevant = db.execute(
                "SELECT expires_at FROM orchestration_durable_leases "
                "WHERE session_id='session'",
            ).fetchone()[0]
            unrelated_expiry = db.execute(
                "SELECT expires_at FROM orchestration_durable_leases "
                "WHERE session_id='other-session'",
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(self.now + 50, relevant)
        self.assertEqual(self.now + 5, unrelated_expiry)

    def test_handed_off_work_is_not_polled_or_renewed(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE works SET assignment_epoch=2 WHERE work_id='work'"
            )
            db.execute(
                "UPDATE orchestration_durable_leases SET expires_at=? "
                "WHERE session_id='session'", (self.now + 0.5,),
            )
        relay = FakeRelay(self.receipt())
        result = ManagerDecisionRecovery(self.service, relay).run_once(
            now=self.now + 0.25,
        )
        self.assertTrue(result["lease_owned"])
        self.assertEqual(0, result["checked"])
        self.assertEqual([], relay.calls)
        db = self.store._connect()
        try:
            expires_at = db.execute(
                "SELECT expires_at FROM orchestration_durable_leases "
                "WHERE session_id='session'",
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(self.now + 0.5, expires_at)

    def test_live_lease_renews_but_stale_epoch_is_not_revived(self):
        relay = FakeRelay(self.receipt())
        relay.result_missing = True
        recovery = ManagerDecisionRecovery(self.service, relay)
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_durable_leases SET expires_at=?",
                       (self.now + 0.5,))
        recovery.run_once(now=self.now + 0.25)
        db = self.store._connect()
        try:
            renewed = db.execute(
                "SELECT expires_at FROM orchestration_durable_leases WHERE session_id='session'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertGreater(renewed, self.now + 60)
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_durable_leases SET expires_at=?", (self.now - 1,))
            db.execute("UPDATE orchestration_sessions SET manager_epoch=2 WHERE session_id='session'")
        recovery.run_once(now=self.now + 1)
        db = self.store._connect()
        try:
            expired = db.execute(
                "SELECT expires_at FROM orchestration_durable_leases WHERE session_id='session'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(self.now - 1, expired)

    def test_single_poller_lease_and_long_restart_recovery(self):
        first_relay = FakeRelay(self.receipt())
        first_relay.result_missing = True
        first = ManagerDecisionRecovery(self.service, first_relay)
        self.assertTrue(first.run_once(now=self.now + 1)["lease_owned"])

        second_relay = FakeRelay(self.receipt())
        second = ManagerDecisionRecovery(self.service, second_relay)
        blocked = second.run_once(now=self.now + 2)
        self.assertFalse(blocked["lease_owned"])
        self.assertEqual([], second_relay.calls)

        with self.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_manager_recovery_leases SET expires_at=?",
                (self.now + 3,),
            )
            db.execute(
                "UPDATE orchestration_durable_leases SET expires_at=?",
                (self.now + 3,),
            )
        recovered = second.run_once(now=self.now + 100)
        self.assertTrue(recovered["lease_owned"])
        self.assertEqual(1, recovered["committed"])
        self.assertEqual(1, recovered["acked"])
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        stale = first.run_once(now=self.now + 101)
        self.assertFalse(stale["lease_owned"])


if __name__ == "__main__":
    unittest.main()
