import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from bct.features.comfy_reverse_channel import ComfyReverseChannel, ComfyTransportUnknown
from bct.features.comfy_canvas_adapter import ComfyCanvasAdapter
from bct.service import BCT
from bct.core.models import Principal

ROOT=Path(__file__).resolve().parents[1]
URL="http://127.0.0.1:8188/"
ARGS={"tab_id":123,"url":URL,"session_id":"session1","observed":{"tab_id":123,"url":URL,"session_id":"session1"}}

class ReverseTransportTests(unittest.TestCase):
    def test_core_originated_fixed_canvas_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            bct=BCT(state_path=Path(folder)/"test.sqlite",policy_path=ROOT/"bct.toml")
            principal=Principal("comfy-reverse-test","test",frozenset(bct.operations.capabilities))
            work_id="comfy-reverse-authorized"
            bct.create_work(work_id=work_id,request_summary="isolated",roots=[folder],actions=["comfy_canvas_read"],principal=principal)
            generation=bct.comfy_reverse_channel.bind(work_id,"host-session-1")
            operation_id="a"*32
            errors=[]
            def browser_side():
                try:
                    cmd=bct.comfy_reverse_channel.take(work_id,"host-session-1",generation,5)
                    self.assertEqual(cmd["operation_id"],operation_id)
                    self.assertEqual(cmd["arguments"],{"operation":"comfy_canvas_read","tab_id":123,"url":URL,"session_id":"session1"})
                    result=subprocess.run(["node",str(ROOT/"tests"/"comfy_browser_mock_roundtrip.cjs")],cwd=ROOT,capture_output=True,text=True,timeout=10,check=True)
                    reply=json.loads(result.stdout)
                    self.assertTrue(bct.comfy_reverse_channel.submit(work_id,"host-session-1",generation,operation_id,reply))
                    self.assertFalse(bct.comfy_reverse_channel.submit(work_id,"host-session-1",generation,operation_id,reply))
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=browser_side,daemon=True)
            thread.start()
            try:
                receipt=bct.operations.run(principal=principal,work_id=work_id,operation_id=operation_id,capability="comfy_canvas_read",arguments=ARGS)
                thread.join(6)
                self.assertFalse(errors,repr(errors))
                self.assertEqual(receipt.outcome.value,"APPLIED")
                self.assertEqual(receipt.output["graph"]["nodes"][0]["id"],42)
                saved=bct.store.get_operation_for(operation_id=operation_id,work_id=work_id,principal_id=principal.principal_id)
                self.assertEqual(saved.outcome.value,"APPLIED")
            finally:
                bct.cdp_connections.close()
    def test_disconnect_preserves_unknown_and_disallows_replay(self):
        channel=ComfyReverseChannel()
        generation=channel.bind("w","session")
        results=[]
        def reader():
            try:
                channel.read_canvas({"_work_id":"w","_operation_id":"c"*32,"tab_id":123})
            except Exception as exc:
                results.append(str(exc))
        thread=threading.Thread(target=reader,daemon=True)
        thread.start()
        command=channel.take("w","session",generation,3)
        self.assertEqual(command["operation_id"],"c"*32)
        self.assertFalse(channel.submit("w","session",generation,"c"*32,{"requestId":"wrong","ok":True}))
        channel.disconnect("w","session",generation)
        thread.join(3)
        self.assertTrue(results)
        self.assertIn("NO_RETRY",results[0])
        with self.assertRaises(PermissionError):
            channel.take("w","session",generation,0)

    def test_wrong_generation_duplicate_and_timeout(self):
        channel=ComfyReverseChannel()
        generation=channel.bind("w","s")
        with self.assertRaises(PermissionError):
            channel.take("w","other",generation,0)
        with self.assertRaises(PermissionError):
            channel.take("w","s",generation+1,0)
        with self.assertRaises(ComfyTransportUnknown):
            channel.read_canvas({"_work_id":"w","_operation_id":"b"*32,"tab_id":123})
        self.assertIsNone(channel.take("w","s",generation,0))
