"""Safety regression for read-only Worktree audit; disposable Git repos only."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.bct_worktree_hygiene import audit, _worktrees, _inside


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return done.stdout.strip()


class WorktreeHygieneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "BCT Audit Test")
        git(self.repo, "config", "user.email", "worktree-audit@example.invalid")
        (self.repo / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
        (self.repo / "file.txt").write_text("source\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore", "file.txt")
        git(self.repo, "commit", "-m", "initial")
        self.wtroot = self.base / "worktrees"
        self.wtroot.mkdir()
        self.wt = self.wtroot / "documentation-finished"
        git(self.repo, "worktree", "add", "-b", "docs/completed", str(self.wt), "HEAD")
        self.db = self.base / "state.sqlite"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE works(work_id TEXT, state TEXT, roots_json TEXT);
            CREATE TABLE operations(state TEXT, outcome TEXT, target TEXT);
        """)
        con.execute("INSERT INTO works VALUES(?,?,?)",
                    ("historical", "ACTIVE", json.dumps([str(self.repo)])))
        con.execute("INSERT INTO operations VALUES(?,?,?)", ("FINISHED", "APPLIED", str(self.repo)))
        con.commit()
        con.close()

    def report(self, process_paths=None, database=True):
        return audit(
            self.repo, self.wtroot, self.db if database else None,
            process_paths=[] if process_paths is None else process_paths,
        )

    def entry(self, report):
        # Git for Windows can print a canonical path unlike tempfile's spelling.
        # An exact unique test branch is the stable repository identity.
        matches = [x for x in report["entries"] if x.get("branch") == "docs/completed"]
        self.assertEqual(1, len(matches), f"worktree inventory: {report['entries']}")
        return matches[0]

    def test_clean_merged_unreferenced_is_review_only(self):
        r = self.report()
        e = self.entry(r)
        self.assertTrue(
            e["review_candidate"],
            f"Git path={e['path']!r}; fixture root={self.wtroot!s}; holds={e['hold_reasons']}",
        )
        self.assertEqual([], e["hold_reasons"])
        self.assertEqual(1, r["review_candidate_count"])
        self.assertEqual({"ACTIVE": 1}, r["work_authority_states"])
        self.assertTrue(r["work_authority_is_not_execution_progress"])
        self.assertTrue(r["candidates_are_not_delete_authorization"])
        self.assertTrue(self.wt.is_dir())

    def test_work_authority_active_without_running_operation_is_not_busy(self):
        r = self.report()
        self.assertEqual({"ACTIVE": 1}, r["work_authority_states"])
        self.assertEqual({"FINISHED/APPLIED": 1}, r["operation_states"])
        self.assertTrue(self.entry(r)["review_candidate"])

    def test_untracked_and_ignored_files_block_review(self):
        (self.wt / "untracked.txt").write_text("do not discard", encoding="utf-8")
        self.assertIn("STATUS_NOT_CLEAN", self.entry(self.report())["hold_reasons"])
        (self.wt / "untracked.txt").unlink()
        (self.wt / "cached.ignored").write_text("do not discard", encoding="utf-8")
        self.assertIn("IGNORED_FILES_OR_UNKNOWN", self.entry(self.report())["hold_reasons"])

    def test_exact_work_and_unknown_effect_block_review(self):
        db = sqlite3.connect(self.db)
        try:
            db.execute("INSERT INTO works VALUES(?,?,?)",
                       ("owner", "ACTIVE", json.dumps([str(self.wt)])))
            db.commit()
        finally:
            db.close()
        exact = self.entry(self.report())
        self.assertIn(
            "BCT_WORK_REFERENCE", exact["hold_reasons"],
            f"Git path={exact['path']!r}; stored Work root={self.wt!s}",
        )
        db = sqlite3.connect(self.db)
        try:
            db.execute("DELETE FROM works WHERE work_id='owner'")
            db.execute("INSERT INTO operations VALUES(?,?,?)",
                       ("FINISHED", "UNKNOWN", str(self.wt)))
            db.commit()
        finally:
            db.close()
        self.assertIn("NONTERMINAL_OR_UNKNOWN_OPERATION_REFERENCE",
                      self.entry(self.report())["hold_reasons"])

    def test_process_path_and_missing_ledger_block_review(self):
        e = self.entry(self.report([str(self.wt)]))
        self.assertIn(
            "ACTIVE_PROCESS_REFERENCE", e["hold_reasons"],
            f"Git path={e['path']!r}; input process={self.wt!s}; holds={e['hold_reasons']}",
        )
        e = self.entry(self.report(database=False))
        self.assertIn("WORK_LEDGER_UNAVAILABLE", e["hold_reasons"])

    def test_unmerged_branch_cannot_be_candidate(self):
        (self.wt / "file.txt").write_text("new commit\n", encoding="utf-8")
        git(self.wt, "add", "file.txt")
        git(self.wt, "commit", "-m", "unique")
        e = self.entry(self.report())
        self.assertFalse(e["merged_main"])
        self.assertIn("UNMERGED_OR_DETACHED", e["hold_reasons"])

    def test_locked_worktree_cannot_be_candidate(self):
        git(self.repo, "worktree", "lock", str(self.wt))
        e = self.entry(self.report())
        self.assertFalse(e["review_candidate"])
        self.assertIn("LOCKED_OR_PRUNABLE", e["hold_reasons"])

    def test_dirty_main_blocks_review(self):
        (self.repo / "new.txt").write_text("uncommitted", encoding="utf-8")
        e = self.entry(self.report())
        self.assertIn("MAIN_DIRTY", e["hold_reasons"])

    def test_same_worktree_different_normalized_spelling(self):
        alias = self.wt.parent / "nonexistent-segment" / ".." / self.wt.name
        self.assertTrue(_inside(str(self.wt), str(alias)))
        self.assertTrue(_inside(str(alias), str(self.wt.parent)))
        self.assertFalse(_inside(str(self.repo), str(self.wt)))

    def test_git_porcelain_parses_crlf_without_losing_worktrees(self):
        original = (
            "worktree C:/source\r\nHEAD 123\r\nbranch refs/heads/main\r\n\r\n"
            "worktree C:/worktrees/accepted\r\nHEAD 456\r\n"
            "branch refs/heads/docs/completed\r\n\r\n"
        )
        rows = _worktrees(original)
        self.assertEqual(["main", "docs/completed"], [x["branch"] for x in rows])

    def test_audit_does_not_change_repository(self):
        before = git(self.repo, "status", "--porcelain=v1", "-uall")
        head = git(self.repo, "rev-parse", "HEAD")
        self.report()
        self.assertEqual(before, git(self.repo, "status", "--porcelain=v1", "-uall"))
        self.assertEqual(head, git(self.repo, "rev-parse", "HEAD"))
        self.assertTrue(self.wt.exists())


if __name__ == "__main__":
    unittest.main()
