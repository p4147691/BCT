import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native"))
os.environ.setdefault("BCT_BRIDGE_MCP_URL", "http://127.0.0.1:19991/mcp")
import persistent_host

ID = "a" * 32

def response(value, error=False):
    return SimpleNamespace(isError=error, structuredContent=value)

def receipt(**kw):
    item = dict(operation_id=ID, state="FINISHED", outcome="APPLIED",
                evidence={"path": "fixture"}, duplicate=False,
                output={"text": "content"})
    item.update(kw)
    return item

class ReceiptSchemaTests(unittest.TestCase):
    def test_valid_read_and_receipt_lookup(self):
        for typ in ("bridge_read", "receipt_lookup"):
            with self.subTest(typ=typ):
                self.assertTrue(persistent_host.core_reply(response(receipt()), ID, typ)["ok"])

    def test_known_core_errors_and_unknown(self):
        for outcome in ("FAILED", "NOT_APPLIED", "UNKNOWN"):
            r = persistent_host.core_reply(response(receipt(outcome=outcome)), ID)
            self.assertFalse(r["ok"])
            self.assertEqual(outcome, r["outcome"])

    def test_is_error(self):
        self.assertEqual("RECEIPT_ERROR", persistent_host.core_reply(response(receipt(), True), ID)["outcome"])

    def test_rejects_untrusted_shapes(self):
        bad = [None, "", "ok", [], {}, {"outcome": "APPLIED"},
               receipt(operation_id="b" * 32), receipt(state="BOGUS"),
               receipt(outcome="ALIEN"), receipt(evidence=None),
               receipt(duplicate="false"), receipt(outcome=None),
               receipt(output={}), receipt(output={"text": 123}),
               receipt(state="FINISHED", outcome=None)]
        for content in bad:
            with self.subTest(content=content):
                r = persistent_host.core_reply(response(content), ID)
                self.assertFalse(r["ok"])
                self.assertEqual("RECEIPT_ERROR", r["outcome"])

    def test_pending_not_success(self):
        r = persistent_host.core_reply(response(receipt(state="RUNNING", outcome=None)), ID)
        self.assertFalse(r["ok"])
        self.assertEqual("PENDING", r["outcome"])

    def test_wrong_read_output_does_not_block_receipt_lookup(self):
        self.assertFalse(persistent_host.core_reply(response(receipt(output={})), ID, "bridge_read")["ok"])
        self.assertTrue(persistent_host.core_reply(response(receipt(output={})), ID, "receipt_lookup")["ok"])

if __name__ == "__main__":
    unittest.main()
