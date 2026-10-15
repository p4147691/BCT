import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
LAUNCHER = NATIVE / "launcher" / "Program.cs"
ACTIVATION_POLICY = NATIVE / "launcher" / "BridgeActivationPolicyFixture.cs"
sys.path.insert(0, str(NATIVE))
os.environ.setdefault("BCT_BRIDGE_MCP_URL", "http://127.0.0.1:19991/mcp")
import persistent_host


class BridgeBoundaryContractTests(unittest.TestCase):
    def test_launcher_rejects_path_python_and_prefix_origin(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertNotIn('ProcessStartInfo("python")', source)
        self.assertIn('BCT_BRIDGE_PYTHON_EXE', source)
        self.assertIn('Path.IsPathFullyQualified(python)', source)
        self.assertIn('string.Equals(args[0], ApprovedOrigin, StringComparison.Ordinal)', source)
        self.assertNotIn('StartsWith("chrome-extension://"', source)

    def test_activation_policy_is_explicit_fixture_only_and_denies_before_read(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        policy = ACTIVATION_POLICY.read_text(encoding="utf-8")
        self.assertIn('args[0] == "--bridge-activation-policy-server"', launcher)
        self.assertIn('args[0] == "--bridge-activation-policy-client"', launcher)
        self.assertIn("GetNamedPipeClientSessionId", policy)
        server_read = policy.index("pipe.ReadAsync(request.AsMemory()")
        self.assertLess(policy.index("!GetNamedPipeClientSessionId("), server_read)
        self.assertLess(policy.index("DENIED_BEFORE_READ"), server_read)
        self.assertLess(policy.index("pipe.WriteAsync(new byte[] { Verified }"),
                        server_read)
        client_start = policy.index("internal static async Task<int> RunClient")
        client_gate_read = policy.index("pipe.ReadAsync(policyGate.AsMemory()",
                                        client_start)
        client_payload_write = policy.index(
            "pipe.WriteAsync(new byte[] { Request }", client_start)
        self.assertLess(client_gate_read, client_payload_write)
        for runtime_dependency in (
            "PeerAdapter", "BindingLifecycle", "DpapiFileSecretStore",
            "peer_frame", "persistent_host.py",
        ):
            self.assertNotIn(runtime_dependency, policy)

    def test_core_receipt_error_does_not_become_success(self):
        r = persistent_host.core_reply(SimpleNamespace(isError=True, structuredContent={"error": "not_found"}), "a"*32)
        self.assertFalse(r["ok"])
        self.assertEqual("RECEIPT_ERROR", r["outcome"])
        r = persistent_host.core_reply(SimpleNamespace(isError=False, structuredContent={"operation_id":"a"*32,"state":"FINISHED","outcome":"UNKNOWN","evidence":{},"duplicate":False}), "a"*32)
        self.assertFalse(r["ok"])
        self.assertEqual("UNKNOWN", r["outcome"])

    def test_host_rejects_wrong_origin_before_network(self):
        env = dict(os.environ)
        env.update(BCT_BRIDGE_EXTENSION_ORIGIN="chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/",
                   BCT_BRIDGE_MCP_URL="http://127.0.0.1:19991/mcp")
        proc = subprocess.run([sys.executable, str(NATIVE/"persistent_host.py"), "chrome-extension://wrong/"],
                              input=b"", capture_output=True, env=env, timeout=10)
        self.assertEqual(4, proc.returncode)
        self.assertEqual(b"", proc.stdout)

    def test_host_auth_denied_is_framed_without_core(self):
        env = dict(os.environ)
        env.update(BCT_BRIDGE_EXTENSION_ORIGIN="chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/",
                   BCT_BRIDGE_MCP_URL="http://127.0.0.1:19991/mcp", BCT_BRIDGE_WORK_ID="",
                   BCT_BRIDGE_TOKEN_PATH=str(ROOT/"no-token-is-created"))
        payload = b'{"schema_version":1,"type":"bridge_read","request_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","operation_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","capability":"read","arguments":{"path":"fixture"}}'
        request = struct.pack("<I", len(payload)) + payload
        proc = subprocess.run([sys.executable, str(NATIVE/"persistent_host.py"), env["BCT_BRIDGE_EXTENSION_ORIGIN"]],
                              input=request, capture_output=True, env=env, timeout=10)
        self.assertEqual(4, proc.returncode)
        self.assertGreaterEqual(len(proc.stdout), 4)
        import json
        size = struct.unpack("<I", proc.stdout[:4])[0]
        reply = json.loads(proc.stdout[4:4+size])
        self.assertEqual("AUTH_DENIED", reply["outcome"])
        self.assertEqual("a"*32, reply["request_id"])


if __name__ == "__main__":
    unittest.main()
