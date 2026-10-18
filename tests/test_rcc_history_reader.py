"""Exact-work RCC history-only read protocol: unit tests never operate Chrome."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, Principal, PreconditionError
from bct.features.rcc import RelayBrowserFeature
from bct.service import BCT

CID = "6ad365ef-159c-83ee-8fe9-08742f99a24c"

class MockClient:
    def __init__(self):
        self.calls = []
        self.result = {}
    def request(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)

class HistoryOnlyRccTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bct-history-rcc-")
        root = Path(self.tmp.name)
        policy = root / "bct.toml"
        policy.write_text('[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',encoding="utf-8")
        self.client = MockClient()
        self.bct = BCT(state_path=root / "state.sqlite",policy_path=policy)
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(self.client)
        self.owner = Principal("history-owner","test",frozenset({"relay_browser"}))
        self.bct.create_work(work_id="history-work",request_summary="history-only fixture",
                             roots=[str(root)],actions=["relay_browser"],principal=self.owner)
    def tearDown(self):
        self.tmp.cleanup()
    def call(self,op,arguments):
        return self.bct.operations.run(principal=self.owner,work_id="history-work",
                operation_id=op,capability="relay_browser",arguments=arguments)
    def opening(self):
        self.client.result={
            "ok":True,"created":True,"inactive":True,"state":"HISTORY_TAB_READY",
            "instanceId":"instance123","operationId":"history-open-01",
            "sessionId":"session-h","conversationKey":CID,
            "exactUrl":"https://chatgpt.com/c/"+CID,"tabId":801,"windowId":51,
        }
        return self.call("history-open-01",{"command":"history-open",
                    "instance_id":"instance123","conversation_key":CID})
    def request(self):
        return {"command":"history-read","instance_id":"instance123",
                "conversation_key":CID,"open_operation_id":"history-open-01",
                "session_id":"session-h","tab_id":801,"window_id":51,
                "max_steps":3,"max_turns":10,"max_bytes":10000}
    def test_open_requires_exact_uuid_and_has_conversation_scoped_claim(self):
        with self.assertRaisesRegex(PreconditionError,"RCC_HISTORY_OPEN_CONVERSATION_KEY_INVALID"):
            self.call("invalid-open",{"command":"history-open","instance_id":"instance123",
                      "conversation_key":"https://evil.example/"})
        self.assertFalse(self.client.calls)
        result=self.opening()
        self.assertEqual(Outcome.APPLIED,result.outcome)
        self.assertEqual("history-open",result.evidence["command"])
        self.assertEqual(801,result.evidence["tab_id"])
        self.assertEqual(CID,result.evidence["conversation_key"])
        self.assertTrue(result.evidence["no_message_sent"])
        self.assertEqual("history-open",self.client.calls[0]["command"])
        self.assertEqual("history-open-01",self.client.calls[0]["extra"]["operationId"])
        self.assertEqual(CID,self.client.calls[0]["extra"]["conversationKey"])
        self.assertEqual("instance123",self.client.calls[0]["extra"]["instanceId"])
        self.assertTrue(self.call("history-open-01",{
            "command":"history-open","instance_id":"instance123","conversation_key":CID}).duplicate)
        self.assertEqual(1,len(self.client.calls))
    def test_read_only_owned_created_tab_with_partial_response(self):
        self.opening()
        self.client.result={
            "ok":True,"state":"HISTORY_PARTIAL","status":"PARTIAL",
            "coverage":"OBSERVED_VISIBLE_TURNS",
            "fullHistoryVerified":False,"gapsVerifiable":False,
            "instanceId":"instance123","sessionId":"session-h",
            "conversationKey":CID,"openOperationId":"history-open-01",
            "tabId":801,"windowId":51,"identified":2,"unidentified":1,
            "truncated":False,"messages":[{"id":"t1","text":"기록"},{"id":"t2","text":"과거"}],
        }
        result=self.call("history-read-01",self.request())
        self.assertEqual(Outcome.APPLIED,result.outcome)
        self.assertEqual("PARTIAL",result.evidence["status"])
        self.assertFalse(result.evidence["full_history_verified"])
        self.assertEqual("과거",result.output["result"]["messages"][1]["text"])
        self.assertEqual(2,len(self.client.calls))
        self.assertEqual("history-read",self.client.calls[1]["command"])
        self.assertEqual(801,self.client.calls[1]["extra"]["tabId"])
        self.assertNotIn("operationId",self.client.calls[1]["extra"])
        self.assertTrue(self.call("history-read-01",self.request()).duplicate)
        self.assertEqual(2,len(self.client.calls))
    def test_read_requires_original_receipt_before_native_call(self):
        with self.assertRaisesRegex(Exception,"OPERATION"):
            self.call("orphan-read",self.request())
        self.assertEqual(0,len(self.client.calls))
        self.opening()
        initial=len(self.client.calls)
        for field,value in [("tab_id",999),("window_id",99),("session_id","another"),
                            ("conversation_key","6ad4b590-dfc8-83ee-b29f-92033f07fc08")]:
            args=self.request(); args[field]=value
            with self.assertRaisesRegex(PreconditionError,"RCC_HISTORY_OPEN_RECEIPT_MISMATCH"):
                self.call("bad-"+field,args)
        self.assertEqual(initial,len(self.client.calls))
    def test_read_denies_unknown_open_and_oversized_bounds(self):
        # Even a transient/ambiguous open is never adequate history read authority.
        self.client.result={"ok":False,"state":"CREATE_UNKNOWN"}
        opened=self.call("history-open-01",{"command":"history-open",
            "instance_id":"instance123","conversation_key":CID})
        self.assertEqual(Outcome.UNKNOWN,opened.outcome)
        with self.assertRaisesRegex(PreconditionError,"RCC_HISTORY_OPEN_RECEIPT_MISMATCH"):
            self.call("unsafe-read",self.request())
        self.assertEqual(1,len(self.client.calls))
        # Unknown creation is rejected before the bounds/dispatch stage too.
        with self.assertRaisesRegex(PreconditionError,"RCC_HISTORY_OPEN_RECEIPT_MISMATCH"):
            self.call("large-read",{**self.request(),"max_bytes":99999})
        self.assertEqual(1,len(self.client.calls))
    def test_opened_tab_still_has_bounded_history_reads(self):
        self.opening()
        with self.assertRaisesRegex(PreconditionError,"RCC_HISTORY_READ_BOUNDS_INVALID"):
            self.call("large-read",{**self.request(),"max_bytes":99999})
        self.assertEqual(1,len(self.client.calls))
    def test_unverified_read_response_never_reports_pass(self):
        self.opening()
        self.client.result={"ok":True,"state":"HISTORY_PARTIAL",
           "status":"COMPLETE","fullHistoryVerified":True,"messages":[]}
        outcome=self.call("history-read-bad-output",self.request())
        self.assertEqual(Outcome.UNKNOWN,outcome.outcome)
        self.assertEqual(2,len(self.client.calls))

if __name__=="__main__": unittest.main()
