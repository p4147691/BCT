"""Crash-safe automatic finalization of a prepared Worker/S replacement."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct.automatic_prepared_replacement import AutomaticPreparedReplacement
from bct.conversation_network import (
    configure_conversation_scope, conversation_scope_directory,
)
from bct.core.models import Work
from bct.core.store import Store
from bct.node_recovery import NodeRecoveryLedger, observe_node
from tests.test_node_recovery import OLD, NEW, view


class PreparedReplaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / "state.db")
        self.work = self.store.create_work(Work(
            "work", "original Worker task", (temp.name,),
            frozenset({"browser"}), "principal",
        ))
        self.ledger = NodeRecoveryLedger(self.store)
        self.offline_old = True
        self.offline_new = False
        self.stale = False
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="Old",
            scope_name="network original", role_tags=["Worker"],
            assigned_task="the exact original task",
        )
        configure_conversation_scope(
            self.store, conversation_key=NEW, display_name="New",
            scope_name="", role_tags=[],
        )
        self.ledger.check(
            work=self.work, case_id="case-replacement",
            task_id="task-original", conversation_key=OLD,
            evidence=observe_node(view(disconnected=True), OLD), kind="CHECK",
        )
        self.ledger.pause(
            work=self.work, case_id="case-replacement", reason="confirmed unavailable",
        )
        self.ledger.prepare_replace(
            work=self.work, case_id="case-replacement",
            successor_conversation_key=NEW, inheritance_task_id="task-inheritance",
            successor_evidence=observe_node(view(NEW), NEW),
        )
        self.coordinator = AutomaticPreparedReplacement(
            store=self.store, status_provider=self.snapshot,
        )

    def snapshot(self):
        statuses = []
        if not self.offline_old:
            statuses.extend(view(OLD)["current_nodes"]["items"])
        if not self.offline_new:
            statuses.extend(view(NEW)["current_nodes"]["items"])
        return {"monitor": {
            "current_nodes": {
                "observation": {"state": "STALE" if self.stale else "FRESH"},
                "items": statuses,
            },
            "rcc": {"instances": []},
        }}

    def inherit(self, *, state="MANAGER_DECISION_REQUIRED", evidence=True):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches"
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES(?,1,?,?,?, ?,?)",
                ("task-inheritance", NEW, "inherit-turn", "send-receipt",
                 state,
                 json.dumps({
                     "work_id": "work",
                     "observed_response_sha": "f" * 64 if evidence else "",
                     "assignment_epoch": 1,
                 })),
            )

    def test_automatic_successor_inheritance_finalizes_without_duplicate(self):
        self.inherit()
        first = self.coordinator.run_once()
        self.assertEqual("REPLACED", first["events"][0]["status"], first)
        self.assertFalse(first["events"][0]["duplicate"])
        second = AutomaticPreparedReplacement(
            store=self.store, status_provider=self.snapshot,
        ).run_once()
        self.assertEqual("IDLE", second["status"])
        info = conversation_scope_directory(self.store, conversation_keys=[OLD, NEW])
        self.assertEqual(["Worker"], info[NEW]["role_tags"])
        self.assertEqual("the exact original task", info[NEW]["assigned_task"])
        self.assertEqual([], info[OLD]["role_tags"])
        self.assertEqual("REPLACED", self.ledger.get(
            work=self.work, case_id="case-replacement",
        )["state"])

    def test_reserved_watch_cannot_claim_inheritance_was_sent(self):
        self.inherit(state="WATCHING", evidence=False)
        result = self.coordinator.run_once()
        self.assertEqual("AWAIT_INHERITANCE_PROOF", result["events"][0]["status"])
        self.assertEqual("REPLACEMENT_PREPARED", self.ledger.get(
            work=self.work, case_id="case-replacement",
        )["state"])

    def test_core_restart_waits_then_uses_real_response(self):
        self.inherit(state="WATCHING", evidence=False)
        self.assertEqual("AWAIT_INHERITANCE_PROOF",
                         self.coordinator.run_once()["events"][0]["status"])
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches "
                "SET state='MANAGER_DECISION_REQUIRED',"
                "context_json=json_set(context_json,'$.observed_response_sha',?) "
                "WHERE task_id='task-inheritance'", ("f" * 64,),
            )
        resumed = AutomaticPreparedReplacement(
            store=self.store, status_provider=self.snapshot,
        )
        self.assertEqual("REPLACED", resumed.run_once()["events"][0]["status"])

    def test_original_node_reappears_so_replacement_does_not_takeover(self):
        self.inherit()
        self.offline_old = False
        result = self.coordinator.run_once()
        self.assertEqual("OLD_NODE_RECOVERED", result["events"][0]["status"])
        self.assertEqual("REPLACEMENT_PREPARED", self.ledger.get(
            work=self.work, case_id="case-replacement",
        )["state"])

    def test_unknown_original_effect_stays_unresolved(self):
        self.inherit()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches"
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES('unknown-task',1,?,'turn','send','UNKNOWN',?)",
                (OLD, json.dumps({"work_id": "work"})),
            )
        self.assertEqual("UNKNOWN_RECONCILIATION_REQUIRED",
                         self.coordinator.run_once()["events"][0]["status"])
        self.assertEqual("REPLACEMENT_PREPARED", self.ledger.get(
            work=self.work, case_id="case-replacement",
        )["state"])

    def test_manager_uses_epoch_rebinding_instead_of_role_only_replace(self):
        self.inherit()
        # Deliberately include Manager role, not simply Worker.
        with self.store.transaction() as db:
            db.execute(
                "UPDATE conversation_network_membership_tags SET tag='Manager' "
                "WHERE conversation_key=? AND tag='Worker'", (OLD,),
            )
        self.assertEqual("MANAGER_EPOCH_REBIND_REQUIRED",
                         self.coordinator.run_once()["events"][0]["status"])

    def test_global_supervisor_replacement_uses_same_recovery_and_role(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="Global S",
            scope_name="", role_tags=["supervisor"], assigned_task="CI and E2E",
        )
        self.inherit()
        result = self.coordinator.run_once()
        self.assertEqual("REPLACED", result["events"][0]["status"], result)
        directory = conversation_scope_directory(self.store, conversation_keys=[OLD, NEW])
        self.assertEqual(["supervisor"], directory[NEW]["role_tags"])
        self.assertEqual("CI and E2E", directory[NEW]["assigned_task"])
        self.assertEqual([], directory[OLD]["role_tags"])

    def test_global_supervisor_active_work_must_not_be_silently_stranded(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="Global S",
            scope_name="", role_tags=["supervisor"], assigned_task="CI",
        )
        self.inherit()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches"
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES('another-active-work',1,?,'turn','send','WATCHING',?)",
                (NEW, json.dumps({
                    "work_id": "work", "supervisor_conversation_key": OLD,
                    "manager_conversation_key": NEW,
                })),
            )
        outcome = self.coordinator.run_once()["events"][0]
        self.assertEqual("SUPERVISOR_GLOBAL_REBIND_REQUIRED", outcome["status"])
        self.assertEqual("REPLACEMENT_PREPARED", self.ledger.get(
            work=self.work, case_id="case-replacement",
        )["state"])
        original = conversation_scope_directory(self.store, conversation_keys=[OLD, NEW])
        self.assertEqual(["supervisor"], original[OLD]["role_tags"])
        self.assertEqual([], original[NEW]["role_tags"])

    def test_prepared_manager_without_any_active_watch_is_still_fenced(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="Global Manager",
            scope_name="network original", role_tags=["Manager"], assigned_task="Original A",
        )
        self.inherit()
        self.assertEqual("MANAGER_EPOCH_REBIND_REQUIRED",
                         self.coordinator.run_once()["events"][0]["status"])

    def test_stale_monitor_cannot_replace(self):
        self.inherit()
        self.stale = True
        self.assertEqual("SENSOR_UNKNOWN", self.coordinator.run_once()["status"])
        self.assertEqual("REPLACEMENT_PREPARED", self.ledger.get(
            work=self.work, case_id="case-replacement",
        )["state"])


if __name__ == "__main__":
    unittest.main()
