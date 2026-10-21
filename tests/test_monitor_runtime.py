from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.monitor_runtime import _rcc_states, build_monitor_state
from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable
from bct.conversation_network import upsert_conversation


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
            self.assertFalse(state["observability"]["read_only"])
            self.assertEqual("DISPLAY_LABELS_ONLY", state["observability"]["registry_sync"])
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
            self.assertEqual(0, state["counts"]["unresolved_claims_shared"])
            self.assertEqual(0, state["counts"]["unresolved_claims_exact"])
            self.assertNotIn("roots", state["works"][0])
            self.assertEqual([], state["operations"])

    def test_rcc_payload_reports_exact_hash_match_without_paths_or_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.js"
            live = root / "live.js"
            source.write_bytes(b"same payload")
            live.write_bytes(b"same payload")
            store = Store(root / "state.sqlite")
            with patch("bct.monitor_runtime.discover_instance_ids", return_value=[]):
                state = build_monitor_state(
                    store=store, service_state={"ready": True},
                    data_root=root / "data", rcc_source_path=source,
                    rcc_live_path=live,
                )
            payload = state["rcc"]["payload"]
            self.assertEqual("MATCH", payload["state"])
            self.assertTrue(payload["files_match"])
            self.assertEqual(payload["source_sha256"], payload["live_sha256"])
            self.assertNotIn(str(root), repr(payload))
            live.write_bytes(b"different payload")
            with patch("bct.monitor_runtime.discover_instance_ids", return_value=[]):
                changed = build_monitor_state(
                    store=store, service_state={"ready": True},
                    data_root=root / "data", rcc_source_path=source,
                    rcc_live_path=live,
                )
            self.assertEqual("MISMATCH", changed["rcc"]["payload"]["state"])

    def test_rcc_probe_timeout_is_not_disconnection_and_recovers_on_bounded_retry(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        calls = []

        class Client:
            def request(self, **kwargs):
                calls.append((kwargs["command"], kwargs["timeout_s"]))
                if len(calls) == 2:
                    raise RelayEffectUnknown("RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH")
                return {"state": {"sessionId": "healthy", "tabs": [], "endpoints": []}}

        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                first = _rcc_states(["slow-rcc"])[0]
                self.assertEqual("OPEN", first["state"])
                second = _rcc_states(["slow-rcc"])[0]
                self.assertEqual("PROBE_TIMEOUT", second["state"])
                self.assertEqual("RelayEffectUnknown", second["error"])
                cached = _rcc_states(["slow-rcc"])[0]
                self.assertEqual("PROBE_TIMEOUT", cached["state"])
                self.assertTrue(cached["cached"])
                self.assertEqual("OPEN", cached["last_known_state"])
                self.assertLessEqual(cached["retry_in_ms"], 5000)
                self.assertEqual(2, len(calls))
                _RCC_HEALTH["slow-rcc"]["retry_at"] = 0
                recovered = _rcc_states(["slow-rcc"])[0]
                self.assertEqual("OPEN", recovered["state"])
                self.assertEqual(3, len(calls))
                self.assertEqual(0.35, calls[-1][1])
                self.assertNotIn("probe_state", _RCC_HEALTH["slow-rcc"])
                self.assertNotIn("cached", recovered)
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_explicit_pipe_disconnection_retains_unavailable_and_full_backoff(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        class Client:
            calls = 0
            def request(self, **kwargs):
                self.calls += 1
                raise RelayUnavailable("RCC_PIPE_UNAVAILABLE")

        client = Client()
        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=client):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                first = _rcc_states(["disconnected-rcc"])[0]
                self.assertEqual("UNAVAILABLE", first["state"])
                second = _rcc_states(["disconnected-rcc"])[0]
                self.assertTrue(second["cached"])
                self.assertEqual("UNAVAILABLE", second["state"])
                self.assertGreater(second["retry_in_ms"], 10000)
                self.assertEqual(1, client.calls)
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_unknown_pipe_identity_mismatch_is_not_disconnection(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        class Client:
            def request(self, **kwargs):
                raise RelayEffectUnknown("RCC_STATE_INSTANCE_MISMATCH")

        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                failed = _rcc_states(["wrong-rcc"])[0]
                self.assertEqual("PROBE_ERROR", failed["state"])
                self.assertEqual("RelayEffectUnknown", failed["error"])
                self.assertEqual("PROBE_ERROR", _rcc_states(["wrong-rcc"])[0]["state"])
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_invalid_rcc_probe_is_error_not_disconnection(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        class Client:
            def request(self, **kwargs):
                return {"state": "invalid"}

        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                bad = _rcc_states(["invalid-rcc"])[0]
                self.assertEqual("PROBE_ERROR", bad["state"])
                self.assertEqual("ValueError", bad["error"])
                self.assertEqual("PROBE_ERROR", _rcc_states(["invalid-rcc"])[0]["state"])
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_unavailable_instance_is_cached_and_healthy_instance_remains_fresh(self):
        from bct.monitor_runtime import _RCC_HEALTH
        calls = []
        class Client:
            def request(self, **kwargs):
                ident = kwargs["instance_id"]
                calls.append(ident)
                if ident == "bad-instance":
                    raise RelayUnavailable("RCC_PIPE_UNAVAILABLE")
                return {"state": {"sessionId": "live", "tabs": [], "endpoints": []}}
        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            _RCC_HEALTH.clear()
            try:
                first = _rcc_states(["bad-instance", "good-instance"])
                second = _rcc_states(["bad-instance", "good-instance"])
                self.assertEqual(["bad-instance", "good-instance", "good-instance"], calls)
                self.assertEqual("UNAVAILABLE", second[0]["state"])
                self.assertTrue(second[0]["cached"])
                self.assertEqual("OPEN", second[1]["state"])
                self.assertFalse("cached" in second[1])
                self.assertEqual("RelayUnavailable", first[0]["error"])
            finally:
                _RCC_HEALTH.clear()

    def test_four_instances_have_bounded_first_probes_and_stale_retry(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        calls = []
        class Client:
            def request(self, **kwargs):
                calls.append((kwargs["instance_id"], kwargs["timeout_s"]))
                if kwargs["instance_id"].startswith("bad"):
                    raise RelayUnavailable("RCC_PIPE_UNAVAILABLE")
                return {"state": {"sessionId": "healthy", "tabs": [], "endpoints": []}}
        ids = ["bad-a", "bad-b", "good-c", "bad-d"]
        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                first = _rcc_states(ids)
                self.assertEqual(2, len(calls))
                self.assertEqual("UNKNOWN", first[2]["state"])
                self.assertTrue(all(t <= 0.25 for _, t in calls))
                second = _rcc_states(ids)
                self.assertEqual(4, len(calls))
                self.assertEqual("OPEN", second[2]["state"])
                self.assertEqual("UNAVAILABLE", second[0]["state"])
                third = _rcc_states(ids)
                self.assertEqual(5, len(calls))
                for item in _RCC_HEALTH.values():
                    if item.get("unavailable"):
                        item["retry_at"] = 0
                start = len(calls)
                fourth = _rcc_states(ids)
                self.assertEqual(2, len(calls) - start)  # healthy + just one retry
                self.assertEqual("OPEN", fourth[2]["state"])
                self.assertEqual(ids, [row["instance_id"] for row in fourth])
                self.assertEqual([], list(_RCC_INFLIGHT))
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_last_known_state_never_masquerades_as_live(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        class Client:
            calls = 0
            def request(self, **kwargs):
                self.calls += 1
                if self.calls > 1:
                    raise RelayUnavailable("RCC_PIPE_UNAVAILABLE")
                return {"state": {"sessionId": "healthy", "tabs": [], "endpoints": []}}
        client = Client()
        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=client):
            _RCC_HEALTH.clear()
            try:
                self.assertEqual("OPEN", _rcc_states(["service-a"])[0]["state"])
                self.assertEqual("UNAVAILABLE", _rcc_states(["service-a"])[0]["state"])
                stale = _rcc_states(["service-a"])[0]
                self.assertEqual("UNAVAILABLE", stale["state"])
                self.assertEqual("OPEN", stale["last_known_state"])
                self.assertTrue(stale["cached"])
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_transient_timeout_retains_last_verified_tabs_as_stale_display_data(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        conversation = "6ad733b6-95d4-83ee-b4ba-49a671229d77"

        class Client:
            calls = 0

            def request(self, **kwargs):
                self.calls += 1
                if self.calls > 1:
                    raise TimeoutError("short monitor probe timed out")
                return {"state": {
                    "backgroundBuildId": "verified-build",
                    "sessionId": "verified-session",
                    "tabs": [{
                        "id": 71, "windowId": 44, "title": "격리 검증 방법 안내",
                        "url": f"https://chatgpt.com/c/{conversation}",
                    }],
                    "endpoints": [{
                        "tabId": 71, "conversationKey": conversation,
                        "presence": "OPEN", "tabActive": True,
                    }],
                }}

        client = Client()
        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=client):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                live = _rcc_states(["service-a"])[0]
                timed_out = _rcc_states(["service-a"])[0]
                deferred = _rcc_states(["service-a"])[0]
                self.assertEqual("OPEN", live["state"])
                self.assertEqual("PROBE_TIMEOUT", timed_out["state"])
                self.assertEqual("PROBE_TIMEOUT", deferred["state"])
                self.assertTrue(deferred["cached"])
                self.assertEqual("verified-session", deferred["session_id"])
                self.assertEqual("verified-build", deferred["background_build_id"])
                self.assertEqual(71, deferred["tabs"][0]["tab_id"])
                self.assertEqual(conversation, deferred["tabs"][0]["conversation_key"])
            finally:
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_parallel_monitor_reads_do_not_duplicate_inflight_probe(self):
        from bct.monitor_runtime import _RCC_HEALTH, _RCC_INFLIGHT
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        entered, release = Event(), Event()
        calls = []
        class Client:
            def request(self, **kwargs):
                calls.append(kwargs["instance_id"])
                entered.set()
                if not release.wait(timeout=2.0):
                    raise TimeoutError("test timeout")
                return {"state": {"sessionId": "live", "tabs": [], "endpoints": []}}
        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            _RCC_HEALTH.clear()
            _RCC_INFLIGHT.clear()
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future = executor.submit(_rcc_states, ["parallel-a"])
                    self.assertTrue(entered.wait(1.0))
                    duplicate = executor.submit(_rcc_states, ["parallel-a"]).result(1.0)
                    self.assertEqual("UNKNOWN", duplicate[0]["state"])
                    self.assertTrue(duplicate[0]["cached"])
                    release.set()
                    self.assertEqual("OPEN", future.result(2.0)[0]["state"])
                self.assertEqual(["parallel-a"], calls)
                self.assertFalse(_RCC_INFLIGHT)
            finally:
                release.set()
                _RCC_HEALTH.clear()
                _RCC_INFLIGHT.clear()

    def test_rcc_state_exposes_only_window_tab_and_presence_fields(self):
        class Client:
            def request(self, **kwargs):
                return {"state": {
                    "backgroundBuildId": "build-1",
                    "sessionId": "session-123",
                    "settings": {"token": "must-not-leak"},
                    "registrations": {"MANAGER": {"secret": "must-not-leak"}},
                    "tabs": [{"id": 12, "windowId": 34, "index": 7, "title": "Manager", "url": "https://chatgpt.com/c/x"}],
                    "endpoints": [{"tabId": 12, "tabIndex": 8, "presence": "OPEN", "tabActive": True, "generating": False}],
                }}

        with patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
            rows = _rcc_states(["instance_123"])
        self.assertEqual("OPEN", rows[0]["state"])
        self.assertEqual("session-123", rows[0]["session_id"])
        self.assertEqual(12, rows[0]["tabs"][0]["tab_id"])
        self.assertEqual(7, rows[0]["tabs"][0]["tab_index"])
        self.assertNotIn("settings", rows[0])
        self.assertNotIn("registrations", rows[0])
        self.assertNotIn("must-not-leak", repr(rows))

    def test_registered_conversation_gets_its_durable_display_label(self):
        conversation = "6ad5afa4-b1e0-83ee-8692-aec4bb51523e"
        class Client:
            def request(self, **kwargs):
                return {"state": {
                    "sessionId": "live", "tabs": [{"id": 12, "windowId": 34, "title": "Manager", "url": f"https://chatgpt.com/c/{conversation}"}],
                    "endpoints": [{"tabId": 12, "conversationKey": conversation, "presence": "OPEN"}],
                }}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "state.sqlite")
            upsert_conversation(store, conversation_key=conversation, display_name="Manager")
            with patch("bct.monitor_runtime.discover_instance_ids", return_value=["instance_123"]), \
                 patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
                state = build_monitor_state(store=store, service_state={"ready": True}, data_root=root / "data")
        self.assertEqual("N1", state["rcc"]["instances"][0]["tabs"][0]["node_label"])

    def test_observed_conversation_is_registered_once_for_display_only(self):
        conversation = "6ad5afa4-b1e0-83ee-8692-aec4bb51523e"
        class Client:
            def request(self, **kwargs):
                return {"state": {"sessionId": "live", "tabs": [{"id": 1, "windowId": 2, "title": "Observed", "url": f"https://chatgpt.com/c/{conversation}"}], "endpoints": [{"tabId": 1, "conversationKey": conversation, "presence": "OPEN"}]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); store = Store(root / "state.sqlite")
            with patch("bct.monitor_runtime.discover_instance_ids", return_value=["instance"]), patch("bct.monitor_runtime.NamedPipeRelayClient", return_value=Client()):
                first = build_monitor_state(store=store, service_state={}, data_root=root / "data")
                second = build_monitor_state(store=store, service_state={}, data_root=root / "data")
        self.assertEqual("N1", first["rcc"]["instances"][0]["tabs"][0]["node_label"])
        self.assertEqual("N1", second["rcc"]["instances"][0]["tabs"][0]["node_label"])


if __name__ == "__main__":
    unittest.main()
