from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/"native"
ORIGIN="chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"
N23="33333333-3333-4333-8333-333333333333"
N14="22222222-2222-4222-8222-222222222222"
DID="a"*32
ACK="b"*32


def wire(t,a,n):
    data=json.dumps({"schema_version":1,"type":t,
                     "request_id":f"{n:032x}","arguments":a},
                    ensure_ascii=False,separators=(",",":")).encode("utf-8")
    return struct.pack("<I",len(data))+data


def unpack(data):
    out=[]
    stream=io.BytesIO(data)
    while header:=stream.read(4):
        if len(header)!=4:raise AssertionError("TRUNCATED_HEADER")
        length=struct.unpack("<I",header)[0]
        if not 0<length<=65536:raise AssertionError("FRAME_LIMIT")
        payload=stream.read(length)
        if len(payload)!=length:raise AssertionError("TRUNCATED_FRAME")
        out.append(json.loads(payload.decode("utf-8")))
    return out


@unittest.skipUnless(os.name=="nt","real DPAPI Native Host process requires Windows")
class NativeRelayWindowsProcessE2E(unittest.TestCase):
    def test_native_host_restarts_preserve_exact_mailbox_and_no_mcp(self):
        with tempfile.TemporaryDirectory(prefix="bct-native-node-fixture-") as d:
            db=Path(d)/"synthetic-mailbox.sqlite3"
            env=dict(os.environ)
            # Exact synthetic frame route. No BCT Core, RCC or live MCP token.
            for field in ("BCT_BRIDGE_MCP_URL","BCT_BRIDGE_WORK_ID",
                          "BCT_BRIDGE_TOKEN_PATH"):
                env.pop(field,None)
            env.update(BCT_BRIDGE_EXTENSION_ORIGIN=ORIGIN,
                       BCT_BRIDGE_NODE_RELAY_ENABLED="1",
                       BCT_BRIDGE_NODE_MAILBOX_DB=str(db),
                       PYTHONDONTWRITEBYTECODE="1")
            def child(*packets):
                p=subprocess.run([sys.executable,"-B",str(NATIVE/"persistent_host.py"),ORIGIN],
                  input=b"".join(packets),capture_output=True,timeout=15,env=env)
                self.assertEqual(0,p.returncode,p.stderr.decode("utf-8","replace")[:500])
                return unpack(p.stdout)
            prompt="독립 Native Host 영속 릴레이 확인용 합성 메시지"
            reply="N14 테스트 프로세스가 N23에 회신"
            sha=lambda text:hashlib.sha256(text.encode("utf-8")).hexdigest()
            enq=dict(delivery_id=DID,sender_node="N23",sender_key=N23,
                     receiver_node="N14",receiver_key=N14,
                     original_sha=sha(prompt),text=prompt)
            first=child(wire("node_relay_enqueue",enq,1))
            self.assertTrue(first[0]["ok"],first)
            self.assertEqual("QUEUED",first[0]["receipt"]["state"])
            self.assertTrue(db.is_file())
            assert prompt.encode("utf-8") not in db.read_bytes()
            # New Native Host process, same protected SQLite mailbox.
            claim=child(wire("node_relay_claim",{
                "delivery_id":DID,"receiver_node":"N14","receiver_key":N14},2))
            self.assertEqual(prompt,claim[0]["receipt"]["text"])
            self.assertEqual("CLAIMED",claim[0]["receipt"]["state"])
            lost=child(wire("node_relay_claim",{
                "delivery_id":DID,"receiver_node":"N14","receiver_key":N14},3))
            self.assertFalse(lost[0]["ok"])
            self.assertEqual("BRIDGE_CLAIM_ALREADY_ISSUED_NO_RETRY",lost[0]["error"])
            ack=child(wire("node_relay_ack",{
                "delivery_id":DID,"receiver_node":"N14",
                "receiver_key":N14,"ack_id":ACK},4),
                wire("node_relay_reply",{
                "delivery_id":DID,"receiver_node":"N14","receiver_key":N14,
                "ack_id":ACK,"text":reply,"response_sha":sha(reply)},5))
            self.assertEqual(["ACKED","REPLIED"],[r["receipt"]["state"] for r in ack])
            got=child(wire("node_relay_inspect",{
                "delivery_id":DID,"sender_node":"N23","sender_key":N23},6))
            self.assertEqual(reply,got[0]["receipt"]["response_text"])
            self.assertEqual(sha(reply),got[0]["receipt"]["response_sha"])
            self.assertNotIn(reply.encode("utf-8"),db.read_bytes())
            self.assertFalse(got[0]["chatgpt_submitted"])
            self.assertFalse(got[0]["receipt"]["chatgpt_reply_verified"])


if __name__=="__main__":
    unittest.main()
