import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.store import Store
from bct.loop_store import LoopStore
from bct.loop_recovery_executor import LoopRecoveryExecutor


class LoopRecoveryExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"state.sqlite"
        self.store=Store(self.path)
        self.store.get_work=lambda _: object()
        self.loop=LoopStore(self.store)
        self.loop.start(work_id="w",direction_id="d",task_id="t",
                        owner="node-a",plan_text="plan",now=100)

    def executor(self, ready=True):
        return LoopRecoveryExecutor(Store(self.path),principal_id="principal",
                                    owner_ready=lambda owner: ready and owner=="node-a")

    def test_manual_recovery_is_exact_work_scoped(self):
        result=self.executor().run_once(now=161,work_id_filter="other-work")
        self.assertEqual(result["checked"],0)
        self.assertEqual(self.loop.get("w")["epoch"],1)
        owned=self.executor().run_once(now=161,work_id_filter="w")
        self.assertEqual(owned["checked"],1)
        self.assertEqual(self.loop.get("w")["epoch"],2)

    def test_disconnected_node_does_not_claim(self):
        result=self.executor(False).run_once(now=161)
        self.assertEqual(result["results"][0]["status"],"OWNER_UNAVAILABLE")
        self.assertEqual(self.loop.get("w")["epoch"],1)

    def test_restart_with_exact_applied_receipt_advances_once(self):
        self.loop.prepare_operation(work_id="w",owner="node-a",epoch=1,
                                    operation_id="op",now=101)
        # Inject a recorded receipt into the independent reopened Store.
        restarted=Store(self.path)
        def receipt(**kwargs):
            self.assertEqual(kwargs["operation_id"],"op")
            return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                   outcome=SimpleNamespace(value="APPLIED"))
        restarted.get_operation_for=receipt
        recovery=LoopRecoveryExecutor(restarted,principal_id="principal",
                                     owner_ready=lambda _: True)
        result=recovery.run_once(now=161)
        self.assertEqual(result["results"][0]["status"],"STEP_CONFIRMED")
        self.assertEqual(self.loop.get("w")["epoch"],2)
        self.assertEqual(self.loop.get("w")["next_step"],1)
        self.assertEqual(recovery.run_once(now=162)["checked"],0)

    def test_restart_missing_receipt_never_advances(self):
        self.loop.prepare_operation(work_id="w",owner="node-a",epoch=1,
                                    operation_id="op",now=101)
        result=self.executor().run_once(now=161)
        self.assertEqual(result["results"][0]["status"],"RECEIPT_CHECK_REQUIRED")
        self.assertEqual(self.loop.get("w")["next_step"],0)
        self.assertEqual(self.loop.get("w")["operation_id"],"op")


if __name__=="__main__":
    unittest.main()
