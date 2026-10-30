"""Bounded Native Host unsolicited Core->Browser command roundtrip."""
import asyncio
import os
import queue
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault("BCT_BRIDGE_MCP_URL","http://127.0.0.1:18791/mcp")
sys.path.insert(0,str(ROOT/"modules"/"browser-bridge"/"native"))
import persistent_host

class Input:
    def __init__(self):
        self.queue=queue.Queue()
    def send(self,m):
        self.queue.put(m)

class MockClient:
    def __init__(self,*args,**kwargs): pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return None

@asynccontextmanager
async def mock_stream(*args,**kwargs):
    yield None,None,None

class MockSession:
    def __init__(self,*args,**kwargs):
        self.submitted=[]
        self.taken=False
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return None
    async def initialize(self):pass
    async def call_tool(self,name,args):
        if name=="bct_comfy_bridge_bind":
            self.session=args["session_id"]
            return SimpleNamespace(isError=False,structuredContent={"generation":3})
        if name=="bct_comfy_bridge_take":
            if not self.taken:
                self.taken=True
                return SimpleNamespace(isError=False,structuredContent={"request":{"operation_id":"a"*32,"arguments":{"tab_id":123,"url":"http://127.0.0.1:8188/","session_id":"s1"},"generation":3}})
            await asyncio.sleep(0.1)
            return SimpleNamespace(isError=False,structuredContent={"request":None})
        if name=="bct_comfy_bridge_submit":
            self.submitted.append(args)
            return SimpleNamespace(isError=False,structuredContent={"accepted":True})
        if name=="bct_read":
            return SimpleNamespace(isError=False,structuredContent={
                "operation_id":args["operation_id"],"state":"FINISHED","outcome":"APPLIED",
                "evidence":{},"duplicate":False,"output":{"text":"ok"}})
        raise AssertionError(name)

class PersistentHostReverseTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_unsolicited_command_and_exact_reply(self):
        session=MockSession()
        inp=Input()
        out=[]
        bootstrap={"schema_version":1,"type":"bridge_read","request_id":"b"*32,
                   "operation_id":"b"*32,"capability":"read","arguments":{"path":"fixture"}}
        inp.send(bootstrap)
        with tempfile.TemporaryDirectory() as temp:
            token=Path(temp)/"token"
            token.write_text("dummy",encoding="utf8")
            def read_frame(_inp,*args):
                return inp.queue.get(timeout=8)
            def write_frame(_out,frame):
                out.append(frame)
                if frame.get("type")=="core_comfy_read_command":
                    inp.send({"type":"comfy_canvas_result","request_id":frame["request_id"],
                              "session_id":frame["session_id"],"generation":frame["generation"],
                              "response":{"ok":True,"requestId":frame["request_id"],
                                          "tab_id":123,"url":"http://127.0.0.1:8188/",
                                          "session_id":"s1","source":"live_canvas_memory",
                                          "graph":{"nodes":[],"links":[]}}})
                    inp.send(None)
            with patch.object(persistent_host,"WORK_ID","isolated-work"), \
                 patch.object(persistent_host,"TOKEN_PATH",token), \
                 patch.object(persistent_host,"read_frame",read_frame), \
                 patch.object(persistent_host,"write_frame",write_frame), \
                 patch.object(persistent_host.httpx,"AsyncClient",MockClient), \
                 patch.object(persistent_host,"streamable_http_client",mock_stream), \
                 patch.object(persistent_host,"ClientSession",lambda *a,**k:session):
                result=await persistent_host.serve(inp,out)
            self.assertEqual(result,0)
            self.assertTrue(any(x.get("type")=="core_comfy_read_command" for x in out))
            self.assertEqual(len(session.submitted),1)
            self.assertEqual(session.submitted[0]["operation_id"],"a"*32)
