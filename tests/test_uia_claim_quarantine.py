from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from bct.core.models import ConflictError, PreconditionError, Work
from bct.core.store import Store
from bct.features.claim_reconciliation import ReadOnlyClaimReconcileFeature


ORIGINAL = "monitor-live-reload-menu-expand-20261020-01"
WORK = "test-ui-expand-work"
DIGEST = "a" * 64
ERROR = "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:DESKTOP_UIA_ACTION_CHANGED_FOREGROUND"
NEW_KEY = "desktop-control:quarantined-uia-expand:" + ORIGINAL
ACK = "ACK_UNKNOWN_UIA_EXPAND_EFFECT_NO_REPLAY"


class FakeAgent:
    def __init__(self, *, lease=None, available=True):
        self.lease = lease
        self.available = available
        self.commands = []

    def control(self, *, request_id, command, arguments):
        self.commands.append(command)
        if not self.available:
            raise RuntimeError("SIMULATED_AGENT_UNAVAILABLE")
        return {
            "instanceId": "session-agent-isolated-test",
            "session": {"inputDesktopAvailable": True},
            "control": {
                "lease": self.lease,
                "emergencyStop": {"active": False},
                "observedAtUtc": datetime.now(timezone.utc).isoformat(),
            }
        }


class DesktopUiaQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fixture.sqlite"
        self.store = Store(self.path)
        self.work = Work(WORK, "isolated test", (str(self.path.parent),),
                         frozenset({"desktop_uia_element_action"}), "bct-mcp-local")
        self.store.create_work(self.work)
        stamp = time.time()-600
        with self.store.transaction() as db:
            for operation_id, cap, target, state, outcome, error in (
                (ORIGINAL, "desktop_uia_element_action", "expand:desktop-uia",
                 "FINISHED", "UNKNOWN", ERROR),
                ("resolve-test", "claim_reconcile",
                 "quarantine_uia_expand:" + ORIGINAL, "RUNNING", None, None),
            ):
                db.execute("""INSERT INTO operations
                (operation_id,work_id,principal_id,request_digest,capability,target,
                state,outcome,evidence_json,error,assignment_epoch,policy_revision,
                created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (operation_id, WORK, "bct-mcp-local", DIGEST if operation_id==ORIGINAL
                 else "b"*64, cap, target, state, outcome, "{}", error, 1,
                 "unit-test", stamp, stamp))
            for key, op in (
                ("desktop-control:interactive-session", ORIGINAL),
                ("claim-reconcile:" + ORIGINAL, "resolve-test"),
            ):
                db.execute("""INSERT INTO resource_claims
                (resource_key,operation_id,work_id,assignment_epoch,unresolved)
                VALUES(?,?,?,?,1)""",(key,op,WORK,1))

    def tearDown(self):
        self.tmp.cleanup()

    def evidence(self):
        return {
            "operation":"quarantine_uia_expand",
            "audit_kind":"OPERATOR_QUARANTINE_NOT_RECONCILIATION",
            "original_operation_id":ORIGINAL,
            "expected_original_digest":DIGEST,
            "new_resource_key":NEW_KEY,
            "original_outcome_preserved":"UNKNOWN",
            "lease_state":"NONE",
            "agent_instance_id":"agent-tested",
            "observed_at_utc":datetime.now(timezone.utc).isoformat(),
            "operator_acknowledgement":ACK,
            "operator_justification":"Old menu expand unknown, no replay requested",
        }

    def quarantine(self, evidence=None):
        return self.store.finish_uia_expand_claim_operator_quarantine(
            resolver_operation_id="resolve-test",
            original_operation_id=ORIGINAL,
            expected_original_digest=DIGEST,
            expected_work_id=WORK,
            evidence=self.evidence() if evidence is None else evidence)

    def original(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT outcome,error FROM operations WHERE operation_id=?",(ORIGINAL,)
            ).fetchone()

    def claim(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT resource_key,unresolved FROM resource_claims WHERE operation_id=?",
                (ORIGINAL,)).fetchone()

    def test_quarantines_only_broad_claim_and_keeps_unknown(self):
        result=self.quarantine()
        self.assertEqual(result.outcome.value,"APPLIED")
        self.assertEqual(self.original(),("UNKNOWN",ERROR))
        self.assertEqual(self.claim(),(NEW_KEY,1))
        quarantined = [c for c in self.store.claim_diagnostics()
                       if c["operation_id"] == ORIGINAL]
        self.assertEqual(len(quarantined),1)
        self.assertEqual(quarantined[0]["scope"],"EXACT_RESOURCE")
        self.assertFalse(quarantined[0]["blocks_unrelated_work"])
        self.assertFalse(quarantined[0]["can_auto_release"])
        with closing(sqlite3.connect(self.path)) as db:
            events=db.execute("""SELECT kind FROM events WHERE
                subject_id=? ORDER BY event_id""",(ORIGINAL,)).fetchall()
        self.assertIn(("UIA_UNKNOWN_EXPAND_CLAIM_OPERATOR_QUARANTINED",),events)

    def test_wrong_digest_rejected_without_mutation(self):
        with self.assertRaises(ConflictError):
            self.store.finish_uia_expand_claim_operator_quarantine(
                resolver_operation_id="resolve-test",original_operation_id=ORIGINAL,
                expected_original_digest="b"*64,expected_work_id=WORK,
                evidence=self.evidence())
        self.assertEqual(self.claim(),("desktop-control:interactive-session",1))

    def test_wrong_error_rejected(self):
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET error='OTHER' WHERE operation_id=?",(ORIGINAL,))
        with self.assertRaises(ConflictError):self.quarantine()
        self.assertEqual(self.original(),("UNKNOWN","OTHER"))
        self.assertEqual(self.claim(),("desktop-control:interactive-session",1))

    def test_wrong_capability_rejected(self):
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET capability='desktop_input' WHERE operation_id=?",(ORIGINAL,))
        with self.assertRaises(ConflictError):self.quarantine()

    def test_more_than_one_unresolved_claim_rejected(self):
        with self.store.transaction() as db:
            db.execute("""INSERT INTO resource_claims VALUES(?,?,?,1,1)""",
                       ("another-resource",ORIGINAL,WORK))
        with self.assertRaises(ConflictError):self.quarantine()

    def test_stale_observation_rejected(self):
        evidence=self.evidence()
        evidence["observed_at_utc"]="2020-01-01T00:00:00+00:00"
        with self.assertRaises(ConflictError):self.quarantine(evidence)

    def test_ack_required(self):
        evidence=self.evidence()
        evidence["operator_acknowledgement"]="not approved"
        with self.assertRaises(ConflictError):self.quarantine(evidence)

    def test_new_operation_cannot_repeat(self):
        self.quarantine()
        with self.assertRaises(ConflictError):self.quarantine()

    def test_feature_requires_explicit_mode_and_exact_ack(self):
        f=ReadOnlyClaimReconcileFeature(self.store,FakeAgent())
        args={"original_operation_id":ORIGINAL,"reason":"operator ack",
              "mode":"quarantine_uia_expand","expected_original_digest":DIGEST,
              "operator_acknowledgement":ACK}
        with self.assertRaises(PreconditionError):
            f.prepare(work=self.work,arguments={**args,"operator_acknowledgement":"YES"})
        request=f.prepare(work=self.work,arguments=args)
        bound=replace(request,operation_id="resolve-test",
                      preconditions={"work_id":WORK,"principal_id":"bct-mcp-local"})
        proof=f.execute(bound)
        self.assertEqual(proof.evidence["lease_state"],"NONE")
        self.assertEqual(proof.reconciled_operation_ids,())

    def test_operation_coordinator_quarantine_end_to_end(self):
        from bct.core.operations import OperationCoordinator
        from bct.core.policy import Policy
        from bct.core.models import Principal
        config = self.path.parent / "bct.toml"
        config.write_text(
            '[policy]\nnormal_actions=["desktop_uia_element_action"]\n'
            'approval_actions=[]\n', encoding="utf-8")
        with self.store.transaction() as db:
            db.execute("DELETE FROM resource_claims WHERE operation_id='resolve-test'")
            db.execute("DELETE FROM operations WHERE operation_id='resolve-test'")
        coordinator=OperationCoordinator(store=self.store,policy=Policy(config))
        client=FakeAgent()
        coordinator.register(ReadOnlyClaimReconcileFeature(self.store,client))
        principal=Principal("bct-mcp-local","test",
                            frozenset({"desktop_uia_element_action"}))
        result=coordinator.run(
            principal=principal,work_id=WORK,operation_id="resolve-coordinator",
            capability="claim_reconcile",
            arguments={"original_operation_id":ORIGINAL,"reason":"operator-approved stale expand",
                       "mode":"quarantine_uia_expand",
                       "expected_original_digest":DIGEST,
                       "operator_acknowledgement":ACK})
        self.assertEqual(result.outcome.value,"APPLIED")
        self.assertEqual(client.commands,["control_status"])
        self.assertEqual(self.original(),("UNKNOWN",ERROR))
        self.assertEqual(self.claim(),(NEW_KEY,1))
        again=coordinator.run(
            principal=principal,work_id=WORK,operation_id="resolve-coordinator",
            capability="claim_reconcile",
            arguments={"original_operation_id":ORIGINAL,"reason":"operator-approved stale expand",
                       "mode":"quarantine_uia_expand",
                       "expected_original_digest":DIGEST,
                       "operator_acknowledgement":ACK})
        self.assertTrue(again.duplicate)
        self.assertEqual(client.commands,["control_status"])

    def test_feature_rejects_active_lease(self):
        f=ReadOnlyClaimReconcileFeature(self.store,FakeAgent(lease={"leaseId":"active"}))
        req=f.prepare(work=self.work,arguments={"original_operation_id":ORIGINAL,
             "reason":"operator ack","mode":"quarantine_uia_expand",
             "expected_original_digest":DIGEST,"operator_acknowledgement":ACK})
        bound=replace(req,operation_id="resolve-test",
                      preconditions={"work_id":WORK,"principal_id":"bct-mcp-local"})
        with self.assertRaises(PreconditionError):f.execute(bound)
        self.assertEqual(self.claim(),("desktop-control:interactive-session",1))


if __name__=="__main__":
    unittest.main()
