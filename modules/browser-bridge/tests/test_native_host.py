import io
import json
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native"))
os.environ.setdefault("BCT_BRIDGE_MCP_URL", "http://127.0.0.1:19991/mcp")
import native_host as host


def frame(value):
    raw = json.dumps(value).encode()
    return struct.pack("<I", len(raw)) + raw


def valid():
    return {"schema_version": 1, "type": "bridge_read", "request_id": "a" * 32,
            "operation_id": "a" * 32, "capability": "read", "arguments": {"path": r"C:\fixture\hello.txt"}}


class BridgeHostTests(unittest.TestCase):
    def test_frame_roundtrip(self):
        self.assertEqual(valid(), host.read_frame(io.BytesIO(frame(valid()))))
        output = io.BytesIO(); host.write_frame(output, {"ok": True})
        self.assertEqual({"ok": True}, host.read_frame(io.BytesIO(output.getvalue())))

    def test_malformed_frames_rejected(self):
        with self.assertRaisesRegex(ValueError, "FRAME_TOO_LARGE"):
            host.read_frame(io.BytesIO(struct.pack("<I", 65537)))
        with self.assertRaises(ValueError):
            host.read_frame(io.BytesIO(struct.pack("<I", 12) + b"abc"))

    def test_schema_is_read_only_and_exact(self):
        for fields in ({"capability": "write"}, {"type": "execute"}, {"request_id": "bad"}, {"operation_id": "b" * 32}, {"arguments": {"path": "x", "command": "whoami"}}, {"extra": "unexpected"}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError): host.validate({**valid(), **fields})

    def test_origin_fails_closed(self):
        with patch.object(host, "APPROVED_ORIGIN", ""):
            self.assertEqual(4, host.main(argv=["chrome-extension://fake/"], inp=io.BytesIO(frame(valid())), out=io.BytesIO()))
        with patch.object(host, "APPROVED_ORIGIN", "chrome-extension://expected/"):
            self.assertEqual(4, host.main(argv=["chrome-extension://wrong/"], inp=io.BytesIO(frame(valid())), out=io.BytesIO()))

    def test_dispatch_failure_is_unknown_without_retry(self):
        output = io.BytesIO()
        with patch.object(host, "APPROVED_ORIGIN", "chrome-extension://expected/"), patch.object(host, "dispatch", side_effect=RuntimeError("offline")) as dispatch:
            self.assertEqual(0, host.main(argv=["chrome-extension://expected/"], inp=io.BytesIO(frame(valid())), out=output))
            self.assertEqual(1, dispatch.call_count)
        reply = host.read_frame(io.BytesIO(output.getvalue()))
        self.assertFalse(reply["ok"]); self.assertEqual("UNKNOWN", reply["outcome"])

    def test_unconfigured_work_is_denied(self):
        with patch.object(host, "WORK_ID", ""):
            import asyncio
            with self.assertRaisesRegex(ValueError, "HOST_AUTH_NOT_CONFIGURED"):
                asyncio.run(host.dispatch(valid()))


if __name__ == "__main__":
    unittest.main()
