"""RCC Monitor normalized-state integration contract fixtures."""
import unittest
from unittest.mock import patch
from bct.current_nodes import classify_current_nodes
from bct.monitor_runtime import build_monitor_state

UUID = "12345678-1234-1234-1234-123456789abc"

def normalized_tab(**overrides):
    value = {"tab_id": 42, "window_id": 13, "tab_index": 2,
             "conversation_key": UUID, "node_label": "N7",
             "url": "https://chatgpt.com/c/" + UUID, "presence": "OPEN",
             "generating": False}
    value.update(overrides)
    return value

class RccContractTests(unittest.TestCase):
    def test_confirmed_normalized(self):
        r = classify_current_nodes([{"state":"OPEN","tabs":[normalized_tab()]}], observed_at=50)
        self.assertEqual(r["counts"]["confirmed"], 1)
        self.assertEqual((r["items"][0]["window_id"],r["items"][0]["tab_id"],r["items"][0]["tab_index"]),(13,42,2))
    def test_unresolved_home_without_dom_proof(self):
        r = classify_current_nodes([{"state":"OPEN","tabs":[{"url":"https://chatgpt.com/","presence":"OPEN","conversation_key":""}]}])
        self.assertEqual(r["counts"]["unresolved"],1)
        self.assertEqual(r["counts"]["temporary"],0)
    def test_cached_is_unavailable(self):
        r = classify_current_nodes([{"state":"PROBE_TIMEOUT","cached":True,"last_seen_at":20,"tabs":[normalized_tab()]}],observed_at=50)
        self.assertEqual(r["counts"]["confirmed"],0)
        self.assertEqual(r["counts"]["unavailable"],1)
    def test_empty_failure_not_false_zero_health(self):
        r = classify_current_nodes([{"state":"UNAVAILABLE","tabs":[]}])
        self.assertEqual(r["unavailable_instances"],1)
    def test_duplicate_uuid_not_confirmed(self):
        r = classify_current_nodes([{"state":"OPEN","tabs":[normalized_tab(),normalized_tab(tab_id=43,node_label="N8")]}])
        self.assertEqual(r["counts"]["unresolved"],2)
    def test_monitor_payload_preserves_legacy_count(self):
        class Store:
            def monitor_snapshot(self):
                return {k:[] for k in ("works","operations","unresolved_claims","nodes","connections","orchestration_sessions","orchestration_assignments")}
            def wake_node_label_notifications(self,*a,**kw): return None
            def claim_diagnostics(self): return []
        with patch("bct.monitor_runtime._session_states",return_value=[]), \
             patch("bct.monitor_runtime.discover_instance_ids",return_value=["rcc"]), \
             patch("bct.monitor_runtime._rcc_states",return_value=[{"instance_id":"rcc","state":"OPEN","tabs":[normalized_tab()]}]), \
             patch("bct.monitor_runtime.ensure_observed_node_labels",return_value={UUID:"N7"}), \
             patch("bct.monitor_runtime.conversation_scope_directory",return_value={}), \
             patch("bct.monitor_runtime.conversation_display_order_directory",return_value={}):
            from pathlib import Path
            payload=build_monitor_state(store=Store(),service_state={"status":"OK"},data_root=Path("."))
        self.assertEqual(payload["counts"]["nodes"],0)
        self.assertEqual(payload["current_nodes"]["counts"]["confirmed"],1)
        self.assertIn("rcc",payload)

if __name__=="__main__":
    unittest.main()
