import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.orchestration import _digest
from bct.core.durable_pr2 import commit_and_enqueue, create_wake, reserve_wake, record_wake, recovery_snapshot
from bct.core.browser_bridge_pr3a import (install_bridge_schema, completion_report, result_get,
    delivery_request, delivery_receipt_get, recipient_ack, fake_send)

from test_durable_pr2 import PR2Tests

class Transport:
    def __init__(self,ready=True,delivered=True):
        self.ready=ready
        self.delivered=delivered
        self.calls=0
    def send(self, delivery_id, target):
        self.calls+=1
        return self.delivered

class PR3FakeBoundaryTests(unittest.TestCase):
    def setUp(self):
        PR2Tests.setUp(self)
        install_bridge_schema(self.s)
    def args(self):
        return PR2Tests.args(self)
    def completion(self):
        return dict(event_id="evt",session_id="s",assignment_id="result",generation=1,
                    source_node_id="worker",result_message_id="r",result_digest=_digest({"message":"result"}))
    def test_end_to_end_restart_retrieval_ack_dedupe(self):
        self.assertFalse(completion_report(self.s,**self.completion())["duplicate"])
        self.assertTrue(completion_report(self.s,**self.completion())["duplicate"])
        self.assertEqual("worker",result_get(Store(self.s.path),event_id="evt")["source_node_id"])
        create_wake(self.s,wake_id="wake",session_id="s",assignment_id="result",generation=1,
                    result_message_id="r",result_digest=_digest({"message":"result"}))
        w=reserve_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],now=102.)
        record_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],
                    reservation_token=w["reservation_token"],outcome="DELIVERED",now=103.)
        commit_and_enqueue(self.s,**self.args())
        data=delivery_request(self.s,delivery_id="stable-id",session_id="s",target_node_id="worker",
                    attachment_id="att",attachment_generation=1,assignment_id="next",assignment_generation=1)
        self.assertEqual("PENDING",data["state"])
        bridge=Store(self.s.path)
        transport=Transport()
        self.assertEqual("SENT",fake_send(bridge,delivery_id="stable-id",epoch=2,
                         token=self.lease["token"],transport=transport,now=104.))
        self.assertEqual("DELIVERED",delivery_receipt_get(bridge,delivery_id="stable-id",session_id="s")["state"])
        row=delivery_receipt_get(bridge,delivery_id="stable-id",session_id="s")
        digest=hashlib.sha256(row["payload_json"].encode()).hexdigest()
        command=hashlib.sha256(("stable-id:"+digest).encode()).hexdigest()
        kw=dict(delivery_id="stable-id",command_id=command,target_node_id="worker",attachment_id="att",
                attachment_generation=1,payload_digest=digest,ack_digest="ack",epoch=2,token=self.lease["token"],now=105.)
        self.assertFalse(recipient_ack(bridge,**kw)["duplicate"])
        self.assertTrue(recipient_ack(Store(self.s.path),**kw)["duplicate"])
        self.assertEqual("ACKNOWLEDGED",delivery_receipt_get(bridge,delivery_id="stable-id",session_id="s")["state"])
        self.assertEqual([],recovery_snapshot(Store(self.s.path),session_id="s")["resendable"])
    def test_foreign_source_and_duplicate_conflicts(self):
        completion_report(self.s,**self.completion())
        with self.assertRaises(ConflictError):
            completion_report(self.s,**{**self.completion(),"source_node_id":"foreign"})
        with self.assertRaises(ConflictError):
            completion_report(self.s,**{**self.completion(),"result_digest":"wrong"})
    def test_foreign_target_and_generation(self):
        commit_and_enqueue(self.s,**self.args())
        for k,v in (("target_node_id","foreign"),("attachment_generation",9),
                    ("assignment_generation",9)):
            args=dict(delivery_id="stable-id",session_id="s",target_node_id="worker",
                  attachment_id="att",attachment_generation=1,assignment_id="next",assignment_generation=1)
            args[k]=v
            with self.assertRaises(ConflictError): delivery_request(self.s,**args)
    def test_pre_send_abort_and_unknown_do_not_retry(self):
        commit_and_enqueue(self.s,**self.args())
        self.assertEqual("PRE_SEND_ABORT",fake_send(self.s,delivery_id="stable-id",epoch=2,
                         token=self.lease["token"],transport=Transport(ready=False),now=102.))
        transport=Transport(delivered=False)
        self.assertEqual("UNKNOWN",fake_send(self.s,delivery_id="stable-id",epoch=2,
                        token=self.lease["token"],transport=transport,now=103.))
        with self.assertRaises(ConflictError):
            fake_send(Store(self.s.path),delivery_id="stable-id",epoch=2,
                      token=self.lease["token"],transport=transport,now=104.)
        self.assertEqual(1,transport.calls)
        self.assertEqual([],recovery_snapshot(self.s,session_id="s")["resendable"])
    def test_stale_epoch_token_fenced(self):
        commit_and_enqueue(self.s,**self.args())
        for epoch,token in ((1,self.lease["token"]),(2,"foreign")):
            with self.assertRaises(ConflictError):
                fake_send(self.s,delivery_id="stable-id",epoch=epoch,
                         token=token,transport=Transport(),now=102.)

if __name__=="__main__":unittest.main()
