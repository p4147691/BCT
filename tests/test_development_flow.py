from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct import BCT
from bct.core.models import ConflictError, Outcome, PreconditionError, Principal
from bct.features.files import FileReadFeature


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

    def test_read_directory_tree_is_bounded_and_does_not_follow_symlinks(self):
        nested = self.repo / "nested"
        nested.mkdir()
        (nested / "note.txt").write_text("tree entry\n", encoding="utf-8")
        result = self.call("read-tree", "read", {
            "operation": "directory_tree", "path": str(nested), "depth": 2, "limit": 20,
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertIn({"path": "note.txt", "kind": "file"}, result.output["entries"])
        self.assertFalse(result.output["truncated"])

        outside = self.base / "outside"
        outside.mkdir()
        link = self.repo / "outside-link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError:
            return
        linked = self.call("read-tree-link", "read", {
            "operation": "directory_tree", "path": str(self.repo), "depth": 2, "limit": 30,
        })
        self.assertIn({"path": "outside-link", "kind": "symlink"}, linked.output["entries"])
        self.assertFalse(any(item["path"].startswith("outside-link/") for item in linked.output["entries"]))

    def test_read_directory_tree_rejects_outside_scope_and_invalid_bounds(self):
        outside = self.base / "outside"
        outside.mkdir()
        with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
            self.call("read-tree-outside", "read", {
                "operation": "directory_tree", "path": str(outside), "depth": 1, "limit": 20,
            })
        with self.assertRaisesRegex(PreconditionError, "READ_TREE_BOUNDS_INVALID"):
            self.call("read-tree-bad-bounds", "read", {
                "operation": "directory_tree", "path": str(self.repo), "depth": "many", "limit": 20,
            })

    def test_batch_read_returns_files_and_tree_without_persisting_content(self):
        nested = self.repo / "nested"
        nested.mkdir()
        note = nested / "note.txt"
        note.write_text("batch note\n", encoding="utf-8")
        result = self.call("read-batch-1", "read", {
            "operation": "batch",
            "items": [
                {"id": "source", "path": str(self.repo / "calculator.py")},
                {"id": "note", "path": str(note)},
                {"id": "tree", "operation": "directory_tree", "path": str(nested),
                 "depth": 1, "limit": 20},
            ],
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("COMPLETE", result.output["status"])
        self.assertEqual(["source", "note", "tree"], [item["id"] for item in result.output["items"]])
        source = result.output["items"][0]
        self.assertIn("def add", source["output"]["text"])
        self.assertEqual(digest(self.repo / "calculator.py"), source["sha256"])
        self.assertIsInstance(source["observed_at"], float)
        self.assertIn({"path": "note.txt", "kind": "file"}, result.output["items"][2]["output"]["entries"])
        self.assertEqual(3, result.evidence["items_succeeded"])
        self.assertNotIn("output", result.evidence["items"][0])
        database = (self.base / "state.sqlite").read_bytes()
        self.assertNotIn(b"batch note", database)
        self.assertNotIn(b"def add", database)

        duplicate = self.call("read-batch-1", "read", {
            "operation": "batch",
            "items": [
                {"id": "source", "path": str(self.repo / "calculator.py")},
                {"id": "note", "path": str(note)},
                {"id": "tree", "operation": "directory_tree", "path": str(nested),
                 "depth": 1, "limit": 20},
            ],
        })
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(duplicate.output)
        with self.assertRaisesRegex(ConflictError, "OPERATION_ID_REQUEST_MISMATCH"):
            self.call("read-batch-1", "read", {
                "operation": "batch",
                "items": [{"id": "different", "path": str(note)}],
            })

    def test_batch_read_validates_scope_ids_targets_and_bounds_before_start(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
            self.call("read-batch-outside", "read", {
                "operation": "batch",
                "items": [
                    {"id": "inside", "path": str(self.repo / "calculator.py")},
                    {"id": "outside", "path": str(outside)},
                ],
            })
        with self.assertRaisesRegex(PreconditionError, "READ_BATCH_ITEM_ID_DUPLICATE"):
            self.call("read-batch-id", "read", {
                "operation": "batch",
                "items": [
                    {"id": "same", "path": str(self.repo / "calculator.py")},
                    {"id": "same", "path": str(self.repo / "test_calculator.py")},
                ],
            })
        with self.assertRaisesRegex(PreconditionError, "READ_BATCH_TARGET_DUPLICATE"):
            self.call("read-batch-target", "read", {
                "operation": "batch",
                "items": [
                    {"id": "one", "path": str(self.repo / "calculator.py")},
                    {"id": "two", "path": str(self.repo / "calculator.py")},
                ],
            })
        with self.assertRaisesRegex(PreconditionError, "READ_BATCH_ITEMS_INVALID"):
            self.call("read-batch-empty", "read", {"operation": "batch", "items": []})
        with self.assertRaisesRegex(PreconditionError, "READ_BATCH_ITEMS_INVALID"):
            self.call("read-batch-many", "read", {
                "operation": "batch",
                "items": [
                    {"id": f"item-{index}", "path": str(self.repo / "calculator.py")}
                    for index in range(21)
                ],
            })
        oversized = self.repo / "oversized.txt"
        oversized.write_bytes(b"x" * (FileReadFeature.batch_max_file_bytes + 1))
        with self.assertRaisesRegex(PreconditionError, "READ_BATCH_FILE_TOO_LARGE"):
            self.call("read-batch-large", "read", {
                "operation": "batch", "items": [{"id": "large", "path": str(oversized)}],
            })

    def test_batch_read_reports_runtime_item_failure_without_unknown_claim(self):
        binary = self.repo / "binary.dat"
        binary.write_bytes(b"\xff\xfe")
        result = self.call("read-batch-partial", "read", {
            "operation": "batch",
            "items": [
                {"id": "source", "path": str(self.repo / "calculator.py")},
                {"id": "binary", "path": str(binary)},
            ],
        })
        self.assertEqual(Outcome.FAILED, result.outcome)
        self.assertEqual("PARTIAL_FAILURE", result.output["status"])
        self.assertEqual("OK", result.output["items"][0]["status"])
        self.assertEqual("ERROR", result.output["items"][1]["status"])
        self.assertEqual(1, result.evidence["items_failed"])
        claim = self.bct.store.get_operation_for(
            operation_id="read-batch-partial", work_id="dev", principal_id="developer",
        )
        self.assertEqual(Outcome.FAILED, claim.outcome)
        unresolved = self.bct.store.monitor_snapshot()["unresolved_claims"]
        self.assertFalse(any(item["operation_id"] == "read-batch-partial" for item in unresolved))

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

    def test_confirmed_commit_failure_releases_claim_when_head_and_dirty_set_are_unchanged(self):
        source = self.repo / "calculator.py"
        source.write_text("def add(a, b):\n    return 10\n", encoding="utf-8")
        from bct.features import git as git_feature

        original_git = git_feature._git

        def fail_commit(root, *arguments, **kwargs):
            if arguments and arguments[0] == "commit":
                return subprocess.CompletedProcess(
                    ["git", "commit"], 128, "", "confirmed pre-commit rejection"
                )
            return original_git(root, *arguments, **kwargs)

        arguments = {
            "path": str(self.repo), "paths": ["calculator.py"],
            "message": "must fail before commit", "expected_head": self.initial_head,
            "new_files": [],
        }
        with patch("bct.features.git._git", side_effect=fail_commit):
            first = self.call("commit-confirmed-failure-1", "git_commit", arguments)
            second = self.call("commit-confirmed-failure-2", "git_commit", arguments)
        self.assertEqual(Outcome.FAILED, first.outcome)
        self.assertEqual(Outcome.FAILED, second.outcome)
        self.assertIn("GIT_COMMIT_NOT_APPLIED", first.error)
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
