import unittest
from bct.current_nodes import classify_current_nodes

UUID = "12345678-1234-1234-1234-123456789abc"
def tab(**kw):
    return {"url": "https://chatgpt.com/c/" + UUID, "conversation_key": UUID,
            "node_label": "N12", "presence": "OPEN", "tab_id": 4, "window_id": 5, "tab_index": 0, **kw}
def run(tabs, **kwargs):
    return classify_current_nodes([{"state": "OPEN", "tabs": tabs, **kwargs}], observed_at=123.0)

class CurrentNodesTests(unittest.TestCase):
    def test_confirmed(self):
        r=run([tab()])
        self.assertEqual(r["counts"]["confirmed"], 1)
        self.assertEqual(r["items"][0]["tab_index"], 0)
    def test_temporary(self):
        r=run([{"url":"https://chatgpt.com/","presence":"OPEN","new_chat_confirmed":True}])
        self.assertEqual(r["counts"]["temporary"],1)
    def test_loading_is_not_temporary(self):
        r=run([{"url":"https://chatgpt.com/","presence":"OPEN"}])
        self.assertEqual(r["counts"]["unresolved"],1)
    def test_closed_excluded(self):
        r=run([tab(presence="CLOSED")])
        self.assertEqual(len(r["items"]),0)
    def test_cached_not_current(self):
        r=run([tab()], cached=True)
        self.assertEqual(r["counts"]["unavailable"],1)
    def test_rcc_failure(self):
        r=classify_current_nodes([{"state":"PROBE_TIMEOUT","tabs":[tab()]}])
        self.assertEqual(r["counts"]["unavailable"],1)
    def test_duplicate_uuid(self):
        a=tab()
        b={**tab(), "tab_id":6, "node_label":"N13"}
        self.assertEqual(run([a,b])["counts"]["unresolved"],2)
    def test_duplicate_number(self):
        a=tab()
        b={**tab(),"tab_id":6,"conversation_key":"aaaaaaaa-1234-1234-1234-123456789abc","url":"https://chatgpt.com/c/aaaaaaaa-1234-1234-1234-123456789abc"}
        self.assertEqual(run([a,b])["counts"]["unresolved"],2)
    def test_missing_node(self):
        x=tab();x["node_label"]=""
        self.assertEqual(run([x])["counts"]["unresolved"],1)
    def test_other_page_ignored(self):
        self.assertEqual(len(run([{"url":"https://chatgpt.com/plugins","presence":"OPEN"}])["items"]),0)
    def test_minimized_no_inference(self):
        self.assertIsNone(run([tab()])["items"][0]["minimized"])
    def test_no_side_effects(self):
        a=tab(); run([a]);self.assertEqual(a["node_label"],"N12")

if __name__ == "__main__":
    unittest.main()
