"""Fixture-only GitHub status UNKNOWN reconciliation acceptance."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import Outcome, Principal, ConflictError, PreconditionError


class FakeReadOnlyGitHub:
    def __init__(self):
        self.fail = True
        self.head = "a" * 40
        self.merged = False
        self.get_calls = 0
        self.merge_calls = 0

    def get_pull_request(self, repository, number):
        self.get_calls += 1
        if self.fail:
            raise subprocess.TimeoutExpired(["gh", "api", "repos/owner/project/pulls/170"], 30)
        return {"number": 170, "head": {"sha": self.head, "ref": "feature"},
                "base": {"ref": "main"}, "state": "closed" if self.merged else "open",
                "merged": self.merged, "merged_at": None if not self.merged else "2026-10-18T00:00:00Z"}

    def get_check_runs(self, repository, sha):
        return [{"id": 5, "name": "test", "status": "completed",
                 "conclusion": "success", "app": {"slug": "github-actions"}}]

    def merge_pull_request(self, *args, **kwargs):
        self.merge_calls += 1
        raise AssertionError("MUTATION_MUST_NOT_BE_CALLED")


class GitHubStatusReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["github_pr_status"]\napproval_actions=[]\n',
            encoding="utf-8")
        self.fake = FakeReadOnlyGitHub()
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy,
                       github_client=self.fake)
        self.owner = Principal("test-owner", "test", frozenset({"github_pr_status"}))
        self.bct.create_work(work_id="w", request_summary="fixture", roots=[str(self.root)],
                             actions=["github_pr_status"], principal=self.owner)
        self.original = {"repository": "owner/project", "number": 170,
                         "expected_head": "a" * 40, "required_checks": ["test"],
                         "wait_seconds": 0}
        self.assertEqual(Outcome.UNKNOWN, self.call("original", self.original).outcome)
        self.assertTrue(self.original_claim())
        self.fake.fail = False

    def tearDown(self):
        self.temp.cleanup()

    def call(self, op, args, *, work_id="w"):
        return self.bct.operations.run(
            principal=self.owner, work_id=work_id, operation_id=op,
            capability="github_pr_status", arguments=args)

    def resolve_args(self, original=None):
        return {"operation": "reconcile", "original_operation_id": "original",
                "original_arguments": self.original if original is None else original}

    def original_claim(self):
        return any(c["operation_id"] == "original"
                   for c in self.bct.store.monitor_snapshot()["unresolved_claims"])

    def test_atomic_resolution_preserves_original_unknown_and_is_idempotent(self):
        result = self.call("resolver", self.resolve_args())
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertFalse(self.original_claim())
        original = self.bct.store.get_operation_for(
            operation_id="original", work_id="w", principal_id="test-owner")
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual("TimeoutExpired", original.evidence["type"])
        self.assertEqual(Outcome.APPLIED, self.call("resolver", self.resolve_args()).outcome)
        self.assertEqual(0, self.fake.merge_calls)
        self.assertGreaterEqual(self.fake.get_calls, 3)

    def test_mutated_original_digest_fail_closed_and_claim_kept(self):
        tampered = dict(self.original)
        tampered["required_checks"] = ["different-check"]
        with self.assertRaises(PreconditionError):
            self.call("resolver-tamper", self.resolve_args(tampered))
        self.assertTrue(self.original_claim())

    def test_stale_head_and_already_merged_fail_closed(self):
        self.fake.head = "b" * 40
        result = self.call("resolver-stale", self.resolve_args())
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertTrue(self.original_claim())
        self.fake.head = "a" * 40
        self.fake.merged = True
        result = self.call("resolver-merged", self.resolve_args())
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertTrue(self.original_claim())

    def test_no_cross_work_resolution_or_arbitrary_source(self):
        self.bct.create_work(work_id="other", request_summary="other fixture",
                             roots=[str(self.root)], actions=["github_pr_status"],
                             principal=self.owner)
        with self.assertRaises(ConflictError):
            self.call("other-resolver", self.resolve_args(), work_id="other")
        self.assertTrue(self.original_claim())
        self.assertEqual(0, self.fake.merge_calls)

    def test_malformed_external_response_is_not_applied(self):
        self.fake.get_pull_request = lambda repository, number: {"number": "not-an-integer"}
        result = self.call("resolver-malformed", self.resolve_args())
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertTrue(self.original_claim())

    def test_wrong_operation_and_no_original_ownership_blocked(self):
        with self.assertRaises(PreconditionError):
            self.call("bad-op", {**self.resolve_args(), "extra": 1})
        self.assertTrue(self.original_claim())
