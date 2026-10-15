"""Disposable C# Host -> DPAPI -> pipe -> authenticated Core relay E2E."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[2]
BUILT = ROOT / "native" / "launcher" / "bin" / "Release" / "net8.0"
sys.path.insert(0, str(PROJECT / "tests"))

from bct.core.bridge_pr3e_peer_adapter import install_schema as install_peer_schema
from bct.core.bridge_pr3f_binding_lifecycle import BindingLifecycle
from bct.core.bridge_pr3h_dpapi_file_store import DpapiFileSecretStore
from bct.core.bridge_pr3l_pipe_relay import PipeRelay
import test_bridge_pr3e_peer_adapter as peer_fixture


class _Verifier:
    def __init__(self, digest):
        self.digest = digest

    def verified_client_sha256(self, _connection):
        return self.digest


class BridgePipeRelayWindowsTests(unittest.TestCase):
    LAUNCHER = peer_fixture.PeerAdapterTests.LAUNCHER
    grant = peer_fixture.PeerAdapterTests.grant
    completion = peer_fixture.PeerAdapterTests.completion
    frame = peer_fixture.PeerAdapterTests.frame

    def setUp(self):
        self.assertEqual(os.name, "nt", "Windows runner required")
        peer_fixture.PeerAdapterTests.setUp(self)
        install_peer_schema(self.s)
        self.executable = (BUILT / "BctBridgeHost.exe").resolve()
        self.assertTrue(self.executable.is_file(), "dotnet build required")
        self.launcher_sha = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.temp = tempfile.TemporaryDirectory(prefix="bct-bridge-relay-")
        self.addCleanup(self.temp.cleanup)
        self.owned = Path(self.temp.name) / "owned"
        self.owned.mkdir()
        self.secret_store = DpapiFileSecretStore(self.owned)
        self.lifecycle = BindingLifecycle(self.s, self.secret_store)
        self.secret = secrets.token_bytes(32)
        self.peer_id = "fixture-windows-host"
        self.lifecycle.provision(
            self.peer_id, binding_generation=1,
            launcher_sha256=self.launcher_sha, secret=self.secret,
        )
        envelope = peer_fixture.PeerAdapterTests.frame(
            self, peer_fixture.PeerAdapterTests.grant(self)
        )
        self.fixture = Path(self.temp.name) / "relay.json"
        self.fixture.write_text(json.dumps({
            "peer_id": self.peer_id,
            "binding_generation": 1,
            "launcher_sha256": self.launcher_sha,
            "origin": self.binding.origin,
            "sequence": 1,
            "envelope_b64": base64.b64encode(envelope).decode("ascii"),
        }, separators=(",", ":")), encoding="utf-8")
        protected = list(self.owned.glob("*.dpapi"))
        self.assertEqual(1, len(protected))
        self.protected_secret = protected[0]

    def _transport(self, expected_sha):
        pipe_name = "bct-bridge-relay-" + uuid.uuid4().hex
        server = subprocess.Popen(
            [str(self.executable), "--bridge-pipe-relay-server",
             pipe_name, expected_sha],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual("READY\n", server.stdout.readline())
            client = subprocess.run(
                [str(self.executable), "--bridge-pipe-relay-client", pipe_name,
                 str(self.fixture.resolve()), str(self.protected_secret.resolve())],
                capture_output=True, text=True, timeout=20,
            )
            server.wait(timeout=20)
            lines = server.stdout.read().splitlines()
            return client, server.returncode, lines, server.stderr.read()
        finally:
            if server.poll() is None:
                server.kill()
                server.wait(timeout=5)

    def test_dpapi_host_pipe_and_authenticated_core_ingress(self):
        client, server, lines, server_error = self._transport(self.launcher_sha)
        self.assertEqual(0, client.returncode, client.stderr)
        self.assertEqual(0, server, server_error)
        self.assertEqual(1, len(lines))
        marker, attested_sha, encoded = lines[0].split(":", 2)
        self.assertEqual("FRAME", marker)
        self.assertEqual(self.launcher_sha, attested_sha)
        transport = base64.b64decode(encoded, validate=True)
        published = []
        result = PipeRelay(
            peer_id=self.peer_id, binding_provider=self.lifecycle,
            client_verifier=_Verifier(attested_sha),
        ).dispatch(
            self.s, connection=object(), read_frame=lambda: transport,
            publish_result=published.append,
        )
        self.assertFalse(result["duplicate"])
        self.assertEqual([result], published)
        self.lifecycle.revoke(self.peer_id)
        self.assertEqual([], list(self.owned.iterdir()))

    def test_wrong_connected_executable_digest_emits_no_frame(self):
        client, server, lines, _ = self._transport("0" * 64)
        self.assertNotEqual(0, client.returncode)
        self.assertNotEqual(0, server)
        self.assertEqual([], lines)
        self.lifecycle.revoke(self.peer_id)
        self.assertEqual([], list(self.owned.iterdir()))


if __name__ == "__main__":
    unittest.main()
