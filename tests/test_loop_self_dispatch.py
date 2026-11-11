"""Safe Loop SELF delivery tests with exact RCC observations."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore, LoopStateError
from bct.loop_self_outbox import LoopSelfOutbox
from bct.loop_self_dispatch import LoopSelfDispatcher
from bct.current_nodes import classify_current_nodes

OWNER="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def snapshot(*, owner=OWNER, fresh=True, generating=False, disconnected=False):
    telemetry={"readiness":"BUSY" if generating else "IDLE"}
    conn={"disconnected":disconnected}
    node={"status":"CONFIRMED","conversation_uuid":owner,"source":"RCC_FRESH",
          "window_id":3,"tab_id":2,"generating":generating,
          "connection":conn,"telemetry":telemetry}
    tab={"conversation_key":owner,"presence":"OPEN","tab_id":2,
         "window_id":3,"generating":generating,"connection":conn,
         "telemetry":telemetry}
    return {"current_nodes":{"observation":{"state":"FRESH" if fresh else "STALE"},
                             "items":[node]},
            "rcc":{"instances":[{"state":"OPEN","instance_id":"a"*32,
                                 "session_id":"b"*32,"tabs":[tab]}]}}


def production_snapshot(**kwargs):
    view = snapshot(**kwargs)
    for instance in view["rcc"]["instances"]:
        for tab in instance["tabs"]:
            tab.update(url="https://chatgpt.com/c/" + tab["conversation_key"], node_label="N40")
    view["current_nodes"] = classify_current_nodes(view["rcc"]["instances"])
    return view


class FakeOperations:
    def __init__(self):
        self.calls=[]
    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(outcome=SimpleNamespace(value="APPLIED"))


class LoopSelfDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"state.sqlite")
        self.store.create_work(Work(
            work_id="work",request_summary="test",roots=(self.tmp.name,),
            actions=frozenset({"browser"}),owner_principal_id="principal",
        ))
        LoopStore(self.store).start(
            work_id="work",direction_id="dir",task_id="task",owner=OWNER,
            plan_text="plan",now=100,
        )
        self.outbox=LoopSelfOutbox(self.store)
        self.operations=FakeOperations()
        self.dispatcher=LoopSelfDispatcher(self.store,self.operations)
        self.queued=self.outbox.queue(work_id="work",epoch=1,step=0,
                                      owner=OWNER,message="next step",now=110)
        # The real operations runner persists its own receipt. Simulate that
        # exact receipt and assert the operation identifier is never changed.
        def original_receipt(**args):
            self.assertEqual(args["operation_id"],self.queued["operation_id"])
            return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                   outcome=SimpleNamespace(value="APPLIED"))
        self.store.get_operation_for=original_receipt

    def send(self, view):
        with patch("bct.loop_self_dispatch.NodeRecoveryLedger.assert_send_allowed",
                   return_value=None):
            return self.dispatcher.send_once(
                work_id="work",epoch=1,step=0,owner=OWNER,
                snapshot=view,now=111,
            )

    def test_exact_owner_receipt_and_no_second_send(self):
        result=self.send(snapshot())
        self.assertEqual(result["status"],"DELIVERED")
        self.assertEqual(len(self.operations.calls),1)
        self.assertEqual(self.operations.calls[0]["operation_id"],
                         self.queued["operation_id"])
        self.assertEqual(self.operations.calls[0]["arguments"]["conversation_key"],OWNER)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_ALREADY_DISPATCHED"):
            self.send(snapshot())

    def test_core_monitor_envelope_sends_exactly_once(self):
        view = production_snapshot()
        self.assertNotIn("connection", view["current_nodes"]["items"][0])
        self.assertNotIn("telemetry", view["current_nodes"]["items"][0])
        self.assertEqual(self.send({"monitor": view})["status"], "DELIVERED")
        self.assertEqual(len(self.operations.calls), 1)
        with self.assertRaisesRegex(LoopStateError, "LOOP_SELF_ALREADY_DISPATCHED"):
            self.send({"monitor": production_snapshot()})
        self.assertEqual(len(self.operations.calls), 1)

    def test_production_projection_rejects_nonidle_or_mismatched_tab(self):
        mismatch = production_snapshot()
        mismatch["rcc"]["instances"][0]["tabs"][0]["tab_id"] = 99
        for view in (production_snapshot(disconnected=True),
                     production_snapshot(generating=True), mismatch):
            with self.assertRaises(LoopStateError):
                self.send({"monitor": view})
        self.assertEqual(self.operations.calls, [])
        self.assertEqual(self.outbox.get(work_id="work", epoch=1, step=0)["state"], "PENDING")

    def test_invalid_monitor_envelope_never_uses_outer_identity(self):
        for monitor in (None, {}, snapshot(fresh=False), snapshot(disconnected=True)):
            with self.assertRaises(LoopStateError):
                self.send({**snapshot(), "monitor": monitor})
        self.assertEqual(self.operations.calls, [])
        self.assertEqual(self.outbox.get(work_id="work", epoch=1, step=0)["state"], "PENDING")

    def test_stale_generating_disconnected_never_send(self):
        for view in (snapshot(fresh=False),snapshot(generating=True),
                     snapshot(disconnected=True),snapshot(owner="b"*8+"-bbbb-4bbb-8bbb-bbbbbbbbbbbb")):
            with self.assertRaises(LoopStateError):
                self.send(view)
        self.assertEqual(self.operations.calls,[])
        self.assertEqual(self.outbox.get(work_id="work",epoch=1,step=0)["state"],"PENDING")

    def test_cached_rcc_instance_is_rejected(self):
        view=snapshot()
        view["rcc"]["instances"][0]["cached"]=True
        with self.assertRaisesRegex(LoopStateError,"LOOP_RCC_TARGET_NOT_UNIQUE"):
            self.send(view)
        self.assertEqual(self.operations.calls,[])

    def test_invalid_rcc_identity_is_rejected(self):
        view=snapshot()
        view["rcc"]["instances"][0]["instance_id"]="z"*32
        with self.assertRaisesRegex(LoopStateError,"LOOP_RCC_ID_INVALID"):
            self.send(view)
        self.assertEqual(self.operations.calls,[])

    def test_cross_tab_ambiguity_never_send(self):
        view=snapshot()
        view["rcc"]["instances"][0]["tabs"].append(
            dict(view["rcc"]["instances"][0]["tabs"][0])
        )
        with self.assertRaisesRegex(LoopStateError,"LOOP_RCC_TARGET_NOT_UNIQUE"):
            self.send(view)
        self.assertEqual(self.operations.calls,[])


if __name__=="__main__":
    unittest.main()
