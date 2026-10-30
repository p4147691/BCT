import unittest
from bct.features.comfy_canvas_bridge import parse_bridge_snapshot
from bct.features.comfy_graph_snapshot import SnapshotError

class BridgeContractTests(unittest.TestCase):
    def test_valid_live_snapshot(self):
        graph={"nodes":[{"id":1,"type":"CLIPTextEncode","widgets_values":["a"]}],"links":[]}
        self.assertEqual(parse_bridge_snapshot({"source":"live_canvas_memory","url":"http://127.0.0.1:8188/","graph":graph},url="http://127.0.0.1:8188/"),graph)
    def test_reject_saved_json(self):
        with self.assertRaises(SnapshotError):
            parse_bridge_snapshot({"source":"saved_json","url":"http://127.0.0.1:8188/","graph":{"nodes":[],"links":[]}},url="http://127.0.0.1:8188/")
