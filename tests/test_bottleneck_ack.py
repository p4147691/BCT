from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.bottleneck_ack import ACK_PROMPT, BottleneckAckController, load_bottleneck_ack_policy
from bct.core.models import Principal


class _Result:
    def __init__(self, outcome="APPLIED"):
        self.outcome = outcome
    def as_dict(self):
        return {"outcome": self.outcome}


class _Operations:
    def __init__(self):
        self.calls = []
    def run(self, **values):
        self.calls.append(values)
        return _Result()


class _Bct:
    def __init__(self):
        self.operations = _Operations()


class BottleneckAckTests(unittest.TestCase):
    def _policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bct.toml"
            path.write_text('''[bottleneck_ack]
enabled = true
threshold_seconds = 30
cooldown_seconds = 300
watch_instance_id = "instance_123"
watch_conversation_key = "11111111-1111-1111-1111-111111111111"
probe_instance_id = "instance_123"
probe_conversation_key = "22222222-2222-2222-2222-222222222222"
''', encoding="utf-8")
            return load_bottleneck_ack_policy(path)

    @staticmethod
    def _instances(*, source_started=960_000, probe_started=None, probe_finished=None, probe_generating=False):
        return [{"instance_id": "instance_123", "session_id": "a" * 32, "state": "OPEN", "tabs": [
            {"tab_id": 1, "window_id": 10, "conversation_key": "11111111-1111-1111-1111-111111111111",
             "generating": True, "telemetry": {"generation_started_at": source_started}},
            {"tab_id": 2, "window_id": 10, "conversation_key": "22222222-2222-2222-2222-222222222222",
             "generating": probe_generating, "telemetry": {"generation_started_at": probe_started, "generation_finished_at": probe_finished}},
        ]}]

    def test_long_generation_submits_one_fixed_prompt_and_measures_completion(self):
        bct = _Bct()
        controller = BottleneckAckController(
            self._policy(), bct=bct, principal=Principal("p", "test", frozenset({"relay_browser"})),
        )
        first = controller.observe(self._instances(), now_ms=1_000_001)
        self.assertEqual("SUBMITTED", first["state"])
        self.assertEqual(1, len(bct.operations.calls))
        args = bct.operations.calls[0]["arguments"]
        self.assertEqual("send-to-tab", args["command"])
        self.assertEqual(ACK_PROMPT, args["text"])
        self.assertEqual(2, args["tab_id"])
        # The same source onset is fenced even when the next poll still sees it.
        controller.observe(self._instances(), now_ms=1_004_000)
        self.assertEqual(1, len(bct.operations.calls))
        measured = controller.observe(self._instances(probe_started=1_000_100, probe_finished=1_000_500), now_ms=1_001_000)
        self.assertEqual("MEASURED", measured["state"])
        self.assertEqual(99, measured["ack_start_latency_ms"])
        self.assertEqual(499, measured["ack_completion_latency_ms"])

    def test_busy_or_missing_probe_never_submits(self):
        bct = _Bct()
        controller = BottleneckAckController(self._policy(), bct=bct, principal=Principal("p", "test", frozenset()))
        state = controller.observe(self._instances(probe_generating=True), now_ms=1_000_001)
        self.assertEqual("PROBE_BUSY", state["state"])
        self.assertEqual([], bct.operations.calls)

    def test_disabled_policy_needs_no_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bct.toml"
            path.write_text("[bottleneck_ack]\nenabled = false\n", encoding="utf-8")
            self.assertFalse(load_bottleneck_ack_policy(path).enabled)

    def test_same_source_and_probe_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bct.toml"
            path.write_text('''[bottleneck_ack]
enabled = true
watch_instance_id = "instance_123"
watch_conversation_key = "11111111-1111-1111-1111-111111111111"
probe_instance_id = "instance_123"
probe_conversation_key = "11111111-1111-1111-1111-111111111111"
''', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PROBE_MUST_BE_SEPARATE"):
                load_bottleneck_ack_policy(path)


if __name__ == "__main__":
    unittest.main()
