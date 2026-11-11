"""Loop + existing Chain Execute Plan contract, without LIVE DB access."""
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Work
from bct.core.store import Store
from bct.chain_direction import ChainDirectionLedger
from bct.chain_execution_plan import ChainExecutionPlanLedger
from bct.loop_store import LoopStore


class LoopPlanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"state.sqlite")
        self.store.create_work(Work(work_id="loop-test",request_summary="Loop candidate",
                                    roots=(self.tmp.name,),actions=frozenset({"read"}),
                                    owner_principal_id="test"))
        self.direction=ChainDirectionLedger(self.store)
        self.direction.save(direction_id="direction-test",work_id="loop-test",
                            source_kind="USER",decision="NEW_TASK",
                            direction_text="one node does work")
        self.plans=ChainExecutionPlanLedger(self.store)

    def save_plan(self):
        return self.plans.save(plan_id="loop-plan",work_id="loop-test",
                               direction_id="direction-test",task_id="task-1",
                               generation=1,plan_text="step A then verify")

    def test_plan_blocked_until_real_loop_start(self):
        with self.assertRaisesRegex(ValueError,"CHAIN_EXECUTION_PLAN_SOURCE_NOT_STARTED"):
            self.save_plan()
        loop=LoopStore(self.store)
        loop.start(work_id="loop-test",direction_id="direction-test",
                   task_id="task-1",owner="node-a",plan_text="step A then verify")
        result=self.save_plan()
        self.assertEqual(result["plan_id"],"loop-plan")
        self.assertFalse(result["duplicate"])
        self.assertTrue(self.save_plan()["duplicate"])
        self.assertEqual(self.direction.get(direction_id="direction-test")["chain_state"],
                         "NOT_PLANNED")

    def test_existing_chain_started_contract_is_preserved(self):
        # In the isolated fixture, emulate the already-verified Chain transition.
        # Loop must not be a prerequisite for the existing multi-node plan path.
        with self.store.transaction() as db:
            db.execute(
                "UPDATE chain_directions SET chain_state='CHAIN_STARTED', "
                "chain_task_id='task-chain' WHERE direction_id='direction-test'"
            )
        plan=self.plans.save(plan_id="chain-plan",work_id="loop-test",
                             direction_id="direction-test",task_id="task-chain",
                             generation=1,plan_text="existing Chain plan")
        self.assertEqual(plan["plan_id"],"chain-plan")
        self.assertIsNone(LoopStore(self.store).get("loop-test"))

    def test_wrong_task_cannot_steal_loop_plan(self):
        loop=LoopStore(self.store)
        loop.start(work_id="loop-test",direction_id="direction-test",
                   task_id="task-other",owner="node-a",plan_text="step A")
        with self.assertRaisesRegex(ValueError,"CHAIN_EXECUTION_PLAN_SOURCE_NOT_STARTED"):
            self.save_plan()


if __name__=="__main__":
    unittest.main()
