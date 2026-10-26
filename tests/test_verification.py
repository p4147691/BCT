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
from bct.background_operations import (
    launch_background_operation, recover_orphaned_orchestration_operations,
)


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

    def call(self, operation="verify-1", steps=None, principal=None, arguments=None):
        return self.bct.operations.run(principal=principal or self.principal, work_id="work",
            operation_id=operation, capability="verify",
            arguments=arguments or {"steps": self.steps if steps is None else steps})

    def test_real_checks_duplicate_and_durable_metadata(self):
        result = self.call()
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("PASS", result.evidence["status"])
        self.assertNotIn("answer = 42", json.dumps(result.as_dict()))
        with patch.object(self.bct.operations._features["test"], "execute", side_effect=AssertionError("replayed")):
            self.assertTrue(self.call().duplicate)
        receipt = self.bct.store.get_operation_for(operation_id="verify-1", work_id="work", principal_id="owner")
        self.assertEqual(result.evidence, receipt.evidence)
        journal = self.bct.store.get_operation_steps_for(
            operation_id="verify-1", work_id="work", principal_id="owner",
        )
        self.assertEqual(["source", "compile"], [step["step_id"] for step in journal])
        self.assertEqual(["FINISHED", "FINISHED"], [step["state"] for step in journal])
        self.assertEqual(["APPLIED", "APPLIED"], [step["outcome"] for step in journal])
        self.assertTrue(all(len(step["request_digest"]) == 64 for step in journal))

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

    def test_fail_fast_preserves_unknown_receipt_without_blocking_successor(self):
        reader = self.bct.operations._features["read"]
        tester = self.bct.operations._features["test"]
        with patch.object(reader, "execute", return_value=FeatureResult(Outcome.UNKNOWN, {"code": "lost"}, release_claims=False)), patch.object(tester, "execute") as execute:
            result = self.call()
            self.assertEqual(Outcome.UNKNOWN, result.outcome)
            execute.assert_not_called()
        journal = self.bct.store.get_operation_steps(operation_id="verify-1")
        self.assertEqual("UNKNOWN", journal[0]["outcome"])
        self.assertEqual("SKIPPED", journal[1]["state"])
        successor = self.call(operation="cannot-bypass")
        self.assertEqual(Outcome.APPLIED, successor.outcome)
        original = self.bct.store.get_operation_for(
            operation_id="verify-1", work_id="work", principal_id="owner",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)

    def test_test_failure_stops_later_steps(self):
        with patch.object(self.bct.operations._features["test"], "execute", return_value=FeatureResult(Outcome.APPLIED, {"status": "FAIL"})) as execute:
            result = self.call(steps=[self.steps[1], {**self.steps[1], "id": "later"}])
            self.assertEqual(Outcome.FAILED, result.outcome)
            self.assertEqual(1, execute.call_count)
        journal = self.bct.store.get_operation_steps(operation_id="verify-1")
        self.assertEqual("FAILED", journal[0]["outcome"])
        self.assertEqual("SKIPPED", journal[1]["state"])

    def test_unexpected_verification_error_is_failed_not_unknown(self):
        reader = self.bct.operations._features["read"]
        tester = self.bct.operations._features["test"]
        with patch.object(
            reader, "execute", side_effect=RuntimeError("local reader defect")
        ), patch.object(tester, "execute") as execute:
            result = self.call(operation="verification-contract-failure")
        self.assertEqual(Outcome.FAILED, result.outcome)
        self.assertEqual(
            "VERIFY_STEP_CONTRACT_FAILURE",
            result.evidence["steps"][0]["evidence"]["code"],
        )
        execute.assert_not_called()
        self.assertFalse(any(
            item["operation_id"] == "verification-contract-failure"
            for item in self.bct.store.claim_diagnostics()
        ))

    def test_abrupt_worker_loss_leaves_exact_checkpoint_without_replay(self):
        steps = [self.steps[0], self.steps[1], {**self.steps[0], "id": "later"}]
        with patch.object(self.bct.operations._features["test"], "execute",
                          side_effect=KeyboardInterrupt("simulated worker loss")):
            with self.assertRaises(KeyboardInterrupt):
                self.call(operation="abrupt", steps=steps)
        operation = self.bct.store.get_operation_for(
            operation_id="abrupt", work_id="work", principal_id="owner",
        )
        self.assertEqual("RUNNING", operation.state.value)
        journal = self.bct.store.get_operation_steps(operation_id="abrupt")
        self.assertEqual(["FINISHED", "RUNNING", "PENDING"], [step["state"] for step in journal])
        self.assertEqual("APPLIED", journal[0]["outcome"])
        self.assertIsNone(journal[1]["outcome"])

    def test_worker_loss_after_plan_checkpoint_does_not_claim_block_new_operation(self):
        original = self.bct.store.initialize_operation_steps

        def stop_after_checkpoint(**values):
            original(**values)
            raise KeyboardInterrupt("lost after plan checkpoint")

        with patch.object(self.bct.store, "initialize_operation_steps",
                          side_effect=stop_after_checkpoint):
            with self.assertRaises(KeyboardInterrupt):
                self.call(operation="plan-checkpoint")
        operation = self.bct.store.get_operation_for(
            operation_id="plan-checkpoint", work_id="work", principal_id="owner",
        )
        self.assertEqual("RUNNING", operation.state.value)
        journal = self.bct.store.get_operation_steps(operation_id="plan-checkpoint")
        self.assertEqual(["PENDING", "PENDING"], [step["state"] for step in journal])
        successor = self.call(operation="plan-checkpoint-bypass")
        self.assertEqual(Outcome.APPLIED, successor.outcome)

    def test_worker_loss_after_running_checkpoint_does_not_claim_block_new_operation(self):
        original = self.bct.store.start_operation_step

        def stop_after_checkpoint(**values):
            result = original(**values)
            raise KeyboardInterrupt("lost before child dispatch")

        reader = self.bct.operations._features["read"]
        with patch.object(self.bct.store, "start_operation_step",
                          side_effect=stop_after_checkpoint), \
             patch.object(reader, "execute") as execute:
            with self.assertRaises(KeyboardInterrupt):
                self.call(operation="running-checkpoint")
        execute.assert_not_called()
        journal = self.bct.store.get_operation_steps(operation_id="running-checkpoint")
        self.assertEqual(["RUNNING", "PENDING"], [step["state"] for step in journal])
        successor = self.call(operation="running-checkpoint-bypass")
        self.assertEqual(Outcome.APPLIED, successor.outcome)

    def test_fixed_local_recipe_and_versioned_digest(self):
        arguments = {
            "recipe_id": "local-python-validation",
            "recipe_version": 1,
            "inputs": {
                "paths": [str(self.root / "sample.py")],
                "cwd": str(self.root),
                "kind": "py_compile",
                "targets": ["sample.py"],
                "timeout_s": 30,
            },
        }
        result = self.call(operation="recipe-local", arguments=arguments)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("local-python-validation", result.evidence["recipe"]["id"])
        self.assertEqual(1, result.evidence["recipe"]["version"])
        self.assertEqual(64, len(result.evidence["recipe"]["plan_digest"]))
        self.assertEqual(["sources", "tests"], [
            step["step_id"] for step in self.bct.store.get_operation_steps(
                operation_id="recipe-local",
            )
        ])
        self.assertTrue(self.call(operation="recipe-local", arguments=arguments).duplicate)
        changed = {**arguments, "inputs": {**arguments["inputs"], "timeout_s": 31}}
        with self.assertRaises(ConflictError):
            self.call(operation="recipe-local", arguments=changed)

    def test_fixed_pr_recipe_and_invalid_recipe_contracts(self):
        arguments = {
            "recipe_id": "pr-readiness", "recipe_version": 1,
            "inputs": {
                "repository": "owner/repo", "number": 1,
                "expected_head": self.sha, "required_checks": ["test"],
                "wait_seconds": 0,
            },
        }
        result = self.call(operation="recipe-pr", arguments=arguments)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("github_pr_status", self.bct.store.get_operation_steps(
            operation_id="recipe-pr",
        )[0]["capability"])
        invalid = [
            {**arguments, "recipe_version": 2},
            {**arguments, "recipe_version": 1.0},
            {**arguments, "recipe_id": "arbitrary"},
            {**arguments, "steps": self.steps},
            {**arguments, "inputs": {**arguments["inputs"], "unknown": True}},
        ]
        for index, value in enumerate(invalid):
            with self.assertRaises(PreconditionError):
                self.call(operation=f"invalid-recipe-{index}", arguments=value)

    def test_pr_recipe_receipt_is_historical_and_new_operation_reads_current_head(self):
        arguments = {
            "recipe_id": "pr-readiness", "recipe_version": 1,
            "inputs": {
                "repository": "owner/repo", "number": 1,
                "expected_head": self.sha, "required_checks": ["test"],
                "wait_seconds": 0,
            },
        }
        historical = self.call(operation="ci-history", arguments=arguments)
        self.assertEqual(Outcome.APPLIED, historical.outcome)
        self.github.get_pull_request.return_value = {
            **self.pull, "head": {"sha": "b" * 40},
        }
        duplicate = self.call(operation="ci-history", arguments=arguments)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(Outcome.APPLIED, duplicate.outcome)
        current = self.call(operation="ci-current", arguments=arguments)
        self.assertEqual(Outcome.FAILED, current.outcome)
        self.assertEqual(
            "GITHUB_PR_HEAD_MISMATCH",
            current.evidence["steps"][0]["evidence"]["code"],
        )

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

    def test_launch_metadata_failure_does_not_claim_block_new_operation(self):
        process = Mock(pid=123)
        with patch("bct.background_operations._runtime_root", return_value=self.root / "runtime"), \
             patch("bct.background_operations.subprocess.Popen", return_value=process), \
             patch("bct.background_operations.process_identity", side_effect=OSError("unavailable")):
            result = launch_background_operation(self.bct, principal=self.principal, work_id="work",
                operation_id="launch-failed", capability="verify", arguments={"steps": self.steps}, approval_ref=None)
        self.assertEqual("RUNNING", result.state.value)
        process.terminate.assert_not_called()
        successor = self.call(operation="cannot-repeat")
        self.assertEqual(Outcome.APPLIED, successor.outcome)
        jobs = list((self.root / "runtime" / "background-operations").glob("*.job.json"))
        self.assertEqual(1, len(jobs))
        job = json.loads(jobs[0].read_text())
        self.assertLess(job["not_before"] - job["created_at"], 0.1)

    def test_confirmed_process_creation_failure_releases_claim(self):
        with patch(
            "bct.background_operations._runtime_root",
            return_value=self.root / "runtime",
        ), patch(
            "bct.background_operations.subprocess.Popen",
            side_effect=OSError("process creation rejected"),
        ):
            result = launch_background_operation(
                self.bct, principal=self.principal, work_id="work",
                operation_id="spawn-not-started", capability="verify",
                arguments={"steps": self.steps}, approval_ref=None,
            )
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertFalse(any(
            item["operation_id"] == "spawn-not-started"
            for item in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))

    def test_core_startup_relaunches_exact_orphaned_orchestration_job(self):
        runtime = self.root / "orphan-runtime"
        state = runtime / "state" / "state.sqlite"
        policy = self.root / "orphan-policy.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        bct = BCT(state_path=state, policy_path=policy)
        principal = Principal("orphan-owner", "test", frozenset({"orchestrate"}))
        bct.create_work(
            work_id="orphan-work", request_summary="restart exact resolver",
            roots=[str(self.root)], actions=["orchestrate"], principal=principal,
        )
        arguments = {
            "operation": "chain-resume", "session_id": "durable-session",
            "manager_epoch": 1, "original_operation_id": "original-chain",
        }
        jobs = runtime / "background-operations"
        import hashlib
        key = hashlib.sha256(b"orphan-resolver").hexdigest()
        claim = jobs / f"{key}.claim"
        with patch("bct.background_operations._spawn_worker"):
            current = launch_background_operation(
                bct, principal=principal, work_id="orphan-work",
                operation_id="orphan-resolver", capability="orchestrate",
                arguments=arguments, approval_ref=None,
            )
        self.assertEqual("RUNNING", current.state.value)
        # Simulate a crash after O_EXCL created the claim but before JSON/fsync.
        claim.write_bytes(b"")
        (jobs / f"{key}.launch.json").write_text(json.dumps({
            "schema_version": 1, "worker": {
                "pid": 999999, "fingerprint": "gone",
            },
        }), encoding="utf-8")
        with patch("bct.background_operations.process_identity", return_value=None), \
             patch("bct.background_operations._spawn_worker") as spawn:
            recovered = recover_orphaned_orchestration_operations(bct)
        self.assertEqual("RESTARTED_EXACT_JOB", recovered[0]["status"])
        spawn.assert_called_once()
        self.assertFalse(claim.exists())
        self.assertEqual(1, len(list(jobs.glob(f"{key}.claim.stale.*"))))
        still_running = bct.store.get_operation_for(
            operation_id="orphan-resolver", work_id="orphan-work",
            principal_id="orphan-owner",
        )
        self.assertEqual("RUNNING", still_running.state.value)

    def test_durable_job_row_repairs_begin_to_file_crash(self):
        runtime = self.root / "gap-runtime"
        policy = self.root / "gap-policy.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        bct = BCT(
            state_path=runtime / "state" / "state.sqlite", policy_path=policy
        )
        principal = Principal("gap-owner", "test", frozenset({"orchestrate"}))
        bct.create_work(
            work_id="gap-work", request_summary="atomic background intent",
            roots=[str(self.root)], actions=["orchestrate"], principal=principal,
        )
        arguments = {
            "operation": "recover-not-dispatched", "session_id": "gap-session",
            "original_operation_id": "gap-original",
        }
        with patch(
            "bct.background_operations.atomic_json",
            side_effect=OSError("crash before job file"),
        ):
            with self.assertRaises(OSError):
                launch_background_operation(
                    bct, principal=principal, work_id="gap-work",
                    operation_id="gap-resolver", capability="orchestrate",
                    arguments=arguments, approval_ref=None,
                )
        pending = bct.store.get_operation_for(
            operation_id="gap-resolver", work_id="gap-work",
            principal_id="gap-owner",
        )
        self.assertEqual("RUNNING", pending.state.value)
        self.assertIsNotNone(bct.store.background_job("gap-resolver"))
        with patch("bct.background_operations._spawn_worker") as spawn:
            recovered = recover_orphaned_orchestration_operations(bct)
        self.assertEqual("RESTARTED_EXACT_JOB", recovered[0]["status"])
        spawn.assert_called_once()

    def test_orphan_recovery_rebinds_to_current_release_policy(self):
        runtime = self.root / "policy-runtime"
        old_policy = self.root / "old-release" / "bct.toml"
        current_policy = self.root / "current-release" / "bct.toml"
        old_policy.parent.mkdir()
        current_policy.parent.mkdir()
        policy_text = (
            '[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n'
        )
        old_policy.write_text(policy_text, encoding="utf-8")
        current_policy.write_text(policy_text, encoding="utf-8")
        original = BCT(
            state_path=runtime / "state" / "state.sqlite",
            policy_path=old_policy,
        )
        principal = Principal("policy-owner", "test", frozenset({"orchestrate"}))
        original.create_work(
            work_id="policy-work", request_summary="current policy recovery",
            roots=[str(self.root)], actions=["orchestrate"], principal=principal,
        )
        arguments = {
            "operation": "chain-resume", "session_id": "policy-session",
            "manager_epoch": 1, "original_operation_id": "policy-original",
        }
        with patch("bct.background_operations._spawn_worker"):
            launch_background_operation(
                original, principal=principal, work_id="policy-work",
                operation_id="policy-resolver", capability="orchestrate",
                arguments=arguments, approval_ref=None,
            )
        current = BCT(
            state_path=runtime / "state" / "state.sqlite",
            policy_path=current_policy,
        )
        captured = {}
        def capture_spawn(_bct, **values):
            captured.update(json.loads(values["job_path"].read_text(encoding="utf-8")))
            return {}
        with patch(
            "bct.background_operations._spawn_worker", side_effect=capture_spawn
        ):
            duplicate = launch_background_operation(
                current, principal=principal, work_id="policy-work",
                operation_id="policy-resolver", capability="orchestrate",
                arguments=arguments, approval_ref=None,
            )
        self.assertEqual("RUNNING", duplicate.state.value)
        self.assertEqual(str(current_policy.resolve()), captured["policy_path"])
        self.assertNotEqual(str(old_policy.resolve()), captured["policy_path"])

    def test_background_executor_lease_allows_only_one_fingerprint(self):
        runtime = self.root / "lease-runtime"
        policy = self.root / "lease-policy.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        bct = BCT(
            state_path=runtime / "state" / "state.sqlite", policy_path=policy
        )
        principal = Principal("lease-owner", "test", frozenset({"orchestrate"}))
        bct.create_work(
            work_id="lease-work", request_summary="single executor",
            roots=[str(self.root)], actions=["orchestrate"], principal=principal,
        )
        arguments = {
            "operation": "recover-not-dispatched", "session_id": "lease-session",
            "original_operation_id": "lease-original",
        }
        with patch("bct.background_operations._spawn_worker"):
            launch_background_operation(
                bct, principal=principal, work_id="lease-work",
                operation_id="lease-resolver", capability="orchestrate",
                arguments=arguments, approval_ref=None,
            )
        self.assertTrue(bct.store.acquire_background_executor(
            operation_id="lease-resolver", pid=1001, fingerprint="a" * 64,
        ))
        self.assertFalse(bct.store.acquire_background_executor(
            operation_id="lease-resolver", pid=1002, fingerprint="b" * 64,
        ))
        self.assertTrue(bct.store.acquire_background_executor(
            operation_id="lease-resolver", pid=1001, fingerprint="a" * 64,
        ))


if __name__ == "__main__":
    unittest.main()
