import unittest
from bct.recovery_card import build_card
from bct.recovery_supervisor import capability_manifest, mock_supervision

class SupervisorTests(unittest.TestCase):
    def setup_case(self):
        card=build_card(predecessor={"work_id":"N32-INBOX", "conversation":"N32"},
          observations={"worktree":"isolated", "pr":332},
          verified_evidence={"worktree":"local fixture", "pr":"fixture only"},
          protected_resources=["main","Chrome","RCC"],next_minimal_step="Check Inbox CI")
        manifest=capability_manifest(successor="N38-GENERAL",scope="N32-INBOX",
          available_tools={"bct_status","bct_operation_get","bct_relay_control"},
          expressly_allowed={"assignment"})
        work=[{"id":"independent-a","candidate":"N40","task":"inspect PR evidence"},
              {"id":"independent-b","candidate":"N41","task":"inspect tests"}]
        return card,manifest,work
    def test_manifest_does_not_infer_permissions(self):
        _,m,_=self.setup_case()
        self.assertEqual(m["tools"]["status_read"]["state"],"AVAILABLE")
        self.assertEqual(m["tools"]["inbox_read"]["state"],"UNAVAILABLE")
        self.assertFalse(m["role_tags_grant_authority"])
        self.assertIn("main_merge",m["protected_actions"])
    def test_disconnected_escalates(self):
        _,m,_=self.setup_case()
        x=capability_manifest(successor="N40",scope="N32",available_tools={"bct_relay_control"},
                              expressly_allowed={"assignment"},connected=False)
        self.assertEqual(x["tools"]["assignment"]["state"],"UNAVAILABLE")
        self.assertEqual(m["tools"]["card_write"]["state"],"UNAVAILABLE")
    def test_general_node_two_independent_mock_results(self):
        c,m,a=self.setup_case()
        results={"independent-a":{"verified":True,"sha256":"a"*64},
                 "independent-b":{"verified":True,"sha256":"b"*64}}
        v=mock_supervision(card=c,manifest=m,assignments=a,results=results)
        self.assertEqual(v["state"],"MOCK_COMPLETE")
        self.assertEqual(len(v["assignments"]),2)
        self.assertEqual(len(set(x["idempotency_key"] for x in v["assignments"])),2)
        self.assertEqual(len(v["results"]),2)
        self.assertEqual(v["effects"],[])
        self.assertEqual(v["next_minimal_step"],"SUPERVISOR_DECIDE_NEXT_CARD_OR_COMPLETE")
        self.assertEqual(v,mock_supervision(card=c,manifest=m,assignments=a,results=results))
    def test_missing_result_unknown_not_success(self):
        c,m,a=self.setup_case()
        v=mock_supervision(card=c,manifest=m,assignments=a,results={})
        self.assertEqual(v["next_minimal_step"],"REVIEW_UNKNOWN_RESULTS")
    def test_no_assignment_authority_escalates(self):
        c,m,a=self.setup_case()
        m["tools"]["assignment"]["state"]="ESCALATE"
        v=mock_supervision(card=c,manifest=m,assignments=a,results={})
        self.assertEqual(v["state"],"ESCALATE")
        self.assertEqual(v["effects"],[])
    def test_korean_emoji_utf8_not_console(self):
        m=capability_manifest(successor="일반 노드 🧭",scope="복구 작업",
          available_tools=set(),expressly_allowed=set())
        from json import dumps
        raw=dumps(m,ensure_ascii=False).encode("utf-8")
        self.assertIn("일반 노드 🧭",raw.decode("utf-8"))
        self.assertNotEqual(raw,raw.decode("cp949",errors="replace").encode("cp949",errors="replace"))
if __name__=="__main__":unittest.main()
