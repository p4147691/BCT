from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct import BCT
from bct.core.models import ConflictError, Outcome, PreconditionError, Principal
from bct.features.git_authority import (
    SYNC_CONFLICT,
    SYNC_IN_SYNC,
    SYNC_PENDING,
    classify_publish_sync,
    read_git_authority,
)


def git(path: Path, *args: str, ok: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if ok and result.returncode:
        raise AssertionError(f"git {args!r}: {result.stderr[-500:]}")
    return result.stdout.strip()


def head(path: Path) -> str:
    return git(path, "rev-parse", "HEAD")


class LocalGitAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bct-local-authority-unit-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.runtime = self.base / "fake-runtime"
        self.source.mkdir()
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "Isolated Integration Owner")
        git(self.source, "config", "user.email", "isolated@invalid.example")
        self.policy = self.source / "bct.toml"
        self.write_policy(local=True)
        (self.source / "app.py").write_text(
            'VALUE = "LOCAL_E2E_OK"\nif __name__ == "__main__":\n    print(VALUE)\n',
            encoding="utf-8",
        )
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "baseline local authority")
        self.initial = head(self.source)
        self.remote = self.base / "github-standin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remote)],
                       capture_output=True, check=True)
        git(self.source, "remote", "add", "origin", str(self.remote))
        git(self.source, "push", "-u", "origin", "main")
        self.principal = Principal(
            "local-owner", "isolated",
            frozenset({"git_commit", "github_push", "github_pr_merge",
                       "github_sync_main", "deploy"}),
        )
        self.bct = BCT(state_path=self.base / "state.sqlite", policy_path=self.policy)
        self.bct.create_work(
            work_id="local-work", request_summary="local authority regression",
            roots=[str(self.source)], actions=list(self.principal.capabilities),
            principal=self.principal,
        )

    def write_policy(self, local: bool):
        section = (
            "[git_authority]\nmode=\"local\"\n"
            f"repository=\"p4147691/BCT\"\nsource_root={json.dumps(str(self.source))}\n\n"
            if local else ""
        )
        self.policy.write_text(
            '[policy]\nnormal_actions=["git_commit","github_push","github_pr_merge",'
            '"github_sync_main","deploy"]\napproval_actions=[]\n\n'
            + section
            + "[deployment.profiles.fake_runtime]\n"
            + f"source_root={json.dumps(str(self.source))}\n"
            + f"runtime_root={json.dumps(str(self.runtime))}\n"
            + 'service_name="isolated-bct-test"\nport=29173\n'
            + 'files=["bct.toml","app.py"]\n',
            encoding="utf-8",
        )

    def call(self, operation_id, capability, arguments):
        return self.bct.operations.run(
            principal=self.principal, work_id="local-work",
            operation_id=operation_id, capability=capability, arguments=arguments,
        )

    def feature(self, name: str, *, filename: str | None = None, content: str | None = None):
        directory = self.base / name
        git(self.source, "worktree", "add", "-b", "feature/" + name, str(directory), "main")
        file = filename or name + ".txt"
        (directory / file).write_text(content or ("feature from " + name + "\n"), encoding="utf-8")
        git(directory, "add", file)
        git(directory, "commit", "-m", "feat " + name)
        return "feature/" + name, head(directory)

    def merge(self, key: str, branch: str, feature_sha: str, *, expected_head: str | None = None):
        return self.call(key, "git_commit", {
            "operation": "merge_local_main", "path": str(self.source), "branch": branch,
            "expected_head": expected_head or head(self.source),
            "expected_feature_head": feature_sha,
            "message": "Merge " + branch + " via local integration owner",
        })

    def publish(self, key: str, expected_remote_sha: str):
        with patch("bct.features.github._remote_matches", return_value=True):
            return self.call(key, "github_push", {
                "path": str(self.source), "repository": "p4147691/BCT",
                "branch": "main", "remote": "origin",
                "expected_head": head(self.source),
                "expected_remote_sha": expected_remote_sha,
            })

    def test_two_agents_merge_and_duplicate_is_idempotent(self):
        branch_a, sha_a = self.feature("agent-a")
        branch_b, sha_b = self.feature("agent-b")
        a = self.merge("merge-a", branch_a, sha_a)
        self.assertEqual(Outcome.APPLIED, a.outcome, a.as_dict())
        self.assertEqual(self.initial, a.evidence["head_before"])
        self.assertEqual(sha_a, a.evidence["feature_head"])
        b = self.merge("merge-b", branch_b, sha_b)
        self.assertEqual(Outcome.APPLIED, b.outcome, b.as_dict())
        self.assertTrue((self.source / "agent-a.txt").exists())
        self.assertTrue((self.source / "agent-b.txt").exists())
        count = git(self.source, "rev-list", "--count", "HEAD")
        again = self.merge("merge-b", branch_b, sha_b, expected_head=a.evidence["head_after"])
        self.assertTrue(again.duplicate)
        self.assertEqual(count, git(self.source, "rev-list", "--count", "HEAD"))
        self.assertEqual(b.evidence, again.evidence)
        self.assertFalse(self.bct.store.monitor_snapshot()["unresolved_claims"])

    def test_merge_owner_resource_claim_blocks_second_merge(self):
        branch, sha = self.feature("claim")
        args = {"operation": "merge_local_main", "path": str(self.source),
                "branch": branch, "expected_head": self.initial,
                "expected_feature_head": sha, "message": "claim check"}
        made, _ = self.bct.operations.begin(
            principal=self.principal, work_id="local-work",
            operation_id="merge-reserved", capability="git_commit", arguments=args,
        )
        self.assertTrue(made)
        with self.assertRaises(ConflictError):
            self.call("merge-contender", "git_commit", args)
        self.assertEqual(self.initial, head(self.source))

    def test_legacy_remote_authority_routes_fail_closed(self):
        with self.assertRaises(PreconditionError):
            self.call("legacy-merge-denied", "github_pr_merge", {
                "repository": "p4147691/BCT", "number": 1,
                "expected_head": "a"*40, "required_checks": ["core (0)"],
            })
        with self.assertRaises(PreconditionError):
            self.call("legacy-sync-denied", "github_sync_main", {
                "path": str(self.source), "repository": "p4147691/BCT",
                "expected_local_head": self.initial,
                "verified_main_sha": self.initial,
            })

    def test_exact_local_sha_fake_deployment_and_e2e_before_remote(self):
        branch, sha = self.feature("deploy")
        merged = self.merge("merge-for-deploy", branch, sha)
        self.assertEqual(Outcome.APPLIED, merged.outcome)
        local_sha = merged.evidence["head_after"]
        self.assertEqual(self.initial, git(self.remote, "rev-parse", "refs/heads/main"))
        release = self.call("deploy-to-fake-runtime", "deploy", {
            "profile": "fake_runtime", "expected_source_head": local_sha,
            "expected_current_source_head": None, "restart": False,
        })
        self.assertEqual(Outcome.APPLIED, release.outcome, release.as_dict())
        manifest = json.loads(
            (self.runtime / "releases" / local_sha / "manifest.json").read_text(encoding="utf-8"),
        )
        current = json.loads((self.runtime / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(local_sha, current["source_head"])
        self.assertEqual(local_sha, manifest["source_head"])
        self.assertEqual(
            hashlib.sha256((self.runtime/"releases"/local_sha/"app.py").read_bytes()).hexdigest(),
            manifest["files"]["app.py"],
        )
        execution = subprocess.run(
            [sys.executable, "-B", str(self.runtime/"releases"/local_sha/"app.py")],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual("LOCAL_E2E_OK", execution.stdout.strip())
        self.assertEqual(0, execution.returncode)
        duplicate = self.call("deploy-to-fake-runtime", "deploy", {
            "profile": "fake_runtime", "expected_source_head": local_sha,
            "expected_current_source_head": None, "restart": False,
        })
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(self.initial, git(self.remote, "rev-parse", "refs/heads/main"))

    def test_publish_offline_confirmed_not_applied_then_nonforce(self):
        branch, sha = self.feature("offline")
        merged = self.merge("merge-offline", branch, sha)
        self.assertEqual(Outcome.APPLIED, merged.outcome)
        git(self.source, "remote", "set-url", "origin", str(self.base/"unavailable.git"))
        offline = self.publish("offline-before-dispatch", self.initial)
        self.assertEqual(Outcome.NOT_APPLIED, offline.outcome, offline.as_dict())
        self.assertIn(SYNC_PENDING, offline.error or "")
        self.assertFalse(self.bct.store.monitor_snapshot()["unresolved_claims"])
        self.assertEqual(self.initial, git(self.remote, "rev-parse", "refs/heads/main"))
        git(self.source, "remote", "set-url", "origin", str(self.remote))
        pushed = self.publish("sync-post-local-e2e", self.initial)
        self.assertEqual(Outcome.APPLIED, pushed.outcome, pushed.as_dict())
        self.assertEqual(SYNC_IN_SYNC, pushed.evidence["sync_state"])
        self.assertEqual(head(self.source), git(self.remote, "rev-parse", "refs/heads/main"))
        # A failed stand-in CI audit does not revert an already accepted fake LIVE.
        current_before = head(self.source)
        failed_ci = subprocess.run([sys.executable, "-B", "-c", "raise SystemExit(3)"],
                                   capture_output=True, timeout=10)
        self.assertEqual(3, failed_ci.returncode)
        self.assertEqual(current_before, head(self.source))

    def test_remote_divergence_rejected_without_force(self):
        branch, sha = self.feature("diverge")
        self.assertEqual(Outcome.APPLIED, self.merge("merge-diverge", branch, sha).outcome)
        other = self.base / "other-writer"
        subprocess.run(["git", "clone", "-b", "main", str(self.remote), str(other)],
                       capture_output=True, check=True)
        git(other, "config", "user.name", "remote-divergent-writer")
        git(other, "config", "user.email", "remote@invalid.example")
        (other/"remote.txt").write_text("unrelated remote main\n",encoding="utf-8")
        git(other, "add", "remote.txt")
        git(other, "commit", "-m", "simulated remote update")
        git(other, "push", "origin", "main")
        remote_current=git(self.remote,"rev-parse","refs/heads/main")
        local_current=head(self.source)
        rejected=self.publish("reject-divergent-push", self.initial)
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome, rejected.as_dict())
        self.assertIn(SYNC_CONFLICT, rejected.error or "")
        self.assertEqual(remote_current,git(self.remote,"rev-parse","refs/heads/main"))
        self.assertEqual(local_current,head(self.source))
        self.assertFalse(self.bct.store.monitor_snapshot()["unresolved_claims"])

    def test_merge_conflict_is_preflight_not_dirty(self):
        branch, feature_sha = self.feature("conflict", filename="app.py",
                                           content='VALUE = "FEATURE"\n')
        (self.source/"app.py").write_text('VALUE = "LOCAL_MAIN"\n', encoding="utf-8")
        git(self.source,"add","app.py")
        git(self.source,"commit","-m","local main conflicting change")
        current=head(self.source)
        result=self.merge("conflict-reject", branch, feature_sha)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome, result.as_dict())
        self.assertEqual(current, head(self.source))
        self.assertEqual("", git(self.source,"status","--porcelain=v1"))
        self.assertFalse((self.source/".git"/"MERGE_HEAD").exists())

    def test_wrong_expected_head_and_feature_sha_rejected(self):
        branch, sha = self.feature("stale")
        stale=self.merge("stale-main", branch, sha, expected_head="a"*40)
        self.assertEqual(Outcome.NOT_APPLIED, stale.outcome, stale.as_dict())
        feature_wrong=self.merge("stale-feature", branch, "b"*40)
        self.assertEqual(Outcome.NOT_APPLIED, feature_wrong.outcome, feature_wrong.as_dict())
        self.assertEqual(self.initial, head(self.source))

    def test_github_authority_mode_blocks_local_merge(self):
        # No local authority config => old GitHub behavior remains.
        self.write_policy(local=False)
        branch, sha = self.feature("legacy")
        with self.assertRaises(PreconditionError):
            self.merge("local-not-enabled", branch, sha)
        self.assertEqual(self.initial, head(self.source))

    def test_versioned_windows_authority_path_parses_when_absent_on_ci(self):
        policy = self.base / "portable-policy.toml"
        policy.write_text(
            '[git_authority]\nmode="local"\nrepository="p4147691/BCT"\n'
            'source_root="D:\\\\BCT\\\\source"\n',
            encoding="utf-8",
        )
        authority = read_git_authority(policy)
        self.assertEqual("local", authority.mode)
        self.assertEqual("p4147691/BCT", authority.repository)

    def test_publish_sync_classification_is_explicit(self):
        local = "a" * 40
        remote = "b" * 40
        self.assertEqual(SYNC_IN_SYNC, classify_publish_sync(
            local_sha=local, remote_sha=local, expected_remote_sha=remote,
        ))
        self.assertEqual(SYNC_PENDING, classify_publish_sync(
            local_sha=local, remote_sha=remote, expected_remote_sha=remote,
        ))
        self.assertEqual(SYNC_CONFLICT, classify_publish_sync(
            local_sha=local, remote_sha="c" * 40, expected_remote_sha=remote,
        ))


if __name__ == "__main__":
    unittest.main()
