"""Isolated bootstrap coverage: no live main, no real remote, no Core restart."""
from __future__ import annotations

import importlib.util
from contextlib import closing
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Outcome, Principal, Work
from bct.core.operations import OperationCoordinator
from bct.core.policy import Policy
from bct.core.store import Store
from bct.features.execution import ExecuteFeature
from bct.features.git import GitCommitFeature

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bct_local_main_ff_bootstrap.py"
_spec = importlib.util.spec_from_file_location("n63_local_ff_bootstrap", SCRIPT)
_bootstrap = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_bootstrap)


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=25)
    if out.returncode:
        raise AssertionError(f"git {args}: {out.stderr[-200:]}")
    return out.stdout.strip()


class N63BootstrapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="n63-bootstrap-fixture-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "Bootstrap fixture")
        git(self.source, "config", "user.email", "fixture@example.invalid")
        self.policy_path = self.base / "policy.toml"
        self.policy_path.write_text(
            '[policy]\nnormal_actions=["execute","git_commit"]\n'
            'approval_actions=[]\n[git_authority]\nmode="local"\n'
            'repository="p4147691/BCT"\n'
            f"source_root={json.dumps(str(self.source))}\n", encoding="utf-8",
        )
        (self.source / "base.txt").write_text("base\n", encoding="utf-8")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "baseline")
        self.before = git(self.source, "rev-parse", "HEAD")
        remote = self.base / "origin.git"
        remote.mkdir()
        git(remote, "init", "--bare", "-b", "main")
        git(self.source, "remote", "add", "origin", str(remote))
        git(self.source, "push", "-u", "origin", "main")
        other = self.base / "remote-author"
        proc = subprocess.run(
            ["git", "clone", "-b", "main", str(remote), str(other)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        git(other, "config", "user.name", "remote")
        git(other, "config", "user.email", "remote@example.invalid")
        (other / "remote.txt").write_text("new remote\n", encoding="utf-8")
        git(other, "add", "remote.txt")
        git(other, "commit", "-m", "remote only")
        git(other, "push", "origin", "main")
        self.after = git(remote, "rev-parse", "refs/heads/main")

        self.state_db = self.base / "test-state.sqlite"
        self.store = Store(self.state_db)
        self.principal = Principal("n63-fixture", "isolated",
                                   frozenset({"execute", "git_commit"}))
        self.work_id = "n63-outer-work"
        self.store.create_work(Work(
            self.work_id, "isolated", (str(self.source), str(ROOT)),
            frozenset({"execute", "git_commit"}), self.principal.principal_id,
        ))
        coordinator = OperationCoordinator(store=self.store, policy=Policy(self.policy_path))
        coordinator.register(ExecuteFeature())
        coordinator.register(GitCommitFeature(self.policy_path))
        self.outer_id = "n63-outer-1"
        self.inner_id = "n63-git-1"
        created, row = coordinator.begin(
            principal=self.principal, work_id=self.work_id, operation_id=self.outer_id,
            capability="execute", arguments={
                "kind": "python", "cwd": str(ROOT), "script": str(SCRIPT),
                "args": ["--canonical-root", str(self.source)],
            },
        )
        self.assertTrue(created)
        self.assertEqual("RUNNING", row.state.value)

    def call(self, **overrides):
        args = dict(
            candidate_root=ROOT, canonical_root=self.source,
            policy_path=self.policy_path, state_db=self.state_db,
            work_id=self.work_id, outer_operation_id=self.outer_id,
            git_operation_id=self.inner_id, expected_head=self.before,
            expected_remote_head=self.after,
        )
        args.update(overrides)
        return _bootstrap.run_bootstrap(**args)

    def test_exact_work_operation_and_git_claim_ff(self):
        with patch("bct.features.git._remote_matches", return_value=True):
            result = self.call()
        self.assertEqual("APPLIED", result["operation"]["outcome"])
        self.assertEqual(self.after, git(self.source, "rev-parse", "HEAD"))
        receipt = self.store.get_operation_for(
            operation_id=self.inner_id, work_id=self.work_id,
            principal_id=self.principal.principal_id,
        )
        self.assertEqual(Outcome.APPLIED, receipt.outcome)
        with closing(self.store._connect()) as db:
            row = db.execute("SELECT capability FROM operations WHERE operation_id=?",
                             (self.inner_id,)).fetchone()
            self.assertEqual("git_commit", row["capability"])
        with patch("bct.features.git._remote_matches", return_value=True):
            same = self.call()
        self.assertTrue(same["operation"]["duplicate"])
        self.assertEqual(self.after, git(self.source, "rev-parse", "HEAD"))

    def test_missing_outer_receipt_refuses_before_effect(self):
        with self.assertRaisesRegex(ValueError, "OUTER_OPERATION_FENCE"):
            self.call(outer_operation_id="nonexistent")
        self.assertEqual(self.before, git(self.source, "rev-parse", "HEAD"))

    def test_wrong_exact_remote_head_rejected_with_receipt(self):
        with patch("bct.features.git._remote_matches", return_value=True):
            result = self.call(expected_remote_head=self.before)
        self.assertEqual("NOT_APPLIED", result["operation"]["outcome"])
        self.assertIn("LOCAL_MAIN_FF_REMOTE_SHA_CHANGED",
                      result["operation"]["error"])
        self.assertEqual(self.before, git(self.source, "rev-parse", "HEAD"))

    def test_work_owner_epoch_and_scope_guard(self):
        with patch.object(self.store, "get_work", wraps=self.store.get_work):
            with self.assertRaisesRegex(ValueError, "OUTER_OPERATION_FENCE"):
                self.call(outer_operation_id="other-outer")
        self.assertEqual(self.before, git(self.source, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
