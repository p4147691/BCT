from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from bct import BCT
from bct.core.models import Outcome, Principal


def git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=True,
    )
    return process.stdout.strip()


class FakeGitHub:
    def __init__(self, *, branch_sha: str):
        self.branch_sha = branch_sha
        self.pulls: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = [
            {"name": "test", "status": "completed", "conclusion": "success"}
        ]
        self.create_calls = 0
        self.merge_calls = 0
        self.fail_create_after_apply = False
        self.fail_merge_after_apply = False

    def get_ref_sha(self, repository: str, branch: str) -> str:
        return self.branch_sha

    def list_pull_requests(self, repository: str, *, head: str, base: str) -> list[dict[str, Any]]:
        return [pull for pull in self.pulls
                if pull["head"]["ref"] == head and pull["base"]["ref"] == base]

    def create_pull_request(
        self, repository: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        self.create_calls += 1
        pull = {
            "number": len(self.pulls) + 1,
            "html_url": f"https://github.com/{repository}/pull/{len(self.pulls) + 1}",
            "state": "open",
            "merged": False,
            "merge_commit_sha": None,
            "title": title,
            "body": body,
            "head": {"ref": head, "sha": self.branch_sha},
            "base": {"ref": base},
        }
        self.pulls.append(pull)
        if self.fail_create_after_apply:
            raise RuntimeError("response lost")
        return pull

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        return self.pulls[number - 1]

    def get_check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]:
        return list(self.checks)

    def merge_pull_request(
        self, repository: str, number: int, *, sha: str, method: str
    ) -> dict[str, Any]:
        self.merge_calls += 1
        pull = self.pulls[number - 1]
        pull["merged"] = True
        pull["state"] = "closed"
        pull["merge_commit_sha"] = "b" * 40
        if self.fail_merge_after_apply:
            raise RuntimeError("response lost")
        return {"merged": True, "sha": "b" * 40, "message": "merged"}


class GitHubIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.policy = self.base / "bct.toml"
        self.policy.write_text(
            "[policy]\nnormal_actions=[\"github_push\",\"github_pr_create\","
            "\"github_pr_status\",\"github_pr_merge\",\"github_sync_main\"]\n"
            "approval_actions=[]\n",
            encoding="utf-8",
        )
        self.principal = Principal(
            "developer", "test",
            frozenset({"github_push", "github_pr_create", "github_pr_status",
                       "github_pr_merge", "github_sync_main"}),
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_repo(self, name: str = "project", *, branch: str = "main") -> Path:
        root = self.base / name
        root.mkdir()
        git(root, "init", "-b", branch)
        git(root, "config", "user.name", "BCT Test")
        git(root, "config", "user.email", "bct-test@example.invalid")
        (root / "README.md").write_text("initial\n", encoding="utf-8")
        git(root, "add", "README.md")
        git(root, "commit", "-m", "initial")
        return root

    def make_bct(self, root: Path, fake: FakeGitHub | None = None) -> BCT:
        bct = BCT(
            state_path=self.base / (root.name + "-state.sqlite"),
            policy_path=self.policy,
            github_client=fake,
        )
        bct.create_work(
            work_id=root.name,
            request_summary="GitHub integration acceptance",
            roots=[str(root)],
            actions=list(self.principal.capabilities),
            principal=self.principal,
        )
        return bct

    def call(self, bct: BCT, root: Path, operation: str, capability: str, arguments: dict[str, Any]):
        return bct.operations.run(
            principal=self.principal,
            work_id=root.name,
            operation_id=operation,
            capability=capability,
            arguments=arguments,
        )

    def test_exact_push_and_remote_duplicate_guard(self):
        root = self.make_repo(branch="feature/test")
        bare = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        git(root, "remote", "add", "origin", str(bare))
        head = git(root, "rev-parse", "HEAD")
        bct = self.make_bct(root)
        arguments = {
            "path": str(root), "repository": "owner/project", "branch": "feature/test",
            "remote": "origin", "expected_head": head, "expected_remote_sha": None,
        }
        with patch("bct.features.github._remote_matches", return_value=True):
            pushed = self.call(bct, root, "push-1", "github_push", arguments)
            duplicate = self.call(bct, root, "push-1", "github_push", arguments)
            already = self.call(bct, root, "push-2", "github_push", arguments)
            (root / "README.md").write_text("second\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "commit", "-m", "second")
            second_head = git(root, "rev-parse", "HEAD")
            stale = self.call(bct, root, "push-3", "github_push", {
                **arguments, "expected_head": second_head, "expected_remote_sha": "a" * 40,
            })
        self.assertEqual(Outcome.APPLIED, pushed.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertTrue(already.evidence["already_current"])
        self.assertEqual(Outcome.NOT_APPLIED, stale.outcome)
        self.assertEqual(head, git(root, "ls-remote", "--refs", "origin", "refs/heads/feature/test").split()[0])

    def test_pull_request_create_status_merge_and_cross_operation_dedupe(self):
        root = self.make_repo()
        head = git(root, "rev-parse", "HEAD")
        fake = FakeGitHub(branch_sha=head)
        bct = self.make_bct(root, fake)
        create_arguments = {
            "repository": "owner/project", "head": "feature/github", "base": "main",
            "head_sha": head, "title": "Add GitHub integration", "body": "Verified change.",
        }
        created = self.call(bct, root, "pr-1", "github_pr_create", create_arguments)
        repeated = self.call(bct, root, "pr-2", "github_pr_create", create_arguments)
        status = self.call(bct, root, "status-1", "github_pr_status", {
            "repository": "owner/project", "number": 1, "expected_head": head,
            "required_checks": ["test"],
        })
        merge_arguments = {
            "repository": "owner/project", "number": 1, "expected_head": head,
            "required_checks": ["test"], "method": "squash",
        }
        merged = self.call(bct, root, "merge-1", "github_pr_merge", merge_arguments)
        merged_again = self.call(bct, root, "merge-2", "github_pr_merge", merge_arguments)
        self.assertEqual(Outcome.APPLIED, created.outcome)
        self.assertTrue(repeated.evidence["already_present"])
        self.assertEqual(1, fake.create_calls)
        self.assertTrue(status.evidence["checks_ready"])
        self.assertEqual(Outcome.APPLIED, merged.outcome)
        self.assertTrue(merged_again.evidence["already_merged"])
        self.assertEqual(1, fake.merge_calls)

    def test_response_loss_is_reconciled_without_duplicate_pr_or_merge(self):
        root = self.make_repo()
        head = git(root, "rev-parse", "HEAD")
        fake = FakeGitHub(branch_sha=head)
        fake.fail_create_after_apply = True
        bct = self.make_bct(root, fake)
        created = self.call(bct, root, "lost-pr", "github_pr_create", {
            "repository": "owner/project", "head": "feature/lost", "base": "main",
            "head_sha": head, "title": "Lost response", "body": "Recover by marker.",
        })
        fake.fail_merge_after_apply = True
        merged = self.call(bct, root, "lost-merge", "github_pr_merge", {
            "repository": "owner/project", "number": 1, "expected_head": head,
            "required_checks": ["test"], "method": "squash",
        })
        self.assertEqual(Outcome.APPLIED, created.outcome)
        self.assertEqual(Outcome.APPLIED, merged.outcome)
        self.assertEqual(1, fake.create_calls)
        self.assertEqual(1, fake.merge_calls)

    def test_merge_fails_closed_when_required_check_is_missing(self):
        root = self.make_repo()
        head = git(root, "rev-parse", "HEAD")
        fake = FakeGitHub(branch_sha=head)
        bct = self.make_bct(root, fake)
        self.call(bct, root, "pr-missing", "github_pr_create", {
            "repository": "owner/project", "head": "feature/missing", "base": "main",
            "head_sha": head, "title": "Missing check", "body": "Must not merge.",
        })
        result = self.call(bct, root, "merge-missing", "github_pr_merge", {
            "repository": "owner/project", "number": 1, "expected_head": head,
            "required_checks": ["security"], "method": "squash",
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual(0, fake.merge_calls)

    def test_verified_main_sync_is_fast_forward_only_and_rejects_dirty_tree(self):
        seed = self.make_repo("seed")
        bare = self.base / "main-remote.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        git(seed, "remote", "add", "origin", str(bare))
        git(seed, "push", "-u", "origin", "main")
        local = self.base / "local"
        subprocess.run(["git", "clone", "-b", "main", str(bare), str(local)], check=True, capture_output=True)
        before = git(local, "rev-parse", "HEAD")
        (seed / "README.md").write_text("updated\n", encoding="utf-8")
        git(seed, "add", "README.md")
        git(seed, "commit", "-m", "update")
        after = git(seed, "rev-parse", "HEAD")
        git(seed, "push", "origin", "main")
        bct = self.make_bct(local)
        arguments = {
            "path": str(local), "repository": "owner/project", "remote": "origin",
            "expected_local_head": before, "verified_main_sha": after,
        }
        with patch("bct.features.github._remote_matches", return_value=True):
            synced = self.call(bct, local, "sync-1", "github_sync_main", arguments)
        self.assertEqual(Outcome.APPLIED, synced.outcome)
        self.assertEqual(after, git(local, "rev-parse", "HEAD"))

        dirty_root = self.make_repo("dirty")
        dirty_bare = self.base / "dirty-remote.git"
        subprocess.run(["git", "init", "--bare", str(dirty_bare)], check=True, capture_output=True)
        git(dirty_root, "remote", "add", "origin", str(dirty_bare))
        dirty_head = git(dirty_root, "rev-parse", "HEAD")
        git(dirty_root, "push", "origin", "main")
        (dirty_root / "README.md").write_text("dirty\n", encoding="utf-8")
        dirty_bct = self.make_bct(dirty_root)
        with patch("bct.features.github._remote_matches", return_value=True):
            denied = self.call(dirty_bct, dirty_root, "sync-dirty", "github_sync_main", {
                "path": str(dirty_root), "repository": "owner/project", "remote": "origin",
                "expected_local_head": dirty_head, "verified_main_sha": dirty_head,
            })
        self.assertEqual(Outcome.NOT_APPLIED, denied.outcome)


if __name__ == "__main__":
    unittest.main()
