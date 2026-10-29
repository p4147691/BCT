import unittest
from bct.features.comfy_bridge_contract import validate_read_request, verify_read_response
from bct.features.comfy_graph_snapshot import SnapshotError
class BridgeIdentityTests(unittest.TestCase):
    def test_identity_and_graph(self):
        req=validate_read_request(tab_id=123,url="http://127.0.0.1:8188/",session_id="s1",observed={"tab_id":123,"url":"http://127.0.0.1:8188/","session_id":"s1"})
        data=dict(req,source="live_canvas_memory",graph={"nodes":[],"links":[]})
        self.assertEqual(verify_read_response(data,request=req)["nodes"],[])
    def test_wrong_session(self):
        with self.assertRaises(SnapshotError):validate_read_request(tab_id=123,url="http://127.0.0.1:8188/",session_id="s1",observed={"tab_id":123,"url":"http://127.0.0.1:8188/","session_id":"other"})
    def test_wrong_url(self):
        with self.assertRaises(SnapshotError):validate_read_request(tab_id=123,url="http://localhost:8188/",session_id="s1",observed={})
