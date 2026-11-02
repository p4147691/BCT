import tempfile
import unittest
from pathlib import Path

from bct.core.models import DecisionKind, Principal, Work
from bct.core.policy import Policy


class BrowserCapabilityMigrationTests(unittest.TestCase):
    def test_legacy_work_and_policy_authorize_the_renamed_browser_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.toml"
            policy_path.write_text(
                "[policy]\nnormal_actions=[\"relay_browser\"]\napproval_actions=[]\n",
                encoding="utf-8",
            )
            work = Work(
                "legacy-work", "legacy", (directory,), frozenset({"relay_browser"}), "owner"
            )
            principal = Principal("owner", "test", frozenset({"relay_browser"}))
            decision = Policy(policy_path).decide(
                principal=principal, work=work, action="browser"
            )
        self.assertEqual(DecisionKind.ALLOW, decision.kind)
