"""Automatic Watch/return repair from an exact existing BCT Manager transfer."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.automatic_manager_rebinding import AutomaticManagerRebinding
from bct.chain_manager_recovery import ChainManagerRecoveryLedger
from bct.conversation_network import (
    configure_conversation_scope, transfer_conversation_manager_role,
)
from bct.core.models import Work
from bct.core.store import Store
from bct.send_delayed_message import DurableWatchLedger, SendDelayedMessageService

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
A2 = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
A3 = "ffffffff-ffff-ffff-ffff-ffffffffffff"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
S = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class AutomaticManagerRebindingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "manager-resume-work", "Original chain", (tmp.name,),
            frozenset({"browser"}), "principal",
        ))
        DurableWatchLedger(self.store)
        self.ledger = ChainManagerRecoveryLedger(self.store)
        original = configure_conversation_scope(
            self.store, conversation_key=A,
            display_name="A", scope_name="Project", role_tags=["Manager"],
        )
        self.project = original["scope_id"]
        self.successor = configure_conversation_scope(
            self.store, conversation_key=A2,
            display_name="A2", scope_name="Project", role_tags=["Reviewer"],
        )
        configure_conversation_scope(
            self.store, conversation_key=B,
            display_name="B", scope_name="Project", role_tags=["Worker"],
        )
        self.transfer = None
        self.worker_online = True
        self.successor_online = True
        self.successor_roles = ["Manager", "Reviewer"]
        self.successor_disconnected = False
        with self.store.transaction() as db:
            context = json.dumps({
                "work_id": self.work.work_id,
                "manager_conversation_key": A,
                "manager_instance_id": "old-instance",
                "supervisor_conversation_key": S,
                "chain_direction_id": "direction-1",
            }, sort_keys=True)
            db.execute(
                "INSERT INTO delayed_send_watches "
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES('task-b',1,?,'turn-1','source','WATCHING',?)",
                (B, context),
            )
        self.ledger.record_pending(
            task_id="task-b", generation=1, work_id=self.work.work_id,
            direction_id="direction-1", worker_conversation_key=B,
            manager_conversation_key=A, supervisor_conversation_key=S,
            response_turn_key="turn-1", response_sha256="a" * 64,
            return_payload="Completed Worker work",
        )
        self.runner = AutomaticManagerRebinding(
            store=self.store, status_provider=self.snapshot,
        )

    def snapshot(self):
        rows = []
        tabs = []
        if self.successor_online:
            rows.append({
                "conversation_uuid": A2, "status": "CONFIRMED",
                "tab_id": 21, "window_id": 3,
                "generating": False,
                "roles": self.successor_roles,
                "network_id": self.project,
                "network": "Project",
            })
            tabs.append({
                "conversation_key": A2, "presence": "OPEN",
                "tab_id": 21, "window_id": 3,
                "connection": {"disconnected": self.successor_disconnected},
                "conversation_scope": {
                    "scope_name": "Project", "scope_id": self.project,
                    "role_tags": self.successor_roles,
                },
            })
        if self.worker_online:
            rows.append({
                "conversation_uuid": B, "status": "CONFIRMED",
                "tab_id": 22, "window_id": 3,
                "generating": False, "roles": ["Worker"],
                "network_id": self.project, "network": "Project",
            })
            tabs.append({
                "conversation_key": B, "presence": "OPEN",
                "tab_id": 22, "window_id": 3,
                "conversation_scope": {
                    "scope_name": "Project", "scope_id": self.project,
                    "role_tags": ["Worker"],
                },
            })
        return {"monitor": {
            "current_nodes": {
                "observation": {"state": "FRESH"},
                "items": rows,
            },
            "rcc": {"instances": [{
                "instance_id": "a" * 32, "session_id": "b" * 32,
                "state": "OPEN", "cached": False, "tabs": tabs,
            }]},
        }}

    def make_transfer(self):
        self.transfer = transfer_conversation_manager_role(
            self.store, project_id=self.project,
            predecessor_conversation_key=A,
            successor_conversation_key=A2,
            expected_successor_role_tags_sha256=self.successor["role_tags_sha256"],
        )
        return self.transfer

    def test_a_s_outage_then_formal_manager_replacement_auto_delivers_once(self):
        # B has completed already; original A and global S are inaccessible.
        # Existing Watch/return persist and a formally created successor A2
        # is confirmed by actual BCT role-transfer and fresh RCC Node Info.
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='MANAGER_RECOVERY_PENDING' "
                "WHERE task_id='task-b'",
            )
        self.make_transfer()
        result = self.runner.run_once()
        self.assertEqual("MANAGER_AUTO_REBOUND", result["events"][0]["status"])
        self.assertEqual(1, result["events"][0]["updated_watches"])
        self.assertEqual(1, result["events"][0]["rebound_checkpoints"])
        delivered = []
        service = SendDelayedMessageService(
            store=self.store,
            browser_feature=SimpleNamespace(),
            operations=SimpleNamespace(),
        )
        with (
            patch.object(service, "_conversation_availability", return_value="AVAILABLE"),
            patch.object(
                service, "_send_for",
                side_effect=lambda row, *, destination, message, operation_id:
                    (delivered.append((destination, message, operation_id))
                     or operation_id),
            ),
        ):
            events = service.poll_pending_manager_returns()
            self.assertEqual("MANAGER_RETURN_AUTODELIVERED", events[0]["status"])
            self.assertEqual([], service.poll_pending_manager_returns())
        self.assertEqual(1, len(delivered))
        self.assertEqual(A2, delivered[0][0])
        self.assertIn("Completed Worker work", delivered[0][1])
        self.assertEqual("RETURNED_TO_MANAGER", self.ledger.get(
            task_id="task-b", generation=1,
        )["delivery_state"])
        # Receipt delivery and original A2 acknowledgement are separate.
        self.assertEqual(0.0, self.ledger.get(
            task_id="task-b", generation=1,
        )["acknowledged_at"])
        acknowledged = self.ledger.acknowledge(
            work_id=self.work.work_id, task_id="task-b",
            generation=1, manager_conversation_key=A2,
        )
        self.assertGreater(acknowledged["acknowledged_at"], 0)

    def test_no_transfer_means_no_fake_auto_manager(self):
        self.assertEqual([], self.runner.run_once()["events"])
        self.assertEqual(A, self.ledger.get(
            task_id="task-b", generation=1,
        )["active_manager_conversation_key"])

    def test_actual_manager_transfer_rebinds_watch_and_return_and_no_replay(self):
        self.make_transfer()
        result = self.runner.run_once()
        self.assertEqual("MANAGER_AUTO_REBOUND", result["events"][0]["status"])
        self.assertTrue(result["events"][0]["complete"])
        self.assertEqual(1, result["events"][0]["updated_watches"])
        self.assertEqual(1, result["events"][0]["rebound_checkpoints"])
        with self.store._readonly() as db:
            watch = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id='task-b'"
            ).fetchone()
            context = json.loads(watch["context_json"])
        self.assertEqual(A2, context["manager_conversation_key"])
        self.assertEqual("a" * 32, context["manager_instance_id"])
        self.assertEqual(A2, self.ledger.get(
            task_id="task-b", generation=1,
        )["active_manager_conversation_key"])
        # The Worker remains working on the same exact Task/Generation.
        with self.store._readonly() as db:
            self.assertEqual("WATCHING", db.execute(
                "SELECT state FROM delayed_send_watches WHERE task_id='task-b'"
            ).fetchone()["state"])
        self.assertEqual([], self.runner.run_once()["events"])
        self.assertEqual([], AutomaticManagerRebinding(
            store=self.store, status_provider=self.snapshot,
        ).run_once()["events"])

    def test_offline_successor_and_role_conflict_never_rebind(self):
        self.make_transfer()
        self.successor_online = False
        self.assertTrue(all(x["status"] != "MANAGER_AUTO_REBOUND"
                            for x in self.runner.run_once()["events"]))
        self.successor_online = True
        self.successor_disconnected = True
        self.assertTrue(all(x["status"] != "MANAGER_AUTO_REBOUND"
                            for x in self.runner.run_once()["events"]))
        self.successor_disconnected = False
        self.successor_roles = ["Manager", "Worker"]
        self.assertTrue(all(x["status"] != "MANAGER_AUTO_REBOUND"
                            for x in self.runner.run_once()["events"]))
        self.assertEqual(A, self.ledger.get(
            task_id="task-b", generation=1,
        )["active_manager_conversation_key"])

    def test_stale_transfer_receipt_blocked_inside_write_transaction(self):
        original = self.make_transfer()
        configure_conversation_scope(
            self.store, conversation_key=A3,
            display_name="A3", scope_name="Project", role_tags=["Reviewer"],
        )
        transfer_conversation_manager_role(
            self.store, project_id=self.project,
            predecessor_conversation_key=A2,
            successor_conversation_key=A3,
            expected_successor_role_tags_sha256=configure_conversation_scope(
                self.store, conversation_key=A3,
                display_name="A3", scope_name="Project", role_tags=["Reviewer"],
            )["role_tags_sha256"],
        )
        with self.assertRaisesRegex(ValueError, "PROOF_REQUIRED"):
            self.ledger.rebind_active_manager_atomic(
                work_id=self.work.work_id,
                manager_conversation_key=A2,
                manager_instance_id="a" * 32,
                succession_proofs=[original],
                require_latest_transfer=True,
            )
        self.assertEqual(A, self.ledger.get(
            task_id="task-b", generation=1,
        )["active_manager_conversation_key"])

    def test_missing_checkpoints_table_does_not_block_cold_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "db.sqlite")
            runner = AutomaticManagerRebinding(
                store=store, status_provider=lambda: {},
            )
            self.assertEqual("IDLE", runner.run_once()["status"])


if __name__ == "__main__":
    unittest.main()
