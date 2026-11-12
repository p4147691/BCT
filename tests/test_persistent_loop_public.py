"""Public MCP contract for the new persistent Loop entry."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bct.conversation_network import set_membership, upsert_conversation, upsert_project
from bct.core.models import Work
from bct.core.store import Store
from bct.mcp_server import build_mcp
from bct.persistent_loop_runtime import PersistentLoopCoordinator
from bct.send_delayed_message import _rcc_submitted_text_sha256
from test_loop_self_dispatch import snapshot as loop_snapshot


ROOT = Path(__file__).resolve().parents[1]
MANAGER = "11111111-1111-1111-1111-111111111111"
SUPERVISOR = "22222222-2222-2222-2222-222222222222"


class NoEffects:
    capabilities = ("browser", "conversation_network_update")

    def run(self, **kwargs):
        raise AssertionError("state-only public test must not execute capabilities")


class PersistentLoopPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_from_chat_uses_unique_rcc_turn_and_reuses_armed_run(self):
        source = "BCT Control Start this task in LOOP."
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.sqlite")
            store.create_work(Work(
                "loop-public-work", "persistent loop", (),
                frozenset({"browser", "conversation_network_update"}), "bct-mcp-local",
            ))
            # Tool execution can occur between generation signals. The exact
            # RCC turn proof, rather than the sampled BUSY bit, must select A.
            monitor = loop_snapshot(owner=MANAGER, generating=False)
            monitor["current_nodes"]["items"].append({
                "conversation_uuid": SUPERVISOR, "status": "CONFIRMED",
                "generating": False, "roles": ["Loop Supervisor"],
            })
            operations = NoEffects()
            operations._features = {"browser": object()}
            server = build_mcp(SimpleNamespace(store=store, operations=operations),
                               status_provider=lambda: {"monitor": monitor}, compact_catalogue=True)
            arguments = {
                "action": "start", "work_id": "loop-public-work",
                "instruction_text": "Start this task in LOOP.", "direction_text": "Verify results.",
                "overall_plan": "Execute and verify.",
                "completion_conditions": {"result": "Result independently verified."},
            }

            async def configure(coordinator, *, loop_id, **kwargs):
                project = coordinator.commands.status(loop_id=loop_id)["context"]["network_project_id"]
                upsert_project(store, project_id=project, display_name="Test LOOP")
                upsert_conversation(store, conversation_key=MANAGER, display_name="Manager")
                set_membership(store, project_id=project, conversation_key=MANAGER)
                return {"status": "READY"}

            observed = {"ok": True, "conversationKey": MANAGER, "latestUserTurnKey": "turn-1",
                        "latestUserTextOccurrenceCount": 1,
                        "latestUserSha256": _rcc_submitted_text_sha256(source)}
            with patch("bct.send_delayed_message.SendDelayedMessageService.latest",
                       return_value={**observed, "latestUserTextOccurrenceCount": 2}), patch.object(
                           PersistentLoopCoordinator, "configure_topology", autospec=True
                       ) as topology:
                _, rejected = await server.call_tool("bct_loop_recipe", arguments)
                self.assertEqual(rejected["reason"], "LOOP_START_SOURCE_NOT_UNIQUE")
                topology.assert_not_awaited()
            with patch("bct.send_delayed_message.SendDelayedMessageService.latest",
                       return_value=observed), patch.object(
                           PersistentLoopCoordinator, "configure_topology", autospec=True,
                           side_effect=configure,
                       ) as topology:
                _, prepared = await server.call_tool("bct_loop_recipe", {
                    "action": "prepare", "work_id": arguments["work_id"],
                    "instruction_text": "@BCT Control\n" + arguments["instruction_text"],
                })
                self.assertEqual(prepared.get("status"), "PREPARED", prepared)
                self.assertEqual(prepared["effects"], "NONE_READ_ONLY")
                self.assertEqual(prepared["manager"]["conversation_key"], MANAGER)
                topology.assert_not_awaited()
                start = {**arguments, "entry_context_id": prepared["entry_context_id"],
                         "instruction_text": prepared["instruction_text"]}
                with patch("bct.send_delayed_message.SendDelayedMessageService.latest",
                           return_value={**observed, "latestUserTurnKey": "another-turn"}):
                    _, stale = await server.call_tool("bct_loop_recipe", start)
                self.assertEqual(stale["reason"], "LOOP_PREPARED_SOURCE_CHANGED")
                topology.assert_not_awaited()
                _, started = await server.call_tool("bct_loop_recipe", start)
                self.assertEqual(started.get("status"), "OK", started)
                self.assertEqual(started["objective"]["manager_conversation_key"], MANAGER)
                self.assertEqual(started["objective"]["supervisor_conversation_key"], SUPERVISOR)
                self.assertEqual(started["objective"]["instruction_text"], source)
                self.assertEqual(started["turn"]["state"], "PREPARING")
                self.assertIsNone(started["turn"]["send_operation_id"])
                _, retry = await server.call_tool("bct_loop_recipe", start)
                self.assertEqual(retry["turn"]["watch_operation_id"],
                                 started["turn"]["watch_operation_id"])
                topology.assert_awaited_once()

    async def test_public_entry_outlines_starts_and_reads_durable_context(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.sqlite")
            store.create_work(Work(
                "loop-public-work", "persistent loop", (),
                frozenset({"browser", "conversation_network_update"}), "bct-mcp-local",
            ))
            snapshot = {"monitor": {"current_nodes": {
                "observed_at": 1, "observation": {"state": "FRESH"},
                "items": [
                    {"conversation_uuid": MANAGER, "status": "CONFIRMED",
                     "generating": False, "tab_id": 1, "window_id": 1},
                    {"conversation_uuid": SUPERVISOR, "status": "CONFIRMED",
                     "generating": False, "tab_id": 2, "window_id": 1},
                ],
            }, "rcc": {"instances": []}}}
            server = build_mcp(SimpleNamespace(store=store, operations=NoEffects()),
                               status_provider=lambda: snapshot, compact_catalogue=True)
            tools = await server.list_tools()
            public = next(tool for tool in tools if tool.name == "bct_loop_recipe")
            self.assertNotIn("bct_persistent_loop_recipe", {tool.name for tool in tools})
            self.assertEqual(public.title, "LOOP")
            self.assertIn("supervisor_create_operation_id",
                          public.inputSchema["properties"])
            self.assertIn("prepare_supervisor", public.description)
            self.assertIn("official BCT single persistent Loop Recipe", public.description)
            _, outline = await server.call_tool("bct_loop_recipe", {"action": "outline"})
            self.assertEqual(outline["status"], "OK")
            _, started = await server.call_tool("bct_loop_recipe", {
                "action": "start", "work_id": "loop-public-work", "loop_id": "loop-public-1",
                "instruction_text": "Finish this goal.",
                "direction_text": "Continue until completion evidence is verified.",
                "manager_conversation_key": MANAGER,
                "supervisor_conversation_key": SUPERVISOR,
                "network_project_id": "loop-public-network-1",
                "task_id": "loop-public-task",
                "overall_plan": "Execute and verify.",
                "completion_conditions": {"result": "Result independently verified."},
            })
            self.assertEqual(started["status"], "OK")
            self.assertEqual(started["objective"]["supervisor_conversation_key"], SUPERVISOR)
            _, status = await server.call_tool("bct_loop_recipe", {
                "action": "status", "loop_id": "loop-public-1",
            })
            self.assertEqual(status["run"]["current_block_id"], "topology")
            self.assertEqual(status["context"]["network_project_id"], "loop-public-network-1")
            self.assertEqual(status["objective"]["overall_plan"], "Execute and verify.")
            _, rejected = await server.call_tool("bct_loop_recipe", {
                "action": "transition", "loop_id": "loop-public-1",
                "block_id": "assess", "link": "complete",
            })
            self.assertEqual(rejected["reason"], "LOOP_USE_ARM_SAVE_PLAN_AND_DECIDE")

    def test_mcp_entry_is_only_a_forwarder(self):
        tree = ast.parse((ROOT / "src/bct/mcp_server.py").read_text(encoding="utf-8"))
        entry = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "bct_loop_recipe")
        self.assertEqual(len(entry.body), 1)
        call = entry.body[0].value.value
        self.assertEqual(ast.unparse(call.func), "persistent_loop_command")
        self.assertEqual(ast.unparse(call.args[0]), "loop_recipe_runtime")
        self.assertEqual(ast.unparse(call.keywords[0].value), "locals()")
