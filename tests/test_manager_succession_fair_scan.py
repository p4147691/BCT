"""Fair automatic Manager monitoring without missing other Work sessions."""
from __future__ import annotations

import unittest
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from bct.manager_succession_recovery import ManagerSuccessionRecovery


class FakeDb:
    def __init__(self, sessions):
        self.sessions = sessions
        self.closed = False

    def execute(self, statement, params):
        assert "s.session_id>?" in statement
        cursor, limit = params
        rows = [dict(session) for session in sorted(
            self.sessions, key=lambda v: v["session_id"],
        ) if session["session_id"] > cursor][:limit]
        return SimpleNamespace(fetchall=lambda: rows)

    def close(self):
        self.closed = True


class FakeStore:
    def __init__(self, count=10):
        self.sessions = [
            {"session_id": "session-%02d" % index}
            for index in range(count)
        ]

    def _connect(self):
        return FakeDb(self.sessions)


class PendingHandoffStore:
    """Small actual SQLite join fixture, not a mocked query response."""

    def __init__(self, count=10):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE works (work_id TEXT,state TEXT,assignment_epoch INTEGER);
            CREATE TABLE orchestration_sessions (
                session_id TEXT,work_id TEXT,manager_epoch INTEGER,
                manager_node_id TEXT,state TEXT,work_assignment_epoch INTEGER);
            CREATE TABLE orchestration_manager_handoffs (
                handoff_id TEXT,session_id TEXT,successor_epoch INTEGER,
                successor_node_id TEXT,attachment_id TEXT,
                attachment_generation INTEGER,instance_id TEXT,
                external_session_id TEXT,tab_id INTEGER,conversation_key TEXT,
                binding_receipt_id TEXT,state TEXT,created_at REAL);
            CREATE TABLE orchestration_attachments (
                attachment_id TEXT,node_id TEXT,active INTEGER,
                generation INTEGER,instance_id TEXT,external_session_id TEXT,
                tab_id INTEGER,conversation_key TEXT,binding_receipt_id TEXT);
            CREATE TABLE orchestration_session_nodes (
                session_id TEXT,node_id TEXT,active INTEGER,session_role TEXT);
        """)
        for index in range(count):
            key = "case-%02d" % index
            self.db.execute("INSERT INTO works VALUES(?,?,?)",
                            (key,"ACTIVE",1))
            self.db.execute(
                "INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?)",
                (key,key,2,"successor","ACTIVE",1),
            )
            self.db.execute(
                "INSERT INTO orchestration_manager_handoffs VALUES("
                "?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key,key,2,"successor",key,1,"instance","session",
                 10,"conversation","receipt","PENDING",float(index)),
            )
            self.db.execute(
                "INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?)",
                (key,"successor",1,1,"instance","session",10,
                 "conversation","receipt"),
            )
            self.db.execute(
                "INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                (key,"successor",1,"MANAGER"),
            )
        self.db.commit()

    @contextmanager
    def _readonly(self):
        yield self.db

class ManagerScanFairnessTests(unittest.TestCase):
    def test_every_manager_is_seen_in_bounded_batches_then_scan_wraps(self):
        store = FakeStore(10)
        recovery = ManagerSuccessionRecovery(
            SimpleNamespace(store=store), client=SimpleNamespace(),
        )
        batches = [
            [item["session_id"] for item in recovery._current(limit=3)]
            for _ in range(5)
        ]
        self.assertEqual(
            [["session-00", "session-01", "session-02"],
             ["session-03", "session-04", "session-05"],
             ["session-06", "session-07", "session-08"],
             ["session-09"],
             ["session-00", "session-01", "session-02"]],
            batches,
        )

    def test_stale_cursor_does_not_strand_new_manager_sessions(self):
        store = FakeStore(2)
        recovery = ManagerSuccessionRecovery(
            SimpleNamespace(store=store), client=SimpleNamespace(),
        )
        recovery._scan_cursor = "session-99"
        self.assertEqual(
            ["session-00", "session-01"],
            [item["session_id"] for item in recovery._current(limit=5)],
        )

    def test_pending_handoffs_rotate_beyond_busy_first_batch(self):
        store = PendingHandoffStore(10)
        self.addCleanup(store.db.close)
        recovery = ManagerSuccessionRecovery(
            SimpleNamespace(store=store), client=SimpleNamespace(),
        )
        batches = [
            [row["handoff_id"] for row in
             recovery._current_pending_handoffs(limit=3)]
            for _ in range(5)
        ]
        self.assertEqual([
            ["case-00","case-01","case-02"],
            ["case-03","case-04","case-05"],
            ["case-06","case-07","case-08"],
            ["case-09"],
            ["case-00","case-01","case-02"],
        ], batches)

    def test_old_epoch_handoff_is_never_a_resume_candidate(self):
        store = PendingHandoffStore(2)
        self.addCleanup(store.db.close)
        store.db.execute(
            "UPDATE orchestration_manager_handoffs SET successor_epoch=1 "
            "WHERE handoff_id='case-00'"
        )
        store.db.commit()
        recovery = ManagerSuccessionRecovery(
            SimpleNamespace(store=store), client=SimpleNamespace(),
        )
        self.assertEqual(["case-01"],[
            row["handoff_id"] for row in
            recovery._current_pending_handoffs(limit=10)
        ])

    def test_none_sensor_payload_is_unknown_not_a_failed_node(self):
        from tests.test_orchestration import FakeRelay
        recovery = ManagerSuccessionRecovery(
            SimpleNamespace(store=FakeStore()), client=FakeRelay(),
        )
        attachment = {
            "instance_id": "abc", "external_session_id": "def",
            "tab_id": 1, "conversation_key": "conversation-id",
        }
        self.assertEqual("UNKNOWN", recovery._readiness(attachment, None))


if __name__ == "__main__":
    unittest.main()
