from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct import BCT
from bct.core.models import Principal, Work
from bct.github_inbox_autofollow import schedule_pr_ci_inbox


class AutoInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        policy = root / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["github_pr_create","github_run_watch"]\n'
            'approval_actions=[]\n[github_inbox]\ninitial_seconds=5\n'
            'max_seconds=30\ntimeout_seconds=3600\n', encoding="utf-8"
        )
        self.bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
        self.principal = Principal("ci-user", "test",
                                   frozenset({"github_pr_create", "github_run_watch"}))
        self.work = Work("ci-work", "create PR", (str(root),),
                         frozenset({"github_pr_create"}), "ci-user")
        self.bct.store.create_work(self.work)
        self.evidence = {"repository": "p4147691/BCT",
                         "head_sha": "a" * 40, "number": 385}

    def tearDown(self):
        self.temp.cleanup()

    def test_auto_uses_work_inbox_without_inventing_manager(self):
        launched = []
        with patch("bct.github_inbox_autofollow.launch_background_operation",
                   side_effect=lambda *args, **kwargs: (
                       launched.append(kwargs) or
                       SimpleNamespace(state=SimpleNamespace(value="RUNNING")))):
            result = schedule_pr_ci_inbox(self.bct, self.principal,
                                          "ci-work", self.evidence)
        self.assertEqual("REGISTERED", result["status"])
        self.assertEqual("WORK", result["recipient_kind"])
        self.assertTrue(launched[0]["arguments"]["initiator_node_id"].startswith("work:"))
        self.assertFalse(launched[0]["arguments"]["notify_manager"])
        self.assertEqual("ci-work", launched[0]["arguments"]["inbox_work_id"])
        self.assertEqual("github_run_watch", launched[0]["capability"])
        self.assertEqual("RUNNING", result["receipt_state"])

    def test_same_exact_pr_uses_same_follow_work_and_operation(self):
        records = []
        with patch("bct.github_inbox_autofollow.launch_background_operation",
                   side_effect=lambda *a, **k: (
                       records.append(k) or
                       SimpleNamespace(state=SimpleNamespace(value="RUNNING")))):
            first = schedule_pr_ci_inbox(self.bct, self.principal, "ci-work", self.evidence)
            second = schedule_pr_ci_inbox(self.bct, self.principal, "ci-work", self.evidence)
        self.assertEqual(first["watch_work_id"], second["watch_work_id"])
        self.assertEqual(records[0]["operation_id"], records[1]["operation_id"])

    def test_no_pr_identity_has_no_effect(self):
        with patch("bct.github_inbox_autofollow.launch_background_operation") as spy:
            result = schedule_pr_ci_inbox(self.bct, self.principal, "ci-work", {})
        self.assertEqual("NO_EXACT_PR_EVIDENCE", result["status"])
        spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
