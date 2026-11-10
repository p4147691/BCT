"""Fair automatic Manager monitoring without missing other Work sessions."""
from __future__ import annotations

import unittest
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
