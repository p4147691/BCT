"""Atomic, unbounded Manager Watch/return recovery tests."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bct.chain_manager_recovery import ChainManagerRecoveryLedger
from bct.core.store import Store
from bct.send_delayed_message import DurableWatchLedger

OLD = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NEW = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WORKER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SUPERVISOR = "dddddddd-dddd-dddd-dddd-dddddddddddd"


class AtomicManagerRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "db.sqlite")
        DurableWatchLedger(self.store)
        self.ledger = ChainManagerRecoveryLedger(self.store)

    def seed(self, count=1):
        with self.store.transaction() as db:
            for index in range(count):
                task = "task-" + str(index)
                ctx = json.dumps({
                    "work_id": "my-work",
                    "chain_direction_id": "direction-1",
                    "manager_conversation_key": OLD,
                    "manager_instance_id": "old-instance",
                    "supervisor_conversation_key": SUPERVISOR,
                }, sort_keys=True)
                db.execute(
                    "INSERT INTO delayed_send_watches "
                    "(task_id,generation,conversation_key,response_turn_id,"
                    "source_send_receipt,state,context_json) "
                    "VALUES(?,1,?,?,?,'WATCHING',?)",
                    (task, WORKER, "turn-" + str(index), "send-receipt", ctx),
                )
                db.execute(
                    "INSERT INTO chain_manager_return_checkpoints "
                    "(task_id,generation,work_id,direction_id,worker_conversation_key,"
                    "manager_conversation_key,active_manager_conversation_key,"
                    "supervisor_conversation_key,response_turn_key,response_sha256,"
                    "return_payload,delivery_state,created_at,updated_at) "
                    "VALUES(?,1,'my-work','direction-1',?,?,?,?,?,'a','reply',"
                    "'PENDING',1.0,1.0)",
                    (task, WORKER, OLD, OLD, SUPERVISOR, "turn-" + str(index)),
                )

    def proof(self):
        return [{"predecessor_conversation_key": OLD,
                 "successor_conversation_key": NEW}]

    def test_all_121_watches_and_returns_rebind_without_truncation(self):
        self.seed(121)
        # The next SELF generation may be pre-reserved while A is replaced.
        # Its Manager binding must be included in the same durable transfer.
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='RESERVED' "
                "WHERE task_id='task-120'",
            )
        full = self.ledger.full_recovery_relations(work_id="my-work")
        self.assertEqual(121, len(full["watches"]))
        self.assertEqual(121, len(full["checkpoints"]))
        result = self.ledger.rebind_active_manager_atomic(
            work_id="my-work", manager_conversation_key=NEW,
            manager_instance_id="new-instance", succession_proofs=self.proof(),
        )
        self.assertEqual(121, result["updated_watches"])
        self.assertEqual(121, result["rebound_checkpoints"])
        self.assertEqual(121, result["examined_watches"])
        self.assertEqual(121, result["examined_checkpoints"])
        self.assertTrue(result["atomic"])
        with self.store._readonly() as db:
            self.assertEqual(121, db.execute(
                "SELECT COUNT(*) FROM delayed_send_watches "
                "WHERE json_extract(context_json,'$.manager_conversation_key')=?",
                (NEW,),
            ).fetchone()[0])
            self.assertEqual(121, db.execute(
                "SELECT COUNT(*) FROM chain_manager_return_checkpoints "
                "WHERE active_manager_conversation_key=?", (NEW,)
            ).fetchone()[0])
        again = self.ledger.rebind_active_manager_atomic(
            work_id="my-work", manager_conversation_key=NEW,
            manager_instance_id="new-instance", succession_proofs=[],
        )
        self.assertEqual(0, again["updated_watches"])
        self.assertEqual(0, again["rebound_checkpoints"])

    def test_paused_watch_rebinds_but_unknown_remains_unreplayed(self):
        self.seed(3)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='PAUSED' WHERE task_id='task-1'",
            )
            db.execute(
                "UPDATE delayed_send_watches SET state='UNKNOWN' WHERE task_id='task-2'",
            )
        inventory = self.ledger.full_recovery_relations(work_id="my-work")
        self.assertFalse(inventory["complete"])
        self.assertEqual(2, len(inventory["watches"]))
        self.assertEqual(
            [{"task_id": "task-2", "generation": 1, "state": "UNKNOWN"}],
            inventory["unresolved_watches"],
        )
        result = self.ledger.rebind_active_manager_atomic(
            work_id="my-work", manager_conversation_key=NEW,
            manager_instance_id="new-instance", succession_proofs=self.proof(),
        )
        self.assertEqual(2, result["updated_watches"])
        self.assertEqual(3, result["rebound_checkpoints"])
        self.assertFalse(result["complete"])
        self.assertEqual("UNKNOWN", result["unresolved_watches"][0]["state"])
        with self.store._readonly() as db:
            paused = db.execute(
                "SELECT state,context_json FROM delayed_send_watches WHERE task_id='task-1'",
            ).fetchone()
            self.assertEqual("PAUSED", paused["state"])
            self.assertEqual(NEW, json.loads(paused["context_json"])["manager_conversation_key"])
            unknown = db.execute(
                "SELECT state,context_json FROM delayed_send_watches WHERE task_id='task-2'",
            ).fetchone()
            self.assertEqual("UNKNOWN", unknown["state"])
            self.assertEqual(OLD, json.loads(unknown["context_json"])["manager_conversation_key"])

    def test_missing_proof_never_partially_changes_either_ledger(self):
        self.seed(2)
        with self.assertRaisesRegex(ValueError, "SUCCESSION_PROOF_REQUIRED"):
            self.ledger.rebind_active_manager_atomic(
                work_id="my-work", manager_conversation_key=NEW,
                manager_instance_id="new-instance", succession_proofs=[],
            )
        self.assertEqual(OLD, self.ledger.full_recovery_relations(
            work_id="my-work")["checkpoints"][0]["active_manager_conversation_key"])
        self.assertEqual(OLD, self.ledger.full_recovery_relations(
            work_id="my-work")["watches"][0]["context"]["manager_conversation_key"])

    def test_crash_during_checkpoint_update_rolls_back_watch_change(self):
        self.seed(2)
        with self.store.transaction() as db:
            db.execute(
                "CREATE TRIGGER fail_rebind BEFORE UPDATE OF "
                "active_manager_conversation_key ON chain_manager_return_checkpoints "
                "BEGIN SELECT RAISE(ABORT,'simulated-update-failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.rebind_active_manager_atomic(
                work_id="my-work", manager_conversation_key=NEW,
                manager_instance_id="new-instance", succession_proofs=self.proof(),
            )
        original = self.ledger.full_recovery_relations(work_id="my-work")
        self.assertTrue(all(r["context"]["manager_conversation_key"] == OLD
                            for r in original["watches"]))
        self.assertTrue(all(r["active_manager_conversation_key"] == OLD
                            for r in original["checkpoints"]))


if __name__ == "__main__":
    unittest.main()
