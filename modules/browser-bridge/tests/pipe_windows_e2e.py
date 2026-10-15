"""Disposable Windows named-pipe PID and executable-digest probe (no Core)."""
import hashlib
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "native" / "launcher" / "bin" / "Release" / "net8.0"


class BridgePipeProbeTests(unittest.TestCase):
    def _run_case(self, expected_sha):
        self.assertEqual(os.name, "nt", "Windows runner required")
        executable = BUILT / "BctBridgeHost.exe"
        self.assertTrue(executable.is_file(), "dotnet build required")
        pipe_name = "bct-bridge-probe-" + uuid.uuid4().hex
        server = subprocess.Popen(
            [str(executable), "--bridge-pipe-probe-server", pipe_name, expected_sha],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual("READY\n", server.stdout.readline())
            client = subprocess.run(
                [str(executable), "--bridge-pipe-probe-client", pipe_name],
                capture_output=True, text=True, timeout=15,
            )
            server.wait(timeout=15)
            return client.returncode, server.returncode, client.stderr, server.stderr.read()
        finally:
            if server.poll() is None:
                server.kill(); server.wait(timeout=5)

    def test_current_user_client_and_exact_executable_digest_are_accepted(self):
        executable = BUILT / "BctBridgeHost.exe"
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        client, server, client_error, server_error = self._run_case(digest)
        self.assertEqual(0, client, client_error)
        self.assertEqual(0, server, server_error)

    def test_wrong_executable_digest_is_fail_closed(self):
        client, server, client_error, server_error = self._run_case("0" * 64)
        self.assertNotEqual(0, client, client_error)
        self.assertNotEqual(0, server, server_error)


if __name__ == "__main__":
    unittest.main()
