from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import Outcome, PreconditionError, Principal


def run_git(root: Path, *args: str) -> str:
    process = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", shell=False, check=True)
    return process.stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DevelopmentFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "project"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.name", "BCT Test")
        run_git(self.repo, "config", "user.email", "bct-test@example.invalid")
        (self.repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.repo / "test_calculator.py").write_text(
            "import unittest\nfrom calculator import add\n\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(5, add(2, 3))\n",
            encoding="utf-8",
        )
        run_git(self.repo, "add", "calculator.py", "test_calculator.py")
        run_git(self.repo, "commit", "-m", "initial")
        self.initial_head = run_git(self.repo, "rev-parse", "HEAD")
        policy = self.base / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["read","write","test","git_commit"]\n'
            'approval_actions=["deploy"]\n', encoding="utf-8"
        )
        self.bct = BCT(state_path=self.base / "state.sqlite", policy_path=policy)
        self.principal = Principal("developer", "test", frozenset({"read", "write", "test", "git_commit"}))
        self.bct.create_work(work_id="dev", request_summary="change calculator",
                             roots=[str(self.repo)], actions=["read", "write", "test", "git_commit"],
                             principal=self.principal)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation_id, capability, arguments):
        return self.bct.operations.run(principal=self.principal, work_id="dev",
                                       operation_id=operation_id, capability=capability,
                                       arguments=arguments)

    def test_complete_read_reedit_test_new_file_commit_flow(self):
        source = self.repo / "calculator.py"
        read = self.call("read-1", "read", {"path": str(source)})
        self.assertEqual(Outcome.APPLIED, read.outcome)
        self.assertIn("def add", read.output["text"])
        self.assertNotIn("text", read.evidence)
        self.assertNotIn(b"def add", (self.base / "state.sqlite").read_bytes())
        first = self.call("write-1", "write", {
            "path": str(source), "expected_sha256": read.evidence["sha256"],
            "content": "def add(a, b):\n    return int(a) + int(b)\n",
        })
        second = self.call("write-2", "write", {
            "path": str(source), "expected_sha256": first.evidence["sha256"],
            "content": "def add(a, b):\n    \"\"\"Return the integer sum.\"\"\"\n    return int(a) + int(b)\n",
        })
        new_file = self.repo / "CHANGELOG.md"
        created = self.call("write-3", "write", {
            "path": str(new_file), "expected_absent": True,
            "content": "# Changes\n\n- BCT acceptance.\n",
        })
        compiled = self.call("test-1", "test", {
            "cwd": str(self.repo), "kind": "py_compile", "targets": ["calculator.py"],
        })
        tested = self.call("test-2", "test", {
            "cwd": str(self.repo), "kind": "unittest", "targets": ["test_calculator"],
        })
        self.assertEqual("PASS", compiled.evidence["status"])
        self.assertEqual("PASS", tested.evidence["status"])
        committed = self.call("commit-1", "git_commit", {
            "path": str(self.repo), "paths": ["calculator.py", "CHANGELOG.md"],
            "message": "acceptance: complete BCT development flow", "expected_head": self.initial_head,
            "new_files": [{"path": "CHANGELOG.md", "sha256": created.evidence["sha256"]}],
        })
        self.assertEqual(Outcome.APPLIED, committed.outcome, committed.as_dict())
        self.assertNotEqual(self.initial_head, committed.evidence["head_after"])
        self.assertEqual({"calculator.py", "CHANGELOG.md"}, set(committed.evidence["files"]))
        self.assertEqual("", run_git(self.repo, "status", "--porcelain"))
        duplicate = self.call("commit-1", "git_commit", {
            "path": str(self.repo), "paths": ["calculator.py", "CHANGELOG.md"],
            "message": "acceptance: complete BCT development flow", "expected_head": self.initial_head,
            "new_files": [{"path": "CHANGELOG.md", "sha256": created.evidence["sha256"]}],
        })
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(committed.evidence["head_after"], run_git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(first.evidence["path"], second.evidence["path"])

    def test_foreign_dirty_is_not_committed(self):
        source = self.repo / "calculator.py"
        source.write_text("def add(a, b):\n    return 10\n", encoding="utf-8")
        foreign = self.repo / "test_calculator.py"
        foreign.write_text(foreign.read_text(encoding="utf-8") + "\n# foreign\n", encoding="utf-8")
        result = self.call("commit-foreign", "git_commit", {
            "path": str(self.repo), "paths": ["calculator.py"], "message": "should not commit",
            "expected_head": self.initial_head, "new_files": [],
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual(self.initial_head, run_git(self.repo, "rev-parse", "HEAD"))

    def test_stale_head_is_not_committed(self):
        source = self.repo / "calculator.py"
        source.write_text("def add(a, b):\n    return 10\n", encoding="utf-8")
        result = self.call("commit-stale", "git_commit", {
            "path": str(self.repo), "paths": ["calculator.py"], "message": "should not commit",
            "expected_head": "0" * 40, "new_files": [],
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual(self.initial_head, run_git(self.repo, "rev-parse", "HEAD"))

    def test_stale_file_hash_is_not_written(self):
        source = self.repo / "calculator.py"
        before = source.read_text(encoding="utf-8")
        result = self.call("write-stale", "write", {
            "path": str(source), "expected_sha256": "0" * 64,
            "content": "changed\n",
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual(before, source.read_text(encoding="utf-8"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_escape_is_denied_when_platform_allows_creation(self):
        outside = self.base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.repo / "link.txt"
        try:
            os.symlink(outside, link)
        except OSError:
            self.skipTest("symlink creation is not permitted")
        with self.assertRaises(PreconditionError):
            self.call("read-link", "read", {"path": str(link)})


if __name__ == "__main__":
    unittest.main()
