import unittest
from unittest.mock import Mock
from bct.features.comfy_live_read import request_live_graph, validate_comfy_target
from bct.features.comfy_graph_snapshot import SnapshotError
class LiveReadTests(unittest.TestCase):
    def test_reject_foreign_origin(self):
        with self.assertRaises(SnapshotError): validate_comfy_target("http://localhost:8188/")
    def test_reject_unverified_saved_graph(self):
        manager=Mock()
        manager.request.return_value={"url":"http://127.0.0.1:8188/","source":"saved_json","graph":{"nodes":[],"links":[]}}
        with self.assertRaises(SnapshotError): request_live_graph(manager,tab_id="594836812",url="http://127.0.0.1:8188/")
    def test_fixed_command(self):
        manager=Mock()
        manager.request.return_value={"url":"http://127.0.0.1:8188/","source":"live_canvas_memory","graph":{"nodes":[],"links":[]}}
        self.assertEqual(request_live_graph(manager,tab_id="594836812",url="http://127.0.0.1:8188/")["nodes"],[])
        manager.request.assert_called_once_with("tools/call",{"name":"comfy_read_live_graph","arguments":{"tab_id":"594836812","url":"http://127.0.0.1:8188/"}})
