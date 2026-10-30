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


class SeparateRecoveryReceiptTest(unittest.TestCase):
    def test_missing_evidence_never_verifies(self):
        from bct.features.rcc_unknown_diagnostics import build_separate_recovery_receipt
        source = {"operation_id":"old", "outcome":"UNKNOWN", "state":"FINISHED"}
        before = dict(source)
        result = build_separate_recovery_receipt(
            recovery_operation_id="recovery", original=source,
            proof={}, expected={})
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("EXACT_RESPONSE_RECEIPT", result["missing_proof"])
        self.assertEqual(source, before)
        self.assertTrue(result["no_resend"])

    def test_exact_evidence_verifies_without_mutation(self):
        from hashlib import sha256
        from bct.features.rcc_unknown_diagnostics import build_separate_recovery_receipt
        digest = sha256(b"request").hexdigest()
        text_hash = sha256(b"prompt").hexdigest()
        response = "answer"
        response_hash = sha256(response.encode()).hexdigest()
        target = dict(instance_id="instance",session_id="session",
                      tab_id=3,window_id=4,conversation_key="uuid")
        original = dict(operation_id="old",outcome="UNKNOWN",
                        state="FINISHED",request_digest=digest)
        expected = dict(target,request_digest=digest,text_sha256=text_hash)
        proof = dict(target,request_digest=digest,user_turn_count=1,
                     user_turn_sha256=text_hash,submitted=True,
                     ack_operation_id="old",result_state="RESULT_PERSISTED",
                     response_text=response,response_sha256=response_hash,
                     response_operation_id="old")
        original_before = dict(original)
        r = build_separate_recovery_receipt(
            recovery_operation_id="recover-1",original=original,
            proof=proof,expected=expected)
        self.assertEqual(r["status"],"VERIFIED")
        self.assertEqual(r["missing_proof"],[])
        self.assertEqual(original,original_before)

class DurableRecoveryStoreTest(unittest.TestCase):
    def test_persist_separately_and_preserve_original(self):
        import tempfile, sqlite3, json, hashlib
        from pathlib import Path
        from bct.core.store import Store
        from bct.core.models import Outcome
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"test.sqlite")
            now=1.0
            digest=hashlib.sha256(b"request").hexdigest()
            with store.transaction() as db:
                db.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                    ("work","test","[]","[]","owner",1,"ACTIVE"))
                db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("original","work","owner",digest,"relay_browser","instance",
                     "FINISHED","UNKNOWN",json.dumps({"phase":"EXECUTION"}),"RCC_UNKNOWN",
                     1,"test",now,now))
                db.execute("INSERT INTO resource_claims VALUES(?,?,?,?,?)",
                    ("exact:original","original","work",1,1))
            with store.transaction() as db:
                before_original=tuple(db.execute("SELECT * FROM operations WHERE operation_id='original'").fetchone())
                before_claims=[tuple(r) for r in db.execute("SELECT * FROM resource_claims")]
            evidence={"status":"INSUFFICIENT_EVIDENCE","original_operation_id":"original",
                      "recovery_operation_id":"recovery","no_resend":True,
                      "missing_proof":["EXACT_RESPONSE_RECEIPT"]}
            first=store.record_independent_unknown_recovery(
                recovery_operation_id="recovery",work_id="work",principal_id="owner",
                original_operation_id="original",expected_original_digest=digest,evidence=evidence)
            self.assertEqual(first.outcome,Outcome.NOT_APPLIED)
            again=store.record_independent_unknown_recovery(
                recovery_operation_id="recovery",work_id="work",principal_id="owner",
                original_operation_id="original",expected_original_digest=digest,evidence=evidence)
            self.assertTrue(again.duplicate)
            with store.transaction() as db:
                self.assertEqual(before_original,tuple(db.execute("SELECT * FROM operations WHERE operation_id='original'").fetchone()))
                self.assertEqual(before_claims,[tuple(r) for r in db.execute("SELECT * FROM resource_claims")])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM operations WHERE operation_id='recovery'").fetchone()[0],1)
            with self.assertRaises(Exception):
                store.record_independent_unknown_recovery(
                    recovery_operation_id="other",work_id="foreign",principal_id="owner",
                    original_operation_id="original",expected_original_digest=digest,evidence=evidence)
            with self.assertRaises(Exception):
                store.record_independent_unknown_recovery(
                    recovery_operation_id="untrusted-success",work_id="work",
                    principal_id="owner",original_operation_id="original",
                    expected_original_digest=digest,
                    evidence=dict(evidence, status="VERIFIED",
                                  recovery_operation_id="untrusted-success"))
            with self.assertRaises(Exception):
                store.record_independent_unknown_recovery(
                    recovery_operation_id="recovery",work_id="work",principal_id="owner",
                    original_operation_id="original",expected_original_digest="bad",evidence=evidence)
