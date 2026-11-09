from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.models import Work
from bct.core.store import Store
from bct.conversation_network import (
    configure_conversation_scope, conversation_scope_directory,
    transfer_conversation_state,
)
from bct.send_delayed_message import DurableWatchLedger
from bct.mcp_server import build_mcp
from bct.node_recovery import NodeRecoveryLedger, observe_node


OLD = "11111111-1111-1111-1111-111111111111"
NEW = "22222222-2222-2222-2222-222222222222"


def view(key=OLD, *, generating=False, fresh=True, disconnected=False,
         attention=None, last_activity_at=100, rendered_chars=10):
    return {
        "status": "OK",
        "current_nodes": {
            "observed_at": 10.0,
            "observation": {"state": "FRESH" if fresh else "STALE"},
            "items": [{
                "conversation_uuid": key, "status": "CONFIRMED",
                "node_number": "N4", "window_id": 12, "tab_id": 13,
                "generating": generating, "name": "node", "network": "test",
                "network_id": "network.test", "roles": [], "assigned_task": "task",
                "connection": {"disconnected": disconnected,
                               "reason": "network-banner" if disconnected else ""},
                "telemetry": {"readiness": "BUSY" if generating else "IDLE",
                              "generation_state": "GENERATING" if generating else "IDLE",
                              "last_activity_at": last_activity_at,
                              "rendered_chars": rendered_chars, "turns": 2,
                              "user_attention": attention, "signal_source": "dom"},
            }],
        },
    }


class NodeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "work", "test", (self.temp.name,), frozenset({"browser"}), "principal",
        ))
        self.ledger = NodeRecoveryLedger(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_check_recheck_and_pause_fence_exact_node(self):
        first = self.ledger.check(
            work=self.work, case_id="case-1", task_id="task-1",
            conversation_key=OLD, evidence=observe_node(view(generating=True), OLD),
            kind="CHECK",
        )
        self.assertEqual(("WAIT", "RECHECK"), (first["result"], first["next_action"]))
        second = self.ledger.check(
            work=self.work, case_id="case-1", task_id="task-1",
            conversation_key=OLD, evidence=observe_node(view(generating=False), OLD),
            kind="RECHECK",
        )
        self.assertEqual(("OK", "CONTINUE"), (second["result"], second["next_action"]))

        delayed = DurableWatchLedger(self.store)
        delayed.prearm_task(
            task_id="task-1", work_id=self.work.work_id,
            principal_id=self.work.owner_principal_id,
            assignment_epoch=self.work.assignment_epoch,
            instance_id="instance", conversation_key=OLD,
            manager_conversation_key=NEW, manager_instance_id="instance",
            baseline={"responseTurnCount": 0, "generating": False,
                      "responseSha256": "a" * 64, "responseTurnKey": "turn-0",
                      "latestUserTurnKey": "user-0", "latestUserSha256": "b" * 64,
                      "latestUserTextOccurrenceCount": 1},
            registration_receipt="arm", planned_send_operation_id="send",
            planned_send_text="instruction",
        )
        delayed.prearm_task(
            task_id="task-other", work_id=self.work.work_id,
            principal_id=self.work.owner_principal_id,
            assignment_epoch=self.work.assignment_epoch,
            instance_id="instance", conversation_key=OLD,
            manager_conversation_key=NEW, manager_instance_id="instance",
            baseline={"responseTurnCount": 0, "generating": False,
                      "responseSha256": "c" * 64, "responseTurnKey": "turn-other",
                      "latestUserTurnKey": "user-other", "latestUserSha256": "d" * 64,
                      "latestUserTextOccurrenceCount": 1},
            registration_receipt="arm-other", planned_send_operation_id="send-other",
            planned_send_text="other instruction",
        )
        paused = self.ledger.pause(work=self.work, case_id="case-1", reason="no progress")
        self.assertEqual("PAUSED", paused["state"])
        self.assertEqual(2, paused["delayed_sends_paused"])
        self.assertRaisesRegex(
            ValueError, "NODE_RECOVERY_SEND_FENCED",
            self.ledger.assert_send_allowed, work_id="work", conversation_key=OLD,
        )
        self.ledger.assert_send_allowed(work_id="work", conversation_key=NEW)

    def test_replace_requires_inheritance_watch_before_commit(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="old",
            scope_name="test network", role_tags=["Manager"],
            node_memo="old memo", assigned_task="old task",
        )
        configure_conversation_scope(
            self.store, conversation_key=NEW, display_name="new",
            scope_name="", role_tags=[],
        )
        self.ledger.check(
            work=self.work, case_id="case-2", task_id="task-old",
            conversation_key=OLD, evidence=observe_node(view(), OLD), kind="CHECK",
        )
        self.ledger.pause(work=self.work, case_id="case-2", reason="stalled")
        prepared = self.ledger.prepare_replace(
            work=self.work, case_id="case-2", successor_conversation_key=NEW,
            inheritance_task_id="task-new", successor_evidence=observe_node(view(NEW), NEW),
        )
        self.assertEqual("REPLACEMENT_PREPARED", prepared["state"])
        with self.assertRaisesRegex(ValueError, "INHERITANCE_NOT_SENT"):
            self.ledger.commit_replace(
                work=self.work, case_id="case-2", successor_evidence=observe_node(view(NEW), NEW),
            )
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches(task_id,generation,conversation_key,"
                "response_turn_id,source_send_receipt,state,context_json) VALUES(?,?,?,?,?,?,?)",
                ("task-new", 1, NEW, "turn", "send", "WATCHING",
                 '{"work_id":"work","principal_id":"principal","assignment_epoch":1}'),
            )
        committed = self.ledger.commit_replace(
            work=self.work, case_id="case-2", successor_evidence=observe_node(view(NEW), NEW),
        )
        self.assertEqual("REPLACED", committed["state"])
        directory = conversation_scope_directory(self.store, conversation_keys=[OLD, NEW])
        self.assertEqual("", directory[OLD]["scope_id"])
        self.assertEqual([], directory[OLD]["role_tags"])
        self.assertEqual("test network", directory[NEW]["scope_name"])
        self.assertEqual(["Manager"], directory[NEW]["role_tags"])
        self.assertEqual("old memo", directory[NEW]["node_memo"])
        self.assertEqual("old task", directory[NEW]["assigned_task"])

    def test_replace_accepts_completed_inheritance_awaiting_manager_decision(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="old supervisor",
            scope_name="", role_tags=["supervisor"],
        )
        configure_conversation_scope(
            self.store, conversation_key=NEW, display_name="new supervisor",
            scope_name="", role_tags=[],
        )
        self.ledger.check(
            work=self.work, case_id="case-manager-decision", task_id="task-old",
            conversation_key=OLD, evidence=observe_node(view(), OLD), kind="CHECK",
        )
        self.ledger.pause(work=self.work, case_id="case-manager-decision", reason="stalled")
        self.ledger.prepare_replace(
            work=self.work, case_id="case-manager-decision", successor_conversation_key=NEW,
            inheritance_task_id="task-manager-decision",
            successor_evidence=observe_node(view(NEW), NEW),
        )
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches(task_id,generation,conversation_key,"
                "response_turn_id,source_send_receipt,state,context_json) VALUES(?,?,?,?,?,?,?)",
                ("task-manager-decision", 1, NEW, "turn", "send",
                 "MANAGER_DECISION_REQUIRED",
                 '{"work_id":"work","principal_id":"principal","assignment_epoch":1,'
                 '"observed_response_sha":"' + "a" * 64 + '"}'),
            )
        committed = self.ledger.commit_replace(
            work=self.work, case_id="case-manager-decision",
            successor_evidence=observe_node(view(NEW), NEW),
        )
        self.assertEqual("REPLACED", committed["state"])

    def test_unassigned_supervisor_moves_without_duplicate(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="old supervisor",
            scope_name="", role_tags=["supervisor"], assigned_task="release",
        )
        configure_conversation_scope(
            self.store, conversation_key=NEW, display_name="new supervisor",
            scope_name="", role_tags=[],
        )
        moved = transfer_conversation_state(
            self.store, predecessor_conversation_key=OLD,
            successor_conversation_key=NEW,
        )
        self.assertEqual(["supervisor"], moved["role_tags"])
        directory = conversation_scope_directory(self.store, conversation_keys=[OLD, NEW])
        self.assertEqual([], directory[OLD]["role_tags"])
        self.assertEqual(["supervisor"], directory[NEW]["role_tags"])
        self.assertEqual("release", directory[NEW]["assigned_task"])

    def test_replace_scope_conflict_rolls_back_every_state_change(self):
        configure_conversation_scope(
            self.store, conversation_key=OLD, display_name="old",
            scope_name="network a", role_tags=["Manager"],
        )
        configure_conversation_scope(
            self.store, conversation_key=NEW, display_name="new",
            scope_name="network b", role_tags=[],
        )
        self.ledger.check(
            work=self.work, case_id="case-conflict", task_id="task-old",
            conversation_key=OLD, evidence=observe_node(view(), OLD), kind="CHECK",
        )
        self.ledger.pause(work=self.work, case_id="case-conflict", reason="stalled")
        self.ledger.prepare_replace(
            work=self.work, case_id="case-conflict", successor_conversation_key=NEW,
            inheritance_task_id="task-conflict", successor_evidence=observe_node(view(NEW), NEW),
        )
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches(task_id,generation,conversation_key,"
                "response_turn_id,source_send_receipt,state,context_json) VALUES(?,?,?,?,?,?,?)",
                ("task-conflict", 1, NEW, "turn", "send", "WATCHING",
                 '{"work_id":"work","principal_id":"principal","assignment_epoch":1}'),
            )
        with self.assertRaisesRegex(ValueError, "SUCCESSOR_SCOPE_CONFLICT"):
            self.ledger.commit_replace(
                work=self.work, case_id="case-conflict",
                successor_evidence=observe_node(view(NEW), NEW),
            )
        directory = conversation_scope_directory(self.store, conversation_keys=[OLD, NEW])
        self.assertEqual(("network a", ["Manager"]),
                         (directory[OLD]["scope_name"], directory[OLD]["role_tags"]))
        self.assertEqual(("network b", []),
                         (directory[NEW]["scope_name"], directory[NEW]["role_tags"]))
        case = self.ledger.get(work=self.work, case_id="case-conflict")
        self.assertEqual("REPLACEMENT_PREPARED", case["state"])

    def test_reset_preserves_unknown_close_for_reconciliation(self):
        self.ledger.check(
            work=self.work, case_id="case-3", task_id="", conversation_key=OLD,
            evidence=observe_node(view(), OLD), kind="CHECK",
        )
        self.ledger.pause(work=self.work, case_id="case-3", reason="stalled")
        planned = self.ledger.prepare_reset(
            work=self.work, case_id="case-3", node_evidence=observe_node(view(), OLD),
        )
        self.assertEqual("HISTORICAL_ONLY_NEW_NUMBER_ON_RESTORE", planned["node_number_policy"])
        result = self.ledger.finish_reset(
            work=self.work, case_id="case-3", close_outcome="UNKNOWN", operation_id="close-1",
        )
        self.assertEqual("RESET_UNKNOWN", result["state"])
        self.assertRaisesRegex(
            ValueError, "NODE_RECOVERY_SEND_FENCED",
            self.ledger.assert_send_allowed, work_id="work", conversation_key=OLD,
        )

    def test_observation_never_turns_missing_node_into_automatic_replace(self):
        evidence = observe_node({"status": "OK", "current_nodes": {
            "observation": {"state": "FRESH"}, "items": []}}, OLD)
        self.assertEqual("CHECK", evidence["result"])
        self.assertEqual("NODE_NOT_OBSERVED", evidence["reason"])

    def test_observation_uses_existing_connection_and_dom_attention_signals(self):
        disconnected = observe_node(view(disconnected=True), OLD)
        self.assertEqual(("CHECK", "NODE_CONNECTION_DISCONNECTED"),
                         (disconnected["result"], disconnected["reason"]))
        self.assertTrue(disconnected["activity"]["connection"]["disconnected"])

        retry = observe_node(view(attention={
            "kind": "RETRY_REQUIRED", "label": "다시 시도 필요",
        }), OLD)
        self.assertEqual(("CHECK", "NODE_RETRY_REQUIRED"),
                         (retry["result"], retry["reason"]))
        self.assertEqual("RETRY_REQUIRED", retry["activity"]["user_attention"]["kind"])

    def test_recheck_waits_when_existing_activity_evidence_changed(self):
        self.ledger.check(
            work=self.work, case_id="case-progress", task_id="task-progress",
            conversation_key=OLD,
            evidence=observe_node(view(disconnected=True, last_activity_at=100), OLD),
            kind="CHECK",
        )
        changed = self.ledger.check(
            work=self.work, case_id="case-progress", task_id="task-progress",
            conversation_key=OLD,
            evidence=observe_node(view(disconnected=True, last_activity_at=101), OLD),
            kind="RECHECK",
        )
        self.assertTrue(changed["progress_changed"])
        self.assertEqual("RECHECK", changed["next_action"])
        unchanged = self.ledger.check(
            work=self.work, case_id="case-progress", task_id="task-progress",
            conversation_key=OLD,
            evidence=observe_node(view(disconnected=True, last_activity_at=101), OLD),
            kind="RECHECK",
        )
        self.assertTrue(unchanged["unchanged"])
        self.assertEqual("RESTART", unchanged["next_action"])

    def test_check_compares_existing_task_progress_without_new_operation(self):
        first = self.ledger.check(
            work=self.work, case_id="case-task-progress", task_id="task-existing",
            conversation_key=OLD,
            evidence=observe_node(view(disconnected=True), OLD), kind="CHECK",
        )
        self.assertIsNone(first["evidence"]["task_activity"])
        DurableWatchLedger(self.store).prearm_task(
            task_id="task-existing", work_id=self.work.work_id,
            principal_id=self.work.owner_principal_id,
            assignment_epoch=self.work.assignment_epoch,
            instance_id="instance", conversation_key=OLD,
            manager_conversation_key=NEW, manager_instance_id="instance",
            baseline={"responseTurnCount": 0, "generating": False,
                      "responseSha256": "a" * 64, "responseTurnKey": "turn-0",
                      "latestUserTurnKey": "user-0", "latestUserSha256": "b" * 64,
                      "latestUserTextOccurrenceCount": 1},
            registration_receipt="arm",
        )
        second = self.ledger.check(
            work=self.work, case_id="case-task-progress", task_id="task-existing",
            conversation_key=OLD,
            evidence=observe_node(view(disconnected=True), OLD), kind="RECHECK",
        )
        self.assertTrue(second["progress_changed"])
        self.assertEqual("WATCHING", second["evidence"]["task_activity"]["state"])
        self.assertEqual("RECHECK", second["next_action"])


class _Applied:
    def as_dict(self):
        return {"state": "FINISHED", "outcome": "APPLIED", "evidence": {}}


class _Operations:
    capabilities = ("browser",)

    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return _Applied()


class NodeRecoveryPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_then_pause_fences_common_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            store.create_work(Work(
                "work", "test", (root,), frozenset({"browser"}), "bct-mcp-local",
            ))
            ops = _Operations()
            snapshot = {"monitor": {"current_nodes": view()["current_nodes"], "rcc": {"instances": []}}}
            mcp = build_mcp(
                SimpleNamespace(store=store, operations=ops),
                status_provider=lambda: snapshot, compact_catalogue=True,
            )
            _, checked = await mcp.call_tool("bct_check_node", {
                "work_id": "work", "conversation_key": OLD,
                "task_id": "task-1", "case_id": "case-public",
            })
            self.assertEqual("OK", checked["status"])
            _, paused = await mcp.call_tool("bct_pause_node", {
                "work_id": "work", "case_id": "case-public", "reason": "stalled",
            })
            self.assertEqual("PAUSED", paused["pause_node"]["state"])
            _, chain = await mcp.call_tool("bct_task_message", {
                "work_id": "work", "task_id": "task-2", "operation_id": "chain-2",
                "action": "start", "instance_id": "instance", "session_id": "a" * 32,
                "target_tab_id": 13, "target_window_id": 12,
                "target_conversation_key": OLD, "origin_conversation_key": NEW,
                "origin_instance_id": "instance", "instruction": "continue",
                "acceptance": "Return the observed result to the Manager.",
            })
            self.assertEqual("PAUSED", chain["status"], chain)
            self.assertEqual([], ops.calls)


if __name__ == "__main__":
    unittest.main()
