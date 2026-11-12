"""Public MCP contract for the new persistent Loop entry."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from bct.core.models import Work
from bct.core.store import Store
from bct.mcp_server import build_mcp


ROOT = Path(__file__).resolve().parents[1]
MANAGER = "11111111-1111-1111-1111-111111111111"
SUPERVISOR = "22222222-2222-2222-2222-222222222222"


class NoEffects:
    capabilities = ("browser", "conversation_network_update")

    def run(self, **kwargs):
        raise AssertionError("state-only public test must not execute capabilities")


class PersistentLoopPublicTests(unittest.IsolatedAsyncioTestCase):
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
            })
            self.assertEqual(started["status"], "OK")
            self.assertEqual(started["context"]["supervisor_conversation_key"], SUPERVISOR)
            _, status = await server.call_tool("bct_loop_recipe", {
                "action": "status", "loop_id": "loop-public-1",
            })
            self.assertEqual(status["run"]["current_block_id"], "resume")
            self.assertEqual(status["context"]["network_project_id"], "loop-public-network-1")

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
