"""Isolated RCC timing metadata checks; no installed RCC or live pipe access."""
from __future__ import annotations
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "modules/rcc/extension/background.js"
HOST = ROOT / "modules/rcc/native-host/RelayNativeHostV2.cs"


class RccStateTimingContractTests(unittest.TestCase):
    def test_aggregate_and_anonymous_probe_metrics_are_redacted(self):
        script = ROOT / "modules/rcc/extension/test_endpoint_presence.js"
        run = subprocess.run(
            ["node", str(script.name)], cwd=script.parent,
            capture_output=True, text=True, encoding="utf-8", timeout=35,
        )
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        logs = [line for line in run.stdout.splitlines() if line.startswith("RCC_STATE_")]
        self.assertEqual(2, len(logs), logs)
        expected = {
            "RCC_STATE_TIMING": {"load_state_ms", "tabs_query_ms", "activity_probe_ms", "total_ms"},
            "RCC_STATE_PROBE_TIMING": {"slowest_tab_probe_ms", "total_tabs"},
        }
        for line in logs:
            label, serialized = line.split(" ", 1)
            payload = json.loads(serialized)
            self.assertEqual(expected[label], set(payload))
            self.assertNotRegex(serialized.lower(), "https?://|token|message|url|tabid|requestid|content|title")
            for key, value in payload.items():
                if isinstance(value, list):
                    self.assertTrue(all(isinstance(v, (int, float)) and v >= 0 for v in value))
                    self.assertEqual(sorted(value, reverse=True), value)
                    self.assertLessEqual(len(value), 32)
                else:
                    self.assertIsInstance(value, (int, float))
                    self.assertGreaterEqual(value, 0)

    def test_native_host_state_only_timing_is_bounded_and_fixed_keys(self):
        source = HOST.read_text(encoding="utf-8")
        self.assertIn('bool stateOnly = String.Equals(GetString(msg, "command"), "state", StringComparison.Ordinal);', source)
        self.assertIn('StatePipeTraces.TryRemove(requestId, out discarded);', source)
        self.assertIn('StatePipeTraces.TryRemove(pair.Key, out discarded)', source)
        self.assertIn('RecordStateTiming("threadpool_queue_wait", trace, queueWaitMs)', source)
        self.assertIn('RecordStateTiming("pipe_receive_to_chrome_result", trace)', source)
        self.assertIn('RecordStateTiming("pipe_receive_to_pipe_reply", trace)', source)
        self.assertIn('RecordStateTiming("connection_closed_before_result", discarded)', source)
        self.assertIn('Interlocked.Increment(ref StateTraceSequence)', source)
        self.assertIn('HandlePipeClient(connectedPipe, acceptedAt)', source)
        start = source.index('static void RecordStateTiming(')
        end = source.index('static readonly ConcurrentDictionary<string, Dictionary<string, object>> Endpoints', start)
        body = source[start:end]
        self.assertIn('"RCC_STATE_TIMING trace="', body)
        self.assertIn('" stage=" + stage + " ms="', body)

        for forbidden in ("requestId", "text", "tabId", "token", "payload", "url"):
            self.assertNotIn(forbidden, body)
