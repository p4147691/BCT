"""Focused regression coverage for BCT canonical instruction boundary adapters."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import FeatureRequest, PreconditionError
from bct.features.git import GitCommitFeature

from bct.instruction_preflight import (
    find_branch_worktree,
    inspect_feature_branch,
    inspect_work_roots,
    inspect_worktree,
)

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "AGENTS.md",
    ".cursor/rules/bct-delivery-flow.mdc",
    "modules/monitor/extension/AGENTS.md",
)


class InstructionPreflightTests(unittest.TestCase):
    def test_current_canonical_root_matches_itself(self):
        report = inspect_worktree(ROOT, ROOT)
        self.assertEqual("MATCH", report["status"])
        self.assertEqual(3, len(report["results"]))

    def test_changed_worktree_is_stale_and_not_modified(self):
        with tempfile.TemporaryDirectory() as raw:
            tree = Path(raw)
            for rel in FILES:
                target = tree / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / rel).read_bytes())
            original = tree / "AGENTS.md"
            original.write_text("obsolete policy", encoding="utf-8")
            report = inspect_worktree(ROOT, tree)
            self.assertEqual("STALE_INSTRUCTIONS", report["status"])
            self.assertEqual("obsolete policy", original.read_text(encoding="utf-8"))

    def test_missing_worktree_returns_unknown_without_false_success(self):
        with tempfile.TemporaryDirectory() as raw:
            report = inspect_worktree(ROOT, Path(raw) / "missing")
            self.assertEqual("UNKNOWN", report["status"])

    def test_registration_checks_only_linked_worktrees(self):
        with tempfile.TemporaryDirectory() as raw:
            tree = Path(raw)
            canonical = tree / "source"
            canonical.mkdir()
            linked = tree / "worktrees" / "linked"
            linked.mkdir(parents=True)
            (linked / ".git").write_text("gitdir: some-location", encoding="utf-8")
            unrelated = tree / "regular"
            unrelated.mkdir()
            with patch("bct.instruction_preflight.inspect_worktree",
                       return_value={"status": "STALE_INSTRUCTIONS"}) as observe:
                results = inspect_work_roots(canonical, [str(canonical), str(unrelated), str(linked)])
            self.assertEqual([{"status": "STALE_INSTRUCTIONS"}], results)
            observe.assert_called_once_with(canonical.resolve(), linked.resolve())

    def test_too_many_roots_fails_observation_as_unknown(self):
        result = inspect_work_roots(ROOT, [str(ROOT)] * 13)
        self.assertEqual("UNKNOWN", result[0]["status"])

    def test_exact_worktree_branch_resolution(self):
        fixture = (
            "worktree C:/a/source\nHEAD " + "1" * 40 + "\nbranch refs/heads/main\n\n"
            "worktree C:/a/feature\nHEAD " + "2" * 40 +
            "\nbranch refs/heads/fix/sample\n\n"
        )
        completed = subprocess.CompletedProcess(["git"], 0, fixture, "")
        with patch("bct.instruction_preflight.subprocess.run", return_value=completed):
            path = find_branch_worktree(ROOT, "fix/sample")
            missing = find_branch_worktree(ROOT, "fix/other")
        self.assertEqual(Path("C:/a/feature").resolve(), path)
        self.assertIsNone(missing)

    def test_integration_unknown_without_attached_worktree(self):
        with patch("bct.instruction_preflight.find_branch_worktree", return_value=None):
            report = inspect_feature_branch(ROOT, "feature/no-tree")
        self.assertEqual("UNKNOWN", report["status"])
        self.assertEqual("FEATURE_WORKTREE_NOT_ATTACHED", report["reason"])

    def test_merge_rejects_missing_or_stale_candidate_before_effect(self):
        expected_main = "a" * 40
        expected_feature = "b" * 40
        request = FeatureRequest(
            "git_commit", str(ROOT),
            {"operation": "merge_local_main", "branch": "fix/sample",
             "message": "test-only", "expected_head": expected_main,
             "expected_feature_head": expected_feature},
            (),
            {"expected_head": expected_main, "expected_feature_head": expected_feature},
        )
        feature = GitCommitFeature()

        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate"
            candidate.mkdir()
            calls = []

            def fake_git(root, *args, **kwargs):
                calls.append(tuple(args))
                if args == ("rev-parse", "HEAD"):
                    sha = (expected_feature if Path(root).resolve() == candidate.resolve()
                           else expected_main)
                    return subprocess.CompletedProcess(args, 0, sha + "\n", "")
                if args == ("branch", "--show-current"):
                    return subprocess.CompletedProcess(args, 0, "main\n", "")
                if args == ("rev-parse", "--verify", "refs/heads/fix/sample^{commit}"):
                    return subprocess.CompletedProcess(args, 0, expected_feature + "\n", "")
                if args == ("merge-base", "--is-ancestor", expected_feature, expected_main):
                    return subprocess.CompletedProcess(args, 1, "", "")
                raise AssertionError("Unexpected Git action: " + repr(args))

            with (patch("bct.features.git.require_local_main"),
                  patch("bct.features.git._git", side_effect=fake_git),
                  patch("bct.features.git._dirty_paths", return_value=set()),
                  patch("bct.features.git.find_branch_worktree", return_value=None)):
                with self.assertRaisesRegex(
                    PreconditionError, "LOCAL_MAIN_INSTRUCTION_WORKTREE_UNAVAILABLE"
                ):
                    feature._execute_local_main_merge(request)

            with (patch("bct.features.git.require_local_main"),
                  patch("bct.features.git._git", side_effect=fake_git),
                  patch("bct.features.git._dirty_paths", return_value=set()),
                  patch("bct.features.git.find_branch_worktree", return_value=candidate),
                  patch("bct.features.git.inspect_worktree",
                        return_value={"status": "STALE_INSTRUCTIONS"})):
                with self.assertRaisesRegex(
                    PreconditionError,
                    "LOCAL_MAIN_INSTRUCTION_REVIEW_REQUIRED:STALE_INSTRUCTIONS"
                ):
                    feature._execute_local_main_merge(request)

            # Neither rejected path may enter the merge preview or the effect.
            self.assertFalse(any(call and call[0] in ("merge", "merge-tree")
                                 for call in calls))

    def test_work_creation_and_merge_are_wired(self):
        server = (ROOT / "src/bct/mcp_server.py").read_text(encoding="utf-8")
        git = (ROOT / "src/bct/features/git.py").read_text(encoding="utf-8")
        self.assertIn("inspect_work_roots", server)
        self.assertIn("await asyncio.to_thread(", server)
        self.assertIn("find_branch_worktree(root, branch)", git)
        self.assertIn("LOCAL_MAIN_INSTRUCTION_REVIEW_REQUIRED", git)
        self.assertIn("LOCAL_MAIN_INSTRUCTION_CHECKER_UNAVAILABLE", git)
        self.assertLess(git.index("inspect_worktree(root, candidate)"),
                        git.index('preview = _git(root, "merge-tree"'))


if __name__ == "__main__":
    unittest.main()
