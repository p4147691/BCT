import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.store import Store
from bct.loop_store import LoopStore
from bct.loop_self_outbox import LoopSelfOutbox
from bct.loop_self_continuation import LoopSelfContinuation
from bct.send_delayed_message import _rcc_submitted_text_sha256
from test_loop_self_dispatch import OWNER, snapshot, production_snapshot


class FakeClient:
    def __init__(self, observed):
        self.observed=observed
        self.calls=[]
    def request(self,**kw):
        self.calls.append(kw)
        return self.observed


class LoopContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"state.sqlite")
        self.store.get_work=lambda _: object()
        self.loop=LoopStore(self.store)
        self.loop.start(work_id="w",direction_id="d",task_id="t",
                        owner=OWNER,plan_text="plan",now=100)
        self.out=LoopSelfOutbox(self.store)
        self.out.queue(work_id="w",epoch=1,step=0,owner=OWNER,
                       message="initial SELF",now=110)
        self.out.reserve(work_id="w",epoch=1,step=0,owner=OWNER,now=111)
        self.out.reconcile_receipt=lambda:None
        self.out.reconcile_from_mock=None
        original=self.out.get(work_id="w",epoch=1,step=0)
        def receipt(**kw):
            self.assertEqual(kw["operation_id"],original["operation_id"])
            return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                   outcome=SimpleNamespace(value="APPLIED"))
        self.store.get_operation_for=receipt
        self.out.reconcile(work_id="w",epoch=1,step=0,
                           principal_id="test",now=112)
        self.loop.prepare_operation(work_id="w",owner=OWNER,epoch=1,
                                    operation_id="external-1",now=113)
        self.loop.reconcile(work_id="w",owner=OWNER,epoch=1,
                            operation_id="external-1",result="APPLIED",now=114)
        self.loop.advance(work_id="w",owner=OWNER,epoch=1,next_step=1,now=115)
        self.row=self.out.get(work_id="w",epoch=1,step=0)
        self.response="PROGRESS: 1/2 — done\nNEXT TASK — SELF\ncontinue exact plan"
        self.sha=hashlib.sha256(self.response.encode()).hexdigest()
        source=_rcc_submitted_text_sha256("initial SELF")
        self.observed={"ok":True,"conversationKey":OWNER,"terminal":True,
                       "observationState":"TERMINAL","generating":False,
                       "inputReady":True,"latestUserSha256":source,
                       "responseSourceUserSha256":source,
                       "latestUserTurnKey":"turn-1",
                       "responseSourceUserTurnKey":"turn-1",
                       "responseText":self.response,
                       "responseSha256":self.sha,"responseTurnKey":"reply-1"}
        self.client=FakeClient(self.observed)
        self.cont=LoopSelfContinuation(self.store,SimpleNamespace(client=self.client))

    def test_terminal_exact_response_queues_next_step_once(self):
        result=self.cont.observe_once(row=self.row,snapshot=snapshot(),now=116)
        self.assertEqual(result["status"],"NEXT_SELF_QUEUED")
        self.assertEqual(self.out.get(work_id="w",epoch=1,step=0)["state"],"ACKED")
        self.assertEqual(self.out.get(work_id="w",epoch=1,step=1)["state"],"PENDING")
        self.assertEqual(len(self.client.calls),1)
        self.assertEqual(self.client.calls[0]["extra"]["conversationKey"],OWNER)

    def test_old_delivered_response_recovers_same_owner_new_epoch(self):
        claimed=self.loop.claim(work_id="w",owner=OWNER,epoch=1,now=161)
        self.assertEqual(claimed["epoch"],2)
        result=self.cont.observe_once(row=self.row,snapshot=snapshot(),now=162)
        self.assertEqual(result["status"],"NEXT_SELF_QUEUED")
        self.assertEqual(self.out.get(work_id="w",epoch=1,step=0)["state"],"ACKED")
        pending=self.out.get(work_id="w",epoch=2,step=1)
        self.assertEqual(pending["state"],"PENDING")
        self.assertEqual(pending["conversation_key"],OWNER)

    def test_core_monitor_envelope_observes_and_queues_exact_self(self):
        result = self.cont.observe_once(row=self.row, snapshot={"monitor": production_snapshot()}, now=116)
        self.assertEqual(result["status"], "NEXT_SELF_QUEUED")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0]["extra"]["conversationKey"], OWNER)
        self.assertEqual(self.out.get(work_id="w", epoch=1, step=1)["state"], "PENDING")

    def test_completed_run_stops_auto_response_polling(self):
        self.loop.complete(work_id="w",owner=OWNER,epoch=1,
                           verified=True,now=116)
        self.assertEqual(self.out.list_delivered(),[])
        self.assertEqual(self.out.get(work_id="w",epoch=1,step=0)["state"],
                         "DELIVERED")

    def test_mismatched_response_never_requeues(self):
        self.observed["responseSourceUserSha256"]="bad"
        result=self.cont.observe_once(row=self.row,snapshot=snapshot(),now=116)
        self.assertEqual(result["status"],"RESPONSE_SOURCE_UNVERIFIED")
        self.assertIsNone(self.out.get(work_id="w",epoch=1,step=1))
        self.assertEqual(self.row["state"],"DELIVERED")


if __name__=="__main__":
    unittest.main()
