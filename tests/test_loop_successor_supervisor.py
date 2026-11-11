"""Multi-turn Loop successor E2E using bounded fake RCC and exact BCT receipts."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore
from bct.loop_successor_supervisor import LoopSuccessorSupervisor
from bct.send_delayed_message import _rcc_submitted_text_sha256

OLD="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NEW="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
INSTANCE="a"*32
SESSION="b"*32


def monitor(*,clock=103,blank=False,linked=False,connected=False):
    tabs=[{"tab_id":10,"window_id":34,"conversation_key":OLD,
           "presence":"OPEN","connection":{"disconnected":not connected}}]
    if blank or linked:
        tabs.append({"tab_id":12,"window_id":34,
                     "conversation_key":NEW if linked else "",
                     "presence":"OPEN"})
    return {"monitor":{
        "current_nodes":{"observation":{"state":"FRESH"},
                         "observed_at":clock,
                         "items":[{"conversation_uuid":OLD,
                                   "status":"CONFIRMED","source":"RCC_FRESH",
                                   "connection":{"disconnected":not connected}}]},
        "rcc":{"instances":[{"instance_id":INSTANCE,
                              "session_id":SESSION,"state":"OPEN","tabs":tabs}]},
    }}


class FakeOperations:
    def __init__(self):
        self.receipts={}
        self.calls=[]

    def run(self,**kwargs):
        self.calls.append(kwargs)
        args=kwargs["arguments"]
        if args["command"]=="create-chat-tab":
            evidence={"command":"create-chat-tab","instance_id":INSTANCE,
                      "created_request_id":kwargs["operation_id"],
                      "created_tab_id":12,"created_window_id":34}
        else:
            assert args["command"]=="send-message"
            evidence={"command":"send-to-created-tab","instance_id":INSTANCE,
                      "host_request_id":kwargs["operation_id"],
                      "source_message_sha256":_rcc_submitted_text_sha256(args["text"]),
                      "conversation_key":NEW}
        self.receipts[kwargs["operation_id"]]=SimpleNamespace(
            state=SimpleNamespace(value="FINISHED"),
            outcome=SimpleNamespace(value="APPLIED"),
            evidence=evidence,
        )
        return SimpleNamespace(outcome=SimpleNamespace(value="APPLIED"))


class FakeClient:
    def __init__(self,operations):
        self.operations=operations
        self.calls=[]
    def request(self,**kw):
        self.calls.append(kw)
        body="LOOP_SUCCESSOR_READY"
        send=self.operations.calls[-1]
        assert send["arguments"]["command"]=="send-message"
        source_sha=_rcc_submitted_text_sha256(send["arguments"]["text"])
        return {
            "ok":True,"conversationKey":NEW,
            "terminal":True,"generating":False,
            "observationState":"TERMINAL",
            "responseText":body,
            "responseSha256":hashlib.sha256(body.encode()).hexdigest(),
            "responseTurnKey":"successor-reply",
            "responseSourceUserSha256":source_sha,
            "latestUserSha256":source_sha,
            "responseSourceUserTurnKey":"inherit-user",
            "latestUserTurnKey":"inherit-user",
        }


class SuccessorE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"state.sqlite")
        self.store.create_work(Work(
            work_id="w",request_summary="test",roots=(self.tmp.name,),
            actions=frozenset({"browser"}),owner_principal_id="principal",
        ))
        self.loop=LoopStore(self.store)
        self.loop.start(work_id="w",direction_id="d",task_id="t",
                        owner=OLD,plan_text="two step plan",now=100)
        self.ops=FakeOperations()
        self.store.get_operation_for=lambda **kw:self.ops.receipts[kw["operation_id"]]
        self.client=FakeClient(self.ops)
        self.supervisor=LoopSuccessorSupervisor(
            self.store,self.ops,SimpleNamespace(client=self.client),
            principal_id="principal",
        )

    def test_six_stage_takeover_with_real_uuid_proof_and_fencing(self):
        def once(t,**opts):
            result=self.supervisor.run_once(snapshot=monitor(clock=t,**opts),
                prior_snapshot=monitor(clock=100),now=t)
            self.assertEqual(result["checked"],1)
            return result["outcomes"][0]["status"]
        self.assertEqual(once(161),"CREATE_RESERVED")
        self.assertEqual(once(162,blank=True),"CREATE_CONFIRMED")
        self.assertEqual(once(163,blank=True),"HANDOFF_RESERVED")
        self.assertEqual(once(164,linked=True),"UUID_CONFIRMED")
        self.assertEqual(once(165,linked=True),"HANDOFF_ACK")
        self.assertEqual(once(166,linked=True),"EPOCH_SUCCEEDED")
        self.assertEqual(self.loop.get("w")["owner"],NEW)
        self.assertEqual(self.loop.get("w")["epoch"],2)
        from bct.node_recovery import NodeRecoveryLedger
        with self.assertRaisesRegex(ValueError,"NODE_RECOVERY_SEND_FENCED"):
            NodeRecoveryLedger(self.store).assert_send_allowed(
                work_id="w",conversation_key=OLD,
            )
        self.assertEqual(len(self.ops.calls),2)
        self.assertEqual(self.supervisor.run_once(
            snapshot=monitor(clock=167,linked=True),now=167)["checked"],0)

    def test_predecessor_reconnect_blocks_successor(self):
        response=self.supervisor.run_once(
            snapshot=monitor(clock=161,connected=True),
            prior_snapshot=monitor(clock=100),now=161)
        self.assertEqual(response["outcomes"][0]["status"],"PREFER_ORIGINAL_NODE")
        self.assertEqual(self.ops.calls,[])
        self.assertEqual(self.loop.get("w")["owner"],OLD)

    def test_predecessor_recovers_before_takeover_no_fence(self):
        def advance(clock,**kwargs):
            return self.supervisor.run_once(
                snapshot=monitor(clock=clock,**kwargs),
                prior_snapshot=monitor(clock=100),now=clock,
            )
        advance(161)
        advance(162,blank=True)
        advance(163,blank=True)
        advance(164,linked=True)
        advance(165,linked=True)
        result=advance(166,linked=True,connected=True)
        self.assertEqual(result["outcomes"][0]["status"],"PREFER_ORIGINAL_NODE")
        self.assertEqual(self.loop.get("w")["epoch"],1)
        from bct.node_recovery import NodeRecoveryLedger
        NodeRecoveryLedger(self.store).assert_send_allowed(
            work_id="w",conversation_key=OLD,
        )

    def test_unknown_create_receipt_never_creates_again(self):
        self.supervisor.run_once(
            snapshot=monitor(clock=161),prior_snapshot=monitor(clock=100),now=161)
        self.ops.receipts.clear()
        next_result=self.supervisor.run_once(snapshot=monitor(clock=162,blank=True),now=162)
        self.assertEqual(next_result["outcomes"][0]["status"],"HELD")
        self.assertEqual(len(self.ops.calls),1)
        self.assertEqual(self.loop.get("w")["epoch"],1)


if __name__=="__main__":
    unittest.main()
