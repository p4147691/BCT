"""ComfyUI fixed-read Core + Native schema integration, no live browser."""
from __future__ import annotations
import sys
import os
os.environ.setdefault("BCT_BRIDGE_MCP_URL","http://127.0.0.1:18791/mcp")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bct.service import BCT
from bct.core.models import Principal, AuthorizationError, ConfirmedFailure
from bct.features.comfy_canvas_adapter import ComfyCanvasAdapter
from bct.features.comfy_canvas_read import ComfyCanvasReadFeature

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules" / "browser-bridge" / "native"))
import native_host
import persistent_host

URL = "http://127.0.0.1:8188/"
REQUEST = {"tab_id":123,"url":URL,"session_id":"session1","observed":{"tab_id":123,"url":URL,"session_id":"session1"}}
GRAPH = {"nodes":[{"id":1,"type":"CLIPTextEncode","widgets_values":["hello"]}],"links":[]}
class FakeTransport:
    def read_canvas(self, args):
        return {"tab_id":args["tab_id"],"url":args["url"],"session_id":args["session_id"],"source":"live_canvas_memory","graph":GRAPH}

class NodeBridgeTransport:
    """Run only the isolated MAIN/ISOLATED mock; no operating Chrome access."""
    def read_canvas(self, args):
        import json
        import subprocess
        completed = subprocess.run(
            ["node", str(ROOT/"tests"/"comfy_browser_mock_roundtrip.cjs")],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        )
        reply = json.loads(completed.stdout)
        if any(reply.get(k) != args[k] for k in ("tab_id", "url", "session_id")):
            raise ValueError("COMFY_MOCK_IDENTITY_MISMATCH")
        return reply

JS_GRAPH = {"nodes":[{"id":42,"type":"CLIPTextEncode","widgets_values":["untouched prompt"]}],"links":[]}

class ComfyCoreIntegrationTests(unittest.TestCase):
    def test_policy_fence_and_durable_core_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            bct=BCT(state_path=Path(folder)/"state.sqlite",policy_path=ROOT/"bct.toml",comfy_canvas_transport=FakeTransport())
            principal=Principal("comfy-tester","test",frozenset(bct.operations.capabilities))
            try:
                bct.create_work(work_id="comfy-test-allowed",request_summary="test",roots=[folder],actions=["comfy_canvas_read"],principal=principal)
                result=bct.operations.run(principal=principal,work_id="comfy-test-allowed",operation_id="comfy-isolated-01",capability="comfy_canvas_read",arguments=REQUEST)
                self.assertEqual(result.outcome.value,"APPLIED")
                self.assertEqual(result.output["graph"],GRAPH)
                receipt=bct.store.get_operation_for(operation_id="comfy-isolated-01",work_id="comfy-test-allowed",principal_id=principal.principal_id)
                self.assertEqual(receipt.outcome.value,"APPLIED")
                bct.create_work(work_id="comfy-test-denied",request_summary="test",roots=[folder],actions=["read"],principal=principal)
                with self.assertRaises(AuthorizationError):
                    bct.operations.run(principal=principal,work_id="comfy-test-denied",operation_id="comfy-denied-01",capability="comfy_canvas_read",arguments=REQUEST)
            finally:
                bct.cdp_connections.close()
    def test_unbound_transport_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            bct=BCT(state_path=Path(folder)/"state.sqlite",policy_path=ROOT/"bct.toml")
            principal=Principal("comfy-unbound","test",frozenset(bct.operations.capabilities))
            try:
                bct.create_work(work_id="comfy-unbound-work",request_summary="test",roots=[folder],actions=["comfy_canvas_read"],principal=principal)
                result=bct.operations.run(principal=principal,work_id="comfy-unbound-work",operation_id="unbound-01",capability="comfy_canvas_read",arguments=REQUEST)
                self.assertNotEqual(result.outcome.value,"APPLIED")
            finally:
                bct.cdp_connections.close()

    def test_native_dispatch_into_core_receipt_isolated(self):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        import asyncio
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            token_file=Path(folder)/"token"
            token_file.write_text("test-only-token",encoding="utf-8")
            bct=BCT(state_path=Path(folder)/"state.sqlite",policy_path=ROOT/"bct.toml",comfy_canvas_transport=NodeBridgeTransport())
            principal=Principal("native-comfy-tester","test",frozenset(bct.operations.capabilities))
            bct.create_work(work_id="native-bridge-work",request_summary="test",roots=[folder],actions=["comfy_canvas_read"],principal=principal)
            class FakeClient:
                def __init__(self,*args,**kwargs): pass
                async def __aenter__(self): return self
                async def __aexit__(self,*args): pass
            class FakeSession:
                def __init__(self,*args,**kwargs):pass
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def initialize(self):return None
                async def call_tool(self,name,args):
                    if name!="bct_comfy_canvas_read":raise AssertionError("WRONG_CORE_CAPABILITY")
                    result=bct.operations.run(principal=principal,work_id=args["work_id"],operation_id=args["operation_id"],capability="comfy_canvas_read",arguments=args["arguments"])
                    return SimpleNamespace(isError=False,structuredContent={"operation_id":args["operation_id"],"state":result.state.value,"outcome":result.outcome.value,"evidence":result.evidence,"duplicate":False,"output":result.output})
            @asynccontextmanager
            async def fake_stream(*args,**kwargs):
                yield None,None,None
            operation_id="a"*32
            message={"schema_version":1,"type":"comfy_canvas_read","request_id":operation_id,"operation_id":operation_id,"capability":"comfy_canvas_read","arguments":REQUEST}
            try:
                with patch.object(native_host,"WORK_ID","native-bridge-work"),patch.object(native_host,"TOKEN_PATH",token_file),patch("httpx.AsyncClient",FakeClient),patch("mcp.client.streamable_http.streamable_http_client",fake_stream),patch("mcp.ClientSession",FakeSession):
                    reply=asyncio.run(native_host.dispatch(message))
                self.assertTrue(reply["ok"])
                self.assertEqual(reply["request_id"],operation_id)
                self.assertEqual(reply["result"]["output"]["graph"],JS_GRAPH)
                receipt=bct.store.get_operation_for(operation_id=operation_id,work_id="native-bridge-work",principal_id=principal.principal_id)
                self.assertEqual(receipt.outcome.value,"APPLIED")
            finally:
                bct.cdp_connections.close()
    def test_native_fixed_command_schema_and_receipt(self):
        id="a"*32
        message={"schema_version":1,"type":"comfy_canvas_read","request_id":id,"operation_id":id,"capability":"comfy_canvas_read","arguments":REQUEST}
        self.assertEqual(native_host.validate(message)[0],id)
        for bad in [
            {**message,"capability":"read"},
            {**message,"arguments":{**REQUEST,"url":"http://evil.test/"}},
            {**message,"operation_id":"b"*32},
        ]:
            with self.assertRaises(ValueError):native_host.validate(bad)
        from types import SimpleNamespace
        receipt={"operation_id":id,"state":"FINISHED","outcome":"APPLIED","evidence":{"read_only":True},"duplicate":False,"output":{"graph":GRAPH}}
        result=persistent_host.core_reply(SimpleNamespace(isError=False,structuredContent=receipt),id,"comfy_canvas_read")
        self.assertTrue(result["ok"])
        receipt["output"]={"graph":{"nodes":[],"links":[[4,1,0,2,0,"IMAGE"]]}}
        self.assertFalse(persistent_host.core_reply(SimpleNamespace(isError=False,structuredContent=receipt),id,"comfy_canvas_read")["ok"])
