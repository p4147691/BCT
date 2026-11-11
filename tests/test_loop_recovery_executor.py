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

    def test_no_id_recovery_only_when_one_owned_work_exists(self):
        from bct.core.models import Work
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"owned.sqlite")
            def create(name,principal):
                store.create_work(Work(
                    work_id=name,request_summary="test",roots=(root,),
                    actions=frozenset({"read"}),owner_principal_id=principal,
                ))
                LoopStore(store).start(
                    work_id=name,direction_id="d",task_id="t",
                    owner="node-a",plan_text="plan",now=100,
                )
            create("first","principal")
            create("foreign","other-principal")
            self.assertEqual(
                LoopRecoveryExecutor.resolve_single_work(
                    store,principal_id="principal"
                ),"first"
            )
            create("second","principal")
            from bct.loop_store import LoopStateError
            with self.assertRaisesRegex(LoopStateError,"LOOP_WORK_AMBIGUOUS"):
                LoopRecoveryExecutor.resolve_single_work(
                    store,principal_id="principal"
                )

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

    def test_disconnected_applied_receipt_advances_once_without_claim_or_lease(self):
        for state in ("PREPARED", "UNKNOWN", "APPLIED"):
            with self.subTest(state=state):
                with self.store.transaction() as db:
                    db.execute("UPDATE loop_recipe_runs SET operation_id='op',operation_state=?,next_step=0 WHERE work_id='w'", (state,))
                before = self.loop.get("w")
                reopened = Store(self.path)
                calls = []
                def receipt(**kwargs):
                    calls.append(kwargs)
                    return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                           outcome=SimpleNamespace(value="APPLIED"))
                reopened.get_operation_for = receipt
                recovery = LoopRecoveryExecutor(reopened, principal_id="principal", owner_ready=lambda _: False)
                self.assertEqual(recovery.run_once(now=161)["results"][0]["status"], "STEP_CONFIRMED")
                after = self.loop.get("w")
                self.assertEqual(after["next_step"], 1)
                self.assertIsNone(after["operation_state"])
                self.assertEqual(after["epoch"], before["epoch"])
                self.assertEqual(after["lease_until"], before["lease_until"])
                recovery.run_once(now=162)
                self.assertEqual(self.loop.get("w")["next_step"], 1)
                self.assertEqual(calls, [dict(operation_id="op", work_id="w", principal_id="principal")])

    def test_disconnected_unknown_and_not_applied_receipts_do_not_advance(self):
        for outcome in ("UNKNOWN", "NOT_APPLIED"):
            with self.subTest(outcome=outcome):
                with self.store.transaction() as db:
                    db.execute("UPDATE loop_recipe_runs SET operation_id='op',operation_state='PREPARED' WHERE work_id='w'")
                reopened = Store(self.path)
                reopened.get_operation_for = lambda **_: SimpleNamespace(
                    state=SimpleNamespace(value="FINISHED"), outcome=SimpleNamespace(value=outcome))
                recovery = LoopRecoveryExecutor(reopened, principal_id="principal", owner_ready=lambda _: False)
                recovery.run_once(now=161)
                self.assertEqual(self.loop.get("w")["next_step"], 0)
                self.assertEqual(self.loop.get("w")["operation_state"], outcome)
                self.assertEqual(self.loop.get("w")["epoch"], 1)
                self.assertEqual(self.loop.get("w")["lease_until"], 160)

    def test_disconnected_receipt_read_race_cannot_advance_new_epoch(self):
        self.loop.prepare_operation(work_id="w", owner="node-a", epoch=1, operation_id="op", now=101)
        reopened = Store(self.path)
        def receipt(**_):
            self.loop.claim(work_id="w", owner="node-a", epoch=1, now=161)
            return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                   outcome=SimpleNamespace(value="APPLIED"))
        reopened.get_operation_for = receipt
        recovery = LoopRecoveryExecutor(reopened, principal_id="principal", owner_ready=lambda _: False)
        result = recovery.run_once(now=161)
        self.assertEqual(result["results"][0]["reason"], "LOOP_EXPIRED_OPERATION_FENCED")
        self.assertEqual(self.loop.get("w")["next_step"], 0)
        self.assertEqual(self.loop.get("w")["epoch"], 2)

    def test_disconnected_missing_receipt_stays_prepared(self):
        self.loop.prepare_operation(work_id="w", owner="node-a", epoch=1, operation_id="op", now=101)
        result = self.executor(False).run_once(now=161)
        self.assertEqual(result["results"][0]["reason"], "LOOP_RECEIPT_NOT_FOUND")
        self.assertEqual(self.loop.get("w")["operation_state"], "PREPARED")
        self.assertEqual(self.loop.get("w")["epoch"], 1)


if __name__=="__main__":
    unittest.main()
