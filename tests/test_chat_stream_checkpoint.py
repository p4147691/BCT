from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.chat_stream_checkpoint import ChatStreamCheckpoint
from bct.core.models import ConflictError, Work, Principal, Outcome
from bct.core.store import Store
from bct.service import BCT


SHA = "92a7feaf6cfc2f6b11af04c17d1e5a863cd0f551"


class ChatStreamCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite")
        self.work = self.store.create_work(Work(
            "stream-work", "stream reconnection", (self.temp.name,),
            frozenset({"orchestrate"}), "operator",
        ))
        self.service = ChatStreamCheckpoint(self.store)

    def receipt(self, operation_id="effect-a", outcome="APPLIED", state="FINISHED"):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, self.work.work_id, self.work.owner_principal_id,
                 "digest-"+operation_id, "relay_browser", "exact-worker",
                 state, outcome, '{"source":"fixture","sha":"x"}',
                 None, self.work.assignment_epoch, "revision", 1., 1.),
            )

    def save(self, operation_id="effect-a", **kwargs):
        return self.service.save(
            work=self.work, stream_id="long-chat-A", sequence=kwargs.get("sequence", 0),
            step_id=kwargs.get("step_id", "send"), source_operation_id=operation_id,
            source_release_sha=SHA, next_step=kwargs.get("next_step", "inspect reply"),
        )

    def view(self):
        return self.service.inspect(work=self.work, stream_id="long-chat-A")

    def test_durable_applied_checkpoint_survives_new_service_object(self):
        self.receipt()
        first = self.save()
        self.assertEqual(first["source_outcome"], "APPLIED")
        self.assertFalse(first["duplicate"])
        self.assertTrue(self.save()["duplicate"])
        result = ChatStreamCheckpoint(Store(self.root / "state.sqlite")).inspect(
            work=self.work, stream_id="long-chat-A")
        self.assertEqual("READY_TO_PROPOSE_NEXT_STEP", result["decision"])
        self.assertEqual("inspect reply", result["next_step_proposal"])
        self.assertFalse(result["will_execute"])
        self.assertFalse(result["will_resend"])
        db = self.store._connect()
        try:
            self.assertEqual(1, db.execute(
                "SELECT COUNT(*) FROM operations").fetchone()[0])
        finally:
            db.close()

    def test_unknown_never_becomes_authorized_after_client_reconnect(self):
        self.receipt(outcome="UNKNOWN")
        self.save()
        self.service.report_transport(work=self.work, stream_id="long-chat-A",
            incident_id="client-timeout-1", signal="STREAM_TIMEOUT")
        self.service.report_transport(work=self.work, stream_id="long-chat-A",
            incident_id="client-connected-2", signal="CLIENT_RECONNECTED")
        result = self.view()
        self.assertEqual("STOP_UNKNOWN_NO_RESEND", result["decision"])
        self.assertIsNone(result["next_step_proposal"])
        self.assertEqual(["STREAM_TIMEOUT", "CLIENT_RECONNECTED"],
            [x["signal"] for x in result["client_transport_reports"]])
        self.assertTrue(all(x["unverified_client_report"]
            for x in result["client_transport_reports"]))
        self.receipt("effect-b")
        with self.assertRaisesRegex(ConflictError, "STREAM_PREVIOUS_EFFECT_NOT_ACCEPTED"):
            self.save("effect-b", sequence=1, step_id="return")

    def test_missing_running_and_failed_operations_fail_closed(self):
        with self.assertRaisesRegex(ConflictError, "STREAM_SOURCE_RECEIPT_NOT_OWNED"):
            self.save("not-recorded")
        self.receipt(state="RUNNING", outcome=None)
        self.save()
        self.assertEqual("WAIT_ORIGINAL_EXECUTION", self.view()["decision"])
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET state='FINISHED',outcome='FAILED' "
                       "WHERE operation_id='effect-a'")
        self.assertEqual("RECEIPT_CHANGED_OR_UNAVAILABLE", self.view()["decision"])

    def test_persisted_unknown_blocks_subsequent_step_even_after_reload(self):
        self.receipt()
        self.save()
        self.receipt("effect-b", "UNKNOWN")
        self.save("effect-b", sequence=1, step_id="manager-return",
                  next_step="finish safely")
        self.assertEqual("STOP_UNKNOWN_NO_RESEND", self.view()["decision"])
        self.receipt("effect-c")
        with self.assertRaisesRegex(ConflictError, "STREAM_PREVIOUS_EFFECT_NOT_ACCEPTED"):
            self.save("effect-c", sequence=2, step_id="next")
        self.assertEqual(2, len(self.view()["steps"]))

    def test_source_tampering_and_duplicate_mutation_never_rewrites(self):
        self.receipt()
        self.save()
        with self.assertRaisesRegex(ConflictError, "STREAM_CHECKPOINT_IMMUTABLE"):
            self.save(next_step="different action")
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET evidence_json=? WHERE operation_id=?",
                       ('{"changed":true}', "effect-a"))
        self.assertEqual("RECEIPT_CHANGED_OR_UNAVAILABLE", self.view()["decision"])
        self.assertIsNone(self.view()["next_step_proposal"])

    def test_scope_and_source_sha_validation(self):
        self.receipt()
        with self.assertRaisesRegex(ValueError, "STREAM_SOURCE_SHA_INVALID"):
            self.service.save(work=self.work,stream_id="chat",sequence=0,
                step_id="one",source_operation_id="effect-a",
                source_release_sha="bad",next_step="later")
        with self.assertRaisesRegex(ValueError, "STREAM_CHECKPOINT_ID_INVALID"):
            self.service.inspect(work=self.work, stream_id="../other")
        other = self.store.create_work(Work("other","other",(self.temp.name,),
                                           frozenset({"orchestrate"}),"different"))
        with self.assertRaisesRegex(ConflictError, "STREAM_SOURCE_RECEIPT_NOT_OWNED"):
            self.service.save(work=other,stream_id="x",sequence=0,
                step_id="one",source_operation_id="effect-a",
                source_release_sha=SHA,next_step="anything")

    def test_transport_incident_immutable_and_independent(self):
        first = self.service.report_transport(work=self.work,stream_id="long-chat-A",
            incident_id="net-a",signal="DISCONNECTED")
        self.assertFalse(first["duplicate"])
        second = self.service.report_transport(work=self.work,stream_id="long-chat-A",
            incident_id="net-a",signal="DISCONNECTED")
        self.assertTrue(second["duplicate"])
        with self.assertRaisesRegex(ConflictError, "STREAM_SIGNAL_IMMUTABLE"):
            self.service.report_transport(work=self.work,stream_id="long-chat-A",
                incident_id="net-a",signal="CONNECTED")
        self.assertEqual("NO_DURABLE_CHECKPOINT",self.view()["decision"])

    def test_sequence_gap_and_step_immutability(self):
        self.receipt()
        with self.assertRaisesRegex(ConflictError, "STREAM_CHECKPOINT_SEQUENCE_GAP"):
            self.save(sequence=2)
        self.save()
        self.receipt("effect-b")
        with self.assertRaisesRegex(ConflictError, "STREAM_CHECKPOINT_SEQUENCE_GAP"):
            self.save("effect-b",sequence=2)
        self.save("effect-b",sequence=1,step_id="next")
        self.assertEqual(2,len(self.view()["steps"]))

    def test_orchestrate_exposes_safe_checkpoint_and_resume(self):
        policy = self.root / "bct.toml"
        policy.write_text('[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n',
                          encoding="utf-8")
        core = BCT(state_path=self.root / "via-bct.sqlite", policy_path=policy)
        principal = Principal("operator","test",frozenset({"orchestrate"}))
        core.create_work(work_id="workflow",request_summary="safe checkpoint",
            roots=[str(self.root)], actions=["orchestrate"],principal=principal)
        with core.store.transaction() as db:
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("already-applied", "workflow","operator","digest","relay_browser",
                 "worker", "FINISHED","APPLIED",'{"ok":true}',None,1,"policy",1.,1.))
        saved=core.operations.run(principal=principal,work_id="workflow",
            operation_id="checkpoint-op-1",capability="orchestrate",
            arguments={"operation":"chat-stream-checkpoint","session_id":"stream-A",
                "sequence":0,"step_id":"worker-result","source_operation_id":"already-applied",
                "source_release_sha":SHA,"next_step":"inspect manager receipt"})
        self.assertEqual(Outcome.APPLIED,saved.outcome)
        resumed=core.operations.run(principal=principal,work_id="workflow",
            operation_id="resume-op-1",capability="orchestrate",
            arguments={"operation":"chat-stream-resume-inspect","session_id":"stream-A"})
        self.assertEqual("READY_TO_PROPOSE_NEXT_STEP",
                         resumed.evidence["decision"])
        self.assertFalse(resumed.output["chat_stream"]["will_execute"])
        self.assertFalse(resumed.output["chat_stream"]["will_resend"])
        self.assertEqual("inspect manager receipt",
            resumed.output["chat_stream"]["next_step_proposal"])
        reported=core.operations.run(principal=principal,work_id="workflow",
            operation_id="report-reconnected-1",capability="orchestrate",
            arguments={"operation":"chat-stream-report","session_id":"stream-A",
                "incident_id":"ui-reconnect-1","signal":"CLIENT_RECONNECTED"})
        self.assertEqual(Outcome.APPLIED,reported.outcome)
        self.assertEqual("READY_TO_PROPOSE_NEXT_STEP",
            reported.output["chat_stream"]["resume_inspection"]["decision"])
        self.assertFalse(reported.output["chat_stream"]["resume_inspection"]["will_execute"])
        self.assertEqual("CLIENT_RECONNECTED",
            reported.output["chat_stream"]["client_report"]["signal"])



if __name__ == "__main__":
    unittest.main()
