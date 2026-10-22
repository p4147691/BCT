from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.chat_stream_checkpoint import ChatStreamCheckpoint
from bct.core.chat_stream_rcc_watch import ChatStreamRccWatch
from bct.core.models import ConflictError, Outcome, Principal, Work
from bct.core.store import Store
from bct.integrations.rcc import RelayUnavailable
from bct.service import BCT

KEY = "6ad96afd-f3ac-83e8-8eb6-a28b4c958364"
OTHER = "6ad7ff62-fa64-83ee-a485-1138f1538e53"
INSTANCE = "6174664e1c1b4e6db1d4729c841db3c9"
SHA = "e22ad5ce2e0a465d7ce631920a8b46afc376fdd7"


class FakeRcc:
    def __init__(self):
        self.calls = []
        self.session = "s1"
        self.endpoints = []
        self.unavailable = False

    def set_connection(self, *, disconnected: bool, generating: bool = False,
                       key=KEY, presence="OPEN", reason="chatgpt-connection-banner"):
        self.endpoints = [{
            "conversationKey": key, "presence": presence, "generating": generating,
            "connection": {"disconnected": disconnected, "reason": reason,
                           "message": "untrusted page content"},
        }]

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.unavailable:
            raise RelayUnavailable("temporary pipe outage")
        return {"ok": True, "state": {"instanceId": INSTANCE,
            "sessionId": self.session, "endpoints": list(self.endpoints)}}


class ChatStreamRccWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state.sqlite")
        self.work = self.store.create_work(Work(
            "owned-work", "safe stream", (str(self.root),),
            frozenset({"orchestrate"}), "operator",
        ))
        self.fake = FakeRcc()
        self.watch = ChatStreamRccWatch(self.store, self.fake)
        self.checkpoint = ChatStreamCheckpoint(self.store)

    def source(self, outcome="APPLIED"):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("source-op", self.work.work_id, "operator", "digest",
                 "relay_browser", "worker", "FINISHED", outcome,
                 '{"work":"scoped"}', None, 1, "policy", 1., 1.),
            )
        self.checkpoint.save(
            work=self.work, stream_id="stream-1", sequence=0,
            step_id="worker-step", source_operation_id="source-op",
            source_release_sha=SHA, next_step="inspect manager output",
        )

    def bind(self):
        return self.watch.bind(
            work=self.work, stream_id="stream-1", instance_id=INSTANCE,
            conversation_key=KEY,
        )

    def test_no_binding_means_no_rcc_poll(self):
        self.assertEqual([], self.watch.poll_once())
        self.assertEqual([], self.fake.calls)

    def test_exact_binding_requires_scoped_checkpoint_and_is_immutable(self):
        with self.assertRaisesRegex(ConflictError, "STREAM_WATCH_CHECKPOINT_REQUIRED"):
            self.bind()
        self.source()
        self.assertFalse(self.bind()["duplicate"])
        self.assertTrue(self.bind()["duplicate"])
        with self.assertRaisesRegex(ConflictError, "STREAM_WATCH_BINDING_IMMUTABLE"):
            self.watch.bind(work=self.work, stream_id="stream-1",
                            instance_id=INSTANCE, conversation_key=OTHER)
        self.assertEqual("UNOBSERVED", self.watch.status(
            work=self.work, stream_id="stream-1")["last_state"])
        self.assertEqual([], self.fake.calls)

    def test_disconnected_reconnected_emits_once_and_inspects_original_receipt(self):
        self.source()
        self.bind()
        self.fake.set_connection(disconnected=False, generating=True)
        self.assertEqual([], self.watch.poll_once(), "ordinary generating is not a disconnection")
        self.fake.set_connection(disconnected=True, generating=True)
        disconnected = self.watch.poll_once()
        self.assertEqual(1, len(disconnected))
        self.assertEqual("DISCONNECTED", disconnected[0]["signal"])
        self.assertEqual([], self.watch.poll_once(), "repeat state is not a new event")
        self.fake.set_connection(disconnected=False, generating=True)
        recovered = self.watch.poll_once()
        self.assertEqual(1, len(recovered))
        self.assertEqual("CLIENT_RECONNECTED", recovered[0]["signal"])
        self.assertEqual("READY_TO_PROPOSE_NEXT_STEP",
                         recovered[0]["resume_inspection"]["decision"])
        self.assertEqual("inspect manager output",
                         recovered[0]["resume_inspection"]["next_step_proposal"])
        self.assertFalse(recovered[0]["will_execute"])
        self.assertFalse(recovered[0]["will_resend"])
        self.assertEqual([], self.watch.poll_once())
        status = self.watch.status(work=self.work, stream_id="stream-1")
        self.assertEqual("CLIENT_RECONNECTED", status["last_rcc_signal"])
        self.assertEqual("READY_TO_PROPOSE_NEXT_STEP",
                         status["resume_inspection"]["decision"])
        view = self.checkpoint.inspect(work=self.work, stream_id="stream-1")
        self.assertEqual(["DISCONNECTED", "CLIENT_RECONNECTED"],
                         [r["signal"] for r in view["client_transport_reports"]])
        self.assertTrue(all("message" not in r for r in view["client_transport_reports"]))
        db = self.store._connect()
        try:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM operations").fetchone()[0])
        finally:
            db.close()

    def test_unknown_still_blocks_after_reconnect(self):
        self.source(outcome="UNKNOWN")
        self.bind()
        self.fake.set_connection(disconnected=True)
        self.watch.poll_once()
        self.fake.set_connection(disconnected=False)
        events = self.watch.poll_once()
        self.assertEqual("STOP_UNKNOWN_NO_RESEND",
                         events[0]["resume_inspection"]["decision"])
        self.assertIsNone(events[0]["resume_inspection"]["next_step_proposal"])

    def test_outage_and_missing_or_ambiguous_endpoint_are_not_reconnect(self):
        self.source()
        self.bind()
        self.fake.set_connection(disconnected=True)
        self.watch.poll_once()
        self.fake.unavailable = True
        self.assertEqual([], self.watch.poll_once())
        self.fake.unavailable = False
        self.fake.set_connection(disconnected=False, key=OTHER)
        self.assertEqual([], self.watch.poll_once())
        same = dict(self.fake.endpoints[0])
        self.fake.endpoints = [{**same, "conversationKey": KEY},
                               {**same, "conversationKey": KEY}]
        self.assertEqual([], self.watch.poll_once())
        self.assertEqual("DISCONNECTED", self.watch.status(
            work=self.work, stream_id="stream-1")["last_state"])

    def test_session_replacement_is_not_chatgpt_reconnection(self):
        self.source()
        self.bind()
        self.fake.set_connection(disconnected=True)
        self.watch.poll_once()
        self.fake.session = "new-rcc-session"
        self.fake.set_connection(disconnected=False)
        self.assertEqual([], self.watch.poll_once())
        new_status = self.watch.status(work=self.work, stream_id="stream-1")
        self.assertEqual("CONNECTED", new_status["last_state"])
        self.assertIsNone(new_status["last_rcc_signal"])
        self.assertNotIn("resume_inspection", new_status)
        self.assertEqual(["DISCONNECTED"], [
            i["signal"] for i in self.checkpoint.inspect(
                work=self.work, stream_id="stream-1")["client_transport_reports"]
        ])

    def test_durable_watch_across_process_restart_does_not_duplicate(self):
        self.source()
        self.bind()
        self.fake.set_connection(disconnected=True)
        first = self.watch.poll_once()
        replacement = ChatStreamRccWatch(
            Store(self.root / "state.sqlite"), self.fake)
        self.assertEqual([], replacement.poll_once())
        self.fake.set_connection(disconnected=False)
        recovered = replacement.poll_once()
        self.assertEqual(1, len(recovered))
        self.assertEqual("CLIENT_RECONNECTED", recovered[0]["signal"])
        self.assertEqual([], replacement.poll_once())
        self.assertNotEqual(first[0]["incident_id"], recovered[0]["incident_id"])

    def test_work_assignment_change_disables_old_watch(self):
        self.source()
        self.bind()
        self.fake.set_connection(disconnected=True)
        self.watch.poll_once()
        self.fake.set_connection(disconnected=False)
        previous_calls = len(self.fake.calls)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE works SET assignment_epoch=assignment_epoch+1 "
                "WHERE work_id=?", (self.work.work_id,),
            )
        self.assertEqual([], self.watch.poll_once())
        self.assertEqual(previous_calls, len(self.fake.calls))
        with self.assertRaisesRegex(ConflictError, "STREAM_WORK_FENCE_CHANGED"):
            self.bind()
        self.assertEqual(["DISCONNECTED"], [
            r["signal"] for r in self.checkpoint.inspect(
                work=self.store.get_work(self.work.work_id),
                stream_id="stream-1")["client_transport_reports"]
        ])

    def test_orchestrate_requires_authorized_exact_bind(self):
        policy = self.root / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        bct = BCT(state_path=self.root / "service.sqlite", policy_path=policy)
        principal = Principal("operator", "test", frozenset({"orchestrate"}))
        bct.create_work(work_id="bound", request_summary="bound",
                        roots=[str(self.root)], actions=["orchestrate"],
                        principal=principal)
        with bct.store.transaction() as db:
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("source-op", "bound", "operator", "digest", "relay_browser",
                 "target", "FINISHED", "APPLIED", "{}", None, 1, "policy", 1., 1.),
            )
        saved = bct.operations.run(
            principal=principal, work_id="bound", operation_id="saved-1",
            capability="orchestrate", arguments={
                "operation":"chat-stream-checkpoint","session_id":"stream-1",
                "sequence":0,"step_id":"worker","source_operation_id":"source-op",
                "source_release_sha":SHA,"next_step":"read manager",
            })
        self.assertEqual(Outcome.APPLIED, saved.outcome)
        bound = bct.operations.run(
            principal=principal, work_id="bound", operation_id="bind-1",
            capability="orchestrate", arguments={
                "operation":"chat-stream-rcc-watch-bind","session_id":"stream-1",
                "instance_id":INSTANCE,"conversation_key":KEY,
            })
        self.assertEqual(Outcome.APPLIED,bound.outcome)
        status = bct.operations.run(
            principal=principal, work_id="bound", operation_id="status-1",
            capability="orchestrate", arguments={
                "operation":"chat-stream-rcc-watch-status","session_id":"stream-1",
            })
        self.assertEqual(Outcome.APPLIED,status.outcome)
        self.assertEqual(KEY,status.output["chat_stream"]["conversation_key"])
        self.assertFalse(status.output["chat_stream"]["will_resend"])


if __name__ == "__main__":
    unittest.main()
