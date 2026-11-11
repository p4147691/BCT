"""Public BCT Loop MCP contract in isolated SQLite, never LIVE."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.models import Work
from bct.core.store import Store
from bct.chain_direction import ChainDirectionLedger
from bct.mcp_server import build_mcp, MCP_PRINCIPAL_ID


class LoopMcpContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"state.sqlite")
        self.store.create_work(Work(
            work_id="loop-mcp-work",request_summary="Loop test",
            roots=(self.tmp.name,),actions=frozenset({"read","browser"}),
            owner_principal_id=MCP_PRINCIPAL_ID,
        ))
        ChainDirectionLedger(self.store).save(
            direction_id="loop-mcp-direction",work_id="loop-mcp-work",
            source_kind="USER",decision="NEW_TASK",
            direction_text="Run the bounded single-node plan",
        )
        self.server=build_mcp(
            SimpleNamespace(store=self.store,
                            operations=SimpleNamespace(capabilities=("read","browser"))),
        )

    async def result(self, action, **args):
        value=await self.server.call_tool("bct_loop_recipe",{
            "action":action,"work_id":"loop-mcp-work",**args,
        })
        return value[1] if isinstance(value,tuple) else (
            getattr(value,"structuredContent",None) or value
        )

    async def test_public_start_preserves_chain_state_and_plan(self):
        response=await self.result(
            "start",direction_id="loop-mcp-direction",
            task_id="loop-mcp-task",owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            plan_text="first verified step",
        )
        self.assertEqual(response["status"],"OK")
        self.assertEqual(response["loop"]["state"],"LOOP_STARTED")
        self.assertEqual(response["plan"]["task_id"],"loop-mcp-task")
        original=ChainDirectionLedger(self.store).get(
            direction_id="loop-mcp-direction"
        )
        self.assertEqual(original["chain_state"],"NOT_PLANNED")
        again=await self.result(
            "start",direction_id="loop-mcp-direction",
            task_id="loop-mcp-task",owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            plan_text="first verified step",
        )
        self.assertEqual(again["status"],"OK")
        self.assertTrue(again["plan"]["duplicate"])

    async def test_public_verified_completion_is_terminal(self):
        from bct.loop_store import LoopStore
        owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        await self.result(
            "start",direction_id="loop-mcp-direction",
            task_id="loop-mcp-task",owner=owner,
            plan_text="first verified step",
        )
        without_proof=await self.result(
            "complete",owner=owner,epoch=1,verified=False,
        )
        self.assertEqual(without_proof["status"],"INVALID_REQUEST")
        ledger=LoopStore(self.store)
        ledger.prepare_operation(work_id="loop-mcp-work",owner=owner,
                                 epoch=1,operation_id="step-1")
        ledger.reconcile(work_id="loop-mcp-work",owner=owner,
                         epoch=1,operation_id="step-1",result="APPLIED")
        ledger.advance(work_id="loop-mcp-work",owner=owner,
                       epoch=1,next_step=1)
        result=await self.result("complete",owner=owner,epoch=1,verified=True)
        self.assertEqual(result["status"],"OK")
        self.assertEqual(result["loop"]["state"],"COMPLETED")
        further=await self.result("claim",owner=owner,epoch=1)
        self.assertEqual(further["status"],"INVALID_REQUEST")

    async def test_public_workless_start_rejected(self):
        result=await self.server.call_tool("bct_loop_recipe",{
            "action":"start","work_id":"",
        })
        value=result[1] if isinstance(result,tuple) else (
            getattr(result,"structuredContent",None) or result
        )
        self.assertEqual(value["status"],"INVALID_REQUEST")


if __name__=="__main__":
    unittest.main()
