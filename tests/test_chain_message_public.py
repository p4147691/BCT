from __future__ import annotations
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from bct.core.models import Work
from bct.core.store import Store
from bct.delayed_send_message import DurableWatchLedger, DelayedSendMessageRunner, Watch
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
        tools={x.name: x for x in await self.mcp.list_tools()}
        names=set(tools)
        self.assertIn("bct_chain_message",names)
        self.assertIn("DEFAULT ENTRY", tools["bct_chain_message"].description)
        self.assertIn("EXPLICIT REQUEST ONLY", tools["bct_send_message"].description)
        self.assertTrue({
            "bct_check_node", "bct_recheck_node", "bct_pause_node",
            "bct_replace_node", "bct_reset_node",
        }.issubset(names))
        self.assertNotIn("bct_chain_run",names)

    async def test_capabilities_publish_the_default_message_entry_rule(self):
        _, capabilities = await self.mcp.call_tool("bct_capabilities", {})
        self.assertEqual("CHAIN_MESSAGE", capabilities["message_entry_policy"]["default_entry"])
        self.assertEqual("bct_chain_message", capabilities["message_entry_policy"]["ordinary_request_tool"])
        self.assertEqual(
            ["bct_task_message", "bct_send_message"],
            capabilities["message_entry_policy"]["explicit_only_tools"],
        )
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
        self.assertEqual(0, arm["arguments"]["max_generations"])
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

    async def test_status_exposes_terminal_manager_review_without_sending(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work(
                "test-work", "fixture", (), frozenset(), "bct-mcp-local", 1,
            ))
            ledger = DurableWatchLedger(store)
            ledger.prearm_task(
                task_id="test-task", work_id=work.work_id,
                principal_id=work.owner_principal_id,
                assignment_epoch=work.assignment_epoch,
                instance_id="worker-instance", conversation_key="worker-uuid",
                manager_conversation_key="manager-uuid",
                manager_instance_id="manager-instance",
                baseline={
                    "responseTurnCount": 1, "generating": False,
                    "responseTurnKey": "old", "responseSha256": "b" * 64,
                },
                registration_receipt="arm-1",
                planned_send_operation_id="send-1",
                planned_send_text="Complete the task and report the next route.",
            )
            watch = Watch(
                "test-task", 1, "worker-uuid", "task:test-task:1", "arm-1",
            )
            result = DelayedSendMessageRunner(
                ledger,
                read_response=lambda _watch: {
                    "conversation_key": "worker-uuid",
                    "response_turn_id": "task:test-task:1",
                    "response_turn_key": "assistant-2",
                    "response_sha256": "c" * 64,
                    "response_text": "Finished without a route marker.",
                    "response_complete": True, "input_ready": True,
                },
                send_message=lambda *_args: self.fail("must not send"),
            ).poll_once(watch, manager_conversation_key="manager-uuid")
            self.assertEqual("MANAGER_DECISION_REQUIRED", result.status)
            mcp = build_mcp(
                SimpleNamespace(operations=Operations(), store=store),
                compact_catalogue=True,
            )
            _, status = await mcp.call_tool("bct_chain_message", {
                "work_id": "test-work", "task_id": "test-task",
                "operation_id": "status-01", "action": "status",
                "generation": 1,
            })
            self.assertEqual("MANAGER_DECISION_REQUIRED", status["status"])
            self.assertEqual(
                "NEXT_INSTRUCTION_UNAVAILABLE", status["terminal_reason"],
            )
            self.assertEqual(
                "REVIEW_RESPONSE_AND_AUTHOR_NEXT_MESSAGE",
                status["manager_action"],
            )

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
