import unittest
from bct.features.window_layout_unknown import diagnose_unknown

class UnknownDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.original={"operation_id":"op-one","outcome":"UNKNOWN","detail":{"raw":"keep"}}
        self.before={"hwnd":"20","pid":45,"x":0}
        self.fingerprint=("hwnd","pid")
    def run_diagnosis(self,after):
        return diagnose_unknown(self.original,self.before,after,fingerprint_keys=self.fingerprint,effect_keys=("x",))
    def test_original_preserved_and_no_replay(self):
        snapshot=repr(self.original)
        result=self.run_diagnosis({**self.before,"x":50})
        self.assertEqual(result["diagnosis"],"STATE_CHANGED_CAUSALITY_UNPROVEN")
        self.assertFalse(result["replay_allowed"])
        self.assertEqual(repr(self.original),snapshot)
    def test_missing_and_changed_identity(self):
        self.assertEqual(self.run_diagnosis(None)["diagnosis"],"INSUFFICIENT_EVIDENCE")
        self.assertEqual(self.run_diagnosis({**self.before,"pid":46})["diagnosis"],"IDENTITY_CHANGED")
    def test_same_state_not_proof_of_no_effect(self):
        self.assertEqual(self.run_diagnosis(self.before)["diagnosis"],"NO_OBSERVED_CHANGE_NOT_PROOF_OF_NO_EFFECT")
    def test_non_unknown(self):
        receipt={**self.original,"outcome":"APPLIED"}
        r=diagnose_unknown(receipt,self.before,self.before,fingerprint_keys=self.fingerprint,effect_keys=("x",))
        self.assertEqual(r["diagnosis"],"NOT_AN_UNKNOWN")
