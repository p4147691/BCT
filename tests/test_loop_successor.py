"""No-effect Loop successor creation/UUID/handoff/Epoch fault injection."""
import tempfile
import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from bct.core.store import Store
from bct.core.models import Work
from bct.loop_store import LoopStore,LoopStateError
from bct.loop_successor import LoopSuccessorLedger

OLD="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NEW="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
INSTANCE="a"*32
SESSION="b"*32


def snapshot(*, disconnected=True, key="", tab_id=12, observed_at=100.0):
    node={"conversation_uuid":OLD,"status":"CONFIRMED",
          "source":"RCC_FRESH",
          "connection":{"disconnected":disconnected},
          "generating":False}
    return {"monitor":{"current_nodes":{"observation":{"state":"FRESH"},"observed_at":observed_at,"items":[node]},
            "rcc":{"instances":[{"state":"OPEN","instance_id":INSTANCE,
                                  "session_id":SESSION,"tabs":[{
                                      "tab_id":tab_id,"window_id":34,
                                      "conversation_key":key,"presence":"OPEN",
                                  }]}]}}}


class SuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"s.sqlite")
        self.store.create_work(Work(
            work_id="w",request_summary="isolated",
            roots=(self.tmp.name,),actions=frozenset({"browser"}),
            owner_principal_id="principal",
        ))
        self.loop=LoopStore(self.store)
        self.loop.start(work_id="w",direction_id="d",task_id="t",
                        owner=OLD,plan_text="plan",now=100)
        self.ledger=LoopSuccessorLedger(self.store)
        self.created=None
        self.sent=None
        def get_receipt(**kw):
            if self.created and kw["operation_id"]==self.created["create_op"]:
                return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                       outcome=SimpleNamespace(value="APPLIED"),
                                       evidence={"command":"create-chat-tab",
                                       "instance_id":INSTANCE,
                                       "created_request_id":self.created["create_op"],
                                       "created_tab_id":12,"created_window_id":34})
            if self.sent and kw["operation_id"]==self.sent["send_op"]:
                return SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                                       outcome=SimpleNamespace(value="APPLIED"),
                                       evidence={"conversation_key":NEW,
                                                 "command":"send-to-created-tab",
                                                 "host_request_id":self.sent["send_op"],
                                                 "source_message_sha256":self.sent["handoff_text_sha"],
                                                 "instance_id":INSTANCE})
            raise KeyError()
        self.store.get_operation_for=get_receipt

    def prepare(self):
        return self.ledger.prepare(work_id="w",snapshot_a=snapshot(observed_at=100),
                                   snapshot_b=snapshot(observed_at=103),instance_id=INSTANCE,
                                   window_id=34,now=161)

    def test_two_fresh_disconnections_required(self):
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_NOT_PROVEN_UNAVAILABLE"):
            self.ledger.prepare(work_id="w",snapshot_a=snapshot(observed_at=100),
                                snapshot_b=snapshot(disconnected=False,observed_at=103),
                                instance_id=INSTANCE,window_id=34,now=161)
        self.assertIsNone(self.ledger.get("w"))

    def test_no_create_receipt_stays_unconfirmed(self):
        self.created=self.prepare()
        self.assertEqual(self.created["state"],"CREATE_INTENT")
        self.created=None  # no original external create receipt was persisted
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_CREATE_RECEIPT_UNKNOWN"):
            self.ledger.confirm_create(work_id="w",principal_id="principal",
                                       snapshot=snapshot(),now=162)
        self.assertEqual(self.ledger.get("w")["state"],"CREATE_INTENT")
        self.assertEqual(self.loop.get("w")["epoch"],1)

    def test_blank_tab_cannot_be_successor(self):
        self.created=self.prepare()
        self.ledger.confirm_create(work_id="w",principal_id="principal",
                                   snapshot=snapshot(),now=162)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_SEND_RECEIPT_UNKNOWN"):
            self.ledger.bind_successor(work_id="w",principal_id="principal",
                                       snapshot=snapshot(),now=163)

    def test_full_inheritance_and_fencing(self):
        self.created=self.prepare()
        self.ledger.confirm_create(work_id="w",principal_id="principal",
                                   snapshot=snapshot(),now=162)
        from bct.send_delayed_message import _rcc_submitted_text_sha256
        self.sent=self.ledger.reserve_effect(
            work_id="w",kind="send",
            handoff_text_sha=_rcc_submitted_text_sha256("INHERITANCE"),
            now=162.5,
        )
        identified=self.ledger.bind_successor(work_id="w",principal_id="principal",
                                               snapshot=snapshot(key=NEW),now=163)
        self.assertEqual(identified["successor"],NEW)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_RESPONSE_UNVERIFIED"):
            self.ledger.verify_handoff(work_id="w",principal_id="principal",
                                       successor_response={},expected_response_sha="a"*64,now=164)
        from hashlib import sha256
        body="LOOP_SUCCESSOR_READY"
        digest=sha256(body.encode()).hexdigest()
        response={"conversationKey":NEW,"terminal":True,"generating":False,
                  "observationState":"TERMINAL","responseText":body,
                  "responseSha256":digest,"responseTurnKey":"reply-one",
                  "responseSourceUserSha256":self.sent["handoff_text_sha"],
                  "latestUserSha256":self.sent["handoff_text_sha"],
                  "responseSourceUserTurnKey":"turn-one",
                  "latestUserTurnKey":"turn-one"}
        self.ledger.verify_handoff(work_id="w",principal_id="principal",
                                   successor_response=response,
                                   expected_response_sha=digest,now=164)
        from bct.node_recovery import NodeRecoveryLedger, observe_node
        from bct.status_views import status_view
        recovery=NodeRecoveryLedger(self.store)
        work=self.store.get_work("w")
        proof=observe_node(status_view(snapshot(),"node"),conversation_key=OLD)
        recovery.check(work=work,case_id="loop-fence-"+hashlib.sha256(b"w:1").hexdigest()[:24],task_id="t",
                       conversation_key=OLD,evidence=proof,kind="CHECK")
        recovery.pause(work=work,case_id="loop-fence-"+hashlib.sha256(b"w:1").hexdigest()[:24],
                       reason="proven first reply")
        result=self.ledger.finish(work_id="w",now=165)
        self.assertEqual(result["epoch"],2)
        self.assertEqual(result["owner"],NEW)
        with self.assertRaisesRegex(LoopStateError,"LOOP_FENCED"):
            self.loop.prepare_operation(work_id="w",owner=OLD,epoch=1,
                                        operation_id="old-send",now=166)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_HANDOFF_NOT_ACKED"):
            self.ledger.finish(work_id="w",now=167)


if __name__=="__main__":
    unittest.main()
