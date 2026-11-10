"""One-node SELF->response->SELF integration without real RCC effects."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore,LoopStateError
from bct.loop_self_outbox import LoopSelfOutbox
from bct.loop_self_dispatch import LoopSelfDispatcher
from bct.loop_self_continuation import LoopSelfContinuation
from bct.send_delayed_message import _rcc_submitted_text_sha256
from test_loop_self_dispatch import OWNER,snapshot,FakeOperations


class MockRcc:
    def __init__(self):
        self.response={}
    def request(self,**kwargs):
        return self.response


class LoopAutomaticRoundTripTests(unittest.TestCase):
    def test_two_turn_self_without_user_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"db.sqlite")
            store.create_work(Work(work_id="w",request_summary="test",
                roots=(root,),actions=frozenset({"browser"}),
                owner_principal_id="principal"))
            loop=LoopStore(store)
            loop.start(work_id="w",direction_id="d",task_id="t",
                       owner=OWNER,plan_text="two verified steps",now=100)
            out=LoopSelfOutbox(store)
            ops=FakeOperations()
            sent=set()
            def original_receipt(**kwargs):
                self.assertIn(kwargs["operation_id"],sent)
                return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                       outcome=SimpleNamespace(value="APPLIED"))
            store.get_operation_for=original_receipt
            dispatcher=LoopSelfDispatcher(store,ops)
            rcc=MockRcc()
            observer=LoopSelfContinuation(store,SimpleNamespace(client=rcc))
            out.queue(work_id="w",epoch=1,step=0,owner=OWNER,
                      message="first turn",now=110)
            with patch("bct.loop_self_dispatch.NodeRecoveryLedger.assert_send_allowed",
                       return_value=None):
                # The mock transport's receipt is known before reconciliation.
                original_run=ops.run
                def run(**kw):
                    sent.add(kw["operation_id"])
                    return original_run(**kw)
                ops.run=run
                first=dispatcher.send_once(
                    work_id="w",epoch=1,step=0,owner=OWNER,
                    snapshot=snapshot(),now=111)
                self.assertEqual(first["status"],"DELIVERED")
                loop.prepare_operation(work_id="w",owner=OWNER,epoch=1,
                                       operation_id="external-step-1",now=112)
                loop.reconcile(work_id="w",owner=OWNER,epoch=1,
                               operation_id="external-step-1",
                               result="APPLIED",now=113)
                loop.advance(work_id="w",owner=OWNER,epoch=1,
                             next_step=1,now=114)
                body="PROGRESS: 1/2 — verified\nNEXT TASK — SELF\nsecond turn"
                rcc.response={
                    "ok":True,"conversationKey":OWNER,
                    "terminal":True,"observationState":"TERMINAL",
                    "generating":False,"inputReady":True,
                    "latestUserSha256":_rcc_submitted_text_sha256("first turn"),
                    "responseSourceUserSha256":_rcc_submitted_text_sha256("first turn"),
                    "latestUserTurnKey":"turn-first",
                    "responseSourceUserTurnKey":"turn-first",
                    "responseText":body,
                    "responseSha256":hashlib.sha256(body.encode()).hexdigest(),
                    "responseTurnKey":"reply-first",
                }
                completed=out.get(work_id="w",epoch=1,step=0)
                result=observer.observe_once(row=completed,
                                             snapshot=snapshot(),now=115)
                self.assertEqual(result["status"],"NEXT_SELF_QUEUED")
                second=dispatcher.send_once(
                    work_id="w",epoch=1,step=1,owner=OWNER,
                    snapshot=snapshot(),now=116)
                self.assertEqual(second["status"],"DELIVERED")
                self.assertEqual(len(ops.calls),2)
                self.assertEqual([x["arguments"]["text"] for x in ops.calls],
                                 ["first turn","second turn"])
                with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_ALREADY_DISPATCHED"):
                    dispatcher.send_once(work_id="w",epoch=1,step=1,
                                         owner=OWNER,snapshot=snapshot(),now=117)


if __name__=="__main__":
    unittest.main()
