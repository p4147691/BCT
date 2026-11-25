from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import Mock, patch

from bct_maintenance.errors import PreconditionError
from bct_maintenance.release_risk import MCP, release_risk, _usage_only, verify_ci
from bct_maintenance.rollout import _recover


class RiskTests(unittest.TestCase):
    def test_only_literal_desktop_help_is_eligible(self):
        before = '_CAPABILITY_USAGE = {"desktop_explore": "before", "browser": "route"}'
        self.assertTrue(_usage_only(before, before.replace('"before"', '"after"')))
        self.assertFalse(_usage_only(before, before.replace('"before"', 'render()')))
        self.assertFalse(_usage_only(before, before.replace('"route"', '"other"')))
        self.assertFalse(_usage_only(before, before + '\nstart()'))

    def test_committed_diff_uses_highest_risk_and_fails_on_wrong_ancestor(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, encoding="utf-8",
                                               stderr=subprocess.DEVNULL).strip()

            def commit(name):
                git("add", ".")
                git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", name)
                return git("rev-parse", "HEAD")

            git("init")
            mcp = root / MCP
            mcp.parent.mkdir(parents=True)
            medium = mcp.with_name("status_views.py")
            mcp.write_text('_CAPABILITY_USAGE = {"desktop_explore": "one"}\n', encoding="utf-8")
            medium.write_text("pass\n", encoding="utf-8")
            before = commit("baseline")
            mcp.write_text('_CAPABILITY_USAGE = {"desktop_explore": "two"}\n', encoding="utf-8")
            low = commit("help")
            medium.write_text("view = {}\n", encoding="utf-8")
            mid = commit("projection")
            mcp.write_text('start()\n', encoding="utf-8")
            high = commit("executable")
            self.assertEqual("LOW", release_risk(root, before, low)["level"])
            self.assertEqual("MEDIUM", release_risk(root, before, mid)["level"])
            self.assertEqual("HIGH", release_risk(root, before, high)["level"])
            with self.assertRaises(PreconditionError):
                release_risk(root, high, low)

    def test_unrelated_successful_ci_run_is_rejected(self):
        with TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.toml"
            policy.write_text('[git_authority]\nrepository = "owner/repo"\n', encoding="utf-8")
            run = ('{"id":12,"path":".github/workflows/ci.yml","head_sha":"other",'
                   '"status":"completed","conclusion":"success","run_attempt":1,'
                   '"head_repository":{"full_name":"owner/repo"}}')
            with patch("bct_maintenance.release_risk.subprocess.run", return_value=SimpleNamespace(stdout=run)):
                with self.assertRaisesRegex(PreconditionError, "EXACT_CI"):
                    verify_ci(policy, "a" * 40, 12)


class RecoveryTests(unittest.TestCase):
    def test_never_replays_unverified_activation(self):
        tool = Mock()
        tool.controller.inspect.return_value = {"state": "STOPPED"}
        tool.current_pointer.return_value = {"source_head": "old"}
        tool.receipt_path.return_value = Path("activate.json")
        tool.root = Path("runtime")
        with patch("bct_maintenance.rollout.read_json", side_effect=[{"state": "UNKNOWN"}, None]):
            self.assertFalse(_recover(tool, "op", "old", "old-hash", "new", "new-hash", "activate"))
        tool.run.assert_not_called()

    def test_verified_rollback_cites_original_unknown(self):
        tool = Mock()
        tool.controller.inspect.return_value = {"state": "STOPPED"}
        tool.current_pointer.return_value = {"source_head": "old"}
        tool.receipt_path.return_value = Path("activate.json")
        tool.root = Path("runtime")
        proof = {"state": "ROLLED_BACK", "rollback_verified": True, "previous_source_head": "old",
                 "source_head": "new", "manifest_sha256": "new-hash", "prepared_at": 2}
        with patch("bct_maintenance.rollout.read_json", side_effect=[{"state": "UNKNOWN", "started_at": 3}, proof]):
            self.assertFalse(_recover(tool, "op", "old", "old-hash", "new", "new-hash", "activate"))
        tool.run.assert_not_called()
        with patch("bct_maintenance.rollout.read_json", side_effect=[{"state": "UNKNOWN", "started_at": 1}, proof]), \
                patch("bct_maintenance.rollout._wait_identity"):
            self.assertTrue(_recover(tool, "op", "old", "old-hash", "new", "new-hash", "activate"))
        tool.run.assert_any_call("recover", operation_id="op-recover", expected_current="old",
                                 target="old", resolves="op-activate")

