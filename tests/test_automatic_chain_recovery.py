"""Automatic-first, exact-UUID node checks across a whole Chain network."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct.automatic_chain_recovery import AutomaticChainNodeRecovery, _identity, _targets
from bct.chain_direction import ChainDirectionLedger
from bct.chain_manager_recovery import ChainManagerRecoveryLedger
from bct.core.models import Work
from bct.core.store import Store
from bct.node_recovery import NodeRecoveryLedger
from bct.send_delayed_message import DurableWatchLedger

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
S = "dddddddd-dddd-dddd-dddd-dddddddddddd"


class AutomaticChainRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "existing-work", "original Chain Recipe", (tmp.name,),
            frozenset({"browser"}), "principal",
        ))
        DurableWatchLedger(self.store)
        self.offline = set()
        self.generating = set()
        self.stale = False
        self.sensor_unavailable = False
        for task, key in (("task-b", B), ("task-c", C)):
            self.seed_watch(task, key)
        self.coordinator = AutomaticChainNodeRecovery(
            store=self.store, status_provider=self.snapshot,
        )

    def seed_watch(self, task, worker):
        context = json.dumps({
            "work_id": self.work.work_id, "chain_direction_id": "original-direction",
            "manager_conversation_key": A,
            "supervisor_conversation_key": S,
        })
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches "
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES(?,1,?,?,?,'WATCHING',?)",
                (task, worker, "original-response-turn", "original-send", context),
            )

    def seed_direction(self, *, direction_id, target="", task_id="",
                       recipe_state="IN_PROGRESS", chain_state="NOT_PLANNED",
                       assessment=None):
        ChainDirectionLedger(self.store)
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO chain_directions "
                "(direction_id,work_id,source_kind,source_task_id,source_generation,"
                "source_result_sha256,decision,direction_text,assessment_json,"
                "target_conversation_key,chain_task_id,chain_state,recipe_state,"
                "created_at,updated_at) "
                "VALUES(?,?, 'USER','',0,'','NEW_TASK','saved Direction',"
                "?,?,?,?,?,1,1)",
                (direction_id, "direction-only-work",
                 json.dumps(assessment if assessment is not None else {}),
                 target, task_id, chain_state, recipe_state),
            )

    def direction_only_work(self):
        return self.store.create_work(Work(
            "direction-only-work", "Direction before Watch",
            self.work.roots, frozenset({"browser"}), "principal",
        ))

    def snapshot(self):
        if self.sensor_unavailable:
            raise RuntimeError("RCC observe failed")
        rows, tabs = [], []
        for idx, key in enumerate((A, B, C, S), 1):
            if key in self.offline:
                continue
            rows.append({
                "conversation_uuid": key, "status": "CONFIRMED",
                "tab_id": idx, "window_id": 10, "node_number": "N" + str(idx),
                "generating": key in self.generating,
                "connection": {"disconnected": False},
                "telemetry": {
                    "generation_state": "GENERATING" if key in self.generating else "IDLE",
                },
            })
            tabs.append({
                "tab_id": idx, "window_id": 10, "conversation_key": key,
                "presence": "OPEN", "connection": {"disconnected": False},
                "telemetry": {},
            })
        return {"monitor": {
            "current_nodes": {
                "observation": {"state": "STALE" if self.stale else "FRESH"},
                "observed_at": 100,
                "items": rows,
            },
            "rcc": {
                "instances": [{
                    "instance_id": "fixture", "state": "OPEN",
                    "cached": False, "tabs": tabs,
                }],
            },
        }}

    def test_saved_direction_monitors_a_and_s_before_first_watch(self):
        self.direction_only_work()
        self.seed_direction(
            direction_id="manager-pending", recipe_state="READY",
            assessment={
                "manager_conversation_key": A,
                "supervisor_conversation_key": S,
                "targets": [{"conversation_key": B, "role": "worker"}],
            },
        )
        found = {
            (row["work_id"], row["conversation_key"], row["role"])
            for row in _targets(self.store)
        }
        self.assertIn(("direction-only-work", A, "manager"), found)
        self.assertIn(("direction-only-work", S, "supervisor"), found)
        # No Worker send occurred; don't diagnose B as failed before delivery.
        self.assertNotIn(("direction-only-work", B, "worker"), found)

    def test_started_child_direction_without_watch_is_monitored_until_return(self):
        self.direction_only_work()
        self.seed_direction(
            direction_id="started-child", target=C,
            task_id="child-task", chain_state="CHAIN_STARTED",
        )
        targets = _targets(self.store)
        self.assertTrue(any(
            row["work_id"] == "direction-only-work"
            and row["conversation_key"] == C and row["task_id"] == "child-task"
            for row in targets
        ))
        ChainManagerRecoveryLedger(self.store).record_pending(
            task_id="child-task", generation=1,
            work_id="direction-only-work", direction_id="started-child",
            worker_conversation_key=C, manager_conversation_key=A,
            supervisor_conversation_key=S, response_turn_key="turn-1",
            response_sha256="a" * 64, return_payload="completed",
        )
        found = {
            (row["work_id"], row["conversation_key"], row["role"])
            for row in _targets(self.store)
        }
        self.assertNotIn(("direction-only-work", C, "worker"), found)

    def test_completed_or_planned_directions_never_spawn_worker_recovery(self):
        self.direction_only_work()
        self.seed_direction(
            direction_id="planned-child", target=B,
            task_id="planned-task", chain_state="CHAIN_PLANNED",
        )
        self.seed_direction(
            direction_id="completed-child", target=C,
            task_id="completed-task", chain_state="CHAIN_STARTED",
            recipe_state="COMPLETED",
        )
        found = {
            (row["work_id"], row["conversation_key"])
            for row in _targets(self.store)
        }
        self.assertNotIn(("direction-only-work", B), found)
        self.assertNotIn(("direction-only-work", C), found)

    def test_all_a_b_c_s_are_checked_and_healthy_nodes_untouched(self):
        result = self.coordinator.run_once()
        self.assertEqual("OBSERVED", result["status"])
        self.assertEqual(4, result["known_nodes"])
        self.assertEqual(4, result["observed"])
        self.assertEqual([], result["events"])
        with self.store._readonly() as db:
            self.assertEqual(0, db.execute(
                "SELECT COUNT(*) FROM node_recovery_cases"
            ).fetchone()[0])
            self.assertEqual(2, db.execute(
                "SELECT COUNT(*) FROM delayed_send_watches WHERE state='WATCHING'"
            ).fetchone()[0])

    def test_loss_check_recheck_then_same_uuid_returns_without_replay(self):
        self.offline.add(A)
        first = self.coordinator.run_once()
        self.assertEqual("RECHECKING", first["events"][0]["status"])
        second = self.coordinator.run_once()
        self.assertEqual("RECOVERY_EVIDENCE_READY", second["events"][0]["status"])
        case = _identity("existing-work", A, self.work.assignment_epoch)
        self.assertEqual("RECOVERY_NEEDED", self.coordinator.ledger.get(
            work=self.work, case_id=case,
        )["state"])
        with self.store._readonly() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM node_recovery_checks WHERE case_id=?",
                (case,),
            ).fetchone()[0]
        self.coordinator.run_once()
        with self.store._readonly() as db:
            self.assertEqual(count, db.execute(
                "SELECT COUNT(*) FROM node_recovery_checks WHERE case_id=?",
                (case,),
            ).fetchone()[0])
        self.offline.clear()
        repaired = self.coordinator.run_once()
        self.assertEqual("RECOVERED_SAME_UUID", repaired["events"][0]["status"])
        self.assertEqual("RECOVERED", self.coordinator.ledger.get(
            work=self.work, case_id=case,
        )["state"])
        with self.store._readonly() as db:
            self.assertEqual(2, db.execute(
                "SELECT COUNT(*) FROM delayed_send_watches WHERE state='WATCHING'"
            ).fetchone()[0])
        self.assertEqual([], self.coordinator.run_once()["events"])

    def test_worker_and_supervisor_have_identical_automatic_recovery(self):
        self.offline.update((B, S))
        self.coordinator.run_once()
        result = self.coordinator.run_once()
        self.assertEqual({"worker", "supervisor"}, {
            item["role"] for item in result["events"]
            if item["status"] == "RECOVERY_EVIDENCE_READY"
        })
        self.offline.clear()
        recovered = self.coordinator.run_once()
        self.assertEqual(2, sum(
            item["status"] == "RECOVERED_SAME_UUID"
            for item in recovered["events"]
        ))

    def test_completed_worker_return_does_not_trigger_new_worker_recovery(self):
        # B has already finished and returned to A. B may now be closed:
        # only A/S pending-return continuity remains relevant to this Watch.
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='MANAGER_RECOVERY_PENDING' "
                "WHERE task_id='task-b'",
            )
        self.offline.add(B)
        one = self.coordinator.run_once()
        two = self.coordinator.run_once()
        self.assertNotIn(B, [
            event["conversation_key"] for event in
            one["events"] + two["events"]
        ])
        self.assertEqual(3, two["known_nodes"])
        with self.store._readonly() as db:
            self.assertEqual(0, db.execute(
                "SELECT COUNT(*) FROM node_recovery_cases"
            ).fetchone()[0])

    def test_generating_never_becomes_failed_node(self):
        self.generating.add(A)
        for _ in range(10):
            result = self.coordinator.run_once()
            self.assertEqual([], result["events"])
        with self.store._readonly() as db:
            self.assertEqual(0, db.execute(
                "SELECT COUNT(*) FROM node_recovery_cases"
            ).fetchone()[0])

    def test_sensor_failure_does_not_create_false_node_recovery(self):
        self.offline.add(A)
        self.sensor_unavailable = True
        result = self.coordinator.run_once()
        self.assertEqual("SENSOR_UNKNOWN", result["status"])
        self.sensor_unavailable = False
        self.stale = True
        result = self.coordinator.run_once()
        self.assertEqual("SENSOR_UNKNOWN", result["status"])
        with self.store._readonly() as db:
            self.assertEqual(0, db.execute(
                "SELECT COUNT(*) FROM node_recovery_cases"
            ).fetchone()[0])

    def test_core_restart_retains_original_recovery_case(self):
        self.offline.add(A)
        self.coordinator.run_once()
        resumed = AutomaticChainNodeRecovery(
            store=self.store, status_provider=self.snapshot,
        )
        result = resumed.run_once()
        self.assertEqual("RECOVERY_EVIDENCE_READY", result["events"][0]["status"])
        self.offline.clear()
        result = resumed.run_once()
        self.assertEqual("RECOVERED_SAME_UUID", result["events"][0]["status"])

    def test_fair_batch_iteration_over_more_than_one_hundred_nodes(self):
        # The monitoring loop cannot strand all nodes beyond the first batch.
        for i in range(105):
            worker = "%08x-%04x-%04x-%04x-%012x" % (i+0x10000000,1,2,3,i+1)
            self.seed_watch("bulk-%03d" % i, worker)
        seen = set()
        for _ in range(7):
            result = self.coordinator.run_once(limit=20)
            self.assertLessEqual(result["observed"], 20)
            # A missing Worker is a positive CHECK, not a send/replay effect.
            seen.update(
                x["conversation_key"] for x in result["events"]
            )
        self.assertEqual(109, result["known_nodes"])
        self.assertGreaterEqual(len(seen), 100)


if __name__ == "__main__":
    unittest.main()
