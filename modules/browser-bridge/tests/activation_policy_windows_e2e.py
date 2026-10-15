"""Disposable Windows owner/DACL and logon-session policy proof (no Core)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "native" / "launcher" / "bin" / "Release" / "net8.0"


class BridgeActivationPolicyWindowsTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.name, "nt", "Windows runner required")
        self.executable = (BUILT / "BctBridgeHost.exe").resolve()
        self.assertTrue(self.executable.is_file(), "dotnet build required")
        self.temp = tempfile.TemporaryDirectory(prefix="bct-bridge-policy-")
        self.addCleanup(self.temp.cleanup)

    def _root(self, name="owned"):
        return Path(self.temp.name, name).resolve()

    def _connected_case(self, mode):
        root = self._root()
        pipe_name = "bct-bridge-policy-" + uuid.uuid4().hex
        server = subprocess.Popen(
            [str(self.executable), "--bridge-activation-policy-server",
             str(root), pipe_name, mode],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = server.stdout.readline()
            if not ready.startswith("READY:") or not ready[6:].strip().isdigit():
                server.wait(timeout=5)
                self.fail(f"ready={ready!r}; stderr={server.stderr.read()!r}")
            client = subprocess.run(
                [str(self.executable), "--bridge-activation-policy-client", pipe_name],
                capture_output=True, text=True, timeout=20,
            )
            server.wait(timeout=20)
            lines = server.stdout.read().splitlines()
            return client, server.returncode, lines, server.stderr.read(), root
        finally:
            if server.poll() is None:
                server.kill()
                server.wait(timeout=5)
            server.stdout.close()
            server.stderr.close()

    def test_exact_owner_dacl_and_same_logon_session_are_accepted(self):
        client, server, lines, server_error, root = self._connected_case("valid")
        self.assertEqual(0, client.returncode, client.stderr)
        self.assertEqual(0, server, server_error)
        self.assertEqual(["CLEANED"], lines)
        self.assertFalse(root.exists())

    def test_session_mismatch_is_denied_before_payload_read(self):
        client, server, lines, server_error, root = self._connected_case("session-mismatch")
        self.assertNotEqual(0, client.returncode, client.stderr)
        self.assertEqual(["DENIED_WITHOUT_WRITE"], client.stdout.splitlines())
        self.assertNotEqual(0, server, server_error)
        self.assertEqual(["DENIED_BEFORE_READ", "CLEANED"], lines)
        self.assertFalse(root.exists())

    def test_root_file_and_pipe_acl_tampering_are_denied_and_cleaned(self):
        for mode in ("root-acl", "file-acl", "pipe-acl"):
            with self.subTest(mode=mode):
                client, server, lines, server_error, root = self._connected_case(mode)
                self.assertNotEqual(0, client.returncode, client.stderr)
                self.assertEqual(["DENIED_WITHOUT_WRITE"], client.stdout.splitlines())
                self.assertNotEqual(0, server, server_error)
                self.assertEqual(["DENIED_BEFORE_READ", "CLEANED"], lines)
                self.assertFalse(root.exists())

    def test_preexisting_and_reparse_roots_are_preserved(self):
        root = self._root()
        root.mkdir()
        sentinel = root / "sentinel.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        result = subprocess.run(
            [str(self.executable), "--bridge-activation-policy-server",
             str(root), "bct-bridge-policy-" + uuid.uuid4().hex, "valid"],
            capture_output=True, text=True, timeout=20,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("preserve", sentinel.read_text(encoding="utf-8"))

        target = self._root("junction-target")
        target.mkdir()
        target_sentinel = target / "sentinel.txt"
        target_sentinel.write_text("preserve", encoding="utf-8")
        junction = self._root("junction")
        linked = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, linked.returncode, linked.stderr)
        try:
            root_below_junction = junction / "owned"
            result = subprocess.run(
                [str(self.executable), "--bridge-activation-policy-server",
                 str(root_below_junction),
                 "bct-bridge-policy-" + uuid.uuid4().hex, "valid"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(root_below_junction.exists())
            self.assertEqual("preserve", target_sentinel.read_text(encoding="utf-8"))
        finally:
            junction.rmdir()

    def test_pipe_collision_cleans_only_the_rejected_fixture(self):
        pipe_name = "bct-bridge-policy-" + uuid.uuid4().hex
        first_root = self._root("first")
        second_root = self._root("second")
        first = subprocess.Popen(
            [str(self.executable), "--bridge-activation-policy-server",
             str(first_root), pipe_name, "valid"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = first.stdout.readline()
            if not ready.startswith("READY:") or not ready[6:].strip().isdigit():
                first.wait(timeout=5)
                self.fail(f"ready={ready!r}; stderr={first.stderr.read()!r}")
            collision = subprocess.run(
                [str(self.executable), "--bridge-activation-policy-server",
                 str(second_root), pipe_name, "valid"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(0, collision.returncode, collision.stderr)
            self.assertEqual(["CLEANED"], collision.stdout.splitlines())
            self.assertFalse(second_root.exists())

            client = subprocess.run(
                [str(self.executable), "--bridge-activation-policy-client", pipe_name],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(0, client.returncode, client.stderr)
            first.wait(timeout=20)
            self.assertEqual(0, first.returncode, first.stderr.read())
            self.assertEqual(["CLEANED"], first.stdout.read().splitlines())
            self.assertFalse(first_root.exists())
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=5)
            first.stdout.close()
            first.stderr.close()


if __name__ == "__main__":
    unittest.main()
