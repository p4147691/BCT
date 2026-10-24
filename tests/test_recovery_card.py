import hashlib
import json
import unittest
from bct.recovery_card import build_card, serialize_card

class RecoveryCardTests(unittest.TestCase):
    def fixture(self):
        return dict(predecessor={"work_id":"BCT-GITHUB-COMPLETION-INBOX-V1-20261025-01",
                    "conversation":"N32","state":"DISCONNECTED"},
            observations={"worktree":r"D:\BCT\worktrees\bct-github-completion-inbox-v1-20261025",
              "branch":"feat/github-completion-inbox-v1-20261025",
              "commit":"351d536276df292920b71856148e9eccbe6b93dc",
              "pr":332,"ci":"UNKNOWN","tests":"focused fixtures PASS","pending":"후임 검증 필요 🧪"},
            verified_evidence={"worktree":"git worktree local","branch":"git symbolic-ref",
              "commit":"git rev-parse",},
            protected_resources=["Chrome","RCC","main","D1 진단 67402ae 🦊"],
            next_minimal_step="PR #332와 CI 최신 상태를 조회해 미완료 작업만 판단")
    def test_deterministic_and_no_claim(self):
        args=self.fixture(); a=build_card(**args);b=build_card(**args)
        self.assertEqual(serialize_card(a),serialize_card(b))
        self.assertEqual(a["successor_assignment"]["state"],"PREPARED_ONLY")
        self.assertNotIn("claim",str(a).lower())
        self.assertEqual(a["effect"],"NONE_READ_ONLY")
    def test_unknown_not_promoted(self):
        a=build_card(**self.fixture())
        self.assertIn("CI_UNVERIFIED",a["UNKNOWN"])
        self.assertNotIn("ci",a["verified_facts"])
    def test_recovered_assignment_same_idempotency(self):
        a=build_card(**self.fixture());b=build_card(**self.fixture())
        self.assertEqual(a["successor_assignment"]["idempotency_key"],b["successor_assignment"]["idempotency_key"])
    def test_utf8_korean_emoji_and_codepage_independent(self):
        a=build_card(**self.fixture());raw=serialize_card(a)
        self.assertEqual(raw.decode("utf-8").encode("utf-8"),raw)
        self.assertIn("PR #332",raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),hashlib.sha256(raw.decode("utf-8").encode("utf-8")).hexdigest())
        self.assertNotEqual(raw.decode("cp949",errors="replace").encode("cp949",errors="replace"),raw)
    def test_unknown_duplicate_resources(self):
        args=self.fixture();args["protected_resources"]=["main","main","RCC"]
        a=build_card(**args)
        self.assertEqual(a["protected_resources"],["RCC","main"])
if __name__=="__main__": unittest.main()
