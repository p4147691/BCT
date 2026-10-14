"""Isolated PR1 consumption tests; all data lives in temporary SQLite files."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.consumption import commit_consumption_decision
from bct.core.models import ConflictError
from bct.core.store import Store


class ConsumptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "isolated.db")
        with self.store.transaction() as db:
            db.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                       ("w", "test", "[]", "[]", "owner", 1, "ACTIVE"))
            db.execute("INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("s", "w", 1, "test", "[]", "[]", "{}", 1, None, 2,
                        "ACTIVE", "{}", 1.0, 1.0))
            for name in ("c1", "c2"):
                db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (name, "s", 2, "r", "{}", "[]", "[]", "{}", "PENDING",
                            1, "{}", 1.0, 1.0))
            for message_id in ("r1", "r2"):
                db.execute("INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (message_id, "s", None, None, "RESULT", None, None,
                            "hash-" + message_id, "{}", 1.0, None, None))

    def run_commit(self, *, consumer="c1", decision_id="d1", digest="request",
                   epoch=2, results=None, decision=None):
        return commit_consumption_decision(
            self.store, session_id="s", consumer_assignment_id=consumer,
            manager_epoch=epoch, decision_id=decision_id, request_digest=digest,
            decision={"action": "continue"} if decision is None else decision,
            results=[("r1", "hash-r1")] if results is None else results,
        )

    def count(self, table):
        db = self.store._connect()
        try:
            return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        finally:
            db.close()

    def test_first_commit_and_exact_idempotency(self):
        self.assertFalse(self.run_commit()["idempotent"])
        self.assertTrue(self.run_commit()["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_independent_consumers_same_result(self):
        self.run_commit()
        self.run_commit(consumer="c2", decision_id="d2")
        self.assertEqual(2, self.count("orchestration_consumption_receipts"))

    def test_digest_and_decision_conflict(self):
        self.run_commit()
        for arguments in ({"digest": "changed"}, {"decision": {"action": "stop"}},
                          {"results": [("r1", "different")]}):
            with self.subTest(arguments=arguments), self.assertRaises(ConflictError):
                self.run_commit(**arguments)
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_stale_epoch(self):
        with self.assertRaises(ConflictError):
            self.run_commit(epoch=1)
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_multiple_results_all_or_nothing(self):
        with self.assertRaises(ConflictError):
            self.run_commit(results=[("r1", "hash-r1"), ("r2", "wrong")])
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(2, self.run_commit(results=[
            ("r1", "hash-r1"), ("r2", "hash-r2")])["results"])

    def test_exception_rolls_back(self):
        # Force failure after the decision insert and before the first receipt insert.
        import bct.core.consumption as consumption
        original = consumption.time.time
        with patch.object(consumption.time, "time", side_effect=RuntimeError("fault")):
            with self.assertRaises(RuntimeError):
                self.run_commit()
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_legacy_not_promoted_or_modified(self):
        db = self.store._connect()
        try:
            before = db.execute("SELECT consumed_at FROM orchestration_mailbox WHERE message_id='r1'").fetchone()[0]
        finally:
            db.close()
        self.assertIsNone(before)
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.run_commit()
        db = self.store._connect()
        try:
            after = db.execute("SELECT consumed_at FROM orchestration_mailbox WHERE message_id='r1'").fetchone()[0]
        finally:
            db.close()
        self.assertIsNone(after)

    def test_sql_failure_after_decision_insert_rolls_back_everything(self):
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON "
                       "orchestration_consumption_receipts BEGIN "
                       "SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(Exception):
            self.run_commit()
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_new_schema_does_not_backfill_legacy(self):
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))


if __name__ == "__main__":
    unittest.main()
