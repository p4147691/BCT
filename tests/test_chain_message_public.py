from __future__ import annotations
import unittest
from types import SimpleNamespace
from bct.mcp_server import build_mcp

class Applied:
    def as_dict(self):
        return {"state":"FINISHED","outcome":"APPLIED","evidence":{"command":"tested"}}

class Operations:
    capabilities=("browser",)
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
        self.assertTrue({
            "bct_check_node", "bct_recheck_node", "bct_pause_node",
            "bct_replace_node", "bct_reset_node",
        }.issubset(names))
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
        self.assertIs(True, arm["arguments"]["exclusive_conversation_watch"])
        self.assertEqual(send["arguments"]["tab_id"],12)
    async def test_canonical_target_and_origin_names_start_the_same_recipe(self):
        legacy = self.arguments()
        canonical = {
            key: value for key, value in legacy.items()
            if key not in {
                "worker_tab_id", "worker_window_id", "worker_conversation_key",
                "manager_conversation_key",
            }
        }
        canonical.update({
            "target_tab_id": 12, "target_window_id": 13,
            "target_conversation_key": legacy["worker_conversation_key"],
            "origin_conversation_key": legacy["manager_conversation_key"],
        })
        await self.mcp.call_tool("bct_chain_message", canonical)
        arm, send = self.ops.calls
        self.assertEqual(legacy["worker_conversation_key"], arm["arguments"]["conversation_key"])
        self.assertEqual(legacy["manager_conversation_key"], arm["arguments"]["manager_conversation_key"])
        self.assertEqual(12, send["arguments"]["tab_id"])
    async def test_conflicting_target_aliases_do_not_send(self):
        await self.mcp.call_tool("bct_chain_message", self.arguments(target_tab_id=99))
        self.assertEqual([], self.ops.calls)
    async def test_unsafe_action_does_not_send(self):
        await self.mcp.call_tool("bct_chain_message",self.arguments(action="chain-run"))
        self.assertEqual([],self.ops.calls)

    async def test_standard_send_message_name_uses_existing_relay_contract(self):
        await self.mcp.call_tool("bct_send_message", {
            "work_id": "test-work", "operation_id": "send-message-01",
            "instance_id": "instance-id", "session_id": "a" * 32,
            "tab_id": 12, "window_id": 13,
            "conversation_key": "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12,
            "text": "one exact message",
        })
        self.assertEqual(1, len(self.ops.calls))
        call = self.ops.calls[0]
        self.assertEqual("browser", call["capability"])
        self.assertEqual("send-message", call["arguments"]["command"])
        self.assertEqual("one exact message", call["arguments"]["text"])

    async def test_standard_tab_names_delegate_to_existing_exact_commands(self):
        identity = {
            "work_id": "test-work", "instance_id": "instance-id", "session_id": "a" * 32,
            "tab_id": 12, "window_id": 13,
            "conversation_key": "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12,
        }
        await self.mcp.call_tool("bct_move_tab", {
            **identity, "operation_id": "move-tab-01", "target_window_id": 15, "index": 0,
        })
        await self.mcp.call_tool("bct_close_tab", {
            **identity, "operation_id": "close-tab-01",
        })
        self.assertEqual(["move-tab", "close-conversation-tab"],
                         [call["arguments"]["command"] for call in self.ops.calls])
    async def test_bad_session_does_not_send(self):
        await self.mcp.call_tool("bct_chain_message",self.arguments(session_id="invalid"))
        self.assertEqual([],self.ops.calls)
