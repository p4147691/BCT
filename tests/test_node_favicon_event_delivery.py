"""Core committed-label event and RCC receipt/identity regression (offline only)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.conversation_network import (
    configure_conversation_scope, ensure_observed_node_labels, upsert_conversation,
)
from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.features.rcc import RelayBrowserFeature
from bct.node_label_notifications import NodeLabelNotifier

A = "6ae269f6-130c-83ee-9384-dffa2d2a946d"
B = "6ae295f6-8090-83e8-b444-02d46f637c20"
INSTANCE = "a" * 32
SESSION = "b" * 32


class FakeClient:
    def __init__(self, *, endpoint_uuid=A, duplicates=False, session=SESSION):
        endpoint = lambda uuid, tab: {
            "tabId": tab, "windowId": 22, "conversationKey": uuid,
            "presence": "OPEN", "url": "https://chatgpt.com/c/" + uuid,
        }
        self.state = {"ok": True, "state": {
            "instanceId": INSTANCE, "sessionId": session,
            "endpoints": [endpoint(endpoint_uuid, 71)] + (
                [endpoint(endpoint_uuid, 72)] if duplicates else []
            ),
        }}
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.state


class Ops:
    def __init__(self, *, failed=False):
        self.calls = []
        self.failed = failed

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.failed:
            raise RuntimeError("UNKNOWN_AFTER_DISPATCH")
        return SimpleNamespace(as_dict=lambda: {"outcome": "APPLIED"})


class NodeFaviconEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        self.wakes = []
        self.store.set_node_label_notifier(self._wake)

    def _wake(self, event_id):
        # Callback can observe the committed event from another DB connection.
        record = self.store.node_label_notification(event_id)
        self.assertEqual(record["status"], "PENDING")
        self.wakes.append(event_id)

    def _event(self):
        return self.store.pending_node_label_notifications()[0]["event_id"]

    def _runner(self, client=None, ops=None):
        ops = ops or Ops()
        fake = SimpleNamespace(store=self.store, operations=ops)
        notifier = NodeLabelNotifier(fake, Principal("bct-test", "test", frozenset({"relay_browser"})),
                                     client=client or FakeClient(), discover=lambda: [INSTANCE])
        return notifier, ops

    def test_three_real_assignment_paths_produce_exactly_one_committed_event(self):
        upsert_conversation(self.store, conversation_key=A, display_name="first")
        self.assertEqual(len(self.wakes), 1)
        upsert_conversation(self.store, conversation_key=A, display_name="rename")
        self.assertEqual(len(self.wakes), 1)
        ensure_observed_node_labels(self.store, conversations=[(A, "same"), (B, "new")])
        self.assertEqual(len(self.wakes), 2)
        configure_conversation_scope(self.store, conversation_key=B, display_name="name",
                                     scope_name="scope", role_tags=["Manager"])
        self.assertEqual(len(self.wakes), 2, "role/scope changes never create label events")
        with self.store.transaction() as db:
            kinds = list(db.execute(
                "SELECT kind FROM events WHERE kind='NODE_LABEL_ASSIGNED' ORDER BY event_id"
            ))
        self.assertEqual(len(kinds), 2)

    def test_scope_registration_is_third_producer(self):
        configure_conversation_scope(self.store, conversation_key=A, display_name="new")
        self.assertEqual(len(self.wakes), 1)

    def test_monitor_observation_wakes_only_on_real_roster_edge(self):
        upsert_conversation(self.store, conversation_key=A, display_name="new")
        self.assertEqual(len(self.wakes), 1)
        original = [(INSTANCE, SESSION, 71, 22, A)]
        self.store.wake_node_label_notifications([A], topology=original)
        self.assertEqual(len(self.wakes), 2)
        self.store.wake_node_label_notifications([A], topology=original)
        self.assertEqual(len(self.wakes), 2, "same Monitor GET must not trigger a new pipe read")
        changed = [(INSTANCE, "c" * 32, 71, 22, A)]
        self.store.wake_node_label_notifications([A], topology=changed)
        self.assertEqual(len(self.wakes), 3, "RCC reconnect produces one event wake")

    def test_uncommitted_label_event_rolls_back(self):
        try:
            with self.store.transaction() as db:
                self.store.record_node_label_assignment(db, A, 18)
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        self.assertFalse(self.store.pending_node_label_notifications())
        self.assertEqual(self.wakes, [])

    def test_exact_operation_receipt_on_delivered_event(self):
        upsert_conversation(self.store, conversation_key=A, display_name="new")
        event_id = self._event()
        runner, ops = self._runner()
        self.assertEqual(runner.deliver(event_id), "ACKED")
        row = self.store.node_label_notification(event_id)
        self.assertEqual(row["status"], "ACKED")
        self.assertEqual(len(ops.calls), 1)
        payload = ops.calls[0]["arguments"]
        self.assertEqual(payload["conversation_key"], A)
        self.assertEqual((payload["tab_id"], payload["window_id"], payload["session_id"]),
                         (71, 22, SESSION))
        self.assertEqual(ops.calls[0]["operation_id"], f"node-label.{event_id}.71")
        self.assertEqual(runner.deliver(event_id), "NO_PENDING_EVENT")
        self.assertEqual(len(ops.calls), 1)

    def test_mismatched_uuid_and_duplicate_tabs_fail_closed_without_claim(self):
        upsert_conversation(self.store, conversation_key=A, display_name="new")
        eid = self._event()
        for client in (FakeClient(endpoint_uuid=B), FakeClient(duplicates=True)):
            runner, ops = self._runner(client)
            self.assertEqual(runner.deliver(eid), "TARGET_ABSENT_OR_AMBIGUOUS")
            self.assertEqual(ops.calls, [])
        self.assertEqual(self.store.node_label_notification(eid)["status"], "PENDING")

    def test_ambiguous_dispatched_effect_stays_unknown_and_is_not_replayed(self):
        upsert_conversation(self.store, conversation_key=A, display_name="new")
        eid = self._event()
        runner, ops = self._runner(ops=Ops(failed=True))
        self.assertEqual(runner.deliver(eid), "UNKNOWN")
        self.assertEqual(self.store.node_label_notification(eid)["status"], "UNKNOWN")
        self.assertEqual(runner.deliver(eid), "NO_PENDING_EVENT")
        self.assertEqual(len(ops.calls), 1)

    def test_rcc_feature_rejects_fabricated_event_and_accepts_claimed_exact_event(self):
        upsert_conversation(self.store, conversation_key=A, display_name="new")
        eid = self._event()
        feature = RelayBrowserFeature(client=FakeClient(), store=self.store)
        work = Work("test", "test", (self.tmp.name,), frozenset({"relay_browser"}), "bct-test")
        args = {"command": "node-label-notify", "instance_id": INSTANCE,
                "session_id": SESSION, "tab_id": 71, "window_id": 22,
                "conversation_key": A, "event_id": eid}
        with self.assertRaises(Exception):
            feature.prepare(work=work, arguments=args)
        self.assertTrue(self.store.claim_node_label_notification(eid, f"node-label.{eid}.71"))
        prepared = feature.prepare(work=work, arguments=args)
        self.assertEqual(prepared.arguments["extra"]["conversationKey"], A)
        with self.assertRaises(Exception):
            feature.prepare(work=work, arguments={**args, "conversation_key": B})


if __name__ == "__main__":
    unittest.main()
