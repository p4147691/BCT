"""End-to-end isolated native persistent port -> simulated BCT Browser Bridge -> Core receipt."""
import asyncio
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault("BCT_BRIDGE_MCP_URL","http://127.0.0.1:18791/mcp")
sys.path.insert(0,str(ROOT/"modules"/"browser-bridge"/"native"))
from bct.service import BCT
from bct.core.models import Principal
import persistent_host

class FakeClient:
    def __init__(self,*args,**kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self,*args): return False

@asynccontextmanager
async def fake_stream(*args,**kwargs):
    yield None,None,None

class BridgeMCP:
    def __init__(self,bct,work_id):
        self.bct=bct
        self.work_id=work_id
        self.ready=threading.Event()
        self.submitted=threading.Event()
        self.accepted=False
    async def __aenter__(self): return self
    async def __aexit__(self,*args):return False
    async def initialize(self): return None
    async def call_tool(self,name,args):
        self.assert_work(args)
        if name=="bct_comfy_bridge_bind":
            g=self.bct.comfy_reverse_channel.bind(args["work_id"],args["session_id"])
            self.ready.set()
            return SimpleNamespace(isError=False,structuredContent={"generation":g})
        if name=="bct_comfy_bridge_take":
            result=await asyncio.to_thread(self.bct.comfy_reverse_channel.take,
              args["work_id"],args["session_id"],args["generation"],args["wait_seconds"])
            return SimpleNamespace(isError=False,structuredContent={"request":result})
        if name=="bct_comfy_bridge_submit":
            self.accepted=self.bct.comfy_reverse_channel.submit(
               args["work_id"],args["session_id"],args["generation"],args["operation_id"],args["response"])
            self.submitted.set()
            return SimpleNamespace(isError=False,structuredContent={"accepted":self.accepted})
        if name=="bct_read":
            return SimpleNamespace(isError=False,structuredContent={
                "operation_id":args["operation_id"],"state":"FINISHED","outcome":"APPLIED",
                "evidence":{},"duplicate":False,"output":{"text":"bootstrap"}})
        raise AssertionError("UNAUTHORIZED_TOOL:"+name)
    def assert_work(self,args):
        if args["work_id"]!=self.work_id:raise AssertionError("WORK_MISMATCH")

class ReverseCompleteRoundtripTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_to_native_to_canvas_and_back(self):
        with tempfile.TemporaryDirectory() as folder:
            bct=BCT(state_path=Path(folder)/"test.sqlite",policy_path=ROOT/"bct.toml")
            work_id="isolated-comfy-approved"
            principal=Principal("isolated-comfy-user","test",frozenset(bct.operations.capabilities))
            bct.create_work(work_id=work_id,request_summary="test",roots=[folder],
                            actions=["comfy_canvas_read"],principal=principal)
            mcp=BridgeMCP(bct,work_id)
            input_queue=queue.Queue()
            bootstrap={"schema_version":1,"type":"bridge_read","request_id":"b"*32,
                       "operation_id":"b"*32,"capability":"read","arguments":{"path":"test"}}
            input_queue.put(bootstrap)
            output=[]
            token=Path(folder)/"bridge-token"
            token.write_text("isolated-token",encoding="utf8")
            def fake_read_frame(_inp,*args):
                return input_queue.get(timeout=15)
            def fake_write_frame(_out,payload):
                output.append(payload)
                if payload.get("type")=="core_comfy_read_command":
                    cmd=payload
                    run=subprocess.run(["node",str(ROOT/"tests"/"comfy_browser_mock_roundtrip.cjs")],
                        capture_output=True,text=True,cwd=ROOT,timeout=8,check=True)
                    response=json.loads(run.stdout)
                    if response.get("requestId")!=cmd["request_id"]:
                        raise AssertionError("OPERATION_ID_MISMATCH")
                    input_queue.put({"type":"comfy_canvas_result",
                        "request_id":cmd["request_id"],"session_id":cmd["session_id"],
                        "generation":cmd["generation"],"response":response})
            patches=[
                patch.object(persistent_host,"WORK_ID",work_id),
                patch.object(persistent_host,"TOKEN_PATH",token),
                patch.object(persistent_host,"read_frame",fake_read_frame),
                patch.object(persistent_host,"write_frame",fake_write_frame),
                patch.object(persistent_host.httpx,"AsyncClient",FakeClient),
                patch.object(persistent_host,"streamable_http_client",fake_stream),
                patch.object(persistent_host,"ClientSession",lambda *a,**kw:mcp),
            ]
            try:
                for p in patches:p.start()
                host_task=asyncio.create_task(persistent_host.serve(None,output))
                self.assertTrue(await asyncio.to_thread(mcp.ready.wait,3))
                receipt=await asyncio.to_thread(bct.operations.run,
                    principal=principal,work_id=work_id,operation_id="a"*32,
                    capability="comfy_canvas_read",
                    arguments={"tab_id":123,"url":"http://127.0.0.1:8188/","session_id":"session1",
                               "observed":{"tab_id":123,"url":"http://127.0.0.1:8188/","session_id":"session1"}})
                self.assertEqual(receipt.outcome.value,"APPLIED")
                self.assertEqual(receipt.output["graph"]["nodes"][0]["id"],42)
                self.assertTrue(mcp.accepted)
                saved=bct.store.get_operation_for(operation_id="a"*32,work_id=work_id,principal_id=principal.principal_id)
                self.assertEqual(saved.outcome.value,"APPLIED")
                input_queue.put(None)
                self.assertEqual(await asyncio.wait_for(host_task,4),0)
            finally:
                for p in reversed(patches):p.stop()
                bct.cdp_connections.close()
