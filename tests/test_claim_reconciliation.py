from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, Work
from bct.core.store import Store
from bct.features.claim_reconciliation import ReadOnlyClaimReconcileFeature


class ReadOnlyClaimReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "work", "fixture", (self.tmp.name,),
            frozenset({"read", "write", "claim_reconcile"}), "owner",
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
        with self.assertRaisesRegex(Exception, "EXACT_READONLY_UNKNOWN_REQUIRED"):
            feature.execute(request)

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
