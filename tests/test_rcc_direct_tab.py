from __future__ import annotations
import unittest
from bct.core.models import Work,PreconditionError
from bct.features.rcc import RelayBrowserFeature
class DirectTabPrepareTests(unittest.TestCase):
    def setUp(self):
        self.feature=RelayBrowserFeature()
        self.work=Work("bounded-work","test",("D:\\BCT\\source",),frozenset({"relay_browser"}),"owner")
        self.args=dict(command="send-to-tab",instance_id="6174664e1c1b4e6db1d4729c841db3c9",session_id="786b7b6b9671446f85497e097111e5ec",tab_id=594834261,window_id=594834176,conversation_key="",text="test")
    def test_single_command_and_work_scoped_resource(self):
        req=self.feature.prepare(work=self.work,arguments=self.args)
        self.assertEqual("relay_browser",req.capability)
        self.assertEqual(("rcc-instance:6174664e1c1b4e6db1d4729c841db3c9:direct-tab:594834261",),req.resources)
        self.assertTrue(req.preconditions["mutating"])
        self.assertEqual(self.work.work_id,req.arguments["extra"]["workId"])

    def test_host_submission_ack_is_checked_against_exact_tab(self):
        from bct.core.models import Outcome,UnknownEffectError
        base=self.args.copy()
        request=self.feature.prepare(work=self.work,arguments=base)
        class FakeHost:
            def __init__(self,wrong=False):
                self.wrong=wrong
                self.calls=[]
            def request(self,**kwargs):
                self.calls.append(kwargs)
                return {"ok":True,"state":"SUBMITTED","operationId":kwargs["request_id"],
                        "instanceId":kwargs["instance_id"],
                        "sessionId":base["session_id"],
                        "tabId":base["tab_id"]+(1 if self.wrong else 0),
                        "windowId":base["window_id"],"submitted":True}
        good=FakeHost()
        self.feature.client=good
        result=self.feature.execute(request)
        self.assertEqual(Outcome.APPLIED,result.outcome)
        self.assertEqual("send-to-tab",good.calls[0]["command"])
        self.assertEqual("bounded-work",good.calls[0]["extra"]["workId"])
        bad=FakeHost(wrong=True)
        self.feature.client=bad
        with self.assertRaises(UnknownEffectError):
            self.feature.execute(request)

    def test_node_harness_one_call_idempotent_and_tab_scoped(self):
        import subprocess,shutil
        from pathlib import Path
        exe=shutil.which("node")
        if not exe:self.skipTest("node unavailable")
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([exe,str(root/"modules/rcc/extension/test_direct_tab_send.js")],
                              cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              timeout=30,check=False)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertIn("RCC_DIRECT_TAB_TEST_PASS",result.stdout)

    def test_blank_requires_explicit_identity(self):
        for change in [{"session_id":""},{"tab_id":0},{"window_id":0},{"text":""},{"conversation_key":"bad"},{"extra":"untrusted"}]:
            with self.subTest(change=change):
                with self.assertRaises(PreconditionError):
                    self.feature.prepare(work=self.work,arguments={**self.args,**change})
