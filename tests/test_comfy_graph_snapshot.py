import unittest
from bct.features.comfy_graph_snapshot import validate_snapshot, isolated_prompt_copy, unchanged_except_prompt, SnapshotError

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.graph={"nodes":[{"id":1,"type":"CLIPTextEncode","widgets_values":["original"]},{"id":2,"type":"PreviewImage","widgets_values":[]}],"links":[[3,1,0,2,0,"IMAGE"]]}
    def test_clone_prompt_preserves_structure(self):
        out=isolated_prompt_copy(self.graph,1,0,"A red apple on a wooden table")
        self.assertTrue(unchanged_except_prompt(self.graph,out,1,0))
        self.assertEqual(self.graph["nodes"][0]["widgets_values"][0],"original")
    def test_reject_missing_link_node(self):
        self.graph["links"][0][3]=99
        with self.assertRaises(SnapshotError): validate_snapshot(self.graph)
    def test_reject_duplicate_id(self):
        self.graph["nodes"][1]["id"]=1
        with self.assertRaises(SnapshotError): validate_snapshot(self.graph)
