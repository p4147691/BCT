import asyncio
import sys
import unittest
from bct.features.cdp_persistent import PersistentCDP, UncertainDelivery


class PersistentCDPTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_process_and_serializes(self):
        script = ("import sys,json\n"
                  "for line in sys.stdin:\n"
                  " m=json.loads(line)\n"
                  " if 'id' in m:\n"
                  "  print(json.dumps({'jsonrpc':'2.0','id':m['id'],"
                  "'result':{'method':m['method']}}),flush=True)\n")
        client = PersistentCDP([sys.executable, "-u", "-c", script])
        try:
            a, b = await asyncio.gather(
                client.request("tools/list"), client.request("tools/list"))
            self.assertEqual(a["method"], "tools/list")
            self.assertEqual(b["method"], "tools/list")
            self.assertEqual(client.generation, 1)
        finally:
            await client.close()

    async def test_no_replay_after_stream_closes(self):
        script = ("import sys,json\n"
                  "for line in sys.stdin:\n"
                  " m=json.loads(line)\n"
                  " if m.get('method')=='initialize':\n"
                  "  print(json.dumps({'id':m['id'],'result':{}}),flush=True)\n"
                  " elif m.get('method')=='tools/call':\n"
                  "  break\n")
        client = PersistentCDP([sys.executable, "-u", "-c", script], timeout=2)
        try:
            with self.assertRaises(UncertainDelivery):
                await client.request("tools/call", {"name": "test"})
            self.assertEqual(client.generation, 1)
        finally:
            await client.close()
