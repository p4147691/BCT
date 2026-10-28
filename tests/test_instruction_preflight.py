"""Focused regression coverage for BCT canonical instruction boundary adapters."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_work_creation_and_merge_are_wired(self):
        server = (ROOT / "src/bct/mcp_server.py").read_text(encoding="utf-8")
        git = (ROOT / "src/bct/features/git.py").read_text(encoding="utf-8")
        self.assertIn("inspect_work_roots", server)
        self.assertIn("await asyncio.to_thread(", server)
        self.assertIn("find_branch_worktree(root, branch)", git)
        self.assertIn("LOCAL_MAIN_INSTRUCTION_REVIEW_REQUIRED", git)
        self.assertLess(git.index("inspect_worktree(root, candidate)"),
                        git.index('preview = _git(root, "merge-tree"')))


if __name__ == "__main__":
    unittest.main()
