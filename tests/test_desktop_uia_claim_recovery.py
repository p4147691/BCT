"""Exact retired desktop UIA claim recovery without erasing UNKNOWN effects."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import ConflictError, Outcome, PreconditionError, Work
from bct.core.store import Store
from bct.features.claim_reconciliation import ReadOnlyClaimReconcileFeature


ERROR = "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:DESKTOP_UIA_ACTION_CHANGED_FOREGROUND"
CLAIM = "desktop-control:interactive-session"


class IdleDesktop:
    def __init__(self, *, lease=None, stopped=False, available=True):
        self.lease = lease
        self.stopped = stopped
        self.available = available
        self.calls = 0

    def control(self, *, request_id, command):
        self.calls += 1
        if not self.available:
            raise OSError("agent unavailable")
        assert command == "control_status"
        assert request_id.endswith((":retired-lease-proof", ":desktop-idle-before-reservation"))
        return {"control": {
            "lease": self.lease,
            "emergencyStop": {"active": self.stopped},
        }}


class RetiredUiaClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "core.sqlite")
        self.work = self.store.create_work(Work(
            "old-monitor-work", "old desktop operation", (self.temp.name,),
            frozenset({"desktop_uia_element_action", "claim_reconcile"}), "owner",
        ))
        self.device = IdleDesktop()
        self.feature = ReadOnlyClaimReconcileFeature(self.store, self.device)

    def tearDown(self):
        self.temp.cleanup()

    def _original(self, *, name="old-uia", error=ERROR, phase="EXECUTION",
                  capability="desktop_uia_element_action", resources=(CLAIM,),
                  outcome=Outcome.UNKNOWN):
        created, _ = self.store.begin_operation(
            operation_id=name, work=self.work, principal_id="owner",
            request_digest="original-fixed-digest", capability=capability,
            target="expand:desktop-uia", resources=resources,
            policy_revision="fixture",
        )
        self.assertTrue(created)
        self.store.finish_operation(
            operation_id=name, outcome=outcome,
            evidence={"phase": phase, "code": error},
            error=error, release_claims=(outcome is not Outcome.UNKNOWN),
        )

    def _request(self, *, original="old-uia"):
        req = self.feature.prepare(work=self.work, arguments={
            "original_operation_id": original,
            "reason": "Retired UIA lease is gone; keep unknown effect",
        })
        return type(req)(req.capability, req.target, req.arguments, req.resources,
                         {"work_id": self.work.work_id,
                          "principal_id": "owner"}, "resolver")

    def _finish_resolver(self, result):
        request = self._request()
        created, _ = self.store.begin_operation(
            operation_id="resolver", work=self.work, principal_id="owner",
            request_digest="resolver-digest", capability=request.capability,
            target=request.target, resources=request.resources,
            policy_revision="fixture",
        )
        self.assertTrue(created)
        return self.store.finish_operation(
            operation_id="resolver", outcome=result.outcome,
            evidence=result.evidence, error=None, release_claims=True,
            reconciled_operation_ids=result.reconciled_operation_ids,
        )

    def test_exact_idle_recovery_keeps_original_receipt_and_journal(self):
        self._original()
        before = self.store.get_operation_for(
            operation_id="old-uia", work_id=self.work.work_id, principal_id="owner")
        journal = self.store.get_effect_journal_for(
            operation_id="old-uia", work_id=self.work.work_id, principal_id="owner")
        result = self.feature.execute(self._request())
        self.assertEqual("RETIRED_DESKTOP_CLAIM_ONLY_EFFECT_REMAINS_UNKNOWN",
                         result.evidence["proof"])
        self.assertEqual(1, self.device.calls)
        self._finish_resolver(result)
        after = self.store.get_operation_for(
            operation_id="old-uia", work_id=self.work.work_id, principal_id="owner")
        self.assertEqual(before, after)
        self.assertEqual(journal, self.store.get_effect_journal_for(
            operation_id="old-uia", work_id=self.work.work_id, principal_id="owner"))
        self.assertEqual([], self.store.claim_diagnostics())
        # The same historical operation cannot create another effect or claim.
        created, prior = self.store.begin_operation(
            operation_id="old-uia", work=self.work, principal_id="owner",
            request_digest="original-fixed-digest",
            capability="desktop_uia_element_action", target="expand:desktop-uia",
            resources=(CLAIM,), policy_revision="fixture",
        )
        self.assertFalse(created)
        self.assertEqual(Outcome.UNKNOWN, prior.outcome)
        # A new operation may acquire the now-idle desktop resource.
        other = self.store.create_work(Work(
            "new-worker", "new desktop task", (self.temp.name,),
            frozenset({"desktop_control_lease"}), "owner",
        ))
        reserved, _ = self.store.begin_operation(
            operation_id="new-acquire", work=other, principal_id="owner",
            request_digest="new", capability="desktop_control_lease",
            target="acquire:window", resources=(CLAIM,),
            policy_revision="fixture",
        )
        self.assertTrue(reserved)

    def test_live_lease_blocks_reclaim(self):
        self._original()
        self.device.lease = {"leaseId": "still-running", "ownerId": "worker"}
        with self.assertRaisesRegex(PreconditionError, "CONTROL_NOT_IDLE"):
            self.feature.execute(self._request())
        self.assertEqual(1, len(self.store.claim_diagnostics()))

    def test_emergency_stop_blocks_reclaim(self):
        self._original()
        self.device.stopped = True
        with self.assertRaisesRegex(PreconditionError, "CONTROL_NOT_IDLE"):
            self.feature.execute(self._request())

    def test_agent_unavailable_blocks_reclaim(self):
        self._original()
        self.device.available = False
        with self.assertRaisesRegex(PreconditionError, "AGENT_UNAVAILABLE"):
            self.feature.execute(self._request())

    def test_no_client_blocks_reclaim(self):
        self._original()
        feature = ReadOnlyClaimReconcileFeature(self.store)
        with self.assertRaisesRegex(PreconditionError, "AGENT_REQUIRED"):
            feature.execute(self._request())

    def test_different_error_code_or_phase_is_not_eligible(self):
        for name, error, phase in (
            ("wrong-code", "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:UNRECOGNIZED", "EXECUTION"),
            ("wrong-phase", ERROR, "UNEXPECTED"),
        ):
            self._original(name=name, error=error, phase=phase,
                           resources=(f"desktop-control:{name}",))
            with self.assertRaisesRegex(PreconditionError, "EXACT_NO_EFFECT_UNKNOWN_REQUIRED"):
                self.feature.execute(self._request(original=name))

    def test_unrelated_old_claim_prevents_atomic_recovery(self):
        self._original(resources=(CLAIM, "other:must-stay"))
        result = self.feature.execute(self._request())
        with self.assertRaisesRegex(ConflictError, "EXACT_CLAIM_REQUIRED"):
            self._finish_resolver(result)
        self.assertEqual(3, len(self.store.claim_diagnostics()))
        self.assertEqual(Outcome.UNKNOWN, self.store.get_operation_for(
            operation_id="old-uia", work_id=self.work.work_id,
            principal_id="owner").outcome)

    def test_late_original_change_rejected_in_final_transaction(self):
        self._original()
        result = self.feature.execute(self._request())
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET error=? WHERE operation_id=?",
                       ("CHANGED_AFTER_PREFLIGHT", "old-uia"))
        with self.assertRaisesRegex(ConflictError, "EXACT_CLAIM_REQUIRED"):
            self._finish_resolver(result)
        # Both the original Claim and this RUNNING resolver's own
        # harmless reconciliation lock are preserved on transaction failure.
        self.assertEqual(2, len(self.store.claim_diagnostics()))

    def test_running_operation_and_other_work_are_not_reclaimed(self):
        created, _ = self.store.begin_operation(
            operation_id="old-uia", work=self.work, principal_id="owner",
            request_digest="old", capability="desktop_uia_element_action",
            target="expand:desktop-uia", resources=(CLAIM,),
            policy_revision="fixture")
        self.assertTrue(created)
        with self.assertRaisesRegex(PreconditionError, "EXACT_NO_EFFECT_UNKNOWN_REQUIRED"):
            self.feature.execute(self._request())
        with self.assertRaisesRegex(Exception, "OPERATION"):
            self.store.get_operation_for(
                operation_id="old-uia", work_id="different-work",
                principal_id="owner")


class AutoRevokeUnknownLeaseTests(unittest.TestCase):
    """New UIA UNKNOWN auto-retires ONLY a verifiably idle desktop Claim."""

    def _invoke(self, *, error=ERROR, lease=None, stopped=False, online=True):
        from bct.core.models import UnknownEffectError
        from bct.features.desktop_session import DesktopUiaElementActionFeature
        from bct.integrations.desktop_session import DesktopSessionEffectUnknown

        class Device(IdleDesktop):
            def uia_element_action(self, **kwargs):
                raise DesktopSessionEffectUnknown(error)

        device = Device(lease=lease, stopped=stopped, available=online)
        work = Work("uia-w", "test", ("C:\\\\fixture",),
                    frozenset({"desktop_uia_element_action"}), "owner")
        feature = DesktopUiaElementActionFeature(device)
        req = feature.prepare(work=work, arguments={
            "lease_id": "a" * 32, "operation": "expand",
            "element_id": "b" * 64,
        })
        req = type(req)(req.capability, req.target, req.arguments, req.resources,
                        req.preconditions, "one-uia")
        with self.assertRaises(UnknownEffectError) as captured:
            feature.execute(req)
        self.assertEqual(error, str(captured.exception))
        return captured.exception.release_claims, device.calls

    def test_new_idle_changed_foreground_unknown_can_auto_retire(self):
        can_release, polls = self._invoke()
        self.assertTrue(can_release)
        self.assertEqual(1, polls)

    def test_new_active_lease_preserves_claim(self):
        can_release, polls = self._invoke(lease={"leaseId": "active"})
        self.assertFalse(can_release)
        self.assertEqual(1, polls)

    def test_new_emergency_stop_preserves_claim(self):
        can_release, _ = self._invoke(stopped=True)
        self.assertFalse(can_release)

    def test_agent_failure_preserves_claim(self):
        can_release, _ = self._invoke(online=False)
        self.assertFalse(can_release)

    def test_other_unknown_reason_never_auto_releases(self):
        can_release, polls = self._invoke(error="UIA_UNEXPECTED_OTHER_FAILURE")
        self.assertFalse(can_release)
        self.assertEqual(0, polls)


class CrossWorkDesktopReacquisitionTests(unittest.TestCase):
    """A terminal claim is NOT an authorization source for new work."""

    def setUp(self):
        from bct.core.models import Principal, Decision, DecisionKind
        from bct.core.operations import OperationCoordinator
        from bct.features.desktop_session import DesktopControlLeaseFeature

        class LocalPolicy:
            def decide(self, **kwargs):
                return Decision(DecisionKind.ALLOW, "ALLOW", "", "fixture")

        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.principal = Principal("owner", "fixture", frozenset({
            "desktop_control_lease", "desktop_uia_element_action"
        }))
        self.old = self.store.create_work(Work(
            "prior", "prior desktop action", (self.temp.name,),
            frozenset({"desktop_uia_element_action"}), "owner"))
        self.new = self.store.create_work(Work(
            "new", "new independent desktop action", (self.temp.name,),
            frozenset({"desktop_control_lease"}), "owner"))
        self.agent = IdleDesktop()
        self.ops = OperationCoordinator(store=self.store, policy=LocalPolicy())
        self.ops.register(DesktopControlLeaseFeature(self.agent))

    def tearDown(self):
        self.temp.cleanup()

    def original(self, *, name="prior-uia", finish=True, capability="desktop_uia_element_action",
                 resources=(CLAIM,)):
        created, _ = self.store.begin_operation(
            operation_id=name, work=self.old, principal_id="owner",
            request_digest="prior-digest", capability=capability,
            target="expand:desktop-uia", resources=resources,
            policy_revision="fixture")
        self.assertTrue(created)
        if finish:
            self.store.finish_operation(
                operation_id=name, outcome=Outcome.UNKNOWN,
                evidence={"phase":"EXECUTION","code":ERROR},
                error=ERROR, release_claims=False)

    def acquire(self, *, id="fresh"):
        return self.ops.begin(
            principal=self.principal, work_id=self.new.work_id,
            operation_id=id, capability="desktop_control_lease",
            arguments={"operation":"acquire", "target_type":"session"})

    def test_new_work_replaces_stale_measurement_without_live_probe(self):
        self.original()
        before=self.store.get_operation_for(
            operation_id="prior-uia",work_id="prior",principal_id="owner")
        journal=self.store.get_effect_journal_for(
            operation_id="prior-uia",work_id="prior",principal_id="owner")
        created, current=self.acquire()
        self.assertTrue(created)
        self.assertEqual("fresh",current.operation_id)
        self.assertEqual(0,self.agent.calls)
        self.assertEqual(before,self.store.get_operation_for(
            operation_id="prior-uia",work_id="prior",principal_id="owner"))
        self.assertEqual(journal,self.store.get_effect_journal_for(
            operation_id="prior-uia",work_id="prior",principal_id="owner"))
        claims=self.store.claim_diagnostics()
        self.assertEqual(["fresh"],[c["operation_id"] for c in claims])
        # Same original ID can never dispatch again, even after the Claim retires.
        duplicate, old=self.store.begin_operation(
            operation_id="prior-uia",work=self.old,principal_id="owner",
            request_digest="prior-digest",capability="desktop_uia_element_action",
            target="expand:desktop-uia",resources=(CLAIM,),
            policy_revision="fixture")
        self.assertFalse(duplicate)
        self.assertEqual(Outcome.UNKNOWN,old.outcome)
        self.store.finish_operation(operation_id="fresh",outcome=Outcome.APPLIED,
            evidence={"phase":"fixture"},error=None,release_claims=True)
        self.assertEqual([],self.store.claim_diagnostics())

    def test_active_agent_lease_does_not_turn_old_claim_into_begin_gate(self):
        self.original()
        self.agent.lease={"leaseId":"still-held"}
        created, _ = self.acquire()
        self.assertTrue(created)
        self.assertEqual("fresh",self.store.claim_diagnostics()[0]["operation_id"])

    def test_emergency_stop_does_not_turn_old_claim_into_begin_gate(self):
        self.original()
        self.agent.stopped=True
        created, _ = self.acquire()
        self.assertTrue(created)

    def test_unavailable_agent_does_not_turn_old_claim_into_begin_gate(self):
        self.original()
        self.agent.available=False
        created, _ = self.acquire()
        self.assertTrue(created)

    def test_unfinished_original_claim_does_not_fence_independent_begin(self):
        self.original(finish=False)
        created, _ = self.acquire()
        self.assertTrue(created)
        self.assertEqual(0,self.agent.calls)

    def test_unrelated_running_resource_does_not_fence_independent_begin(self):
        self.original(capability="desktop_program_launch")
        created, _ = self.acquire()
        self.assertTrue(created)
        self.assertEqual(0,self.agent.calls)

    def test_unrelated_claim_of_original_remains_protected(self):
        self.original(resources=(CLAIM,"other:critical-resource"))
        created,_=self.acquire()
        self.assertTrue(created)
        records=self.store.claim_diagnostics()
        self.assertEqual(2,len(records))
        self.assertEqual({"fresh","prior-uia"},
            {c["operation_id"] for c in records})

    def test_monitor_diagnostics_cannot_block_or_grant_execution(self):
        self.original()
        def no_monitor(*args,**kwargs):
            raise RuntimeError("MONITOR_IS_OBSERVATION_NOT_AUTHORITY")
        self.store.claim_diagnostics=no_monitor
        created,_=self.acquire()
        self.assertTrue(created)

    def test_new_operation_id_does_not_authorize_old_id_replay(self):
        self.original()
        self.acquire()
        with self.assertRaisesRegex(ConflictError,"OPERATION_RESULT_ACCESS_DENIED"):
            self.store.begin_operation(operation_id="prior-uia",work=self.new,
                principal_id="owner",request_digest="new-request",
                capability="desktop_control_lease",target="acquire:session",
                resources=(CLAIM,),policy_revision="fixture")


    def test_executor_metadata_does_not_trigger_finished_operation_probe(self):
        self.original()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO background_jobs VALUES(?,?,?)",
                ("prior-uia", "{}", 100.0))
            db.execute(
                "INSERT INTO background_job_executors VALUES(?,?,?,?)",
                ("prior-uia", 321, "attached-worker", 101.0))
        created, _ = self.acquire()
        self.assertTrue(created)
        self.assertEqual(0, self.agent.calls)

    def test_old_assignment_epoch_does_not_affect_claim_measurement_replacement(self):
        self.original()
        with self.store.transaction() as db:
            db.execute(
                "UPDATE resource_claims SET assignment_epoch=? "
                "WHERE operation_id=?", (9, "prior-uia"))
        created, _ = self.store.begin_operation(
            operation_id="fresh",work=self.new,principal_id="owner",
            request_digest="fresh",capability="desktop_control_lease",
            target="acquire:session",resources=(CLAIM,),
            policy_revision="fixture")
        self.assertTrue(created)

if __name__ == "__main__":
    unittest.main()
