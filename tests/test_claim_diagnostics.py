from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from bct.core.store import Store
from bct.core.models import Principal, Work, Outcome


class ClaimDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/"fixture.sqlite")
        self.work=self.store.create_work(Work(
            "fixture-work","fixture",(self.tmp.name,),frozenset({"read"}),"fixture-owner"))
    def tearDown(self):
        self.tmp.cleanup()

    def claim(self, name):
        created, _=self.store.begin_operation(
            operation_id=name, work=self.work, principal_id="fixture-owner",
            request_digest=name, capability="read", target="fixture",
            resources=("fixture:"+name,),policy_revision="fixture")
        self.assertTrue(created)

    def test_old_claim_resolves_without_recent_operations_window(self):
        self.claim("first")
        self.store.finish_operation(operation_id="first",outcome=Outcome.UNKNOWN,
            evidence={"private_payload":"MUST_NOT_LEAK"},error="timeout",release_claims=False)
        for i in range(110):
            name="other"+str(i)
            self.claim(name)
            self.store.finish_operation(operation_id=name,outcome=Outcome.APPLIED,
                evidence={},error=None,release_claims=True)
        self.assertNotIn("first", [o["operation_id"] for o in self.store.monitor_snapshot()["operations"]])
        rows=self.store.claim_diagnostics()
        self.assertEqual(1,len(rows))
        self.assertEqual("UNKNOWN_EFFECT",rows[0]["diagnosis"])
        self.assertFalse(rows[0]["can_auto_release"])
        self.assertNotIn("private_payload",str(rows))
        self.assertEqual("first",rows[0]["operation_id"])

    def test_other_entity_event_with_same_subject_does_not_override_operation_event(self):
        self.claim("shared-id")
        self.store.finish_operation(operation_id="shared-id", outcome=Outcome.UNKNOWN,
            evidence={"private_payload": "PRIVATE"}, error="timeout", release_claims=False)
        with self.store.transaction() as db:
            self.store._event(db, "NODE_UPDATED", "shared-id", {"secret": "NODE_PRIVATE"})
            self.store._event(db, "WORK_CREATED", "shared-id", {"secret": "WORK_PRIVATE"})
        row = self.store.claim_diagnostics()[0]
        self.assertEqual("OPERATION_FINISHED", row["last_event"]["kind"])
        self.assertEqual("UNKNOWN_EFFECT", row["diagnosis"])
        self.assertNotIn("PRIVATE", str(row))
        self.assertFalse(row["can_auto_release"])

    def test_owner_assignment_epoch_mismatch_is_not_attributed(self):
        self.claim("epoch-case")
        with self.store.transaction() as db:
            db.execute("UPDATE resource_claims SET assignment_epoch=assignment_epoch+1 "
                       "WHERE operation_id=?", ("epoch-case",))
            self.store._event(db, "NODE_UPDATED", "epoch-case", {"note": "unrelated"})
        row = self.store.claim_diagnostics()[0]
        self.assertIsNone(row["operation_state"])
        self.assertIsNone(row["last_event"])
        self.assertIsNone(row["executor"])
        self.assertEqual("INSUFFICIENT_EVIDENCE", row["diagnosis"])
        self.assertFalse(row["can_auto_release"])

    def test_running_without_executor_not_claimed_as_executing(self):
        self.claim("running")
        row=self.store.claim_diagnostics()[0]
        self.assertEqual("INSUFFICIENT_EVIDENCE",row["diagnosis"])
        self.assertIsNone(row["executor"])
        self.assertFalse(row["can_auto_release"])

    def test_finished_claimed_not_auto_released(self):
        self.claim("finished")
        self.store.finish_operation(operation_id="finished",outcome=Outcome.APPLIED,
            evidence={},error=None,release_claims=False)
        row=self.store.claim_diagnostics()[0]
        self.assertEqual("FINISHED_CLAIMED",row["diagnosis"])
        self.assertFalse(row["can_auto_release"])
        self.assertEqual("APPLIED",row["outcome"])
