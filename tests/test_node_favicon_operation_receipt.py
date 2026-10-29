"""Actual BCT Work + Operation receipt across the committed-label notification."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.conversation_network import upsert_conversation
from bct.features.rcc import RelayBrowserFeature
from bct.node_label_notifications import NodeLabelNotifier, ensure_notification_work
from bct.service import BCT

UUID = "6ae269f6-130c-83ee-9384-dffa2d2a946d"
INSTANCE = "a" * 32
SESSION = "b" * 32


class PipeFixture:
    def __init__(self, missing_ack=False):
        self.calls = []
        self.missing_ack = missing_ack

    def request(self, **args):
        self.calls.append(args)
        if args["command"] == "state":
            return {"ok": True, "state": {
                "instanceId": INSTANCE, "sessionId": SESSION,
                "endpoints": [{
                    "presence": "OPEN", "tabId": 71, "windowId": 22,
                    "conversationKey": UUID, "url": "https://chatgpt.com/c/" + UUID,
                }],
            }}
        assert args["command"] == "node-label-notify"
        if self.missing_ack:
            return {"ok": True, "state": "DELIVERED"}
        extra = args["extra"]
        return {
            "ok": True, "type": "host:result", "state": "DELIVERED",
            "operationId": args["request_id"],
            "instanceId": INSTANCE, "sessionId": extra["sessionId"],
            "tabId": extra["tabId"], "windowId": extra["windowId"],
            "conversationKey": extra["conversationKey"], "eventId": extra["eventId"],
        }


class NodeFaviconOperationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        policy = self.root / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=policy)
        self.principal = ensure_notification_work(self.bct, self.root)
        upsert_conversation(self.bct.store, conversation_key=UUID, display_name="fixture")
        self.event_id = self.bct.store.pending_node_label_notifications()[0]["event_id"]

    def run_case(self, missing_ack):
        client = PipeFixture(missing_ack=missing_ack)
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(
            client, store=self.bct.store,
        )
        notifier = NodeLabelNotifier(
            self.bct, self.principal, client=client, discover=lambda: [INSTANCE],
        )
        result = notifier.deliver(self.event_id)
        receipt_id = f"node-label.{self.event_id}.71"
        db = self.bct.store._connect()
        try:
            operation = db.execute(
                "SELECT state,outcome FROM operations WHERE operation_id=?", (receipt_id,),
            ).fetchone()
        finally:
            db.close()
        return result, operation, notifier, client

    def test_applied_exact_receipt_and_durable_ack(self):
        result, op, notifier, client = self.run_case(False)
        self.assertEqual("ACKED", result)
        self.assertEqual("APPLIED", op["outcome"])
        self.assertEqual("ACKED", self.bct.store.node_label_notification(self.event_id)["status"])
        self.assertEqual("NO_PENDING_EVENT", notifier.deliver(self.event_id))
        self.assertEqual(1, sum(x["command"] == "node-label-notify" for x in client.calls))

    def test_missing_exact_ack_is_unknown_and_never_retried(self):
        result, op, notifier, client = self.run_case(True)
        self.assertEqual("UNKNOWN", result)
        self.assertEqual("UNKNOWN", op["outcome"])
        self.assertEqual("UNKNOWN", self.bct.store.node_label_notification(self.event_id)["status"])
        self.assertEqual("NO_PENDING_EVENT", notifier.deliver(self.event_id))
        self.assertEqual(1, sum(x["command"] == "node-label-notify" for x in client.calls))


if __name__ == "__main__":
    unittest.main()
