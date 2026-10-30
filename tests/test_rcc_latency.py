from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, Principal
from bct.features.rcc import RelayBrowserFeature
from bct.features.rcc_latency import send_latency_evidence
from bct.service import BCT
from tests.test_rcc_integration import FakeRelayClient


class SendLatencyEvidenceTests(unittest.TestCase):
    def test_existing_tab_ack_is_measured_not_assumed_for_created_tab(self):
        existing = send_latency_evidence(
            command="send-to-tab", preflight_state_ms=16.521, host_request_ms=125.435
        )
        self.assertEqual(125.435, existing["timing_ms"]["submit_ack"])
        created = send_latency_evidence(
            command="send-to-created-tab", preflight_state_ms=15.0, host_request_ms=5300.0,
            stage_timing={
                "submitAttemptedAt": 10000, "conversationCapturedAt": 13250,
                "completedAt": 15200,
            },
        )
        self.assertNotIn("submit_ack", created["timing_ms"])
        self.assertEqual(3250, created["timing_ms"]["submit_to_conversation"])
        self.assertEqual(1950, created["timing_ms"]["conversation_to_response"])

    def test_readback_timing_and_attempt_count(self):
        metrics = send_latency_evidence(
            command="send-to-created-tab", readback_ms=99.425,
            readback_attempts=2,
        )
        self.assertEqual(99.425, metrics["timing_ms"]["readback"])
        self.assertEqual(2, metrics["readback_attempts"])

    def test_bad_timestamps_not_interpreted_as_latency(self):
        metrics = send_latency_evidence(
            command="send-to-created-tab", preflight_state_ms=-10,
            host_request_ms=float("nan"),
            stage_timing={"submitAttemptedAt": 200, "conversationCapturedAt": 180,
                          "completedAt": "invalid"},
            readback_ms=True, readback_attempts=-1,
        )
        self.assertEqual({}, metrics["timing_ms"])
        self.assertNotIn("readback_attempts", metrics)


class SendLatencyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        config = root / "bct.toml"
        config.write_text('[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n', encoding="utf-8")
        self.client = FakeRelayClient()
        self.bct = BCT(state_path=root / "state.sqlite", policy_path=config)
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(
            self.client, store=self.bct.store, result_readback_timeout_s=0.1
        )
        self.principal = Principal("latency_test", "test", frozenset({"relay_browser"}))
        self.bct.create_work(
            work_id="latency-work", request_summary="passive latency tests",
            roots=[str(root)], actions=["relay_browser"], principal=self.principal
        )

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, id_: str, args: dict):
        return self.bct.operations.run(
            principal=self.principal, work_id="latency-work", operation_id=id_,
            capability="relay_browser", arguments=args,
        )

    @staticmethod
    def state():
        return {
            "ok": True,
            "state": {
                "instanceId": "instance123", "sessionId": "a"*32,
                "tabs": [{"tabId": 10, "windowId": 11,
                          "conversationKey": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"}],
            },
        }

    def test_ack_timing_and_duplicate_without_extra_dispatch(self):
        self.client.target_state = self.state()
        self.client.result = {
            "type": "host:result", "ok": True, "submitted": True, "state": "SUBMITTED",
            "operationId": "latency-existing-01", "instanceId": "instance123",
            "sessionId": "a"*32, "tabId": 10, "windowId": 11,
        }
        args = {
            "command": "send-message", "instance_id": "instance123",
            "session_id": "a"*32, "tab_id": 10, "window_id": 11,
            "conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "text": "latency check",
        }
        first = self.invoke("latency-existing-01", args)
        self.assertEqual(Outcome.APPLIED, first.outcome, (first.error, first.evidence, first.output))
        self.assertIn("preflight_state", first.evidence["timing_ms"])
        self.assertIn("submit_ack", first.evidence["timing_ms"])
        duplicate = self.invoke("latency-existing-01", args)
        self.assertTrue(duplicate.duplicate)
        sent = [x for x in self.client.calls if x["command"] != "state"]
        self.assertEqual(1, len(sent))

    def test_created_tab_host_response_breakdown(self):
        self.client.result = {
            "type": "host:result", "requestId": "latency-created-01",
            "ok": True, "state": "PENDING_UNBOUND", "tabId": 10, "windowId": 11,
        }
        created = self.invoke("latency-created-01", {
            "command": "create-chat-tab", "instance_id": "instance123", "window_id": 11,
        })
        self.assertEqual(Outcome.APPLIED, created.outcome)
        self.client.target_state = self.state()
        self.client.result = {
            "type": "host:result", "ok": True, "state": "RESULT_PERSISTED",
            "stageTiming": {
                "beganAt": 10000, "submitAttemptedAt": 10002,
                "conversationCapturedAt": 12002, "completedAt": 13252,
            },
        }
        sent = self.invoke("latency-created-send-01", {
            "command": "send-message", "instance_id": "instance123",
            "session_id": "a"*32, "tab_id": 10, "window_id": 11,
            "create_operation_id": "latency-created-01", "text": "latency check",
        })
        self.assertEqual(Outcome.APPLIED, sent.outcome)
        times = sent.evidence["timing_ms"]
        self.assertEqual(2000, times["submit_to_conversation"])
        self.assertEqual(1250, times["conversation_to_response"])
        self.assertNotIn("submit_ack", times)


if __name__ == "__main__":
    unittest.main()
