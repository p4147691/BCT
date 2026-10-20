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

    def test_simple_relay_has_no_tab_or_session_input(self):
        args = {
            "command": "simple-relay-bind",
            "instance_id": "6174664e1c1b4e6db1d4729c841db3c9",
            "manager_conversation_key": "6ad5afa4-b1e0-83ee-8692-aec4bb51523e",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
        }
        bound = self.feature.prepare(work=self.work, arguments=args)
        self.assertEqual(("rcc-instance:6174664e1c1b4e6db1d4729c841db3c9:simple-relay:binding",), bound.resources)
        self.assertNotIn("tabId", bound.arguments["extra"])
        send = self.feature.prepare(work=self.work, arguments={
            "command": "simple-relay-send", "instance_id": args["instance_id"],
            "from": "manager", "text": "원문 그대로 보냅니다.",
        })
        self.assertEqual("manager", send.arguments["extra"]["from"])
        self.assertEqual("원문 그대로 보냅니다.", send.arguments["text"])
        self.assertEqual(("rcc-instance:6174664e1c1b4e6db1d4729c841db3c9:simple-relay:manager",), send.resources)
        returned = self.feature.prepare(work=self.work, arguments={
            "command": "simple-relay-return", "instance_id": args["instance_id"],
            "source_operation_id": "manager-send-001",
        })
        self.assertEqual(
            ("rcc-instance:6174664e1c1b4e6db1d4729c841db3c9:simple-relay:return:manager-send-001",),
            returned.resources,
        )
        for invalid in ({"from": "node"}, {"text": ""}, {"tab_id": 99}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PreconditionError):
                    self.feature.prepare(work=self.work, arguments={
                        "command": "simple-relay-send", "instance_id": args["instance_id"],
                        "from": "manager", "text": "x", **invalid,
                    })
        with self.assertRaises(PreconditionError):
            self.feature.prepare(work=self.work, arguments={
                "command": "simple-relay-return", "instance_id": args["instance_id"],
                "source_operation_id": "invalid id",
            })
