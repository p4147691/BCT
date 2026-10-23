from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, Principal, Work
from bct.core.operations import OperationCoordinator
from bct.core.policy import Policy
from bct.core.store import Store
from bct.features.claim_reconciliation import ReadOnlyClaimReconcileFeature


class ReadOnlyClaimReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "work", "fixture", (self.tmp.name,),
            frozenset({"read", "write", "claim_reconcile", "relay_browser"}), "owner",
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def _unknown(self, operation_id: str, capability: str) -> None:
        created, _ = self.store.begin_operation(
            operation_id=operation_id, work=self.work, principal_id="owner",
            request_digest=operation_id, capability=capability, target="fixture",
            resources=("resource:" + operation_id,), policy_revision="fixture",
        )
        self.assertTrue(created)
        self.store.finish_operation(
            operation_id=operation_id, outcome=Outcome.UNKNOWN,
            evidence={"phase": "fixture"}, error="fixture", release_claims=False,
        )

    def test_readonly_unknown_reconciles_and_preserves_original_receipt(self):
        self._unknown("original", "read")
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "original", "reason": "read-only timeout",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        result = feature.execute(request)
        self.assertEqual(("original",), result.reconciled_operation_ids)

        self.store.begin_operation(
            operation_id="resolver", work=self.work, principal_id="owner",
            request_digest="resolver", capability="claim_reconcile",
            target=request.target, resources=request.resources, policy_revision="fixture",
        )
        self.store.finish_operation(
            operation_id="resolver", outcome=result.outcome, evidence=result.evidence,
            error=None, release_claims=True,
            reconciled_operation_ids=result.reconciled_operation_ids,
        )
        original = self.store.get_operation_for(
            operation_id="original", work_id="work", principal_id="owner",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual([], self.store.claim_diagnostics())

    def test_mutating_unknown_is_rejected(self):
        self._unknown("original-write", "write")
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "original-write", "reason": "must reject",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        with self.assertRaisesRegex(Exception, "EXACT_NO_EFFECT_UNKNOWN_REQUIRED"):
            feature.execute(request)

    def test_execute_createprocess_file_not_found_is_proven_no_effect(self):
        self._unknown("missing-executable", "execute")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE operations SET evidence_json=?,error=? WHERE operation_id=?",
                ('{"phase":"UNEXPECTED","type":"FileNotFoundError"}',
                 "[WinError 2] file not found", "missing-executable"),
            )
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "missing-executable", "reason": "pre-dispatch proof",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        result = feature.execute(request)
        self.assertEqual("EXECUTE_CREATEPROCESS_FILE_NOT_FOUND", result.evidence["proof"])

    def test_execute_after_process_creation_remains_unknown(self):
        self._unknown("process-existed", "execute")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE operations SET evidence_json=?,error=? WHERE operation_id=?",
                ('{"phase":"UNEXPECTED","type":"NoSuchProcess"}',
                 "process no longer exists", "process-existed"),
            )
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "process-existed", "reason": "must remain protected",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        with self.assertRaisesRegex(Exception, "EXACT_NO_EFFECT_UNKNOWN_REQUIRED"):
            feature.execute(request)

    def test_legacy_relay_delivery_reuse_claim_is_proven_pre_dispatch(self):
        self._unknown("legacy-relay-reuse", "relay_control")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE operations SET evidence_json=?,error=? WHERE operation_id=?",
                ('{"phase":"UNEXPECTED","type":"ConflictError"}',
                 "DELIVERY_ID_REUSE_MISMATCH", "legacy-relay-reuse"),
            )
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "legacy-relay-reuse",
            "reason": "immutable delivery identity rejected before RCC dispatch",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        result = feature.execute(request)
        self.assertEqual(
            "RELAY_DELIVERY_ID_REUSE_REJECTED_BEFORE_RCC_DISPATCH",
            result.evidence["proof"],
        )

    def test_legacy_missing_delivery_claim_is_proven_pre_dispatch(self):
        self._unknown("legacy-missing-delivery", "relay_browser")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE operations SET evidence_json=?,error=? WHERE operation_id=?",
                ('{"phase":"UNEXPECTED","type":"KeyError"}',
                 "'DELIVERY_NOT_FOUND'", "legacy-missing-delivery"),
            )
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "legacy-missing-delivery",
            "reason": "missing ledger row failed before RCC dispatch",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        result = feature.execute(request)
        self.assertEqual(
            "RELAY_DELIVERY_NOT_FOUND_BEFORE_RCC_DISPATCH",
            result.evidence["proof"],
        )

    def test_other_relay_control_unknown_remains_protected(self):
        self._unknown("other-relay-unknown", "relay_control")
        feature = ReadOnlyClaimReconcileFeature(self.store)
        request = feature.prepare(work=self.work, arguments={
            "original_operation_id": "other-relay-unknown",
            "reason": "must remain protected",
        })
        request = type(request)(
            request.capability, request.target, request.arguments, request.resources,
            {"work_id": "work", "principal_id": "owner"}, "resolver",
        )
        with self.assertRaisesRegex(Exception, "EXACT_NO_EFFECT_UNKNOWN_REQUIRED"):
            feature.execute(request)

    def test_coordinator_reconciles_exact_legacy_relay_claim_under_delegated_policy(self):
        self._unknown("legacy-relay-coordinator", "relay_control")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE operations SET evidence_json=?,error=? WHERE operation_id=?",
                ('{"phase":"UNEXPECTED","type":"ConflictError"}',
                 "DELIVERY_ID_REUSE_MISMATCH", "legacy-relay-coordinator"),
            )
        policy_path = Path(self.tmp.name) / "policy.toml"
        policy_path.write_text(
            '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        coordinator = OperationCoordinator(
            store=self.store, policy=Policy(policy_path),
        )
        coordinator.register(ReadOnlyClaimReconcileFeature(self.store))
        result = coordinator.run(
            principal=Principal(
                "owner", "fixture",
                frozenset({"claim_reconcile", "relay_browser"}),
            ),
            work_id="work", operation_id="legacy-relay-resolver",
            capability="claim_reconcile", arguments={
                "original_operation_id": "legacy-relay-coordinator",
                "reason": "immutable delivery identity rejected before RCC dispatch",
            },
        )
        self.assertEqual(Outcome.APPLIED, result.outcome)
        original = self.store.get_operation_for(
            operation_id="legacy-relay-coordinator",
            work_id="work", principal_id="owner",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual([], self.store.claim_diagnostics())

    def test_coordinator_reconciles_exact_legacy_missing_delivery_claim(self):
        self._unknown("legacy-missing-delivery-coordinator", "relay_browser")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE operations SET evidence_json=?,error=? WHERE operation_id=?",
                ('{"phase":"UNEXPECTED","type":"KeyError"}',
                 "'DELIVERY_NOT_FOUND'", "legacy-missing-delivery-coordinator"),
            )
        policy_path = Path(self.tmp.name) / "policy.toml"
        policy_path.write_text(
            '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        coordinator = OperationCoordinator(
            store=self.store, policy=Policy(policy_path),
        )
        coordinator.register(ReadOnlyClaimReconcileFeature(self.store))
        result = coordinator.run(
            principal=Principal(
                "owner", "fixture",
                frozenset({"claim_reconcile", "relay_browser"}),
            ),
            work_id="work", operation_id="legacy-missing-delivery-resolver",
            capability="claim_reconcile", arguments={
                "original_operation_id": "legacy-missing-delivery-coordinator",
                "reason": "missing ledger row failed before RCC dispatch",
            },
        )
        self.assertEqual(Outcome.APPLIED, result.outcome)
        original = self.store.get_operation_for(
            operation_id="legacy-missing-delivery-coordinator",
            work_id="work", principal_id="owner",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual([], self.store.claim_diagnostics())

    def test_effect_journal_is_ordered_and_redacted(self):
        self._unknown("journal", "read")
        self.store.record_effect_stage(
            operation_id="journal", stage="EFFECT_UNCERTAIN",
            detail={"error_type": "TimeoutError", "secret": "must-not-persist"},
        )
        rows = self.store.get_effect_journal_for(
            operation_id="journal", work_id="work", principal_id="owner",
        )
        self.assertEqual(
            ["CLAIM_RESERVED", "RECEIPT_PERSISTED", "EFFECT_UNCERTAIN"],
            [row["stage"] for row in rows],
        )
        self.assertNotIn("must-not-persist", str(rows))


if __name__ == "__main__":
    unittest.main()
