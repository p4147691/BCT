from __future__ import annotations

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

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.unavailable:
            raise RelayUnavailable("offline")
        if kwargs["command"] == "result":
            if self.result_missing:
                return {"ok": True, "relayId": kwargs["text"], "found": False,
                        "completed": False, "result": None}
            return {"ok": True, "relayId": kwargs["text"], "found": True,
                    "completed": True, "result": self.receipt}
        if kwargs["command"] == "result-ack":
            if self.ack_unknown_once:
                self.ack_unknown_once = False
                raise RelayEffectUnknown("lost ack response")
            return {"ok": True, "relayId": kwargs["text"], "ackState": "ACKED",
                    "resultHash": self.receipt["resultHash"], "duplicate": False}
        raise AssertionError(kwargs["command"])


class ManagerDecisionPRBTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name).resolve())
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.work = Work("work", "fixture", (self.root,), frozenset({"read"}), "owner")
        self.store.create_work(self.work)
        self.service = OrchestrationService(
            self.store, manager_wake_receipt_v2_enabled=True,
        )
        payload = {"status": "done"}
        with self.store.transaction() as db:
            for node, role in (("manager", "MANAGER"), ("worker", "WORKER"),
                               ("next-worker", "WORKER")):
                db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                           (node, node, role, "fixture", 1, 1))
            db.execute("INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "session", "work", 1, "fixture", _canonical([self.root]),
                _canonical(["read"]), "{}", 1, "manager", 1, "ACTIVE", "{}", 1.0, 1.0,
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

    def test_complete_commits_without_successor_and_is_idempotent(self):
        first = self.consume()
        second = self.consume()
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual([], first["successor_assignment_ids"])
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_dispatch_outbox"))

    def test_follow_up_assignment_receipt_decision_and_outbox_are_atomic(self):
        result = self.consume(self.receipt("FOLLOW_UP"))
        self.assertEqual(1, len(result["successor_assignment_ids"]))
        self.assertEqual(2, self.count("orchestration_assignments"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))
        self.assertEqual(1, self.count("orchestration_dispatch_outbox"))
        replay = self.consume(self.receipt("FOLLOW_UP"))
        self.assertTrue(replay["idempotent"])
        self.assertEqual(1, self.count("orchestration_dispatch_outbox"))

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
        restarted = ManagerDecisionRecovery(OrchestrationService(Store(self.store.path)), relay)
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
