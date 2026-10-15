import hashlib
import unittest
from unittest.mock import patch
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.orchestration import _digest
from bct.core.durable_pr2 import commit_and_enqueue,create_wake,reserve_wake,record_wake,recovery_snapshot,reserve_delivery,record_attempt,acknowledge_delivery
from bct.core.bridge_pr3a_safe import (install_schema,completion_report,result_get,delivery_request,
                                       delivery_receipt_get,fake_send,recipient_ack)
from test_durable_pr2 import PR2Tests

class Fake:
    def __init__(self,ready=True,sent=True):self.ready=ready;self.sent=sent;self.calls=0
    def send(self,*args):self.calls+=1;return self.sent

class BridgeSafeTests(unittest.TestCase):
    def setUp(self):
        PR2Tests.setUp(self)
        install_schema(self.s)
    def completion(self):
        return dict(event_id="e",session_id="s",assignment_id="result",generation=1,source_node_id="worker",
                    result_id="r",result_digest=_digest({"message":"result"}))
    def delivery(self):
        return dict(delivery_id="stable-id",session_id="s",target_node_id="worker",attachment_id="att",
                    attachment_generation=1,assignment_id="next",assignment_generation=1)
    def test_full_fake_restart_and_ack(self):
        self.assertFalse(completion_report(self.s,**self.completion())["duplicate"])
        self.assertTrue(completion_report(self.s,**self.completion())["duplicate"])
        self.assertEqual("r",result_get(Store(self.s.path),event_id="e")["result_id"])
        create_wake(self.s,wake_id="wake",session_id="s",assignment_id="result",generation=1,
                    result_message_id="r",result_digest=self.completion()["result_digest"])
        w=reserve_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],now=102.)
        record_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],reservation_token=w["reservation_token"],
                    outcome="DELIVERED",now=103.)
        commit_and_enqueue(self.s,**PR2Tests.args(self))
        self.assertEqual("PENDING",delivery_request(self.s,**self.delivery())["state"])
        fake=Fake()
        self.assertEqual("SENT",fake_send(Store(self.s.path),delivery_id="stable-id",epoch=2,
                              token=self.lease["token"],transport=fake,now=104.))
        rec=delivery_receipt_get(self.s,session_id="s",delivery_id="stable-id")
        self.assertEqual("DELIVERED",rec["state"])
        payload_digest=hashlib.sha256(rec["payload_json"].encode()).hexdigest()
        command_id=hashlib.sha256(("stable-id:"+payload_digest).encode()).hexdigest()
        proof=dict(recipient_node_id="worker",attachment_id="att",generation=1,
                   processed_command_id=command_id,ack_digest="ack",verified_by="isolated_fake_transport")
        args=dict(delivery_id="stable-id",command_id=command_id,target_node_id="worker",attachment_id="att",
                  attachment_generation=1,assignment_id="next",assignment_generation=1,
                  payload_digest=payload_digest,ack_digest="ack",recipient_proof=proof,
                  epoch=2,token=self.lease["token"],now=105.)
        self.assertFalse(recipient_ack(self.s,**args)["duplicate"])
        self.assertTrue(recipient_ack(Store(self.s.path),**args)["duplicate"])
        self.assertEqual("ACKNOWLEDGED",delivery_receipt_get(self.s,session_id="s",delivery_id="stable-id")["state"])
    def test_payload_tamper_and_completion_conflict(self):
        completion_report(self.s,**self.completion())
        with self.assertRaises(ConflictError):
            completion_report(self.s,**{**self.completion(),"source_node_id":"foreign"})
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_mailbox SET payload_json=? WHERE message_id='r'",('{"message":"tampered"}',))
        with self.assertRaises(ConflictError):result_get(self.s,event_id="e")
        with self.assertRaises(ConflictError):completion_report(self.s,**self.completion())
    def test_stale_assignment_detached_recipient(self):
        commit_and_enqueue(self.s,**PR2Tests.args(self))
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_assignments SET current_generation=2 WHERE assignment_id='next'")
        with self.assertRaises(ConflictError):delivery_request(self.s,**self.delivery())
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_assignments SET current_generation=1 WHERE assignment_id='next'")
            db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='att'")
        with self.assertRaises(ConflictError):delivery_request(self.s,**self.delivery())
    def test_unknown_no_retry_stale_epoch(self):
        commit_and_enqueue(self.s,**PR2Tests.args(self))
        for epoch,token in ((1,self.lease["token"]),(2,"wrong")):
            with self.assertRaises(ConflictError):fake_send(self.s,delivery_id="stable-id",epoch=epoch,token=token,
                                                               transport=Fake(),now=102.)
        self.assertEqual("PRE_SEND_ABORT",fake_send(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                                                    transport=Fake(ready=False),now=102.))
        fake=Fake(sent=False)
        self.assertEqual("UNKNOWN",fake_send(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                                             transport=fake,now=103.))
        with self.assertRaises(ConflictError):fake_send(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                                                         transport=fake,now=104.)
        self.assertEqual(1,fake.calls)
        self.assertEqual([],recovery_snapshot(Store(self.s.path),session_id="s")["resendable"])
    def test_ack_atomic_fence_after_validation_invalidation(self):
        for kind in ("attachment", "assignment"):
            with self.subTest(kind=kind):
                self.setUp()
                commit_and_enqueue(self.s,**PR2Tests.args(self))
                reservation=reserve_delivery(self.s,delivery_id="stable-id",epoch=2,
                    token=self.lease["token"],now=102.)
                kw=dict(delivery_id="stable-id",epoch=2,token=self.lease["token"],
                        reservation_token=reservation["reservation_token"])
                record_attempt(self.s,**kw,phase="SEND_STARTED",now=103.)
                record_attempt(self.s,**kw,phase="DELIVERED",now=104.)
                receipt=delivery_receipt_get(self.s,session_id="s",delivery_id="stable-id")
                digest=hashlib.sha256(receipt["payload_json"].encode()).hexdigest()
                command=hashlib.sha256(("stable-id:"+digest).encode()).hexdigest()
                proof=dict(recipient_node_id="worker",attachment_id="att",generation=1,
                    processed_command_id=command,ack_digest="ack",verified_by="isolated_fake_transport")
                args=dict(delivery_id="stable-id",command_id=command,target_node_id="worker",
                    attachment_id="att",attachment_generation=1,assignment_id="next",
                    assignment_generation=1,payload_digest=digest,ack_digest="ack",
                    recipient_proof=proof,epoch=2,token=self.lease["token"],now=105.)
                def injected(store, **kwargs):
                    db=kwargs["_db"]
                    if kind=="attachment":
                        db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='att'")
                    else:
                        db.execute("UPDATE orchestration_assignments SET current_generation=2 WHERE assignment_id='next'")
                    return acknowledge_delivery(store,**kwargs)
                with patch("bct.core.bridge_pr3a_safe.acknowledge_delivery",side_effect=injected):
                    with self.assertRaises(ConflictError):
                        recipient_ack(self.s,**args)
                state=delivery_receipt_get(Store(self.s.path),session_id="s",delivery_id="stable-id")
                self.assertEqual("DELIVERED",state["state"])
                self.assertIsNone(state["ack_digest"])
    def test_foreign_ack_proof_denied(self):
        commit_and_enqueue(self.s,**PR2Tests.args(self))
        rec=delivery_receipt_get(self.s,session_id="s",delivery_id="stable-id")
        digest=hashlib.sha256(rec["payload_json"].encode()).hexdigest()
        cmd=hashlib.sha256(("stable-id:"+digest).encode()).hexdigest()
        for proof in ({},dict(recipient_node_id="foreign",attachment_id="att",generation=1,
                              processed_command_id=cmd,ack_digest="ack",verified_by="isolated_fake_transport")):
            with self.assertRaises(ConflictError):
                recipient_ack(self.s,delivery_id="stable-id",command_id=cmd,target_node_id="worker",
                              attachment_id="att",attachment_generation=1,assignment_id="next",
                              assignment_generation=1,payload_digest=digest,ack_digest="ack",
                              recipient_proof=proof,epoch=2,token=self.lease["token"],now=102.)

if __name__=="__main__":unittest.main()
