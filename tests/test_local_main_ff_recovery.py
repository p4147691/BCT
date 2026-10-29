"""No-live guarded origin/main fast-forward recovery regression."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct import BCT
from bct.core.models import Outcome, Principal, PreconditionError


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8",
        capture_output=True, timeout=35,
    )
    if result.returncode:
        raise AssertionError(f"git {args}: {result.stderr[-450:]}")
    return result.stdout.strip()


class LocalMainGuardedFastForwardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="n63-guarded-ff-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "N63 Isolated")
        git(self.source, "config", "user.email", "n63@example.invalid")
        (self.source / "hello.txt").write_text("baseline\n", encoding="utf-8")
        self.policy = self.source / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["git_commit","github_sync_main"]\n'
            'approval_actions=[]\n[git_authority]\nmode="local"\n'
            'repository="p4147691/BCT"\n'
            f"source_root={json.dumps(str(self.source))}\n", encoding="utf-8",
        )
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "initial")
        self.initial = git(self.source, "rev-parse", "HEAD")
        self.remote = self.base / "origin.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "-b", "main")
        git(self.source, "remote", "add", "origin", str(self.remote))
        git(self.source, "push", "-u", "origin", "main")
        self.other = self.base / "remote-writer"
        clone = subprocess.run(["git", "clone", "-b", "main",
                                str(self.remote), str(self.other)],
                               capture_output=True, text=True, timeout=35)
        self.assertEqual(0, clone.returncode, clone.stderr)
        git(self.other, "config", "user.name", "N63 Remote")
        git(self.other, "config", "user.email", "remote@example.invalid")
        self.principal = Principal("n63", "isolated",
                                   frozenset({"git_commit", "github_sync_main"}))
        self.bct = BCT(state_path=self.base / "state.sqlite", policy_path=self.policy)
        self.bct.create_work(work_id="n63-recovery", request_summary="bounded",
                             roots=[str(self.source)],
                             actions=["git_commit", "github_sync_main"],
                             principal=self.principal)

    def remote_commit(self, filename="remote.txt"):
        (self.other / filename).write_text("from remote\n", encoding="utf-8")
        git(self.other, "add", filename)
        git(self.other, "commit", "-m", "remote change")
        git(self.other, "push", "origin", "main")
        return git(self.remote, "rev-parse", "refs/heads/main")

    def run_recovery(self, operation_id, expected_head=None, expected_remote_head=None):
        with patch("bct.features.git._remote_matches", return_value=True):
            return self.bct.operations.run(
                principal=self.principal, work_id="n63-recovery",
                operation_id=operation_id, capability="git_commit",
                arguments={
                    "operation": "fast_forward_local_main_recovery",
                    "path": str(self.source),
                    "expected_head": expected_head or self.initial,
                    "expected_remote_head": expected_remote_head or self.initial,
                },
            )

    def test_exact_ancestor_clean_remote_forward_and_duplicate(self):
        remote_sha = self.remote_commit()
        result = self.run_recovery("ff-exact", expected_remote_head=remote_sha)
        self.assertEqual(Outcome.APPLIED, result.outcome, result.as_dict())
        self.assertEqual(self.initial, result.evidence["head_before"])
        self.assertEqual(remote_sha, result.evidence["head_after"])
        self.assertFalse(result.evidence["already_current"])
        self.assertEqual(remote_sha, git(self.source, "rev-parse", "HEAD"))
        self.assertEqual("", git(self.source, "status", "--porcelain=v1"))
        duplicate = self.run_recovery("ff-exact", expected_remote_head=remote_sha)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(remote_sha, git(self.source, "rev-parse", "HEAD"))

    def test_already_current_requires_exact_remote_identity(self):
        result = self.run_recovery("ff-current")
        self.assertEqual(Outcome.APPLIED, result.outcome, result.as_dict())
        self.assertTrue(result.evidence["already_current"])
        self.assertEqual(self.initial, git(self.source, "rev-parse", "HEAD"))

    def test_mismatched_remote_sha_does_not_change_local_main(self):
        self.remote_commit()
        result = self.run_recovery("ff-remote-sha-wrong")
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome, result.as_dict())
        self.assertIn("LOCAL_MAIN_FF_REMOTE_SHA_CHANGED", result.error)
        self.assertEqual(self.initial, git(self.source, "rev-parse", "HEAD"))

    def test_local_dirty_tree_is_rejected(self):
        remote_sha = self.remote_commit()
        (self.source / "dirty.txt").write_text("unsaved\n", encoding="utf-8")
        result = self.run_recovery("ff-dirty", expected_remote_head=remote_sha)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome, result.as_dict())
        self.assertIn("LOCAL_MAIN_FF_WORKTREE_DIRTY", result.error)
        self.assertEqual(self.initial, git(self.source, "rev-parse", "HEAD"))

    def test_divergent_local_main_is_rejected_without_merge(self):
        remote_sha = self.remote_commit()
        (self.source / "local.txt").write_text("independent\n", encoding="utf-8")
        git(self.source, "add", "local.txt")
        git(self.source, "commit", "-m", "local divergence")
        local_sha = git(self.source, "rev-parse", "HEAD")
        result = self.run_recovery("ff-diverged", expected_head=local_sha,
                                   expected_remote_head=remote_sha)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome, result.as_dict())
        self.assertIn("LOCAL_MAIN_FF_NOT_ANCESTOR", result.error)
        self.assertEqual(local_sha, git(self.source, "rev-parse", "HEAD"))

    def test_remote_identity_and_main_branch_rejected(self):
        remote_sha = self.remote_commit()
        # Without the exact GitHub repository identity, even a matching SHA
        # cannot authorize an external remote.
        result = self.bct.operations.run(
            principal=self.principal, work_id="n63-recovery",
            operation_id="ff-wrong-remote-identity", capability="git_commit",
            arguments={"operation": "fast_forward_local_main_recovery",
                       "path": str(self.source), "expected_head": self.initial,
                       "expected_remote_head": remote_sha},
        )
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome, result.as_dict())
        self.assertIn("LOCAL_MAIN_FF_REMOTE_IDENTITY_MISMATCH", result.error)
        git(self.source, "checkout", "-b", "not-main")
        branch_result = self.run_recovery("ff-wrong-branch", expected_remote_head=remote_sha)
        self.assertEqual(Outcome.NOT_APPLIED, branch_result.outcome, branch_result.as_dict())
        self.assertIn("LOCAL_MAIN_FF_MAIN_BRANCH_REQUIRED", branch_result.error)

    def test_wrong_expected_local_head_and_extra_arguments_rejected(self):
        result = self.run_recovery("ff-incorrect-local",
                                   expected_head="a" * 40)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome, result.as_dict())
        self.assertIn("LOCAL_MAIN_FF_HEAD_MISMATCH", result.error)
        with self.assertRaises(PreconditionError):
            self.bct.operations.run(
                principal=self.principal, work_id="n63-recovery",
                operation_id="ff-wrong-args", capability="git_commit",
                arguments={"operation": "fast_forward_local_main_recovery",
                           "path": str(self.source), "expected_head": self.initial,
                           "expected_remote_head": self.initial, "force": True},
            )

    def test_existing_github_sync_main_forbidden_unchanged(self):
        with self.assertRaises(PreconditionError) as result:
            self.bct.operations.run(
                principal=self.principal, work_id="n63-recovery",
                operation_id="forbidden-old-sync", capability="github_sync_main",
                arguments={"path": str(self.source), "repository": "p4147691/BCT",
                           "expected_local_head": self.initial,
                           "verified_main_sha": self.initial},
            )
        self.assertIn("LOCAL_MAIN_REMOTE_SYNC_FORBIDDEN", str(result.exception))


if __name__ == "__main__":
    unittest.main()
