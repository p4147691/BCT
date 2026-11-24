from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.chain_direction import ChainBranchRequestLedger, ChainDirectionLedger
from bct.conversation_network import ensure_observed_node_labels
from bct.core.models import Work
from bct.core.store import Store
from bct.monitor_runtime import _conversation_network_manager_statuses
from bct.status_queries import read_status


class StatusReadContentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "fixture.sqlite")

    def test_deferred_snapshot_can_read_during_writer_and_is_consistent(self):
        writer = sqlite3.connect(self.store.path, isolation_level=None)
        self.addCleanup(writer.close)
        writer.execute("CREATE TABLE test_snapshot (value INTEGER)")
        writer.execute("INSERT INTO test_snapshot VALUES(1)")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE test_snapshot SET value=2")
        with self.store.read_transaction() as reader:
            reader.execute("PRAGMA busy_timeout=100")
            self.assertEqual(1, reader.execute("SELECT value FROM test_snapshot").fetchone()[0])
            writer.commit()
            self.assertEqual(1, reader.execute("SELECT value FROM test_snapshot").fetchone()[0])
            with self.assertRaises(sqlite3.OperationalError):
                reader.execute("UPDATE test_snapshot SET value=3")
        with self.store.read_transaction() as reader:
            self.assertEqual(2, reader.execute("SELECT value FROM test_snapshot").fetchone()[0])

    def test_known_labels_and_manager_projection_do_not_reserve_writer(self):
        conversations = [("00000000-0000-4000-8000-000000000001", "fixture")]
        labels = ensure_observed_node_labels(self.store, conversations=conversations)
        with patch.object(self.store, "transaction", side_effect=AssertionError("writer requested")):
            self.assertEqual(labels, ensure_observed_node_labels(self.store, conversations=conversations))
            self.assertEqual([], _conversation_network_manager_statuses(
                self.store, observed_conversation_keys=list(labels),
            ))
        with self.store.read_transaction() as db:
            self.assertEqual(1, db.execute(
                "SELECT count(*) FROM node_label_notification_outbox"
            ).fetchone()[0])

    def test_status_skips_empty_works_but_preserves_owner_order_and_legacy_roots(self):
        ledger = ChainDirectionLedger(self.store)
        for root, owner, state in (
            ("z-root", "owner", "BLOCKED"),
            ("empty", "owner", None),
            ("foreign", "other", "UNKNOWN"),
            ("a-legacy-root", "owner", "UNKNOWN"),
        ):
            self.store.create_work(Work(root, "fixture", (self.tmp.name,), frozenset({"read"}), owner))
            if state is None:
                continue
            ledger.save(direction_id=f"dir-{root}", work_id=root, source_kind="USER",
                        decision="NEW_TASK", direction_text="Read fixture")
            with self.store.transaction() as db:
                db.execute("UPDATE chain_directions SET root_work_id=?,recipe_state=? WHERE direction_id=?",
                           ("" if "legacy" in root else root, state, f"dir-{root}"))
        expected = []
        for root in ("z-root", "empty", "a-legacy-root"):
            expected.extend({"root_work_id": root, **row} for row in
                            ChainBranchRequestLedger.tree(store=self.store, root_work_id=root)["manager_attention"])
        with patch.object(ChainBranchRequestLedger, "tree", wraps=ChainBranchRequestLedger.tree) as tree:
            result = asyncio.run(read_status(
                SimpleNamespace(store=self.store), principal_id="owner",
                status_provider=lambda: {"monitor": {}}, browser_usage="fixture"))
        self.assertEqual(expected, result["chain_branch_attention"])
        self.assertEqual(["z-root", "a-legacy-root"],
                         [call.kwargs["root_work_id"] for call in tree.call_args_list])
        self.assertIn("DO_NOT_RESEND_OR_CREATE_A_REPLACEMENT_OPERATION",
                      result["chain_branch_attention"][1]["prohibited_actions"])


    def test_attention_keeps_public_compact_and_full_limits_and_order(self):
        ledger = ChainDirectionLedger(self.store)
        roots = [f"work-{i:02d}" for i in range(24, -1, -1)]
        for root in roots:
            self.store.create_work(Work(root, "fixture", (self.tmp.name,), frozenset({"read"}), "owner"))
            ledger.save(direction_id=f"dir-{root}", work_id=root, source_kind="USER",
                        decision="NEW_TASK", direction_text="Read fixture")
        with self.store.transaction() as db:
            db.execute("UPDATE chain_directions SET recipe_state='UNKNOWN'")
        for compact, expected in ((True, roots[:5]), (False, roots[:20])):
            result = asyncio.run(read_status(
                SimpleNamespace(store=self.store), principal_id="owner",
                status_provider=lambda: {"monitor": {}}, browser_usage="fixture", compact=compact,
            ))
            self.assertEqual(expected, [row["root_work_id"] for row in result["chain_branch_attention"]])
