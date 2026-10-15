import json
import unittest
from unittest.mock import patch
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.bridge_pr3b_auth import ORIGIN,AUDIENCE
from bct.core.bridge_pr3c_ingress import ingress,parse_envelope,MAX_BYTES
from test_bridge_pr3b_auth import PR3BAuthTests

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

if __name__=="__main__":unittest.main()
