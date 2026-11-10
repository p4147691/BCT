"""Crash-safe Loop SELF outbox tests; no live RCC messages."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.store import Store
from bct.loop_store import LoopStore, LoopStateError
from bct.loop_self_outbox import LoopSelfOutbox

OWNER="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NEXT="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class LoopSelfOutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/"state.sqlite")
        self.store.get_work=lambda _: object()
        self.loop=LoopStore(self.store)
        self.loop.start(work_id="work",direction_id="dir",task_id="task",
                        owner=OWNER,plan_text="plan",now=100)
        self.outbox=LoopSelfOutbox(self.store)

    def queue(self, **extra):
        data=dict(work_id="work",epoch=1,step=0,owner=OWNER,
                  message="continue plan",now=110)
        data.update(extra)
        return self.outbox.queue(**data)

    def test_idempotent_and_no_cross_target(self):
        first=self.queue()
        self.assertEqual(first["state"],"PENDING")
        self.assertEqual(first["conversation_key"],OWNER)
        self.assertEqual(self.queue()["operation_id"],first["operation_id"])
        with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_CONFLICT"):
            self.queue(message="different instruction")
        with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_UNSAFE_STATE"):
            self.queue(owner=NEXT)

    def test_unknown_crash_recovery_never_replays(self):
        row=self.queue()
        self.outbox.reserve(work_id="work",epoch=1,step=0,owner=OWNER,now=111)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_ALREADY_DISPATCHED"):
            self.outbox.reserve(work_id="work",epoch=1,step=0,owner=OWNER,now=112)
        recovered=LoopSelfOutbox(Store(Path(self.temp.name)/"state.sqlite"))
        self.assertEqual(recovered.list_uncertain()[0]["operation_id"],row["operation_id"])
        unknown=recovered.reconcile(work_id="work",epoch=1,step=0,
                                    principal_id="principal",now=113)
        self.assertEqual(unknown["state"],"UNKNOWN")
        with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_ALREADY_DISPATCHED"):
            recovered.reserve(work_id="work",epoch=1,step=0,owner=OWNER,now=114)

    def test_original_receipt_is_authoritative(self):
        row=self.queue()
        self.outbox.reserve(work_id="work",epoch=1,step=0,owner=OWNER,now=111)
        def actual_receipt(**kw):
            self.assertEqual(kw["operation_id"],row["operation_id"])
            return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                   outcome=SimpleNamespace(value="APPLIED"))
        self.store.get_operation_for=actual_receipt
        settled=self.outbox.reconcile(work_id="work",epoch=1,step=0,
                                     principal_id="principal",now=112)
        self.assertEqual(settled["state"],"DELIVERED")
        self.assertEqual(self.outbox.list_uncertain(),[])

    def test_successor_does_not_duplicate_unknown_self_wake(self):
        self.queue()
        self.outbox.reserve(work_id="work",epoch=1,step=0,owner=OWNER,now=111)
        successor=self.loop.claim(work_id="work",owner=NEXT,epoch=1,now=161)
        self.assertEqual(successor["epoch"],2)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_PRIOR_EFFECT_UNRESOLVED"):
            self.outbox.queue(work_id="work",epoch=2,step=0,
                              owner=NEXT,message="continue plan",now=162)

    def test_lease_and_epoch_fence(self):
        self.queue()
        successor=self.loop.claim(work_id="work",owner=NEXT,epoch=1,now=161)
        self.assertEqual(successor["epoch"],2)
        with self.assertRaisesRegex(LoopStateError,"LOOP_FENCED"):
            self.outbox.reserve(work_id="work",epoch=1,step=0,owner=OWNER,now=162)


if __name__=="__main__":
    unittest.main()
