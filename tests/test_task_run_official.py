from __future__ import annotations
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from bct.mcp_server import build_mcp

class Result:
    def as_dict(self):
        return {"state":"FINISHED","outcome":"APPLIED"}

class Tasks:
    capabilities=("orchestrate",)
    def __init__(self): self.calls=[]
    def run(self,**kwargs):
        self.calls.append(kwargs)
        return Result()

class TaskRunOfficialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.operations=Tasks()
        self.mcp=build_mcp(SimpleNamespace(operations=self.operations),compact_catalogue=True)
    async def test_officially_exposed_without_chain_run(self):
        names={t.name for t in await self.mcp.list_tools()}
        self.assertIn("bct_task_run",names)
        self.assertNotIn("bct_chain_run",names)
    async def test_dispatch_uses_existing_authorized_engine(self):
        with patch("bct.mcp_server.launch_background_operation") as launch:
            launch.return_value=Result()
            response=await self.mcp.call_tool("bct_task_run",{
                "work_id":"W","operation_id":"O",
                "arguments":{"session_id":"S","assignment_id":"A","instruction":"do work",
                             "manager_epoch":1,"worker_node_id":"B","attachment_id":"ATT",
                             "acceptance":"complete"}
            })
        self.assertIsInstance(response,tuple)
        self.assertEqual(launch.call_count,1)
        kwargs=launch.call_args.kwargs
        self.assertEqual(kwargs["capability"],"orchestrate")
        self.assertEqual(kwargs["operation_id"],"O")
        self.assertEqual(kwargs["arguments"]["operation"],"dispatch")
        self.assertEqual(kwargs["arguments"]["session_id"],"S")
    async def test_rejects_other_operations_without_effect(self):
        for op in ("chain-run","session-start","node-sync",""):
            result=await self.mcp.call_tool("bct_task_run",{
                "work_id":"W","operation_id":"O",
                "arguments":{"operation":op}
            })
            self.assertIsInstance(result,tuple)
        self.assertEqual([],self.operations.calls)
