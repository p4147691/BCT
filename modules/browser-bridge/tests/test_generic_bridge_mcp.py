from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
from test_mcp_integration import MCPIntegrationTests

HOST = Path(__file__).resolve().parents[1] / "native" / "persistent_host.py"
ORIGIN = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"


def frame(value: dict) -> bytes:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def request(index: int, tool: str, arguments: dict) -> dict:
    return {"schema_version": 2, "type": "tool_call", "request_id": f"{index:032x}",
            "tool_name": tool, "arguments": arguments}


def decode_all(data: bytes) -> list[dict]:
    values = []
    offset = 0
    while offset < len(data):
        size = struct.unpack("<I", data[offset:offset + 4])[0]
        offset += 4
        values.append(json.loads(data[offset:offset + size].decode("utf-8")))
        offset += size
    return values


class GenericBridgeMcpTests(unittest.TestCase):
    def test_exact_native_host_reaches_registered_read_and_control_tools(self):
        fixture = MCPIntegrationTests()
        fixture.setUp()
        try:
            with tempfile.TemporaryDirectory() as stage_text:
                stage = Path(stage_text)
                token = stage / "bridge.token"
                token.write_text(fixture.controller.mcp_secret(), encoding="utf-8")
                work_id = "browser-bridge-generic-e2e"
                messages = [
                    {"schema_version": 2, "type": "tool_list", "request_id": "0" * 32,
                     "tool_name": "", "arguments": {}},
                    request(1, "bct_status", {"compact": True, "scope": "bct"}),
                    request(2, "bct_create_work", {"work_id": work_id,
                            "request_summary": "Browser Bridge generic tool E2E",
                            "roots": [str(fixture.project)], "actions": ["read", "write", "execute"]}),
                    request(3, "bct_read", {"work_id": work_id, "operation_id": "bridge-read-e2e-01",
                            "arguments": {"path": str(fixture.project / "hello.txt")}}),
                    request(4, "bct_write", {"work_id": work_id, "operation_id": "bridge-write-e2e-01",
                            "arguments": {"path": str(fixture.project / "bridge-created.txt"),
                                          "content": "created through Browser Bridge\n",
                                          "expected_absent": True}}),
                    request(5, "bct_execute", {"work_id": work_id, "operation_id": "bridge-execute-e2e-01",
                            "arguments": {"kind": "python", "cwd": str(fixture.project),
                                          "script": str(fixture.project / "slow.py"), "timeout_s": 5}}),
                ]
                env = os.environ.copy()
                env.update({
                    "BCT_BRIDGE_EXTENSION_ORIGIN": ORIGIN,
                    "BCT_BRIDGE_MCP_URL": f"http://127.0.0.1:{fixture.port}/mcp",
                    "BCT_BRIDGE_TOKEN_PATH": str(token),
                    "BCT_BRIDGE_WORK_ID": "",
                    "PYTHONPATH": str(ROOT / "src"),
                })
                process = subprocess.run(
                    [sys.executable, str(HOST), ORIGIN], input=b"".join(map(frame, messages)),
                    capture_output=True, env=env, timeout=45, check=False,
                )
                self.assertEqual(0, process.returncode, process.stderr.decode("utf-8", "replace"))
                replies = decode_all(process.stdout)
                self.assertEqual(6, len(replies))
                self.assertIn("bct_chain_message", replies[0]["tools"])
                self.assertIn("bct_execute", replies[0]["tools"])
                self.assertTrue(replies[1]["ok"])
                self.assertTrue(replies[2]["ok"])
                self.assertTrue(replies[3]["ok"])
                receipt = replies[3]["result"]
                self.assertEqual("APPLIED", receipt["outcome"])
                self.assertEqual("hello from MCP\n", receipt["output"]["text"])
                self.assertTrue(replies[4]["ok"])
                self.assertEqual("APPLIED", replies[4]["result"]["outcome"])
                self.assertEqual("created through Browser Bridge\n",
                                 (fixture.project / "bridge-created.txt").read_text(encoding="utf-8"))
                self.assertTrue(replies[5]["ok"])
                self.assertEqual("APPLIED", replies[5]["result"]["outcome"])
                self.assertIn("slow execution complete", replies[5]["result"]["output"]["stdout"])
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
