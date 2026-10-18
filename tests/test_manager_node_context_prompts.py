"""Manager and worker own the decisions; BCT only reminds and relays."""
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from bct.features import orchestration as orchestration_module

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
        # The default-prompt contract must not depend on an operator's live,
        # editable relay note under D:/BCT/runtime/config.
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(orchestration_module, "_RELAY_NOTES_DIR", Path(directory)):
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


    def test_notes_are_editable_without_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(orchestration_module, "_RELAY_NOTES_DIR", Path(temp)):
                self.assertIn("운영 상기", orchestration_module._relay_note("manager"))
                note = Path(temp) / "manager-relay-note.txt"
                note.write_text("첫 안내", encoding="utf-8")
                self.assertEqual("첫 안내", orchestration_module._relay_note("manager"))
                note.write_text("수정된 안내", encoding="utf-8")
                self.assertEqual("수정된 안내", orchestration_module._relay_note("manager"))

    def test_notes_reject_protocol_marker_and_oversize(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(orchestration_module, "_RELAY_NOTES_DIR", Path(temp)):
                note = Path(temp) / "worker-relay-note.txt"
                note.write_text("[BCT_ORCHESTRATION_RESULT_V1]", encoding="utf-8")
                with self.assertRaises(ValueError):
                    orchestration_module._relay_note("worker")
                note.write_text("x" * 5000, encoding="utf-8")
                with self.assertRaises(ValueError):
                    orchestration_module._relay_note("worker")


    def test_windows_notepad_encoding_switches_without_restart(self):
        sample = "업무 완료 기준 확인 후 Manager가 판단하세요."
        variants = ("utf-8", "utf-8-sig", "utf-16", "utf-16-be", "utf-32", "cp949")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(orchestration_module, "_RELAY_NOTES_DIR", Path(directory)):
                file = Path(directory) / "manager-relay-note.txt"
                for codec in variants:
                    with self.subTest(codec=codec):
                        raw = sample.encode(codec)
                        if codec == "utf-16-be":
                            raw = b"\xfe\xff" + raw
                        file.write_bytes(raw)
                        self.assertEqual(sample, orchestration_module._relay_note("manager"))
                self.assertIn("SUCCEEDED", orchestration_module._relay_note("worker"))

    def test_rejects_malformed_binary_and_preserves_unicode_length_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(orchestration_module, "_RELAY_NOTES_DIR", Path(directory)):
                file = Path(directory) / "worker-relay-note.txt"
                for raw in (b"\x00\x01", b"\x81", b"\xff\xfe\x00",
                            b"valid\x00binary"):
                    with self.subTest(raw=repr(raw)):
                        file.write_bytes(raw)
                        with self.assertRaises(ValueError):
                            orchestration_module._relay_note("worker")
                file.write_bytes(("한" * 2000).encode("utf-8"))
                self.assertEqual(2000, len(orchestration_module._relay_note("worker")))
                file.write_bytes(("한" * 2001).encode("utf-16"))
                with self.assertRaisesRegex(ValueError, "RELAY_NOTE_INVALID_LENGTH"):
                    orchestration_module._relay_note("worker")


if __name__ == "__main__":
    unittest.main()
