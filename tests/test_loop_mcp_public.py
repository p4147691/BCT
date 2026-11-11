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
    async def test_pull_requester_and_new_node_policy_public_contract(self):
        # Historical record fixture: public start is intentionally disabled.
        from bct.loop_store import LoopStore
        from bct.loop_result import LoopResultLedger
        LoopStore(self.store).start(work_id="loop-mcp-work",direction_id="loop-mcp-direction",
            task_id="loop-mcp-task",owner="node-a",plan_text="plan",allow_new_nodes=False)
        LoopResultLedger(self.store).configure(work_id="loop-mcp-work",owner="node-a",requester_ref="dot-origin:42")
        report = (await self.result("status"))["result_report"]
        self.assertEqual(report["requester_ref"], "dot-origin:42")
        self.assertIsNone(report["conversation_key"])
        self.assertEqual(report["state"], "WAITING_ACCEPTANCE")
        changed = await self.result("configure_recovery", owner="node-a", epoch=1, allow_new_nodes=True)
        self.assertEqual(changed["loop"]["allow_new_nodes"], 1)
        blocked = await self.result("configure_requester", owner="node-a", requester_ref="different")
        self.assertEqual(blocked["reason"], "LOOP_REQUESTER_BINDING_CONFLICT")

    async def test_start_rejects_self_requester_before_creating_loop(self):
        from test_loop_self_dispatch import OWNER
        result = await self.result("start",direction_id="loop-mcp-direction",task_id="loop-mcp-task",
            owner=OWNER,plan_text="plan",requester_ref="origin",requester_conversation_key=OWNER)
        self.assertEqual(result["reason"], "LOOP_NEW_START_DISABLED_CHAIN_RESTORED")
        self.assertIsNone((await self.result("status"))["loop"])

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

    async def test_public_start_is_blocked_before_any_partial_record(self):
        before=ChainDirectionLedger(self.store).get(direction_id="loop-mcp-direction")
        for _ in range(2):
            response=await self.result("start",direction_id="loop-mcp-direction",task_id="loop-mcp-task",
                owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",plan_text="plan")
            self.assertEqual(response["reason"],"LOOP_NEW_START_DISABLED_CHAIN_RESTORED")
        self.assertEqual(ChainDirectionLedger(self.store).get(direction_id="loop-mcp-direction"),before)
        with self.store._readonly() as db:
            for name in ("loop_recipe_runs","chain_execution_plans","loop_review_handoffs","loop_result_reports"):
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(name,)).fetchone():
                    self.assertEqual(db.execute("SELECT count(*) FROM "+name).fetchone()[0],0)

    async def test_disabled_start_preserves_existing_unknown_record(self):
        from bct.loop_store import LoopStore
        ledger=LoopStore(self.store)
        owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ledger.start(work_id="loop-mcp-work",direction_id="loop-mcp-direction",
                     task_id="old-task",owner=owner,plan_text="historical plan")
        ledger.prepare_operation(work_id="loop-mcp-work",owner=owner,epoch=1,operation_id="original-unknown")
        ledger.reconcile(work_id="loop-mcp-work",owner=owner,epoch=1,operation_id="original-unknown",result="UNKNOWN")
        before=ledger.get("loop-mcp-work")
        result=await self.result("start",direction_id="new-direction",task_id="replacement",owner=owner,
            plan_text="must not be saved",direction_text="must not be saved")
        self.assertEqual(result["reason"],"LOOP_NEW_START_DISABLED_CHAIN_RESTORED")
        self.assertEqual(ledger.get("loop-mcp-work"),before)
        self.assertIsNone(ChainDirectionLedger(self.store).get(direction_id="new-direction"))
        self.assertEqual((await self.result("status"))["loop"],before)

    async def test_public_verified_completion_is_terminal(self):
        from bct.loop_store import LoopStore
        owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        LoopStore(self.store).start(work_id="loop-mcp-work",direction_id="loop-mcp-direction",
            task_id="loop-mcp-task",owner=owner,plan_text="historical plan")
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

    async def test_busy_current_owner_renews_expired_lease_without_send(self):
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER, production_snapshot
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        self.server = build_mcp(
            SimpleNamespace(store=self.store,
                            operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=lambda: {"monitor": production_snapshot(generating=True)},
        )
        result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["status"], "OK", result)
        self.assertEqual(result["loop"]["epoch"], 2)
        prepared = await self.result("prepare_operation", owner=OWNER, epoch=2,
                                     operation_id="original-receipt")
        self.assertEqual(prepared["status"], "OK", prepared)
        stale = await self.result("claim", owner=OWNER, epoch=1)
        self.assertNotEqual(stale["status"], "OK")
        self.assertEqual(ledger.get("loop-mcp-work")["operation_id"], "original-receipt")

    async def test_current_owner_reobserves_stale_then_busy_without_sending(self):
        from unittest.mock import AsyncMock, patch
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER, production_snapshot
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        snapshots = iter([{"monitor": None}, {"monitor": None},
                          {"monitor": production_snapshot(generating=True)}])
        self.server = build_mcp(
            SimpleNamespace(store=self.store, operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=lambda: next(snapshots))
        with patch("bct.mcp_server.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["status"], "OK", result)
        self.assertEqual(result["loop"]["epoch"], 2)
        self.assertEqual(sleep.await_count, 2)
        self.assertIsNone(result["loop"]["operation_id"])

    async def test_reobservation_preserves_unknown_original_operation(self):
        from unittest.mock import AsyncMock, patch
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER, production_snapshot
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        ledger.prepare_operation(work_id="loop-mcp-work", owner=OWNER,
                                 epoch=1, operation_id="original-unknown", now=101)
        ledger.reconcile(work_id="loop-mcp-work", owner=OWNER, epoch=1,
                         operation_id="original-unknown", result="UNKNOWN", now=102)
        snapshots = iter([{"monitor": None}, {"monitor": production_snapshot(generating=True)}])
        self.server = build_mcp(
            SimpleNamespace(store=self.store, operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=lambda: next(snapshots))
        with patch("bct.mcp_server.asyncio.sleep", new_callable=AsyncMock):
            result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["status"], "OK", result)
        self.assertEqual(result["loop"]["operation_id"], "original-unknown")
        self.assertEqual(result["loop"]["operation_state"], "UNKNOWN")
        self.assertEqual(result["loop"]["next_step"], 0)

    async def test_permanently_stale_owner_is_bounded_and_unchanged(self):
        from unittest.mock import AsyncMock, patch
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER
        ledger = LoopStore(self.store)
        before = ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                              task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        observations = []
        def stale():
            observations.append(1)
            return {"monitor": None}
        self.server = build_mcp(
            SimpleNamespace(store=self.store, operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=stale)
        with patch("bct.mcp_server.asyncio.sleep", new_callable=AsyncMock):
            result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["reason"], "LOOP_NODE_OBSERVATION_STALE")
        self.assertEqual(len(observations), 5)
        self.assertEqual(ledger.get("loop-mcp-work"), before)

    async def test_stale_successor_observation_is_not_retried(self):
        from unittest.mock import AsyncMock, patch
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        self.server = build_mcp(
            SimpleNamespace(store=self.store, operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=lambda: {"monitor": None})
        with patch("bct.mcp_server.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await self.result("claim", owner="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", epoch=1)
        self.assertEqual(result["reason"], "LOOP_NODE_OBSERVATION_STALE")
        sleep.assert_not_awaited()
        self.assertEqual(ledger.get("loop-mcp-work")["owner"], OWNER)

    async def test_owner_epoch_change_during_observation_retry_is_fenced(self):
        from unittest.mock import AsyncMock, patch
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        successor = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        observations = []
        def stale_after_takeover():
            observations.append(1)
            ledger.claim(work_id="loop-mcp-work", owner=successor, epoch=1)
            return {"monitor": None}
        self.server = build_mcp(
            SimpleNamespace(store=self.store, operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=stale_after_takeover)
        with patch("bct.mcp_server.asyncio.sleep", new_callable=AsyncMock):
            result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["reason"], "LOOP_FENCED")
        self.assertEqual(len(observations), 1)
        self.assertEqual(ledger.get("loop-mcp-work")["owner"], successor)

    async def test_busy_successor_and_disconnected_owner_cannot_claim(self):
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER, production_snapshot
        other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        for candidate, view in (
            (other, production_snapshot(owner=other, generating=True)),
            (OWNER, production_snapshot(generating=True, disconnected=True)),
            (OWNER, {"monitor": None}),
        ):
            self.server = build_mcp(
                SimpleNamespace(store=self.store,
                                operations=SimpleNamespace(capabilities=("read", "browser"))),
                status_provider=lambda: view,
            )
            result = await self.result("claim", owner=candidate, epoch=1)
            self.assertNotEqual(result["status"], "OK", result)
            self.assertEqual(ledger.get("loop-mcp-work")["epoch"], 1)

    async def test_busy_owner_claim_is_fenced_by_concurrent_takeover(self):
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER, production_snapshot
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        successor = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        def observation_after_takeover():
            ledger.claim(work_id="loop-mcp-work", owner=successor, epoch=1)
            return {"monitor": production_snapshot(generating=True)}
        self.server = build_mcp(
            SimpleNamespace(store=self.store,
                            operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=observation_after_takeover,
        )
        result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["reason"], "LOOP_FENCED")
        self.assertEqual(ledger.get("loop-mcp-work")["owner"], successor)

    async def test_busy_owner_lease_fix_cannot_reopen_review_pending_loop(self):
        from bct.loop_store import LoopStore
        from test_loop_self_dispatch import OWNER, production_snapshot
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_runs SET state='REVIEW_PENDING' WHERE work_id='loop-mcp-work'")
        self.server = build_mcp(
            SimpleNamespace(store=self.store,
                            operations=SimpleNamespace(capabilities=("read", "browser"))),
            status_provider=lambda: {"monitor": production_snapshot(generating=True)},
        )
        result = await self.result("claim", owner=OWNER, epoch=1)
        self.assertEqual(result["reason"], "LOOP_REVIEW_PENDING", result)
        self.assertEqual(ledger.get("loop-mcp-work")["epoch"], 1)
        self.assertEqual(ledger.get("loop-mcp-work")["state"], "REVIEW_PENDING")

    def expired_completed_cursor(self, snapshot_provider):
        from bct.loop_store import LoopStore
        from bct.loop_supervisor_handoff import LoopReviewLedger
        from test_loop_supervisor_handoff import OWNER, SUPERVISOR, topology
        from unittest.mock import patch
        ledger = LoopStore(self.store)
        ledger.start(work_id="loop-mcp-work", direction_id="loop-mcp-direction",
                     task_id="loop-mcp-task", owner=OWNER, plan_text="plan", now=100)
        ledger.prepare_operation(work_id="loop-mcp-work", owner=OWNER, epoch=1, operation_id="read", now=101)
        ledger.reconcile(work_id="loop-mcp-work", owner=OWNER, epoch=1, operation_id="read", result="APPLIED", now=102)
        ledger.advance(work_id="loop-mcp-work", owner=OWNER, epoch=1, next_step=1, now=103)
        routes = topology()
        with patch("bct.loop_supervisor_handoff.resolve_direction_target", side_effect=lambda **kw: routes[kw["conversation_key"]]):
            LoopReviewLedger(self.store).configure(work_id="loop-mcp-work", owner=OWNER,
                supervisor=SUPERVISOR, instruction="Independent review", snapshot={})
        self.server = build_mcp(SimpleNamespace(store=self.store,
            operations=SimpleNamespace(capabilities=("read", "browser"))), status_provider=snapshot_provider)
        return ledger

    async def test_complete_renews_expired_busy_owner_then_requests_review(self):
        from test_loop_self_dispatch import OWNER, production_snapshot
        ledger = self.expired_completed_cursor(lambda: {"monitor": production_snapshot(generating=True)})
        result = await self.result("complete", owner=OWNER, epoch=1, verified=True,
            candidate_sha="a" * 40, evidence_text="Original applied receipts")
        self.assertEqual(result["status"], "REVIEW_PENDING", result)
        self.assertEqual(result["review"]["epoch"], 2)
        self.assertEqual(ledger.get("loop-mcp-work")["state"], "REVIEW_PENDING")
        self.assertEqual(ledger.get("loop-mcp-work")["operation_id"], "read")

    async def test_complete_stale_observation_does_not_renew_or_send(self):
        from test_loop_self_dispatch import OWNER
        from unittest.mock import AsyncMock, patch
        ledger = self.expired_completed_cursor(lambda: {"monitor": None})
        before = ledger.get("loop-mcp-work")
        with patch("bct.mcp_server.asyncio.sleep", new_callable=AsyncMock):
            result = await self.result("complete", owner=OWNER, epoch=1, verified=True,
                candidate_sha="a" * 40, evidence_text="Original applied receipts")
        self.assertEqual(result["reason"], "LOOP_NODE_OBSERVATION_STALE")
        self.assertEqual(ledger.get("loop-mcp-work"), before)

    async def test_complete_renewal_cannot_hide_unknown_or_change_owner_epoch(self):
        from test_loop_self_dispatch import OWNER, production_snapshot
        from unittest.mock import Mock
        observation = Mock(return_value={"monitor": production_snapshot(generating=True)})
        ledger = self.expired_completed_cursor(observation)
        for owner, epoch, state in ((OWNER, 1, "UNKNOWN"), (OWNER, 9, None),
                                   ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 1, None)):
            with self.store.transaction() as db:
                db.execute("UPDATE loop_recipe_runs SET operation_state=? WHERE work_id='loop-mcp-work'", (state,))
            before = ledger.get("loop-mcp-work")
            result = await self.result("complete", owner=owner, epoch=epoch, verified=True,
                candidate_sha="a" * 40, evidence_text="Original applied receipts")
            self.assertEqual(result["status"], "INVALID_REQUEST")
            self.assertEqual(ledger.get("loop-mcp-work"), before)
        observation.assert_not_called()

    async def test_public_workless_start_rejected(self):
        result=await self.server.call_tool("bct_loop_recipe",{
            "action":"start","work_id":"",
        })
        value=result[1] if isinstance(result,tuple) else (
            getattr(result,"structuredContent",None) or result
        )
        self.assertEqual(value["status"],"INVALID_REQUEST")

    async def test_single_manager_start_creates_no_direction_or_loop(self):
        from unittest.mock import patch
        from test_loop_supervisor_handoff import OWNER, SUPERVISOR, topology
        routes = topology()
        self.server=build_mcp(SimpleNamespace(store=self.store,
            operations=SimpleNamespace(capabilities=("read","browser"))), status_provider=lambda: {})
        with patch("bct.loop_supervisor_handoff.resolve_direction_target",
                   side_effect=lambda **kw: routes[kw["conversation_key"]]):
            result=await self.result("start",direction_id="solo-direction",task_id="solo-task",
                owner=OWNER,plan_text="Bounded source-only task",direction_text="Implement and independently review",
                supervisor=SUPERVISOR,review_instruction="Exact source review only")
        self.assertEqual(result["reason"],"LOOP_NEW_START_DISABLED_CHAIN_RESTORED")
        self.assertIsNone(ChainDirectionLedger(self.store).get(direction_id="solo-direction"))
        self.assertIsNone((await self.result("status"))["loop"])

    async def test_single_manager_start_without_reviewer_does_not_create_direction(self):
        result=await self.result("start",direction_id="missing-reviewer",task_id="solo-task",
            owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",plan_text="plan",direction_text="new direct direction")
        self.assertEqual(result["reason"],"LOOP_NEW_START_DISABLED_CHAIN_RESTORED")
        self.assertIsNone(ChainDirectionLedger(self.store).get(direction_id="missing-reviewer"))


if __name__=="__main__":
    unittest.main()
