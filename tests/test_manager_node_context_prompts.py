"""Manager and worker own the decisions; BCT only reminds and relays."""
import json
import unittest

from bct.features.orchestration import OrchestrationFeature


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
        self.assertIn("원래 지시와 완료 기준", prompt)
        self.assertIn("같은 Worker", prompt)
        self.assertIn("다른 Worker", prompt)
        self.assertIn("탭의 생성", prompt)
        self.assertIn("다른 활성 지시", prompt)
        self.assertIn("COMPLETE", prompt)
        self.assertIn("FOLLOW_UP", prompt)
        marker = "[BCT_ORCHESTRATION_MANAGER_WAKE_V2]"
        end = "[/BCT_ORCHESTRATION_MANAGER_WAKE_V2]"
        envelope = json.loads(prompt.split(marker, 1)[1].split(end, 1)[0])
        self.assertEqual(envelope["session_id"], event["session_id"])
        self.assertEqual(envelope["result_digest"], event["result_digest"])
        self.assertEqual(envelope["manager_epoch"], event["manager_epoch"])

    def test_worker_assignment_retains_original_instruction_and_result_contract(self):
        prompt = OrchestrationFeature._result_envelope(
            session_id="session.s", assignment_id="assignment.a",
            generation=1, manager_epoch=2,
            request_digest="digest.r", result_nonce="nonce.n",
            instruction="독립적으로 계산 검증", acceptance={"must_check": True},
            roots=["D:\\BCT\\source"], actions=["read"], dependencies=[],
        )
        self.assertIn("남은 확인 사항", prompt)
        self.assertIn("차단 사유", prompt)
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
