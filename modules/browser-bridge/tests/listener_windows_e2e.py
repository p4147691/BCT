"""Disposable PR3-o same-connection listener composition proof."""
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
BUILT = ROOT / "native" / "launcher" / "bin" / "Release" / "net8.0"
sys.path.insert(0, str(PROJECT / "tests"))

from bct.core.bridge_pr3e_peer_adapter import install_schema as install_peer_schema
from bct.core.bridge_pr3f_binding_lifecycle import BindingLifecycle
from bct.core.bridge_pr3h_dpapi_file_store import DpapiFileSecretStore
from bct.core.bridge_pr3l_pipe_relay import PipeRelayUnknownEffect
from bct.core.bridge_pr3o_listener import ListenerConfig, ProductionDisabledListener
from bct.core.models import ConflictError
import test_bridge_pr3e_peer_adapter as peer_fixture


def _readline(stream, timeout_seconds):
    result = queue.Queue(maxsize=1)
    worker = threading.Thread(target=lambda: result.put(stream.readline()), daemon=True)
    worker.start()
    try:
        return result.get(timeout=timeout_seconds)
    except queue.Empty:
        raise TimeoutError("bounded fixture read timed out") from None


class _Connection:
    def __init__(self, endpoint, digest, *, publish_unknown=False):
        self.endpoint = endpoint
        self.digest = digest
        self.publish_unknown = publish_unknown
        self.reads = 0

    def read_frame(self, *, timeout_seconds):
        self.reads += 1
        self.endpoint.server.stdin.write("AUTHORIZE\n")
        self.endpoint.server.stdin.flush()
        line = _readline(self.endpoint.server.stdout, timeout_seconds).strip()
        marker, digest, encoded = line.split(":", 2)
        if marker != "FRAME" or digest != self.digest:
            raise RuntimeError("FRAME_DENIED")
        return base64.b64decode(encoded, validate=True)

    def publish_result(self, _result, *, timeout_seconds):
        if self.publish_unknown:
            raise OSError("fixture publish disconnected")
        self.endpoint.server.stdin.write("PUBLISH:OK\n")
        self.endpoint.server.stdin.flush()
        self.endpoint._finish_processes(timeout_seconds)
        if self.endpoint.server.returncode != 0 or self.endpoint.client.returncode != 0:
            raise OSError("fixture ACK was not confirmed")

    def close(self):
        if self.endpoint.server.stdin and not self.endpoint.server.stdin.closed:
            self.endpoint.server.stdin.close()
        self.endpoint._finish_processes()


class _Verifier:
    def verified_client_sha256(self, connection):
        return connection.digest


class _WindowsEndpoint:
    def __init__(self, executable, root, credential, pipe_name, expected_sha,
                 fixture, *, mode="valid", publish_unknown=False,
                 on_attest=None):
        self.executable = executable
        self.root = root
        self.credential = credential
        self.pipe_name = pipe_name
        self.expected_sha = expected_sha
        self.fixture = fixture
        self.mode = mode
        self.publish_unknown = publish_unknown
        self.on_attest = on_attest
        self.server = None
        self.client = None
        self.last_line = None
        self.client_stdout = ""
        self.client_stderr = ""
        self.server_stderr = ""

    def start(self, *, timeout_seconds):
        self.server = subprocess.Popen(
            [str(self.executable), "--bridge-listener-server", str(self.root),
             str(self.credential), self.pipe_name, self.expected_sha, self.mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        ready = _readline(self.server.stdout, timeout_seconds)
        if ready != "READY\n":
            self.server.wait(timeout=5)
            error = self.server.stderr.read()
            self._finish_processes(timeout_seconds)
            raise RuntimeError(error)

    def accept(self, *, timeout_seconds):
        self.client = subprocess.Popen(
            [str(self.executable), "--bridge-listener-client", self.pipe_name,
             str(self.fixture), str(self.credential)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        line = _readline(self.server.stdout, timeout_seconds).strip()
        self.last_line = line
        if not line.startswith("ATTEST:"):
            self._finish_processes(timeout_seconds)
            raise RuntimeError("LISTENER_ACCEPT_DENIED:" + line)
        connection = _Connection(self, line.split(":", 1)[1],
                                 publish_unknown=self.publish_unknown)
        if self.on_attest is not None:
            self.on_attest()
        return connection

    def stop(self, *, timeout_seconds):
        if self.server is not None and self.server.poll() is None:
            if self.server.stdin and not self.server.stdin.closed:
                self.server.stdin.close()
            try:
                self.server.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
        self._finish_processes(timeout_seconds)

    def _finish_processes(self, timeout_seconds=5):
        for process in (self.server, self.client):
            if process is None:
                continue
            if process.poll() is None:
                try:
                    process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream and not stream.closed:
                    content = stream.read()
                    if process is self.client and stream is process.stdout:
                        self.client_stdout += content
                    elif process is self.client and stream is process.stderr:
                        self.client_stderr += content
                    elif process is self.server and stream is process.stderr:
                        self.server_stderr += content
                    stream.close()


class BridgeListenerWindowsTests(unittest.TestCase):
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
        # GitHub's RUNNER_TEMP can live below a junction.  The production
        # boundary deliberately rejects every reparse-point ancestor, so put
        # this disposable fixture below the real user profile instead.
        self.temp = tempfile.TemporaryDirectory(
            prefix="bct-bridge-listener-", dir=Path.home()
        )
        self.addCleanup(self.temp.cleanup)
        self.owned = Path(self.temp.name, "owned").resolve()
        self.owned.mkdir()
        self.secret_store = DpapiFileSecretStore(self.owned)
        self.lifecycle = BindingLifecycle(self.s, self.secret_store)
        self.peer_id = "fixture-listener-host"
        self.secret = secrets.token_bytes(32)
        self.lifecycle.provision(
            self.peer_id, binding_generation=1,
            launcher_sha256=self.launcher_sha, secret=self.secret,
        )
        protected = list(self.owned.glob("*.dpapi"))
        self.assertEqual(1, len(protected))
        self.credential = protected[0].resolve()
        sealed = subprocess.run(
            [str(self.executable), "--bridge-listener-seal-fixture",
             str(self.owned), str(self.credential)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, sealed.returncode, sealed.stderr)
        self.fixture = Path(self.temp.name, "listener.json").resolve()
        self._write_fixture(1)

    def _write_fixture(self, sequence, generation=1):
        envelope = peer_fixture.PeerAdapterTests.frame(
            self, peer_fixture.PeerAdapterTests.grant(self)
        )
        self.fixture.write_text(json.dumps({
            "peer_id": self.peer_id,
            "binding_generation": generation,
            "launcher_sha256": self.launcher_sha,
            "origin": self.binding.origin,
            "sequence": sequence,
            "envelope_b64": base64.b64encode(envelope).decode("ascii"),
        }, separators=(",", ":")), encoding="utf-8")

    def _endpoint(self, *, pipe_name=None, mode="valid", expected_sha=None,
                  publish_unknown=False, on_attest=None, credential=None):
        return _WindowsEndpoint(
            self.executable, self.owned, credential or self.credential,
            pipe_name or "bct-bridge-listener-" + uuid.uuid4().hex,
            expected_sha or self.launcher_sha, self.fixture,
            mode=mode, publish_unknown=publish_unknown, on_attest=on_attest,
        )

    def _sequence_count(self):
        with self.s.transaction() as db:
            return db.execute("SELECT COUNT(*) AS n FROM bridge_peer_sequences").fetchone()["n"]

    def _listener(self, endpoint):
        return ProductionDisabledListener(
            ListenerConfig(True, True, self.peer_id, 10, 10, 5, 10, 10),
            binding_lifecycle=self.lifecycle, secret_store=self.secret_store,
            client_verifier=_Verifier(), endpoint=endpoint,
        )

    def test_same_connection_dispatch_restart_replay_and_persistent_state(self):
        endpoint = self._endpoint()
        listener = self._listener(endpoint)
        listener.start()
        result = listener.dispatch_once(self.s)
        listener.stop()
        self.assertFalse(result["duplicate"])
        self.assertTrue(self.credential.is_file())

        stale_credential = (self.owned / "stale-generation.dpapi").resolve()
        stale_credential.write_bytes(self.credential.read_bytes())
        sealed = subprocess.run(
            [str(self.executable), "--bridge-listener-seal-fixture",
             str(self.owned), str(stale_credential)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, sealed.returncode, sealed.stderr)

        replay_endpoint = self._endpoint()
        replay = self._listener(replay_endpoint)
        replay.start()
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            replay.dispatch_once(self.s)
        replay.stop()
        self.assertTrue(self.credential.is_file())

        self.lifecycle.rotate(
            self.peer_id, binding_generation=2,
            launcher_sha256=self.launcher_sha, secret=secrets.token_bytes(32),
        )
        stale_listener = self._listener(self._endpoint(credential=stale_credential))
        stale_listener.start()
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            stale_listener.dispatch_once(self.s)
        stale_listener.stop()

        current = list(self.owned.glob("*.dpapi"))
        current.remove(stale_credential)
        self.assertEqual(1, len(current))
        self.credential = current[0].resolve()
        sealed = subprocess.run(
            [str(self.executable), "--bridge-listener-seal-fixture",
             str(self.owned), str(self.credential)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, sealed.returncode, sealed.stderr)
        self._write_fixture(1, generation=2)
        next_listener = self._listener(self._endpoint())
        next_listener.start()
        next_listener.dispatch_once(self.s)
        next_listener.stop()
        self.assertTrue(self.credential.is_file())

    def test_normal_native_messaging_path_cannot_enable_listener_from_environment(self):
        forbidden_root = Path(self.temp.name, "must-not-exist").resolve()
        env = dict(os.environ)
        env.update({
            "BCT_BRIDGE_LISTENER_ENABLE": "1",
            "BCT_BRIDGE_LISTENER_ROOT": str(forbidden_root),
            "BCT_BRIDGE_LISTENER_PIPE": "bct-bridge-forbidden-" + uuid.uuid4().hex,
            "BCT_BRIDGE_EXTENSION_ORIGIN": self.binding.origin,
            "BCT_BRIDGE_PYTHON_EXE": str(Path(self.temp.name, "missing.exe")),
            "BCT_BRIDGE_PYTHON_SHA256": "0" * 64,
        })
        result = subprocess.run(
            [str(self.executable), self.binding.origin], env=env,
            input=b"", capture_output=True, timeout=20,
        )
        self.assertEqual(5, result.returncode)
        self.assertFalse(forbidden_root.exists())

    def test_acl_session_and_executable_tamper_deny_before_frame(self):
        before = self._sequence_count()
        for mode, expected in (("root-acl", None), ("file-acl", None),
                               ("pipe-acl", None), ("session-mismatch", None),
                               ("valid", "0" * 64)):
            with self.subTest(mode=mode, expected=expected):
                sealed = subprocess.run(
                    [str(self.executable), "--bridge-listener-seal-fixture",
                     str(self.owned), str(self.credential)],
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(0, sealed.returncode, sealed.stderr)
                endpoint = self._endpoint(mode=mode, expected_sha=expected)
                listener = self._listener(endpoint)
                listener.start()
                with self.assertRaisesRegex(RuntimeError, "LISTENER_ACCEPT_DENIED"):
                    listener.dispatch_once(self.s)
                self.assertEqual("DENIED_BEFORE_READ", endpoint.last_line)
                self.assertNotEqual(0, endpoint.client.returncode)
                self.assertEqual(["DENIED_WITHOUT_WRITE"],
                                 endpoint.client_stdout.splitlines())
                self.assertEqual(before, self._sequence_count())
                listener.stop()

    def test_collision_preserves_winner_and_credential_sentinel(self):
        pipe_name = "bct-bridge-listener-" + uuid.uuid4().hex
        sentinel = self.owned / "sentinel.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        winner = self._endpoint(pipe_name=pipe_name)
        winner.start(timeout_seconds=10)
        collision = self._endpoint(pipe_name=pipe_name)
        with self.assertRaises(RuntimeError):
            collision.start(timeout_seconds=10)
        self.assertIsNone(winner.server.poll())
        self.assertEqual("preserve", sentinel.read_text(encoding="utf-8"))
        self.assertTrue(self.credential.is_file())
        winner.stop(timeout_seconds=5)

    def test_revocation_and_post_dispatch_unknown_do_not_retry(self):
        endpoint = self._endpoint(publish_unknown=True)
        listener = self._listener(endpoint)
        listener.start()
        with self.assertRaisesRegex(PipeRelayUnknownEffect, "EFFECT_UNKNOWN"):
            listener.dispatch_once(self.s)
        self.assertIsNotNone(endpoint.client)
        listener.stop()

        # Revoke after the OS attestation but before Python authorizes payload.
        # PipeRelay's current-binding fence denies without calling read_frame.
        endpoint = self._endpoint(on_attest=lambda: self.lifecycle.revoke(self.peer_id))
        listener = self._listener(endpoint)
        listener.start()
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            listener.dispatch_once(self.s)
        listener.stop()

    def test_partial_and_disconnect_frames_never_emit_core_frame(self):
        for mode in ("partial", "disconnect"):
            with self.subTest(mode=mode):
                endpoint = self._endpoint()
                endpoint.start(timeout_seconds=10)
                endpoint.client = subprocess.Popen(
                    [str(self.executable), "--bridge-listener-fault-client",
                     endpoint.pipe_name, mode],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                attest = _readline(endpoint.server.stdout, 10).strip()
                self.assertTrue(attest.startswith("ATTEST:"), attest)
                endpoint.server.stdin.write("AUTHORIZE\n")
                endpoint.server.stdin.flush()
                endpoint.server.wait(timeout=20)
                remaining = endpoint.server.stdout.read().splitlines()
                self.assertFalse(any(line.startswith("FRAME:") for line in remaining))
                endpoint.stop(timeout_seconds=5)


if __name__ == "__main__":
    unittest.main()
