import unittest
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.orchestration import _digest
from bct.core.durable_pr2 import commit_and_enqueue
from bct.core.bridge_pr3a_safe import install_schema as install_pr3a, completion_report
from bct.core.bridge_pr3b_auth import (install_schema,issue_fake_grant,revoke,call,ORIGIN,AUDIENCE)
from test_durable_pr2 import PR2Tests

class PR3BAuthTests(unittest.TestCase):
    def setUp(self):
        PR2Tests.setUp(self)
        install_pr3a(self.s); install_schema(self.s)
        self.kw=dict(session_id="s",node_id="worker",attachment_id="att",generation=1,
                     origin=ORIGIN,audience=AUDIENCE,now=102.)
    def grant(self,operation="completion_report"):
        return issue_fake_grant(self.s,session_id="s",node_id="worker",attachment_id="att",
                                generation=1,operation=operation,expires_at=200.)
    def completion(self):
        return dict(event_id="evt",session_id="s",assignment_id="result",generation=1,
                    source_node_id="worker",result_id="r",result_digest=_digest({"message":"result"}))
    def invoke(self,credential,operation="completion_report",request_id="nonce",arguments=None,**kw):
        params=dict(credential=credential,request_id=request_id,operation=operation,
                    arguments=self.completion() if arguments is None else arguments,**self.kw)
        params.update(kw)
        return call(Store(self.s.path),**params)
    def test_success_reopen_and_one_shot_replay(self):
        token=self.grant()
        self.assertFalse(self.invoke(token)["duplicate"])
        with self.assertRaisesRegex(ConflictError,"CAPABILITY_REPLAY_DENIED"):
            self.invoke(token)
        with self.assertRaisesRegex(ConflictError,"CAPABILITY_REPLAY_CONFLICT"):
            self.invoke(token,arguments={**self.completion(),"event_id":"altered"})
        token2=self.grant("result_get")
        receipt=self.invoke(token2,operation="result_get",arguments={"event_id":"evt"},request_id="read")
        self.assertEqual("r",receipt["result_id"])
    def test_wrong_bindings(self):
        token=self.grant()
        for field,value in (("origin","chrome-extension://foreign/"),("audience","other"),
                            ("node_id","other"),("session_id","other"),("operation","result_get"),
                            ("generation",2),("attachment_id","different")):
            with self.subTest(field=field),self.assertRaises(ConflictError):
                self.invoke(token,**{field:value})
        with self.assertRaises(ConflictError):
            self.invoke(token+"bad")
    def test_expiry_and_revoke(self):
        token=self.grant()
        with self.assertRaises(ConflictError):self.invoke(token,now=201.)
        revoke(self.s,credential=token)
        with self.assertRaises(ConflictError):self.invoke(token)
    def test_stale_attachment(self):
        token=self.grant()
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='att'")
        with self.assertRaises(ConflictError):self.invoke(token)
    def test_authorization_does_not_override_core_fence(self):
        token=self.grant()
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_assignments SET current_generation=2 WHERE assignment_id='result'")
        with self.assertRaises(ConflictError):self.invoke(token)
    def test_delivery_receipt_fences_target(self):
        commit_and_enqueue(self.s,**PR2Tests.args(self))
        token=self.grant("delivery_receipt_get")
        data=self.invoke(token,operation="delivery_receipt_get",request_id="receipt",
                         arguments={"session_id":"s","delivery_id":"stable-id"})
        self.assertEqual("PENDING",data["state"])
        with self.assertRaises(ConflictError):
            self.invoke(self.grant("delivery_receipt_get"),operation="delivery_receipt_get",
                        request_id="foreign",arguments={"session_id":"other","delivery_id":"stable-id"})
if __name__=="__main__":unittest.main()
