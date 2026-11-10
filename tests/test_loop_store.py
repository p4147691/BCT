"""Deterministic Loop Recipe safety tests; stdlib only."""
import tempfile
import threading
import unittest
from pathlib import Path

from bct.core.store import Store
from bct.loop_store import LoopStateError, LoopStore


class LoopStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        # Existing BCT Work authority is required; stub only this boundary.
        self.store.get_work = lambda work_id: object()
        self.a = LoopStore(self.store)
        self.b = LoopStore(self.store)
        self.a.start(work_id="loop-test",direction_id="direction",task_id="task",
                     owner="node-a",plan_text="step 1",now=100)

    def claim(self, engine, owner, epoch, now):
        return engine.claim(work_id="loop-test",owner=owner,epoch=epoch,now=now)

    def test_start_idempotency_and_conflict(self):
        row=self.a.start(work_id="loop-test",direction_id="direction",task_id="task",
                         owner="node-a",plan_text="step 1",now=105)
        self.assertEqual(row["epoch"],1)
        with self.assertRaisesRegex(LoopStateError,"LOOP_START_CONFLICT"):
            self.a.start(work_id="loop-test",direction_id="direction",
                         task_id="other",owner="node-a",plan_text="step 1")

    def test_prepared_unknown_no_replay(self):
        self.a.prepare_operation(work_id="loop-test",owner="node-a",epoch=1,
                                 operation_id="op-1",now=110)
        self.a.reconcile(work_id="loop-test",owner="node-a",epoch=1,
                         operation_id="op-1",result="UNKNOWN",now=111)
        with self.assertRaisesRegex(LoopStateError,"LOOP_RECONCILE_REQUIRED"):
            self.a.prepare_operation(work_id="loop-test",owner="node-a",
                                     epoch=1,operation_id="op-2",now=112)
        self.a.reconcile(work_id="loop-test",owner="node-a",epoch=1,
                         operation_id="op-1",result="APPLIED",now=113)
        self.a.advance(work_id="loop-test",owner="node-a",epoch=1,
                       next_step=1,now=114)
        self.assertEqual(self.a.get("loop-test")["next_step"],1)

    def test_successor_can_reconcile_unknown_without_replaying(self):
        self.a.prepare_operation(work_id="loop-test",owner="node-a",epoch=1,
                                 operation_id="op-uncertain",now=110)
        self.a.reconcile(work_id="loop-test",owner="node-a",epoch=1,
                         operation_id="op-uncertain",result="UNKNOWN",now=111)
        successor=self.claim(self.b,"node-b",1,200)
        self.assertEqual(successor["epoch"],2)
        self.assertEqual(successor["operation_id"],"op-uncertain")
        with self.assertRaisesRegex(LoopStateError,"LOOP_RECONCILE_REQUIRED"):
            self.b.prepare_operation(work_id="loop-test",owner="node-b",epoch=2,
                                     operation_id="op-replay",now=201)
        self.b.reconcile(work_id="loop-test",owner="node-b",epoch=2,
                         operation_id="op-uncertain",result="APPLIED",now=202)
        self.b.advance(work_id="loop-test",owner="node-b",epoch=2,
                       next_step=1,now=203)
        with self.assertRaisesRegex(LoopStateError,"LOOP_FENCED"):
            self.a.advance(work_id="loop-test",owner="node-a",epoch=1,
                           next_step=1,now=204)

    def test_successor_fencing(self):
        with self.assertRaisesRegex(LoopStateError,"LOOP_LEASE_HELD"):
            self.claim(self.b,"node-b",1,140)
        successor=self.claim(self.b,"node-b",1,161)
        self.assertEqual(successor["epoch"],2)
        with self.assertRaisesRegex(LoopStateError,"LOOP_FENCED"):
            self.a.prepare_operation(work_id="loop-test",owner="node-a",
                                     epoch=1,operation_id="old-op",now=162)

    def test_parallel_claim_single_winner(self):
        barrier=threading.Barrier(2)
        wins=[]
        def run(owner):
            barrier.wait()
            try:
                value=self.claim(LoopStore(self.store),owner,1,161)
                wins.append(value["owner"])
            except LoopStateError:
                pass
        threads=[threading.Thread(target=run,args=(name,))
                 for name in ("node-b","node-c")]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(wins),1)
        self.assertEqual(self.a.get("loop-test")["owner"],wins[0])

    def test_recovery_scan_classifies_original_receipt_first(self):
        from bct.loop_recovery import LoopRecoveryScanner
        scanner=LoopRecoveryScanner(self.store)
        self.assertEqual(scanner.scan(now=150),[])
        self.assertEqual(scanner.scan(now=161)[0]["advisory_action"],
                         "RECHECK_NODE_THEN_RECOVER")
        self.a.prepare_operation(work_id="loop-test",owner="node-a",epoch=1,
                                 operation_id="op-pending",now=120)
        advice=scanner.scan(now=161)
        self.assertEqual(advice[0]["advisory_action"],"RECONCILE_ORIGINAL_RECEIPT")
        self.assertEqual(advice[0]["operation_id"],"op-pending")
        self.assertEqual(advice[0]["external_effect"],"NONE_READ_ONLY")

    def test_core_restart_same_owner_fences_old_epoch(self):
        # The second Store simulates a new Core process on the same DB file.
        restarted = Store(Path(self.temp.name) / "state.sqlite")
        restarted.get_work = lambda work_id: object()
        resumed = LoopStore(restarted).claim(
            work_id="loop-test",owner="node-a",epoch=1,now=161
        )
        self.assertEqual(resumed["epoch"],2)
        with self.assertRaisesRegex(LoopStateError,"LOOP_FENCED"):
            self.a.prepare_operation(work_id="loop-test",owner="node-a",
                                     epoch=1,operation_id="old",now=162)

    def test_applied_receipt_must_advance_before_next_effect(self):
        self.a.prepare_operation(work_id="loop-test",owner="node-a",
                                 epoch=1,operation_id="op-1",now=105)
        self.a.reconcile(work_id="loop-test",owner="node-a",epoch=1,
                         operation_id="op-1",result="APPLIED",now=106)
        with self.assertRaisesRegex(LoopStateError,"LOOP_STEP_PENDING_ADVANCE"):
            self.a.prepare_operation(work_id="loop-test",owner="node-a",
                                     epoch=1,operation_id="op-2",now=107)
        self.a.advance(work_id="loop-test",owner="node-a",epoch=1,
                       next_step=1,now=108)
        with self.assertRaisesRegex(LoopStateError,"LOOP_OPERATION_ALREADY_USED"):
            self.a.prepare_operation(work_id="loop-test",owner="node-a",
                                     epoch=1,operation_id="op-1",now=109)

    def test_completed_run_rejects_late_mutations(self):
        self.a.prepare_operation(work_id="loop-test",owner="node-a",epoch=1,
                                 operation_id="op-final",now=110)
        self.a.reconcile(work_id="loop-test",owner="node-a",epoch=1,
                         operation_id="op-final",result="APPLIED",now=111)
        self.a.advance(work_id="loop-test",owner="node-a",epoch=1,
                       next_step=1,now=112)
        self.a.complete(work_id="loop-test",owner="node-a",epoch=1,
                        verified=True,now=113)
        with self.assertRaisesRegex(LoopStateError,"LOOP_COMPLETED"):
            self.a.reconcile(work_id="loop-test",owner="node-a",epoch=1,
                             operation_id="op-final",result="APPLIED",now=114)
        with self.assertRaisesRegex(LoopStateError,"LOOP_COMPLETED"):
            self.a.advance(work_id="loop-test",owner="node-a",epoch=1,
                           next_step=2,now=115)

    def test_complete_requires_verification_and_is_terminal(self):
        with self.assertRaisesRegex(LoopStateError,"LOOP_COMPLETION_UNVERIFIED"):
            self.a.complete(work_id="loop-test",owner="node-a",epoch=1,
                            verified=False,now=110)
        self.a.prepare_operation(work_id="loop-test",owner="node-a",epoch=1,
                                 operation_id="op-final",now=110)
        from types import SimpleNamespace
        def receipt(**kwargs):
            self.assertEqual(kwargs["operation_id"], "op-final")
            return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                   outcome=SimpleNamespace(value="APPLIED"))
        self.store.get_operation_for = receipt
        self.a.reconcile_from_bct(work_id="loop-test",owner="node-a",epoch=1,
                                  operation_id="op-final",principal_id="test",now=111)
        self.a.advance(work_id="loop-test",owner="node-a",epoch=1,
                       next_step=1,now=112)
        self.a.complete(work_id="loop-test",owner="node-a",epoch=1,
                        verified=True,now=113)
        with self.assertRaisesRegex(LoopStateError,"LOOP_COMPLETED"):
            self.claim(self.b,"node-b",1,200)


if __name__ == "__main__":
    unittest.main()
