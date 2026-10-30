import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bct.features.rcc_unknown_diagnostics import diagnose_unknown_receipt


class UnknownDiagnosticTest(unittest.TestCase):
    def test_unresolved_without_host_proof(self):
        x = diagnose_unknown_receipt(
            original_operation_id="old-1", original_outcome="UNKNOWN",
            original_error="RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH",
            effect_journal=[{"stage": "CLAIM_RESERVED"}, {"stage": "DISPATCH_INTENT"}],
        )
        self.assertEqual(x["status"], "UNRESOLVED")
        self.assertEqual(x["last_success_stage"], "DISPATCH_INTENT")
        self.assertEqual(x["failure_stage"], "HOST_RECEIPT_OBSERVATION")
        self.assertEqual(x["reason"], "RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH")
        self.assertTrue(x["no_resend"])

    def test_host_submitted_is_not_sufficient(self):
        x = diagnose_unknown_receipt(
            original_operation_id="old-1", original_outcome="UNKNOWN",
            original_error=None, effect_journal=[],
            host_receipt={"state": "SUBMITTED"},
        )
        self.assertEqual(x["status"], "UNRESOLVED")
        self.assertIn("EXACT_RESPONSE_RECEIPT", x["remaining_proof"])

    def test_nonunknown_cannot_reconcile(self):
        x = diagnose_unknown_receipt(
            original_operation_id="old-1", original_outcome="APPLIED",
            original_error=None, effect_journal=[],
        )
        self.assertEqual(x["status"], "NOT_ELIGIBLE")
