import unittest
import sqlite3
from unittest.mock import patch
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.orchestration import _digest
from bct.core.durable_pr2 import commit_and_enqueue
from bct.core.bridge_pr3a_safe import install_schema as install_pr3a, completion_report
from bct.core.bridge_pr3b_auth import (install_schema,issue_fake_grant,revoke,call,ORIGIN,AUDIENCE,
                                       create_fake_issuer_fixture,close_fake_issuer_fixture)
from test_durable_pr2 import PR2Tests

class PR3BAuthTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch("bct.core.bridge_pr3b_auth.time.time",return_value=100.)
        self.clock.start();self.addCleanup(self.clock.stop)
        PR2Tests.setUp(self)
        # Copy the fixture database into a newly minted, authority-bound Store.
        fixture, self.issuer = create_fake_issuer_fixture()
        self.addCleanup(close_fake_issuer_fixture, self.issuer)
        source=self.s._connect()
        target=fixture._connect()
        try:
            source.backup(target)
        finally:
            target.close(); source.close()
        self.s=fixture
        install_pr3a(self.s); install_schema(self.s)
        self.kw=dict(session_id="s",node_id="worker",attachment_id="att",generation=1,
                     origin=ORIGIN,audience=AUDIENCE,now=102.)
    def grant(self,operation="completion_report"):
        return issue_fake_grant(self.s,session_id="s",node_id="worker",attachment_id="att",
                                generation=1,operation=operation,expires_at=200.,issuer=self.issuer)
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
        with patch("bct.core.bridge_pr3b_auth.time.time",return_value=201.):
            with self.assertRaises(ConflictError):self.invoke(token,now=-100.)
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
    def test_cross_session_result_denied(self):
        token=self.grant('result_get')
        with patch('bct.core.bridge_pr3b_auth.result_get',
                   return_value={'session_id':'foreign','source_node_id':'worker','result_id':'r'}):
            with self.assertRaisesRegex(ConflictError,'CAPABILITY_SCOPE_DENIED'):
                self.invoke(token,operation='result_get',arguments={'event_id':'foreign'},request_id='cross')

    def test_trusted_clock_boundary_and_nan(self):
        token=self.grant()
        for clock in (200., 201., float('nan'), float('inf')):
            with patch('bct.core.bridge_pr3b_auth.time.time',return_value=clock):
                with self.assertRaises(ConflictError):self.invoke(token,request_id='clock',now=-1e12)
        with patch('bct.core.bridge_pr3b_auth.time.time',return_value=199.999):
            self.assertFalse(self.invoke(token,request_id='preexpiry',now=float('nan'))['duplicate'])

    def test_same_path_name_cannot_forge_fixture_authority(self):
        # An identical Store path is insufficient: issuer binds to Store identity.
        lookalike=Store(self.s.path)
        with self.assertRaisesRegex(ConflictError,'FIXTURE_ONLY'):
            issue_fake_grant(lookalike,session_id='s',node_id='worker',attachment_id='att',
                             generation=1,operation='result_get',expires_at=200.,issuer=self.issuer)
        with self.assertRaisesRegex(ConflictError,'FIXTURE_ONLY'):
            issue_fake_grant(self.s,session_id='s',node_id='worker',attachment_id='att',
                             generation=1,operation='result_get',expires_at=200.,issuer=object())

    def test_fake_issuance_rejects_operational_store(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as d:
            operational=Store(Path(d)/'operational.db')
            install_schema(operational)
            with self.assertRaisesRegex(ConflictError,'FIXTURE_ONLY'):
                issue_fake_grant(operational,session_id='s',node_id='worker',attachment_id='att',
                                 generation=1,operation='result_get',expires_at=200.)

    def test_closed_fixture_issuer_cannot_issue_again(self):
        fixture, issuer = create_fake_issuer_fixture()
        close_fake_issuer_fixture(issuer)
        with self.assertRaisesRegex(ConflictError, 'FIXTURE_ONLY'):
            issue_fake_grant(fixture, session_id='s', node_id='worker', attachment_id='att',
                             generation=1, operation='result_get', expires_at=200., issuer=issuer)

    def test_ack_authorized_path_and_replay(self):
        from bct.core.durable_pr2 import reserve_delivery,record_attempt
        import hashlib
        commit_and_enqueue(self.s,**PR2Tests.args(self))
        reservation=reserve_delivery(self.s,delivery_id='stable-id',epoch=2,token=self.lease['token'],now=102.)
        args=dict(delivery_id='stable-id',epoch=2,token=self.lease['token'],
                  reservation_token=reservation['reservation_token'])
        record_attempt(self.s,**args,phase='SEND_STARTED',now=103.)
        record_attempt(self.s,**args,phase='DELIVERED',now=104.)
        row=__import__('bct.core.bridge_pr3a_safe',fromlist=['delivery_receipt_get']).delivery_receipt_get(
            self.s,session_id='s',delivery_id='stable-id')
        digest=hashlib.sha256(row['payload_json'].encode()).hexdigest()
        cmd=hashlib.sha256(('stable-id:'+digest).encode()).hexdigest()
        proof=dict(recipient_node_id='worker',attachment_id='att',generation=1,
                   processed_command_id=cmd,ack_digest='ack',verified_by='isolated_fake_transport')
        payload=dict(delivery_id='stable-id',command_id=cmd,target_node_id='worker',attachment_id='att',
                     attachment_generation=1,assignment_id='next',assignment_generation=1,
                     payload_digest=digest,ack_digest='ack',recipient_proof=proof,
                     epoch=2,token=self.lease['token'],now=105.)
        token=self.grant('recipient_ack')
        self.assertFalse(self.invoke(token,operation='recipient_ack',request_id='ack',arguments=payload)['duplicate'])
        with self.assertRaises(ConflictError):
            self.invoke(token,operation='recipient_ack',request_id='ack',arguments=payload)
        self.assertEqual('ACKNOWLEDGED',__import__('bct.core.bridge_pr3a_safe',
            fromlist=['delivery_receipt_get']).delivery_receipt_get(self.s,session_id='s',delivery_id='stable-id')['state'])
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
