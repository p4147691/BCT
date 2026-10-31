from __future__ import annotations
import unittest
from types import SimpleNamespace
from bct.mcp_server import build_mcp

class Applied:
    def as_dict(self):
        return {"state":"FINISHED","outcome":"APPLIED","evidence":{"command":"tested"}}

class Operations:
    capabilities=("relay_browser",)
    def __init__(self):self.calls=[]
    def run(self,**kwargs):
        self.calls.append(kwargs)
        return Applied()

class ChainMessagePublicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ops=Operations()
        self.mcp=build_mcp(SimpleNamespace(operations=self.ops),compact_catalogue=True)
    def arguments(self,**other):
        data={"work_id":"test-work","task_id":"test-task","operation_id":"e2e-test-01",
              "action":"start","instance_id":"instance-id","session_id":"a"*32,
              "worker_tab_id":12,"worker_window_id":13,
              "worker_conversation_key":"b"*8+"-"+"b"*4+"-"+"b"*4+"-"+"b"*4+"-"+"b"*12,
              "manager_conversation_key":"c"*8+"-"+"c"*4+"-"+"c"*4+"-"+"c"*4+"-"+"c"*12,
              "instruction":"Please complete a normal test and return NEXT TASK - MANAGER."}
        data.update(other);return data
    async def test_exposed_without_chain_run(self):
        names={x.name for x in await self.mcp.list_tools()}
        self.assertIn("bct_chain_message",names)
        self.assertNotIn("bct_chain_run",names)
    async def test_prearms_before_single_send_with_exact_identity(self):
        await self.mcp.call_tool("bct_chain_message",self.arguments())
        self.assertEqual(2,len(self.ops.calls))
        arm,send=self.ops.calls
        self.assertEqual(["e2e-test-01-arm","e2e-test-01-send"],
                         [arm["operation_id"],send["operation_id"]])
        self.assertEqual("delayed-send-message",arm["arguments"]["command"])
        self.assertEqual("send-message",send["arguments"]["command"])
        self.assertEqual(arm["arguments"]["planned_send_operation_id"],send["operation_id"])
        self.assertEqual(arm["arguments"]["planned_send_text"],send["arguments"]["text"])
        self.assertEqual(send["arguments"]["tab_id"],12)
    async def test_unsafe_action_does_not_send(self):
        await self.mcp.call_tool("bct_chain_message",self.arguments(action="chain-run"))
        self.assertEqual([],self.ops.calls)
    async def test_bad_session_does_not_send(self):
        await self.mcp.call_tool("bct_chain_message",self.arguments(session_id="invalid"))
        self.assertEqual([],self.ops.calls)
