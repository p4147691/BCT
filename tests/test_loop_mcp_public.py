"""Official LOOP MCP name and retained-record boundary."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore
from bct.mcp_server import MCP_PRINCIPAL_ID, build_mcp


class NoEffects:
    capabilities = ("browser", "conversation_network_update")

    def run(self, **kwargs):
        raise AssertionError("catalogue and outline checks must not execute effects")


class LoopMcpContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        self.store.create_work(Work(
            work_id="loop-mcp-work", request_summary="LOOP name replacement test",
            roots=(self.tmp.name,),
            actions=frozenset({"browser", "conversation_network_update"}),
            owner_principal_id=MCP_PRINCIPAL_ID,
        ))
        self.server = build_mcp(SimpleNamespace(store=self.store, operations=NoEffects()))

    async def test_one_official_loop_tool_replaces_both_old_public_entries(self):
        tools = await self.server.list_tools()
        loops = [tool for tool in tools if "loop_recipe" in tool.name]
        self.assertEqual(["bct_loop_recipe"], [tool.name for tool in loops])
        self.assertEqual("LOOP", loops[0].title)
        self.assertIn("official BCT single persistent Loop Recipe", loops[0].description)

        _, outline = await self.server.call_tool("bct_loop_recipe", {"action": "outline"})
        self.assertEqual("OK", outline["status"])
        self.assertEqual("NONE_READ_ONLY", outline["effects"])

    async def test_historical_loop_record_is_preserved_but_not_the_public_contract(self):
        historical = LoopStore(self.store).start(
            work_id="loop-mcp-work", direction_id="historical-direction",
            task_id="historical-task", owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            plan_text="historical plan",
        )
        _, outline = await self.server.call_tool("bct_loop_recipe", {"action": "outline"})
        self.assertEqual("OK", outline["status"])
        self.assertEqual(historical, LoopStore(self.store).get("loop-mcp-work"))

        # The former persistent name and historical action schema are not a
        # second advertised tool. The durable record remains untouched.
        names = {tool.name for tool in await self.server.list_tools()}
        self.assertNotIn("bct_persistent_loop_recipe", names)
        official = next(tool for tool in await self.server.list_tools()
                        if tool.name == "bct_loop_recipe")
        self.assertNotIn("owner", official.inputSchema["properties"])


if __name__ == "__main__":
    unittest.main()
