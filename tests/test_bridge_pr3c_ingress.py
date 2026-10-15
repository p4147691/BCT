import json
import hashlib
import unittest
from unittest.mock import patch
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.bridge_pr3b_auth import ORIGIN,AUDIENCE
from bct.core.bridge_pr3c_ingress import ingress,parse_envelope,MAX_BYTES
from bct.core.bridge_pr3a_safe import delivery_receipt_get, fake_send
from bct.core.durable_pr2 import commit_and_enqueue
from test_bridge_pr3b_auth import PR3BAuthTests
from test_durable_pr2 import PR2Tests

class IngressTests(PR3BAuthTests):
    def frame(self, credential, operation="completion_report", request_id="one", arguments=None, **changes):
        data=dict(version=1,operation=operation,request_id=request_id,origin=ORIGIN,
                  audience=AUDIENCE,credential=credential,session_id="s",node_id="worker",
                  attachment_id="att",generation=1,
                  arguments=self.completion() if arguments is None else arguments)
        data.update(changes)
        return json.dumps(data,separators=(",",":"),allow_nan=False).encode()
    def test_ingress_completion_read_replay(self):
        token=self.grant()
        frame=self.frame(token)
        self.assertFalse(ingress(self.s,frame)["duplicate"])
        with self.assertRaises(ConflictError):ingress(Store(self.s.path),frame)
        read=self.grant("result_get")
        self.assertEqual("r",ingress(self.s,self.frame(read,operation="result_get",
                request_id="read",arguments={"event_id":"evt"}))["result_id"])
    def test_ingress_malformed_and_wrong_scope(self):
        credential=self.grant()
        valid=self.frame(credential)
        bad=[b"",b"\xff",b"{}",valid+b"invalid",b"[" + valid + b"]",
             b'{"version":1,"version":1}',b" "*(MAX_BYTES+1)]
        for key,value in (("version",2),("operation","other"),("origin","foreign"),
                          ("audience","foreign"),("generation",0),
                          ("request_id",123),("arguments",{"event_id":"evt"}),
                          ("unexpected",True)):
            bad.append(self.frame(credential,**{key:value}))
        for frame in bad:
            with self.subTest(frame=frame[:40]),self.assertRaises(ConflictError):
                ingress(self.s,frame)
    def test_ingress_scope_expiry_revoke_and_replay_conflict(self):
        token=self.grant()
        for change in ({"node_id":"other"},{"session_id":"foreign"},
                       {"attachment_id":"foreign"},{"generation":2}):
            with self.assertRaises(ConflictError):ingress(self.s,self.frame(token,**change))
        with patch("bct.core.bridge_pr3b_auth.time.time",return_value=201.):
            with self.assertRaises(ConflictError):ingress(self.s,self.frame(token))
        self.assertFalse(ingress(self.s,self.frame(token))["duplicate"])
        with self.assertRaises(ConflictError):
            ingress(self.s,self.frame(token,arguments={**self.completion(),"event_id":"changed"}))
        from bct.core.bridge_pr3b_auth import revoke
        revoke(self.s,credential=token)
        with self.assertRaises(ConflictError):
            ingress(self.s,self.frame(token,request_id="after-revoke"))
    def test_authorized_then_core_stale(self):
        token=self.grant()
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_assignments SET current_generation=2 WHERE assignment_id='result'")
        with self.assertRaises(ConflictError):ingress(self.s,self.frame(token))

    def _prepare_unknown_delivery(self):
        from test_bridge_pr3a_safe import Fake
        commit_and_enqueue(self.s, **PR2Tests.args(self))
        self.assertEqual("UNKNOWN", fake_send(self.s, delivery_id="stable-id", epoch=2,
                         token=self.lease["token"], transport=Fake(sent=False), now=103.))
        receipt=delivery_receipt_get(self.s, session_id="s", delivery_id="stable-id")
        digest=hashlib.sha256(receipt["payload_json"].encode()).hexdigest()
        command=hashlib.sha256(("stable-id:"+digest).encode()).hexdigest()
        proof=dict(recipient_node_id="worker", attachment_id="att", generation=1,
                   processed_command_id=command, ack_digest="ack",
                   verified_by="isolated_fake_transport")
        return dict(delivery_id="stable-id", command_id=command, target_node_id="worker",
                    attachment_id="att", attachment_generation=1, assignment_id="next",
                    assignment_generation=1, payload_digest=digest, ack_digest="ack",
                    recipient_proof=proof, epoch=2, token=self.lease["token"])

    def test_ingress_delivery_receipt_unknown_and_ack(self):
        ack=self._prepare_unknown_delivery()
        receipt_token=self.grant("delivery_receipt_get")
        receipt=ingress(self.s,self.frame(receipt_token,operation="delivery_receipt_get",
                        request_id="receipt",arguments={"session_id":"s","delivery_id":"stable-id"}))
        self.assertEqual("UNKNOWN", receipt["state"])
        ack_token=self.grant("recipient_ack")
        with patch("bct.core.bridge_pr3c_ingress.time.time",return_value=105.):
            self.assertFalse(ingress(self.s,self.frame(ack_token,operation="recipient_ack",
                             request_id="ack",arguments=ack))["duplicate"])
        self.assertEqual("ACKNOWLEDGED",delivery_receipt_get(self.s,session_id="s",delivery_id="stable-id")["state"])

    def test_ingress_ack_cannot_backdate_expired_lease_or_stale_attachment(self):
        ack=self._prepare_unknown_delivery()
        token=self.grant("recipient_ack")
        with patch("bct.core.bridge_pr3c_ingress.time.time",return_value=201.):
            with self.assertRaises(ConflictError):
                ingress(self.s,self.frame(token,operation="recipient_ack",request_id="expired",arguments=ack))
        self.assertEqual("UNKNOWN",delivery_receipt_get(self.s,session_id="s",delivery_id="stable-id")["state"])
        # A caller cannot smuggle a historical now field through the strict schema.
        with self.assertRaises(ConflictError):
            ingress(self.s,self.frame(self.grant("recipient_ack"),operation="recipient_ack",
                    request_id="forged-now",arguments={**ack,"now":105.}))
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='att'")
        with patch("bct.core.bridge_pr3c_ingress.time.time",return_value=105.):
            with self.assertRaises(ConflictError):
                ingress(self.s,self.frame(self.grant("recipient_ack"),operation="recipient_ack",
                        request_id="stale",arguments=ack))

    def test_ingress_rejects_nonfinite_nested_number(self):
        raw=self.frame(self.grant("recipient_ack"),operation="recipient_ack",arguments={
            "delivery_id":"d","command_id":"c","target_node_id":"worker","attachment_id":"att",
            "attachment_generation":1,"assignment_id":"a","assignment_generation":1,
            "payload_digest":"p","ack_digest":"a","recipient_proof":{"generation":1},
            "epoch":2,"token":"t"})
        raw=raw.replace(b'"generation":1}', b'"generation":1e999}')
        with self.assertRaises(ConflictError):
            ingress(self.s,raw)

if __name__=="__main__":unittest.main()
