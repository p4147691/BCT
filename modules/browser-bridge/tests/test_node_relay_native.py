from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

NATIVE=Path(__file__).resolve().parents[1]/"native"
sys.path.insert(0,str(NATIVE))
os.environ.setdefault("BCT_BRIDGE_MCP_URL","http://127.0.0.1:19991/mcp")
import native_host
import node_relay_native as relay
import node_relay_store as mailbox
import persistent_host

N23="33333333-3333-4333-8333-333333333333"
N14="22222222-2222-4222-8222-222222222222"
DELIVERY="a"*32
ACK="b"*32
SHA=lambda text:hashlib.sha256(text.encode("utf-8")).hexdigest()


class FixtureCodec:
    # Fixture-only reversible obfuscation; production requires Windows DPAPI.
    def protect(self, value, *, context):
        return b"cipher"+bytes(x ^ 0xA5 for x in value)+hashlib.sha256(context).digest()[:8]

    def unprotect(self,value,*,context):
        if not value.startswith(b"cipher") or not value.endswith(hashlib.sha256(context).digest()[:8]):
            raise ValueError("CIPHER_CONTEXT_MISMATCH")
        return bytes(x ^ 0xA5 for x in value[6:-8])


def wire(typ, args, i=1):
    return {"schema_version":1,"type":typ,"request_id":f"{i:032x}",
            "arguments":args}


def encoded(messages):
    buf=io.BytesIO()
    for m in messages:native_host.write_frame(buf,m)
    buf.seek(0)
    return buf


def decoded(buf):
    buf.seek(0)
    out=[]
    while (item:=native_host.read_frame(buf)) is not None:
        out.append(item)
    return out


class NativePersistentRelayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/"relay.sqlite3"
        self.codec=FixtureCodec()
        self.store=mailbox.NodeRelayStore(self.db,self.codec)
        self.prompt="N23에서 N14에게 한 번만 전달할 검증용 문장"
        self.answer="N14 독립 릴레이 응답 확인"
        self.enqueue=wire("node_relay_enqueue",{
            "delivery_id":DELIVERY,"sender_node":"N23","sender_key":N23,
            "receiver_node":"N14","receiver_key":N14,
            "original_sha":SHA(self.prompt),"text":self.prompt})

    def do(self,messages,store=None):
        data=encoded(messages)
        out=io.BytesIO()
        # Runs actual Chrome Native Messaging 4-byte framed loop, not a JSON mock.
        assert relay.serve_node_session(native_host.read_frame(data),data,out,
                                        store or self.store)==0
        return decoded(out)

    def test_persistent_native_frames_full_n23_n14_n23_relay(self):
        first=self.do([self.enqueue])[0]
        self.assertTrue(first["ok"])
        self.assertEqual("QUEUED",first["receipt"]["state"])
        self.assertFalse(first["chatgpt_submitted"])
        self.assertFalse(first["receipt"]["will_resend"])
        same=self.do([self.enqueue])[0]
        self.assertTrue(same["receipt"]["replayed"])
        self.assertEqual("QUEUED",same["receipt"]["state"])
        # The host process/DB connection is recreated across each step.
        reopened=mailbox.NodeRelayStore(self.db,self.codec)
        claimed=self.do([wire("node_relay_claim",{
            "delivery_id":DELIVERY,"receiver_node":"N14","receiver_key":N14},2)],reopened)[0]
        self.assertTrue(claimed["ok"])
        self.assertEqual(self.prompt,claimed["receipt"]["text"])
        self.assertEqual("CLAIMED",claimed["receipt"]["state"])
        lost=self.do([wire("node_relay_claim",{
            "delivery_id":DELIVERY,"receiver_node":"N14","receiver_key":N14},3)])[0]
        self.assertFalse(lost["ok"])
        self.assertEqual("NOT_APPLIED",lost["outcome"])
        self.assertEqual("BRIDGE_CLAIM_ALREADY_ISSUED_NO_RETRY",lost["error"])
        ack=self.do([wire("node_relay_ack",{
            "delivery_id":DELIVERY,"receiver_node":"N14","receiver_key":N14,
            "ack_id":ACK},4)])[0]
        self.assertEqual("ACKED",ack["receipt"]["state"])
        self.assertTrue(self.do([wire("node_relay_ack",{
            "delivery_id":DELIVERY,"receiver_node":"N14","receiver_key":N14,
            "ack_id":ACK},5)])[0]["receipt"]["replayed"])
        delivered=self.do([wire("node_relay_reply",{
            "delivery_id":DELIVERY,"receiver_node":"N14","receiver_key":N14,
            "ack_id":ACK,"text":self.answer,"response_sha":SHA(self.answer)},6)])[0]
        self.assertEqual("REPLIED",delivered["receipt"]["state"])
        self.assertEqual(SHA(self.answer),delivered["receipt"]["response_sha"])
        returned=self.do([wire("node_relay_inspect",{
            "delivery_id":DELIVERY,"sender_node":"N23","sender_key":N23},7)])[0]
        self.assertEqual(self.answer,returned["receipt"]["response_text"])
        self.assertFalse(returned["receipt"]["chatgpt_reply_verified"])
        # Source message plaintext is not stored in the DB itself.
        raw=self.db.read_bytes()
        self.assertNotIn(self.prompt.encode("utf-8"),raw)
        self.assertNotIn(self.answer.encode("utf-8"),raw)

    def test_wrong_identity_hash_and_conflicting_original_denied(self):
        self.assertFalse(self.do([wire("node_relay_enqueue",{
            **self.enqueue["arguments"],"original_sha":"0"*64})])[0]["ok"])
        self.do([self.enqueue])
        wrong=wire("node_relay_claim",{
            "delivery_id":DELIVERY,"receiver_node":"N13","receiver_key":N14},8)
        self.assertEqual("BRIDGE_CLAIM_IDENTITY_DENIED",self.do([wrong])[0]["error"])
        coll=wire("node_relay_enqueue",{
            **self.enqueue["arguments"],"sender_node":"N13"},9)
        self.assertEqual("BRIDGE_DELIVERY_ID_COLLISION",self.do([coll])[0]["error"])

    def test_exact_framing_schema_and_unknown_no_retry(self):
        for invalid in [
            {**self.enqueue,"type":"bridge_read"},
            {**self.enqueue,"arguments":{**self.enqueue["arguments"],"unexpected":"x"}},
            {**self.enqueue,"request_id":"not-a-uuid"},
        ]:
            with self.subTest(invalid=invalid):
                r=self.do([invalid])[0]
                self.assertFalse(r["ok"])
        class Lost:
            def enqueue(self,args):
                raise sqlite3.OperationalError("unknown after side effect")
        lost=self.do([self.enqueue],Lost())[0]
        self.assertEqual("UNKNOWN",lost["outcome"])
        self.assertIn("NO_RETRY",lost["error"])

    def test_persistent_host_entrypoint_uses_origin_and_does_not_contact_core(self):
        inp=encoded([self.enqueue,wire("node_relay_inspect",{
            "delivery_id":DELIVERY,"sender_node":"N23","sender_key":N23},13)])
        out=io.BytesIO()
        with patch.object(persistent_host,"APPROVED_ORIGIN","chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"),patch.object(
            relay,"approved_store",return_value=self.store):
            # No test Core/MCP credential exists or is accessed.
            self.assertEqual(0,persistent_host.main.__name__=="main" and __import__("asyncio").run(
                persistent_host.serve(inp,out)))
        received=decoded(out)
        self.assertEqual(["QUEUED","QUEUED"],[x["receipt"]["state"] for x in received])
        self.assertTrue(all(x["ok"] for x in received))
        # Default production Native Host pathway does not open a mailbox.
        with patch.object(relay,"approved_store",side_effect=ValueError("disabled")):
            out=io.BytesIO()
            self.assertEqual(4,__import__("asyncio").run(
                persistent_host.serve(encoded([self.enqueue]),out)))
            self.assertEqual("AUTH_DENIED",decoded(out)[0]["outcome"])


if __name__=="__main__":
    unittest.main()
