from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from bct.core.manager_decision import DECISION_END, DECISION_SCHEMA, DECISION_START, ManagerDecisionConsumer
from bct.core.orchestration import OrchestrationService, _canonical, _digest
from bct.core.policy import Policy
from bct.core.rcc_result import rcc_result_hash
from bct.core.models import Work
from bct.core.store import Store
from bct.features.orchestration import _RESULT_END, _RESULT_START
from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable
from bct.manager_decision_recovery import ManagerDecisionRecovery
from bct.worker_dispatch_recovery import WorkerDispatchRecovery


class FakeRelay:
    def __init__(self):
        self.calls = []
        self.send_count = 0
        self.wake_send_count = 0
        self.wake_unknown = False
        self.write_count = 0
        self.receipt = None
        self.result_response_updates = {}
        self.send_unknown = False
        self.unavailable = False
        self.ack_unknown_once = False
        self.before_callback = None
        self.before_wake_callback = None
        self.unavailable_wake_ids = set()

    def request(self, **kwargs):
        self.calls.append(kwargs)
        command = kwargs["command"]
        if command == "send":
            self.send_count += 1
            if self.unavailable:
                raise RelayUnavailable("offline before open")
            callback = kwargs.get("before_write")
            if callback:
                if self.before_callback is not None:
                    self.before_callback()
                callback()
            self.write_count += 1
            if self.send_unknown:
                raise RelayEffectUnknown("lost after write")
            return {"type": "host:ack", "ok": True, "submitted": True}
        if command == "send-wakeback":
            self.wake_send_count += 1
            if kwargs["request_id"] in self.unavailable_wake_ids:
                raise RelayUnavailable("wake pipe unavailable before open")
            if self.before_wake_callback is not None:
                self.before_wake_callback()
            callback = kwargs.get("before_write")
            if callback:
                callback()
            if self.wake_unknown:
                raise RelayEffectUnknown("wake response lost after submit")
            return {"type": "host:ack", "ok": True, "submitted": True}
        if command == "result":
            if self.receipt is None:
                return {"ok": True, "relayId": kwargs["text"], "found": False,
                        "completed": False, "pending": True, "result": None}
            return {"ok": True, "relayId": kwargs["text"], "found": True,
                    "completed": True, "pending": False, "result": self.receipt,
                    **self.result_response_updates}
        if command == "result-ack":
            if self.ack_unknown_once:
                self.ack_unknown_once = False
                raise RelayEffectUnknown("lost ack response")
            return {"ok": True, "relayId": kwargs["text"], "ackState": "ACKED",
                    "resultHash": self.receipt["resultHash"], "duplicate": False}
        raise AssertionError(command)


class WorkerDispatchPRCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = str(Path(self.temp.name).resolve())
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.policy_path = Path(self.temp.name) / "bct.toml"
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["read","orchestrate"]\napproval_actions=[]\n', encoding="utf-8",
        )
        self.work = Work("work", "fixture", (root,), frozenset({"read", "orchestrate"}), "owner")
        self.store.create_work(self.work)
        self.service = OrchestrationService(
            self.store, manager_wake_receipt_v2_enabled=True,
            policy=Policy(self.policy_path),
        )
        self.now = time.time()
        payload = {"status": "done"}
        with self.store.transaction() as db:
            for node, role in (("manager", "MANAGER"), ("worker", "WORKER"),
                               ("next-worker", "WORKER")):
                db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                           (node, node, role, "fixture", 1, 1))
            db.execute("INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "session", "work", 1, "fixture", _canonical([root]),
                _canonical(["read"]), "{}", 1, "manager", 1, "ACTIVE", "{}",
                self.now, self.now,
            ))
            for node, role in (("manager", "MANAGER"), ("worker", "WORKER"),
                               ("next-worker", "WORKER")):
                db.execute("INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                           ("session", node, role, 1))
            db.execute("INSERT INTO orchestration_manager_epochs VALUES(?,?,?,?,?,?,?)",
                       ("session", 1, "manager", "fixture", "{}", self.now, None))
            attachments = (
                ("manager-att", "manager", "manager-instance", "manager-session", 11,
                 "manager-conversation", "MANAGER", "manager-binding"),
                ("worker-att", "worker", "worker-instance", "worker-session", 12,
                 "worker-conversation", "WORKER", "worker-binding"),
                ("next-att", "next-worker", "next-instance", "next-session", 13,
                 "next-conversation", "NEXT", "next-binding"),
            )
            for aid, node, instance, external, tab, conversation, role, binding in attachments:
                db.execute("INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    aid, 1, node, "rcc", instance, external, tab, 21, conversation,
                    "endpoint", role, binding, 1, self.now,
                ))
                db.execute("INSERT INTO connections VALUES(?,?,?,?,?,?,?)",
                           ("orch:" + aid, node, "rcc", "{}", "endpoint", 1, 1))
            db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "producer", "session", 1, "request", "{}", _canonical([root]),
                _canonical(["read"]), "{}", "APPLIED", 1, _canonical(payload),
                self.now, self.now,
            ))
            db.execute("INSERT INTO orchestration_assignment_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                "producer", 1, 1, "worker", "worker-att", 1, "APPLIED", None,
                None, self.now, self.now,
            ))
            db.execute("INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                "producer-result", "session", "producer", 1, "RESULT", "worker", None,
                _digest(payload), _canonical(payload), self.now, None, None,
            ))
            assignment = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id='producer'"
            ).fetchone()
            event = self.service._record_manager_wake(
                db, session_id="session", assignment=assignment, generation=1,
                result_message_id="producer-result", result_digest=_digest(payload),
                now=self.now,
            )
            self.event = dict(event)
            self.manager_delivery = "orch.wake.fixture"
            db.execute(
                "UPDATE orchestration_manager_wakes SET state='DELIVERED',delivery_id=? "
                "WHERE event_id=?", (self.manager_delivery, event["event_id"]),
            )
        lease = self.row("orchestration_durable_leases", "session_id", "session")
        decision = {
            "schema": DECISION_SCHEMA, "event_id": self.event["event_id"],
            "session_id": "session", "manager_epoch": 1,
            "result_message_id": "producer-result",
            "result_digest": self.event["result_digest"], "kind": "FOLLOW_UP",
            "summary": "Continue once.", "successors": [{
                "target_node_id": "next-worker", "attachment_id": "next-att",
                "instruction": "Read the next evidence.", "roots": [root],
                "actions": ["read"], "acceptance": {"reported": True},
                "dependencies": ["producer"],
            }],
        }
        reply = DECISION_START + _canonical(decision) + DECISION_END
        result_payload = {"failureEvidence": None, "ok": True, "reply": reply,
                          "error": "", "ambiguous": False}
        manager_receipt = {
            "id": self.manager_delivery, "from": "MANAGER",
            "messageHash": self.event["result_digest"],
            "targetBindingReceipt": "manager-binding",
            "instanceId": "manager-instance", "sessionId": "manager-session",
            "attachmentGeneration": 1, "tabId": 11,
            "conversationKey": "manager-conversation",
            "resultState": "RESULT_PERSISTED", "ackState": "UNACKED",
            "resultHash": rcc_result_hash(result_payload), **result_payload,
        }
        self.manager_receipt = manager_receipt
        consumed = ManagerDecisionConsumer(self.service).consume_receipt(
            work=self.work, event_id=self.event["event_id"], manager_epoch=1,
            lease_token=lease["token"], receipt=manager_receipt, now=self.now + 1,
        )
        self.assignment_id = consumed["successor_assignment_ids"][0]
        self.outbox = self.row("orchestration_dispatch_outbox", "assignment_id",
                               self.assignment_id)
        self.relay = FakeRelay()
        self.dispatcher = WorkerDispatchRecovery(self.service, self.relay)

    def row(self, table, key, value):
        db = self.store._connect()
        try:
            row = db.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
            return None if row is None else dict(row)
        finally:
            db.close()

    def worker_receipt(self):
        assignment = self.service.assignment(
            work=self.store.get_work("work"), session_id="session",
            assignment_id=self.assignment_id,
        )
        nonce = hashlib.sha256(_canonical([
            self.assignment_id, 1, assignment["request_digest"],
        ]).encode("utf-8")).hexdigest()[:32]
        envelope = {
            "schema": 1, "session_id": "session", "assignment_id": self.assignment_id,
            "assignment_generation": 1, "request_digest": assignment["request_digest"],
            "result_nonce": nonce, "status": "SUCCEEDED", "summary": "done",
        }
        reply = _RESULT_START + _canonical(envelope) + _RESULT_END
        payload = {"failureEvidence": None, "ok": True, "reply": reply,
                   "error": "", "ambiguous": False}
        send = next(call for call in self.relay.calls if call["command"] == "send")
        fingerprint = _canonical([
            send["to"], send["text"], False, "", "next-binding",
            assignment["request_digest"], "next-instance", "next-session", 13,
            "next-conversation", 1,
        ])
        return {
            "id": self.outbox["delivery_id"], "from": "NEXT", "fingerprint": fingerprint,
            "messageHash": assignment["request_digest"],
            "targetBindingReceipt": "next-binding", "instanceId": "next-instance",
            "sessionId": "next-session", "tabId": 13,
            "conversationKey": "next-conversation", "attachmentGeneration": 1,
            "resultState": "RESULT_PERSISTED", "ackState": "UNACKED",
            "resultHash": rcc_result_hash(payload), **payload,
        }

    def manager_complete_receipt(self, wake):
        decision = {
            "schema": DECISION_SCHEMA, "event_id": wake["event_id"],
            "session_id": "session", "manager_epoch": 1,
            "result_message_id": wake["result_message_id"],
            "result_digest": wake["result_digest"], "kind": "COMPLETE",
            "summary": "The durable chain is complete.", "successors": [],
        }
        reply = DECISION_START + _canonical(decision) + DECISION_END
        payload = {"failureEvidence": None, "ok": True, "reply": reply,
                   "error": "", "ambiguous": False}
        return {
            "id": wake["delivery_id"], "from": "MANAGER",
            "messageHash": wake["result_digest"],
            "targetBindingReceipt": "manager-binding",
            "instanceId": "manager-instance", "sessionId": "manager-session",
            "attachmentGeneration": 1, "tabId": 11,
            "conversationKey": "manager-conversation",
            "resultState": "RESULT_PERSISTED", "ackState": "UNACKED",
            "resultHash": rcc_result_hash(payload), **payload,
        }

    def test_follow_up_dispatch_result_commit_and_ack_loss_recovery(self):
        first = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(1, first["sent"])
        self.assertEqual(1, self.relay.write_count)
        self.assertEqual("DELIVERED", self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"]
        )["state"])
        self.relay.receipt = self.worker_receipt()
        self.relay.ack_unknown_once = True
        second = self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(1, second["deferred"])
        row = self.row("orchestration_dispatch_outbox", "delivery_id",
                       self.outbox["delivery_id"])
        self.assertEqual("ACKNOWLEDGED", row["state"])
        self.assertIsNone(row["completed_at"])
        self.assertEqual("APPLIED", self.row(
            "orchestration_assignments", "assignment_id", self.assignment_id
        )["state"])
        third = self.dispatcher.run_once(now=self.now + 4)
        self.assertEqual(1, third["acked"])
        self.assertIsNotNone(self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"]
        )["completed_at"])
        self.assertEqual(1, self.relay.send_count)
        wakes = self.store._connect()
        try:
            count = wakes.execute(
                "SELECT COUNT(*) FROM orchestration_manager_wakes WHERE assignment_id=?",
                (self.assignment_id,),
            ).fetchone()[0]
        finally:
            wakes.close()
        self.assertEqual(1, count)
        wake = self.row("orchestration_manager_wakes", "assignment_id", self.assignment_id)
        self.assertEqual("DELIVERED", wake["state"])
        self.assertEqual(1, self.relay.wake_send_count)
        self.relay.receipt = self.manager_complete_receipt(wake)
        manager_recovery = ManagerDecisionRecovery(self.service, self.relay)
        completed = manager_recovery.run_once(now=self.now + 5)
        self.assertEqual(1, completed["committed"])
        self.assertEqual(1, completed["acked"])
        decided = self.row("orchestration_manager_wakes", "event_id", wake["event_id"])
        self.assertIsNotNone(decided["decision_id"])
        self.assertIsNotNone(decided["acknowledged_at"])

    def test_post_write_unknown_never_resends_and_exact_result_recovers(self):
        self.relay.send_unknown = True
        first = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(1, first["sent"])
        self.assertEqual("UNKNOWN", self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"]
        )["state"])
        second = self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(1, second["deferred"])
        self.assertEqual(1, self.relay.send_count)
        self.relay.receipt = self.worker_receipt()
        third = self.dispatcher.run_once(now=self.now + 4)
        self.assertEqual(1, third["committed"])
        self.assertEqual(1, self.relay.send_count)

    def test_manager_wake_unknown_is_never_resent(self):
        self.dispatcher.run_once(now=self.now + 2)
        self.relay.receipt = self.worker_receipt()
        self.relay.wake_unknown = True
        self.dispatcher.run_once(now=self.now + 3)
        wake = self.row("orchestration_manager_wakes", "assignment_id", self.assignment_id)
        self.assertEqual("UNKNOWN", wake["state"])
        self.assertEqual(1, self.relay.wake_send_count)
        self.dispatcher.run_once(now=self.now + 4)
        self.assertEqual(1, self.relay.wake_send_count)

    def test_manager_wake_write_boundary_fences_takeover(self):
        self.dispatcher.run_once(now=self.now + 2)
        self.relay.receipt = self.worker_receipt()

        def takeover():
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE orchestration_sessions SET manager_epoch=2 "
                    "WHERE session_id='session'"
                )

        self.relay.before_wake_callback = takeover
        result = self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(1, result["rejected"])
        wake = self.row("orchestration_manager_wakes", "assignment_id", self.assignment_id)
        self.assertEqual("PENDING", wake["state"])

    def test_manager_wake_write_boundary_fences_attachment_replacement(self):
        self.dispatcher.run_once(now=self.now + 2)
        self.relay.receipt = self.worker_receipt()

        def replace_attachment():
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE orchestration_attachments SET active=0 "
                    "WHERE attachment_id='manager-att' AND generation=1"
                )

        self.relay.before_wake_callback = replace_attachment
        result = self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(1, result["rejected"])
        wake = self.row("orchestration_manager_wakes", "assignment_id", self.assignment_id)
        self.assertEqual("STALE", wake["state"])

    def test_manager_wake_pipe_unavailable_remains_recoverable_pending(self):
        self.dispatcher.run_once(now=self.now + 2)
        self.relay.receipt = self.worker_receipt()

        original = self.relay.request

        def unavailable_wake(**kwargs):
            if kwargs["command"] == "send-wakeback":
                raise RelayUnavailable("offline before open")
            return original(**kwargs)

        self.relay.request = unavailable_wake
        result = self.dispatcher.run_once(now=self.now + 3)
        self.assertGreaterEqual(result["deferred"], 1)
        wake = self.row("orchestration_manager_wakes", "assignment_id", self.assignment_id)
        self.assertEqual("PENDING", wake["state"])

    def test_manager_wake_keyset_cursor_prevents_ninth_wake_starvation(self):
        event_ids = [f"wake.fair.{index:02d}" for index in range(9)]
        with self.store.transaction() as db:
            base = db.execute(
                "SELECT * FROM orchestration_manager_wakes WHERE event_id=?",
                (self.event["event_id"],),
            ).fetchone()
            columns = list(base.keys())
            producer = db.execute(
                "SELECT * FROM orchestration_assignments WHERE assignment_id='producer'"
            ).fetchone()
            assignment_columns = list(producer.keys())
            for index, event_id in enumerate(event_ids):
                assignment_id = f"fair-assignment-{index:02d}"
                assignment_value = dict(producer)
                assignment_value["assignment_id"] = assignment_id
                db.execute(
                    "INSERT INTO orchestration_assignments ("
                    + ",".join(assignment_columns) + ") VALUES("
                    + ",".join("?" for _ in assignment_columns) + ")",
                    tuple(assignment_value[column] for column in assignment_columns),
                )
                value = dict(base)
                value.update({
                    "event_id": event_id, "state": "PENDING", "delivery_id": None,
                    "assignment_id": assignment_id,
                    "result_message_id": f"fair-result-{index:02d}",
                    "delivered_at": None, "acknowledged_at": None,
                    "decision_id": None, "result_hash": None,
                    "result_ack_state": "NOT_REQUESTED",
                    "result_acknowledged_at": None,
                })
                db.execute(
                    "INSERT INTO orchestration_manager_wakes (" + ",".join(columns)
                    + ") VALUES(" + ",".join("?" for _ in columns) + ")",
                    tuple(value[column] for column in columns),
                )
            db.execute(
                "UPDATE orchestration_dispatch_outbox SET state='NOT_APPLIED',"
                "completed_at=? WHERE delivery_id=?",
                (self.now + 1, self.outbox["delivery_id"]),
            )
        self.relay.unavailable_wake_ids = {
            "orch.wake." + hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:32]
            for event_id in event_ids[:8]
        }
        first = self.dispatcher.run_once(limit=8, now=self.now + 2)
        self.assertEqual(0, first["manager_wakes"])
        second = self.dispatcher.run_once(limit=8, now=self.now + 3)
        self.assertGreaterEqual(second["manager_wakes"], 1)
        self.assertEqual("DELIVERED", self.row(
            "orchestration_manager_wakes", "event_id", event_ids[8],
        )["state"])

    def test_pre_write_unavailable_is_not_applied_with_zero_writes(self):
        self.relay.unavailable = True
        result = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(1, result["not_applied"])
        self.assertEqual(0, self.relay.write_count)
        self.assertEqual("NOT_APPLIED", self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"]
        )["state"])
        self.assertEqual("NOT_APPLIED", self.row(
            "orchestration_assignments", "assignment_id", self.assignment_id
        )["state"])

    def test_policy_change_and_work_handoff_fail_before_send(self):
        self.policy_path.write_text(
            '[policy]\nnormal_actions=[]\napproval_actions=["read"]\n', encoding="utf-8",
        )
        denied = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(1, denied["rejected"])
        self.assertEqual(0, self.relay.send_count)
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["read","orchestrate"]\napproval_actions=[]\n', encoding="utf-8",
        )
        with self.store.transaction() as db:
            db.execute("UPDATE works SET assignment_epoch=2 WHERE work_id='work'")
        handed = self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(0, self.relay.send_count)
        self.assertIn(handed["rejected"], {0, 1})

    def test_withdrawn_outer_orchestration_policy_blocks_new_sends_not_readback(self):
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["read"]\napproval_actions=[]\n', encoding="utf-8",
        )
        denied = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(1, denied["rejected"])
        self.assertEqual(0, self.relay.send_count)
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["read","orchestrate"]\napproval_actions=[]\n', encoding="utf-8",
        )
        self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(1, self.relay.send_count)
        self.relay.receipt = self.worker_receipt()
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["read"]\napproval_actions=[]\n', encoding="utf-8",
        )
        recovered = self.dispatcher.run_once(now=self.now + 4)
        self.assertEqual(1, recovered["acked"])
        self.assertEqual(1, self.relay.send_count)
        self.assertEqual(0, self.relay.wake_send_count)

    def test_worker_lookup_requires_exact_outer_and_public_receipt_bindings(self):
        self.dispatcher.run_once(now=self.now + 2)
        base = self.worker_receipt()
        for response_updates, receipt_updates in (
            ({"ok": False}, {}),
            ({"relayId": "wrong-delivery"}, {}),
            ({}, {"from": "WRONG"}),
            ({}, {"tabId": "13"}),
            ({}, {"tabId": True}),
            ({}, {"attachmentGeneration": "1"}),
            ({}, {"attachmentGeneration": True}),
            ({}, {"targetBindingReceipt": "wrong-binding"}),
            ({}, {"resultHash": "0" * 64}),
        ):
            self.relay.result_response_updates = response_updates
            self.relay.receipt = {**base, **receipt_updates}
            result = self.dispatcher.run_once(now=self.now + 3)
            if response_updates:
                self.assertEqual(1, result["deferred"])
            else:
                self.assertEqual(1, result["rejected"])
            row = self.row("orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"])
            self.assertEqual("DELIVERED", row["state"])
            self.assertEqual("DISPATCHING", self.row(
                "orchestration_assignments", "assignment_id", self.assignment_id,
            )["state"])

    def test_authority_change_at_write_fence_does_not_terminalize_assignment(self):
        def handoff():
            with self.store.transaction() as db:
                db.execute("UPDATE works SET assignment_epoch=2 WHERE work_id='work'")

        self.relay.before_callback = handoff
        result = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(1, result["rejected"])
        self.assertEqual(0, self.relay.write_count)
        self.assertEqual("DISPATCHING", self.row(
            "orchestration_assignments", "assignment_id", self.assignment_id,
        )["state"])
        self.assertEqual("RESERVED", self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"],
        )["state"])

    def test_stale_work_does_not_renew_manager_lease(self):
        expiry = time.time() + 5
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_durable_leases SET expires_at=? "
                "WHERE session_id='session'", (expiry,),
            )
            db.execute("UPDATE works SET assignment_epoch=2 WHERE work_id='work'")
        self.dispatcher.run_once(now=time.time())
        self.assertEqual(expiry, self.row(
            "orchestration_durable_leases", "session_id", "session",
        )["expires_at"])

    def test_event_signal_is_hint_and_bounded_poll_is_authoritative(self):
        self.assertFalse(self.dispatcher.wait(0.0))

    def test_committed_manager_outbox_emits_only_post_commit_hint(self):
        notifications = []
        recovery = ManagerDecisionRecovery(
            self.service, self.relay, on_deliveries=lambda: notifications.append(True),
        )
        self.assertTrue(recovery._acquire_recovery_lease(now=self.now + 2))
        replay = recovery.handle_receipt(
            event_id=self.event["event_id"], receipt=self.manager_receipt,
            now=self.now + 2,
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual([True], notifications)

    def test_tampered_hash_and_rotated_attachment_fail_closed(self):
        self.dispatcher.run_once(now=self.now + 2)
        receipt = self.worker_receipt()
        receipt["reply"] += "tampered"
        self.relay.receipt = receipt
        rejected = self.dispatcher.run_once(now=self.now + 3)
        self.assertEqual(1, rejected["rejected"])
        self.assertEqual("DELIVERED", self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"]
        )["state"])
        self.assertEqual(1, self.relay.send_count)
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=0 "
                       "WHERE attachment_id='next-att' AND generation=1")
        rotated = self.dispatcher.run_once(now=self.now + 4)
        self.assertEqual(1, rotated["rejected"])
        self.assertEqual(1, self.relay.send_count)

    def test_expired_dispatcher_takeover_recovers_reserved_without_sending(self):
        # Simulate a crash after the atomic reservation but before pipe open.
        now = self.now + 2
        self.assertTrue(self.dispatcher._acquire(now))
        with self.store.transaction() as db:
            lease = db.execute(
                "SELECT token FROM orchestration_durable_leases WHERE session_id='session'"
            ).fetchone()
            from bct.core.durable_pr2 import reserve_delivery
            reserve_delivery(
                self.store, delivery_id=self.outbox["delivery_id"], epoch=1,
                token=lease["token"], now=now, _db=db,
            )
            db.execute(
                "UPDATE orchestration_manager_recovery_leases SET expires_at=? "
                "WHERE lease_name='worker-dispatcher'", (now - 1,),
            )
        replacement = WorkerDispatchRecovery(self.service, self.relay)
        recovered = replacement.run_once(now=now + 1)
        self.assertEqual(1, recovered["deferred"])
        self.assertEqual(0, self.relay.send_count)
        self.assertEqual("PENDING", self.row(
            "orchestration_dispatch_outbox", "delivery_id", self.outbox["delivery_id"]
        )["state"])
        sent = replacement.run_once(now=now + 2)
        self.assertEqual(1, sent["sent"])
        self.assertEqual(1, self.relay.send_count)

    def test_parallel_dispatcher_is_fenced(self):
        contender = WorkerDispatchRecovery(self.service, self.relay)
        first = self.dispatcher.run_once(now=self.now + 2)
        second = contender.run_once(now=self.now + 3)
        self.assertEqual(1, first["sent"])
        self.assertFalse(second["lease_owned"])
        self.assertEqual(1, self.relay.send_count)

    def test_core_restart_rotates_only_current_expired_manager_lease(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_durable_leases SET expires_at=? "
                "WHERE session_id='session'", (self.now - 1,),
            )
        restarted = WorkerDispatchRecovery(
            OrchestrationService(
                Store(self.store.path), manager_wake_receipt_v2_enabled=True,
                policy=Policy(self.policy_path),
            ), self.relay,
        )
        result = restarted.run_once(now=self.now + 70)
        self.assertEqual(1, result["sent"])
        self.assertEqual(1, self.relay.send_count)

    def test_manager_takeover_fences_old_outbox_without_send(self):
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=2 "
                       "WHERE session_id='session'")
        result = self.dispatcher.run_once(now=self.now + 2)
        self.assertEqual(0, result["checked"])
        self.assertEqual(0, self.relay.send_count)
        self.dispatcher.notify()
        self.assertTrue(self.dispatcher.wait(0.0))
        self.assertFalse(self.dispatcher.wait(0.0))


if __name__ == "__main__":
    unittest.main()
