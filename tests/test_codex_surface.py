import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from bct.core.store import Store
from bct.codex_surface import local_codex_reference, register_codex_surfaces, codex_directory, observed_codex_nodes
A="00000000-0000-4000-8000-000000000001"
B="00000000-0000-4000-8000-000000000002"
def url(ref): return "https://chatgpt.com/local/client-new-thread:"+ref

class CodexSurfaceTests(unittest.TestCase):
    def test_exact_route_and_no_uuid_coercion(self):
        self.assertEqual(A,local_codex_reference(url(A)+"?view=local"))
        for value in ["https://evil.example/local/client-new-thread:"+A,
            "https://chatgpt.com/c/"+A, "https://chat.openai.com/local/client-new-thread:"+A, "https://chatgpt.com/local/other:"+A,
            "https://chatgpt.com/dots/"+A+"~context",url(A)+"/child"]:
            self.assertEqual("",local_codex_reference(value))
    def test_persistent_labels_separate_from_n_and_multiple_tabs(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"state.sqlite";store=Store(path)
            self.assertEqual({},codex_directory(store))
            first=register_codex_surfaces(store,[url(A),url(B),url(A)])
            self.assertEqual("C1",first[A]["node_label"])
            self.assertEqual("C2",first[B]["node_label"])
            self.assertFalse(first[A]["routable"])
            self.assertEqual(first,register_codex_surfaces(Store(path),[url(B),url(A)]))
            nodes=observed_codex_nodes(store,[{"instance_id":"i","session_id":"s","tabs":[
                {"url":url(A),"tab_id":1,"window_id":10},
                {"url":url(A),"tab_id":2,"window_id":20}]}])
            self.assertEqual(["C1","C1"],[n["node_label"] for n in nodes])
            self.assertNotEqual(nodes[0]["tab_id"],nodes[1]["tab_id"])
            with store.transaction() as db:
                self.assertEqual(0,db.execute("SELECT count(*) FROM conversation_network_node_labels").fetchone()[0])
    def test_concurrent_duplicate_registration(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"state.sqlite"
            stores=[Store(path),Store(path)]
            with ThreadPoolExecutor(2) as pool:
                results=list(pool.map(lambda store:register_codex_surfaces(store,[url(A),url(B)]),stores))
            self.assertEqual(results[0],results[1])
            self.assertEqual(2,len(codex_directory(stores[0])))
    def test_batch_invalid_is_atomic(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"state.sqlite")
            with self.assertRaises(ValueError):register_codex_surfaces(store,[url(A),"https://chatgpt.com/"])
            self.assertEqual({},codex_directory(store))

    def test_bct_ui_projection_reads_without_allocating(self):
        from unittest.mock import patch
        from bct.monitor_runtime import build_monitor_ui_state
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"state.sqlite")
            rcc=[{"instance_id":"i","session_id":"s","state":"OPEN","tabs":[
                {"url":url(A),"tab_id":1,"window_id":10,"conversation_key":""}]}]
            with patch("bct.monitor_runtime.discover_instance_ids",return_value=["i"]), patch("bct.monitor_runtime._rcc_states",return_value=rcc):
                before=build_monitor_ui_state(store=store,service_state={},data_root=Path(root))
                self.assertEqual("",before["codex_nodes"][0]["node_label"])
                self.assertEqual({},codex_directory(store))
                register_codex_surfaces(store,[url(A)])
                after=build_monitor_ui_state(store=store,service_state={},data_root=Path(root))
                self.assertEqual("C1",after["codex_nodes"][0]["node_label"])
                self.assertEqual("i",after["codex_nodes"][0]["instance_id"])
                self.assertFalse(after["codex_nodes"][0]["routable"])

    def test_registration_http_boundary(self):
        from types import SimpleNamespace
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient
        from bct.runtime_server import codex_surface_register_response, MONITOR_EXTENSION_ORIGIN
        with tempfile.TemporaryDirectory() as root:
            bct=SimpleNamespace(store=Store(Path(root)/"state.sqlite"))
            async def endpoint(request):return await codex_surface_register_response(bct,request)
            with TestClient(Starlette(routes=[Route("/register",endpoint,methods=["POST"])])) as client:
                self.assertEqual(403,client.post("/register",json={"urls":[url(A)]}).status_code)
                headers={"origin":MONITOR_EXTENSION_ORIGIN}
                response=client.post("/register",headers=headers,json={"urls":[url(A),url(B)]})
                self.assertEqual(200,response.status_code)
                self.assertEqual("C2",response.json()["directory"][B]["node_label"])
                self.assertEqual(400,client.post("/register",headers=headers,json={"urls":[url(A)],"conversation_key":A}).status_code)

    def test_c_labels_cycle_like_n_without_reusing_identity(self):
        from bct.conversation_network import _node_label
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"state.sqlite";store=Store(path)
            refs=[f"00000000-0000-4000-8000-{n:012x}" for n in range(1,200)]
            # Registration is bounded per request; the allocation history spans batches.
            for start in range(0,len(refs),64):
                register_codex_surfaces(store,[url(r) for r in refs[start:start+64]])
            directory=codex_directory(Store(path))
            for index,ref in enumerate(refs,1):
                self.assertEqual("C"+_node_label(index)[1:],directory[ref]["node_label"])
                self.assertEqual(index,directory[ref]["assignment_sequence"])
            self.assertEqual("C99",directory[refs[98]]["node_label"])
            self.assertEqual("C1",directory[refs[99]]["node_label"])
            self.assertEqual("C1",directory[refs[198]]["node_label"])
            # As with N, aliases can overlap while both references are still present.
            nodes=observed_codex_nodes(store,[{"instance_id":"i","session_id":"s","state":"OPEN","tabs":[
                {"url":url(refs[0]),"tab_id":1,"window_id":10},
                {"url":url(refs[99]),"tab_id":2,"window_id":10}]}])
            self.assertEqual(["C1","C1"],[n["node_label"] for n in nodes])
            self.assertNotEqual(nodes[0]["reference"],nodes[1]["reference"])
            self.assertNotEqual(nodes[0]["tab_id"],nodes[1]["tab_id"])
            self.assertTrue(all(not n["routable"] for n in nodes))
            again=register_codex_surfaces(store,[url(refs[0]),url(refs[99])])
            self.assertEqual(1,again[refs[0]]["assignment_sequence"])
            self.assertEqual(100,again[refs[99]]["assignment_sequence"])
