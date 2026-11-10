"""Read-only any-node recovery context tests.

These tests never create tabs, send messages or modify the original Work.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from bct.chain_recovery_context import read_chain_recovery_context

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
S = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OTHER = "dddddddd-dddd-dddd-dddd-dddddddddddd"
UNBOUND = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


class FakeStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _readonly(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA query_only=ON")
            yield con
        finally:
            con.close()


class RecoveryContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "test.db"
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE works (
                work_id TEXT PRIMARY KEY, owner_principal_id TEXT NOT NULL,
                request_summary TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE delayed_send_watches (
                task_id TEXT, generation INTEGER, conversation_key TEXT,
                state TEXT, context_json TEXT);
            CREATE TABLE chain_manager_return_checkpoints (
                task_id TEXT, generation INTEGER, work_id TEXT,
                direction_id TEXT, worker_conversation_key TEXT,
                manager_conversation_key TEXT, active_manager_conversation_key TEXT,
                supervisor_conversation_key TEXT, delivery_state TEXT,
                acknowledged_at REAL, response_sha256 TEXT);
            CREATE TABLE chain_directions (
                direction_id TEXT, work_id TEXT, decision TEXT, chain_state TEXT,
                recipe_state TEXT, source_task_id TEXT, source_generation INTEGER,
                target_conversation_key TEXT, created_at REAL,
                assessment_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE conversation_network_memberships (
                project_id TEXT,conversation_key TEXT,activity TEXT);
            CREATE TABLE operations (
                operation_id TEXT, work_id TEXT, capability TEXT,
                state TEXT, outcome TEXT);
            INSERT INTO works VALUES('root-work','principal','Original work','ACTIVE');
            INSERT INTO works VALUES('private-work','another','Other principal','ACTIVE');
        """)
        ctx = json.dumps({
            "work_id": "root-work", "chain_direction_id": "dir-1",
            "manager_conversation_key": A, "supervisor_conversation_key": S,
        })
        con.execute("INSERT INTO delayed_send_watches VALUES(?,?,?,?,?)",
                    ("task-1", 2, B, "WATCHING", ctx))
        con.execute("INSERT INTO chain_manager_return_checkpoints VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    ("task-old", 1, "root-work", "dir-1", B, A, A, S,
                     "PENDING", 0, "f" * 64))
        con.execute("INSERT INTO chain_directions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("dir-1", "root-work", "NEW_TASK", "STARTED",
                     "ACTIVE", "", 0, B, 1.0, json.dumps({
                         "manager_conversation_key": A,
                         "targets": [{"conversation_key": B, "role": "worker"}],
                         "supervisor_conversation_key": S,
                     })))
        for member in (A, B, OTHER):
            con.execute(
                "INSERT INTO conversation_network_memberships VALUES(?,?,?)",
                ("network-original", member, "ACTIVE"),
            )
        con.execute("INSERT INTO operations VALUES(?,?,?,?,?)",
                    ("op-unknown", "root-work", "browser", "FINISHED", "UNKNOWN"))
        con.commit()
        con.close()
        self.store = FakeStore(path)

    def test_a_b_and_s_all_find_one_original_work(self):
        for node in (A, B, S):
            with self.subTest(node=node):
                r = read_chain_recovery_context(
                    self.store, principal_id="principal", caller_conversation_key=node,
                )
                self.assertEqual("READY", r["status"])
                self.assertEqual("root-work", r["work"]["work_id"])
                self.assertTrue(r["read_only"])
                self.assertEqual(1, len(r["watches"]["items"]))
                self.assertEqual(1, len(r["manager_returns"]["items"]))
                self.assertEqual("UNKNOWN", r["uncertain_operations"]["items"][0]["outcome"])
                self.assertIn("grant_manager_role", r["does_not"])
                self.assertIn("replay_unknown", r["does_not"])

    def test_network_sibling_without_direct_watch_finds_original_work(self):
        # OTHER is an ordinary member of the original conversation network.
        # It has no own Watch or return, but may still coordinate recovery.
        result = read_chain_recovery_context(
            self.store, principal_id="principal",
            caller_conversation_key=OTHER,
        )
        self.assertEqual("READY", result["status"])
        self.assertEqual("root-work", result["work"]["work_id"])

    def test_saved_direction_without_watch_is_a_recovery_link(self):
        db = sqlite3.connect(self.store.path)
        db.execute("DELETE FROM delayed_send_watches")
        db.execute("DELETE FROM chain_manager_return_checkpoints")
        db.execute("UPDATE chain_directions SET target_conversation_key=''")
        db.commit()
        db.close()
        result = read_chain_recovery_context(
            self.store, principal_id="principal",
            caller_conversation_key=A,
        )
        self.assertEqual("READY", result["status"])
        self.assertEqual("root-work", result["work"]["work_id"])

    def test_two_work_candidates_do_not_pick_a_random_manager(self):
        db = sqlite3.connect(self.store.path)
        db.execute("INSERT INTO works VALUES('another-work','principal','Another','ACTIVE')")
        ctx = json.dumps({"work_id":"another-work", "manager_conversation_key":A})
        db.execute("INSERT INTO delayed_send_watches VALUES(?,?,?,?,?)",
                   ("other-task",1,B,"WATCHING",ctx))
        db.commit()
        db.close()
        result = read_chain_recovery_context(
            self.store, principal_id="principal", caller_conversation_key=A,
        )
        self.assertEqual("SELECT_ORIGINAL_CONTEXT", result["status"])
        self.assertEqual(2,len(result["work_candidates"]))
        self.assertTrue(result["read_only"])

    def test_foreign_owner_is_not_exposed(self):
        r = read_chain_recovery_context(self.store, principal_id="another",
                                        caller_conversation_key=A)
        self.assertEqual("NO_BOUND_CONTEXT", r["status"])
        r = read_chain_recovery_context(self.store, principal_id="another",
                                        work_id="root-work")
        self.assertEqual("NOT_FOUND", r["status"])

    def test_without_any_link_returns_recoverable_context_hint(self):
        r = read_chain_recovery_context(self.store, principal_id="principal",
                                        caller_conversation_key=UNBOUND)
        self.assertEqual("NO_BOUND_CONTEXT", r["status"])
        self.assertTrue(r["read_only"])

    def test_truncation_never_claimed_complete(self):
        r = read_chain_recovery_context(self.store, principal_id="principal",
                                        work_id="root-work", limit=1)
        self.assertEqual("READY", r["status"])
        con = sqlite3.connect(self.store.path)
        ctx = json.dumps({"work_id": "root-work", "manager_conversation_key": A})
        con.execute("INSERT INTO delayed_send_watches VALUES(?,?,?,?,?)",
                    ("task-2", 1, B, "WATCHING", ctx))
        con.commit()
        con.close()
        r = read_chain_recovery_context(self.store, principal_id="principal",
                                        work_id="root-work", limit=1)
        self.assertEqual("PARTIAL_EVIDENCE", r["status"])
        self.assertFalse(r["all_rows_examined"])
        self.assertEqual(1, r["next_cursors"]["watches"])
        next_page = read_chain_recovery_context(
            self.store, principal_id="principal", work_id="root-work",
            limit=1, cursors=r["next_cursors"],
        )
        self.assertEqual("PARTIAL_EVIDENCE", next_page["status"])
        self.assertTrue(next_page["page_complete"])
        self.assertEqual("task-2", next_page["watches"]["items"][0]["task_id"])
        self.assertEqual({}, next_page["next_cursors"])

    def test_reading_does_not_create_schema(self):
        db = sqlite3.connect(self.store.path)
        before = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        db.close()
        read_chain_recovery_context(self.store, principal_id="principal", work_id="root-work")
        db = sqlite3.connect(self.store.path)
        after = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        db.close()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
