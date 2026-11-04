from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.models import Work
from bct.core.store import Store
from bct.delayed_send_message import DurableWatchLedger, DelayedSendMessageRunner, Watch
from bct.mcp_server import build_mcp
from bct.task_message import prepare_task_message_instruction


WORKER = "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12
MANAGER = "c" * 8 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 12


class NoEffects:
    capabilities = ("browser",)

    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("preflight must not execute an effect")


class TaskMessageTests(unittest.IsolatedAsyncioTestCase):
    def test_instruction_is_bounded_but_does_not_choose_worker_route(self):
        result = prepare_task_message_instruction(
            "Fix one focused defect.", acceptance="Focused test passes.",
            bb_rule="Continue one safe check.",
            manager_return_rule="Return on complete, risk, or blockage.",
            max_rounds=3,
        )
        self.assertIn("최대 3회", result["instruction"])
        self.assertNotIn("NEXT TASK", result["instruction"])
        self.assertEqual(3, result["max_rounds"])

    def test_zero_rounds_means_progress_based_continuation(self):
        result = prepare_task_message_instruction(
            "Fix one focused defect.", acceptance="Focused test passes.",
            bb_rule="Continue one safe check.",
            manager_return_rule="Return on complete, risk, or blockage.",
            max_rounds=0,
        )
        self.assertIn("고정 횟수로 종료하지 않습니다", result["instruction"])
        self.assertEqual(0, result["max_rounds"])

    async def test_public_recipe_preflight_composes_chain_contract_without_effect(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            store.create_work(Work(
                "task-message-work", "fixture", (root,), frozenset({"browser"}),
                "bct-mcp-local", 1,
            ))
            effects = NoEffects()
            mcp = build_mcp(
                SimpleNamespace(store=store, operations=effects),
                compact_catalogue=True,
            )
            names = {tool.name for tool in await mcp.list_tools()}
            self.assertIn("bct_task_message", names)
            _, result = await mcp.call_tool("bct_task_message", {
                "work_id": "task-message-work", "task_id": "bounded-task",
                "operation_id": "bounded-operation", "action": "preflight",
                "instance_id": "instance", "session_id": "a" * 32,
                "target_tab_id": 10, "target_window_id": 20,
                "target_conversation_key": WORKER,
                "origin_conversation_key": MANAGER,
                "instruction": "Implement one focused repair.",
                "acceptance": "The focused regression test passes.",
                "max_rounds": 4,
            })
            self.assertEqual("READY", result["status"])
            self.assertEqual("Task Message", result["recipe"])
            self.assertEqual(4, result["max_rounds"])
            self.assertEqual("explicit-next-task-v1", result["continuation_output_contract"])
            self.assertEqual([], effects.calls)

    async def test_catalogue_keeps_task_message_separate_from_user_direction(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            store.create_work(Work(
                "task-message-catalogue", "fixture", (root,), frozenset({"browser"}),
                "bct-mcp-local", 1,
            ))
            mcp = build_mcp(SimpleNamespace(store=store, operations=NoEffects()), compact_catalogue=True)
            tools = {tool.name: tool for tool in await mcp.list_tools()}
            self.assertIn("Optional technical envelope", tools["bct_task_message"].description)
            self.assertIn("does not replace A's user direction", tools["bct_task_message"].description)

    async def test_public_recipe_defaults_to_progress_based_continuation(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            store.create_work(Work(
                "task-message-default", "fixture", (root,), frozenset({"browser"}),
                "bct-mcp-local", 1,
            ))
            effects = NoEffects()
            mcp = build_mcp(
                SimpleNamespace(store=store, operations=effects),
                compact_catalogue=True,
            )
            _, result = await mcp.call_tool("bct_task_message", {
                "work_id": "task-message-default", "task_id": "progress-task",
                "operation_id": "progress-operation", "action": "preflight",
                "instance_id": "instance", "session_id": "a" * 32,
                "target_tab_id": 10, "target_window_id": 20,
                "target_conversation_key": WORKER,
                "origin_conversation_key": MANAGER,
                "instruction": "Implement one focused repair.",
                "acceptance": "The focused regression test passes.",
            })
            self.assertEqual("READY", result["status"])
            self.assertEqual(0, result["max_rounds"])

    def test_worker_self_at_limit_returns_to_manager_and_preserves_requested_route(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = DurableWatchLedger(store)
            ledger.prearm_task(
                task_id="bounded-task", work_id="work", principal_id="owner",
                assignment_epoch=1, instance_id="worker-instance",
                conversation_key="worker-uuid",
                manager_conversation_key="manager-uuid",
                manager_instance_id="manager-instance",
                baseline={
                    "responseTurnCount": 1, "generating": False,
                    "responseTurnKey": "old", "responseSha256": "a" * 64,
                },
                registration_receipt="arm-1",
                planned_send_operation_id="send-1",
                planned_send_text="Do bounded work.", max_generations=1,
            )
            watch = Watch(
                "bounded-task", 1, "worker-uuid", "task:bounded-task:1", "arm-1",
            )
            sent = []
            result = DelayedSendMessageRunner(
                ledger,
                read_response=lambda _: {
                    "conversation_key": "worker-uuid",
                    "response_turn_id": "task:bounded-task:1",
                    "response_text": "NEXT TASK — SELF: continue another check.",
                    "response_complete": True, "input_ready": True,
                    "response_turn_key": "reply-1", "response_sha256": "b" * 64,
                },
                send_message=lambda target, body, key: (
                    sent.append((target, body, key)) or "receipt"
                ),
            ).poll_once(watch, manager_conversation_key="manager-uuid")
            self.assertEqual("RETURNED_TO_MANAGER", result.status)
            self.assertEqual("manager-uuid", sent[0][0])
            self.assertIn("BB 반복 한도", sent[0][1])
            saved = json.loads(ledger.get("bounded-task", 1)["context_json"])
            self.assertEqual("SELF", saved["requested_continuation_route"])
            self.assertEqual("MANAGER", saved["effective_continuation_route"])
            self.assertEqual("BB_LIMIT_REACHED", saved["continuation_route_override_reason"])
            context = ledger.read_execution_context(task_id="bounded-task", generation=1)
            self.assertEqual("MANAGER", context["decision"]["route"])

    def test_next_bb_watch_atomically_carries_the_core_limit(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = DurableWatchLedger(store)
            ledger.prearm_task(
                task_id="bounded-task", work_id="work", principal_id="owner",
                assignment_epoch=1, instance_id="worker-instance",
                conversation_key="worker-uuid",
                manager_conversation_key="manager-uuid",
                manager_instance_id="manager-instance",
                baseline={
                    "responseTurnCount": 1, "generating": False,
                    "responseTurnKey": "old", "responseSha256": "a" * 64,
                },
                registration_receipt="arm-1",
                planned_send_operation_id="send-1",
                planned_send_text="Do bounded work.", max_generations=2,
            )
            parent = Watch(
                "bounded-task", 1, "worker-uuid", "task:bounded-task:1", "arm-1",
            )
            next_watch = Watch(
                "bounded-task", 2, "worker-uuid", "task:bounded-task:2", "arm-2",
            )

            self.assertTrue(ledger.reserve_next(parent, next_watch))

            saved = ledger.get("bounded-task", 2)
            self.assertEqual("RESERVED", saved["state"])
            self.assertEqual(
                {"max_generations": 2, "recipe": "task-message-v1"},
                json.loads(saved["context_json"]),
            )


if __name__ == "__main__":
    unittest.main()
