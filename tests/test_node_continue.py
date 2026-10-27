from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from bct.core.models import Outcome, Work
from bct.core.store import Store
from bct.features.rcc import RelayBrowserFeature


INSTANCE = "a" * 32
RCC_SESSION = "b" * 32
CONVERSATION = "12345678-1234-1234-1234-123456789abc"


class _Relay:
    def __init__(self):
        self.generating = True
        self.sent: list[dict] = []

    def request(self, *, instance_id, request_id, command, text="", extra=None, timeout_s=30, **_ignored):
        extra = extra or {}
        if command == "state":
            # The first observation is busy.  The bounded wait must observe
            # the same tab becoming idle before it attempts a submission.
            busy = self.generating
            self.generating = False
            return {"ok": True, "state": {"instanceId": instance_id,
                "sessionId": RCC_SESSION, "tabs": [{"tabId": 71, "windowId": 70,
                "conversationKey": CONVERSATION, "generating": busy}]}}
        self.assertEqual("send-to-tab", command)
        self.sent.append({"request_id": request_id, "text": text, "extra": extra})
        return {"ok": True, "operationId": request_id, "instanceId": instance_id,
                "sessionId": RCC_SESSION, "tabId": 71, "windowId": 70,
                "state": "SUBMITTED", "submitted": True}

    def assertEqual(self, left, right):
        if left != right:
            raise AssertionError(f"{left!r} != {right!r}")


class NodeContinueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "continue-work", "bounded B to B", (self.temp.name,), frozenset({"relay_browser"}), "p",
        ))
        self.store.create_node(node_id="worker-b", name="Worker B")
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("session-1", self.work.work_id, 1, "objective", "[]", "[]", "{}", 1,
                 None, 0, "ACTIVE", "{}", "LEGACY_RETURN_V1", 1.0, 1.0),
            )
            db.execute("INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                       ("session-1", "worker-b", "WORKER", 1))
            db.execute(
                "INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("attachment-b", 1, "worker-b", "rcc", INSTANCE, RCC_SESSION, 71, 70,
                 CONVERSATION, CONVERSATION, "", "receipt", 1, 1.0),
            )
        self.relay = _Relay()
        self.feature = RelayBrowserFeature(self.relay, store=self.store)

    def tearDown(self):
        self.temp.cleanup()

    def _request(self, operation_id: str, **arguments):
        prepared = self.feature.prepare(work=self.work, arguments={
            "instance_id": INSTANCE, "command": "node-continue", "idle_timeout_s": 1,
            "orchestration_session_id": "session-1", "node_id": "worker-b", **arguments,
        })
        return replace(prepared, operation_id=operation_id)

    def test_open_then_one_bounded_self_turn_waits_for_idle(self):
        opened = self.feature.execute(self._request(
            "continue-open", phase="open", continuation_id="continue-1", text="initial task",
            max_self_turns=1, total_timeout_s=60,
        ))
        self.assertEqual(Outcome.APPLIED, opened.outcome)
        self.assertEqual("ACTIVE", opened.output["continuation"]["state"])
        self.assertEqual(["initial task"], [item["text"] for item in self.relay.sent])

        continued = self.feature.execute(self._request(
            "continue-next", phase="continue", continuation_id="continue-1", text="continue once",
        ))
        self.assertEqual(Outcome.APPLIED, continued.outcome)
        self.assertEqual("BUDGET_EXHAUSTED", continued.output["continuation"]["state"])
        self.assertEqual(1, continued.output["continuation"]["used_self_turns"])
        self.assertEqual(["initial task", "continue once"], [item["text"] for item in self.relay.sent])

    def test_continue_cannot_replace_the_original_budget(self):
        self.feature.execute(self._request(
            "continue-open", phase="open", continuation_id="continue-2", text="initial task",
            max_self_turns=2, total_timeout_s=60,
        ))
        with self.assertRaisesRegex(Exception, "NODE_CONTINUATION_BUDGET_IMMUTABLE"):
            self._request(
                "continue-next", phase="continue", continuation_id="continue-2", text="bad",
                max_self_turns=99,
            )
