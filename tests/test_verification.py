from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from bct import BCT
from bct.core.models import AuthorizationError, ConflictError, FeatureResult, Outcome, PreconditionError, Principal
from bct.features.github import _check_evidence
from bct.background_operations import launch_background_operation


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.actions = ["verify", "read", "test", "github_pr_status"]
        self.policy.write_text('[policy]\nnormal_actions=' + json.dumps(self.actions) + '\napproval_actions=[]\n')
        self.github = Mock()
        self.sha = "a" * 40
        self.pull = {"number": 1, "state": "open", "head": {"sha": self.sha, "ref": "feature"}, "base": {"ref": "main"}}
        self.github.get_pull_request.return_value = self.pull
        self.github.get_check_runs.return_value = [{"id": 2, "name": "test", "status": "completed", "conclusion": "success"}]
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy, github_client=self.github)
        self.principal = Principal("owner", "test", frozenset(self.actions))
        self.bct.create_work(work_id="work", request_summary="verify", roots=[str(self.root)], actions=self.actions, principal=self.principal)
        (self.root / "sample.py").write_text("answer = 42\n")
        self.steps = [
            {"id": "source", "capability": "read", "arguments": {"path": str(self.root / "sample.py")}},
            {"id": "compile", "capability": "test", "arguments": {"cwd": str(self.root), "kind": "py_compile", "targets": ["sample.py"]}},
        ]

    def call(self, operation="verify-1", steps=None, principal=None):
        return self.bct.operations.run(principal=principal or self.principal, work_id="work",
            operation_id=operation, capability="verify", arguments={"steps": self.steps if steps is None else steps})

    def test_real_checks_duplicate_and_durable_metadata(self):
        result = self.call()
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("PASS", result.evidence["status"])
        self.assertNotIn("answer = 42", json.dumps(result.as_dict()))
        with patch.object(self.bct.operations._features["test"], "execute", side_effect=AssertionError("replayed")):
            self.assertTrue(self.call().duplicate)
        receipt = self.bct.store.get_operation_for(operation_id="verify-1", work_id="work", principal_id="owner")
        self.assertEqual(result.evidence, receipt.evidence)

    def test_all_steps_prevalidated_and_principal_scoped(self):
        with patch.object(self.bct.operations._features["read"], "execute") as execute:
            for invalid in [
                self.steps + [{"id": "bad", "capability": "deploy", "arguments": {}}],
                self.steps + [self.steps[0]],
                [{"id": "escape", "capability": "read", "arguments": {"path": str(self.root.parent / "outside")}}],
            ]:
                with self.assertRaises(PreconditionError):
                    self.call(steps=invalid)
            with self.assertRaises(AuthorizationError):
                self.call(principal=replace(self.principal, capabilities=frozenset({"verify"})))
            execute.assert_not_called()

    def test_fail_fast_and_unknown_claims_preserved(self):
        reader = self.bct.operations._features["read"]
        tester = self.bct.operations._features["test"]
        with patch.object(reader, "execute", return_value=FeatureResult(Outcome.UNKNOWN, {"code": "lost"}, release_claims=False)), patch.object(tester, "execute") as execute:
            result = self.call()
            self.assertEqual(Outcome.UNKNOWN, result.outcome)
            execute.assert_not_called()
        with self.assertRaises(ConflictError):
            self.call(operation="cannot-bypass")

    def test_test_failure_stops_later_steps(self):
        with patch.object(self.bct.operations._features["test"], "execute", return_value=FeatureResult(Outcome.APPLIED, {"status": "FAIL"})) as execute:
            result = self.call(steps=[self.steps[1], {**self.steps[1], "id": "later"}])
            self.assertEqual(Outcome.FAILED, result.outcome)
            self.assertEqual(1, execute.call_count)

    def test_policy_change_between_steps_stops(self):
        reader = self.bct.operations._features["read"]
        original = reader.execute
        def change_policy(request):
            result = original(request)
            self.policy.write_text('[policy]\nnormal_actions=["verify","read"]\napproval_actions=["test"]\n')
            return result
        with patch.object(reader, "execute", side_effect=change_policy), patch.object(self.bct.operations._features["test"], "execute") as execute:
            result = self.call()
            self.assertEqual(Outcome.FAILED, result.outcome)
            self.assertEqual(2, len(result.evidence["steps"]))
            execute.assert_not_called()

    def ci_step(self, wait=0):
        return {"id": "ci", "capability": "github_pr_status", "arguments": {"repository": "owner/repo", "number": 1,
            "expected_head": self.sha, "required_checks": ["test"], "wait_seconds": wait}}

    def test_ci_wait_ready_and_no_client_polling(self):
        self.github.get_check_runs.side_effect = [
            [{"name": "test", "status": "in_progress"}],
            [{"name": "test", "status": "completed", "conclusion": "success"}],
        ]
        with patch("bct.features.github.time.sleep"):
            result = self.call(steps=[self.ci_step(30)])
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(2, result.evidence["steps"][0]["evidence"]["poll_count"])

    def test_ci_stale_head_pending_failure_and_latest_check(self):
        self.github.get_pull_request.side_effect = [self.pull, {**self.pull, "head": {"sha": "b" * 40}}]
        stale = self.call(steps=[self.ci_step()])
        self.assertEqual(Outcome.FAILED, stale.outcome)
        self.github.get_pull_request.side_effect = None
        self.github.get_check_runs.return_value = [{"name": "test", "status": "in_progress"}]
        pending = self.call(operation="pending", steps=[self.ci_step()])
        self.assertEqual("PENDING", pending.evidence["steps"][0]["evidence"]["wait_status"])
        runs = [{"id": 3, "name": "test", "status": "completed", "conclusion": "failure"},
                {"id": 1, "name": "test", "status": "completed", "conclusion": "success"}]
        self.assertFalse(_check_evidence(runs, ["test"])[0])

    def test_nonfinite_wait_rejected(self):
        for wait in (float("nan"), float("inf"), -1, 301):
            with self.assertRaises(PreconditionError):
                self.call(steps=[self.ci_step(wait)])

    def test_launch_metadata_failure_does_not_release_or_replay(self):
        process = Mock(pid=123)
        with patch("bct.background_operations._runtime_root", return_value=self.root / "runtime"), \
             patch("bct.background_operations.subprocess.Popen", return_value=process), \
             patch("bct.background_operations.process_identity", side_effect=OSError("unavailable")):
            result = launch_background_operation(self.bct, principal=self.principal, work_id="work",
                operation_id="launch-failed", capability="verify", arguments={"steps": self.steps}, approval_ref=None)
        self.assertEqual("RUNNING", result.state.value)
        process.terminate.assert_not_called()
        with self.assertRaises(ConflictError):
            self.call(operation="cannot-repeat")
        jobs = list((self.root / "runtime" / "background-operations").glob("*.job.json"))
        self.assertEqual(1, len(jobs))
        job = json.loads(jobs[0].read_text())
        self.assertLess(job["not_before"] - job["created_at"], 0.1)


if __name__ == "__main__":
    unittest.main()
