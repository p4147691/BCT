"""Manager and worker own the decisions; BCT only reminds and relays."""
import json
import unittest

from bct.features.orchestration import OrchestrationFeature
from bct.core.manager_decision import (
    DECISION_END,
    DECISION_SCHEMA,
    DECISION_START,
    parse_manager_decision,
)


class ManagerNodeContextPromptTests(unittest.TestCase):
    def test_manager_wake_v2_preserves_contract_and_reminds_autonomy(self):
        event = {
            "wake_envelope_schema": 2, "receipt_mode": "RCC_RESULT_POLL_V1",
            "event_id": "wake.e", "session_id": "session.s", "manager_epoch": 2,
            "attachment_id": "att.a", "attachment_generation": 1,
            "assignment_id": "assignment.a", "assignment_generation": 1,
            "result_message_id": "result.r", "result_digest": "digest.d",
        }
        prompt = OrchestrationFeature._manager_wake_envelope(event)
        self.assertIn("결과 영수증", prompt)
        self.assertIn("원래 목표와 영수증", prompt)
        self.assertIn("UNKNOWN 전송", prompt)
        self.assertIn("COMPLETE", prompt)
        self.assertIn("FOLLOW_UP", prompt)
        self.assertIn("선택 routing", prompt)
        self.assertIn("PROVISION_REQUIRED", prompt)
        self.assertIn("자동 생성하지", prompt)
        marker = "[BCT_ORCHESTRATION_MANAGER_WAKE_V2]"
        end = "[/BCT_ORCHESTRATION_MANAGER_WAKE_V2]"
        envelope = json.loads(prompt.split(marker, 1)[1].split(end, 1)[0])
        self.assertEqual(envelope["session_id"], event["session_id"])
        self.assertEqual(envelope["result_digest"], event["result_digest"])
        self.assertEqual(envelope["manager_epoch"], event["manager_epoch"])

    def test_manager_follow_up_routing_advertised_by_wake_is_accepted(self):
        expected = {
            "event_id": "wake.e", "session_id": "session.s", "manager_epoch": 2,
            "result_message_id": "result.r", "result_digest": "a" * 64,
        }
        decision = {
            "schema": DECISION_SCHEMA,
            **expected,
            "kind": "FOLLOW_UP",
            "summary": "idle standby를 사용한다",
            "successors": [{
                "target_node_id": "worker.b", "attachment_id": "att.b",
                "instruction": "후속 확인", "roots": ["D:/BCT/source"],
                "actions": ["read"], "acceptance": {}, "dependencies": [],
                "routing": {
                    "affinity": "PREFERRED", "allow_provision": False,
                    "fallbacks": [{
                        "node_id": "standby.c", "attachment_id": "att.c",
                        "attachment_generation": 1,
                    }],
                },
            }],
        }
        parsed = parse_manager_decision(
            DECISION_START + json.dumps(decision) + DECISION_END,
            expected=expected,
        )
        self.assertEqual("PREFERRED", parsed["successors"][0]["routing"]["affinity"])
        self.assertEqual("standby.c", parsed["successors"][0]["routing"]["fallbacks"][0]["node_id"])

    def test_worker_assignment_retains_original_instruction_and_result_contract(self):
        prompt = OrchestrationFeature._result_envelope(
            session_id="session.s", assignment_id="assignment.a",
            generation=1, manager_epoch=2,
            request_digest="digest.r", result_nonce="nonce.n",
            instruction="독립적으로 계산 검증", acceptance={"must_check": True},
            roots=["D:\\BCT\\source"], actions=["read"], dependencies=[],
        )
        self.assertIn("외부 효과를 무조건 반복하지 마세요", prompt)
        self.assertIn("SUCCEEDED로 보고하지 마세요", prompt)
        marker = "[BCT_ORCHESTRATION_ASSIGNMENT_V1]"
        end = "[/BCT_ORCHESTRATION_ASSIGNMENT_V1]"
        envelope = json.loads(prompt.split(marker, 1)[1].split(end, 1)[0])
        self.assertEqual(envelope["instruction"], "독립적으로 계산 검증")
        self.assertEqual(envelope["acceptance"], {"must_check": True})
        self.assertEqual(envelope["response_contract"]["status"],
                         ["SUCCEEDED", "FAILED", "BLOCKED"])




if __name__ == "__main__":
    unittest.main()
