import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "audit_instruction_worktrees.py"
spec = importlib.util.spec_from_file_location("audit_instruction_worktrees", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class InstructionAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.canon = dict.fromkeys(audit.FILES, "canonical")

    def test_match(self):
        self.assertEqual(audit.classify(self.canon, self.canon, "", "")[0], "MATCH")

    def test_legacy_authority_is_conflict(self):
        current = {**self.canon, audit.FILES[0]: "old"}
        self.assertEqual(audit.classify(current, self.canon, audit.OLD_MAIN, "")[0], "STALE_CONFLICT")

    def test_fast_lane_is_unverified_not_confirmed(self):
        current = {**self.canon, audit.FILES[1]: "old"}
        self.assertEqual(audit.classify(current, self.canon, "", audit.OLD_LANE)[0], "EXCEPTION_UNVERIFIED_HOLD")

    def test_missing_takes_precedence(self):
        current = {**self.canon, audit.FILES[1]: None}
        self.assertEqual(audit.classify(current, self.canon, audit.OLD_MAIN, "")[0], "MISSING")

    def test_retired_rule_is_not_automatic_conflict(self):
        current = {**self.canon, audit.FILES[2]: "retired"}
        self.assertEqual(audit.classify(current, self.canon, "", "")[0], "COMPATIBILITY_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()