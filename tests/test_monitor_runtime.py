from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.monitor_runtime import _rcc_states, build_monitor_state


class MonitorRuntimeTests(unittest.TestCase):
    def test_snapshot_is_bounded_and_omits_operation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "state.sqlite")
            store.create_work(Work(
                "monitor-work", "monitor test", (str(root),), frozenset({"read"}), "owner"
            ))
            with patch("bct.monitor_runtime.discover_instance_ids", return_value=[]):
                state = build_monitor_state(
                    store=store,
                    service_state={"ready": True, "release_sha": "1" * 40, "pid": 123},
                    data_root=root / "data",
                )
            self.assertEqual(1, state["schema"])
            self.assertTrue(state["observability"]["read_only"])
            self.assertIsInstance(state["observability"]["mcp_recent"], list)
            timings = state["observability"]["timings"]
            self.assertEqual(
                {"store_snapshot_ms", "process_sessions_ms", "rcc_discovery_ms", "rcc_state_ms", "total_ms"},
                set(timings),
            )
            self.assertTrue(all(isinstance(value, (float, int)) and value >= 0 for value in timings.values()))
            self.assertGreaterEqual(timings["total_ms"] + 0.01, sum(
                timings[key] for key in ("store_snapshot_ms", "process_sessions_ms", "rcc_discovery_ms", "rcc_state_ms")
            ))
            self.assertEqual(1, state["counts"]["works"])
            self.assertNotIn("roots", state["works"][0])
            self.assertEqual([], state["operations"])

    def test_rcc_state_exposes_only_window_tab_and_presence_fields(self):
        class Client:
            def request(self, **kwargs):
                return {"state": {
                    "backgroundBuildId": "build-1",
                    "sessionId": "session-123",
                    "settings": {"token": "must-not-leak"},
                    "registrations": {"MANAGER": {"secret": "must-not-leak"}},
                    "tabs": [{"id": 12, "windowId": 34, "title": "Manager", "url": "https://chatgpt.com/c/x"}],
                    "endpoints": [{"tabId": 12, "presence": "OPEN", "tabActive": True, "generating": False}],
                }}

        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            rows = _rcc_states(["instance_123"])
        self.assertEqual("OPEN", rows[0]["state"])
        self.assertEqual("session-123", rows[0]["session_id"])
        self.assertEqual(12, rows[0]["tabs"][0]["tab_id"])
        self.assertNotIn("settings", rows[0])
        self.assertNotIn("registrations", rows[0])
        self.assertNotIn("must-not-leak", repr(rows))


if __name__ == "__main__":
    unittest.main()
