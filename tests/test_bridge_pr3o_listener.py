import secrets
import tempfile
import unittest
from pathlib import Path

from bct.core.bridge_pr3e_peer_adapter import install_schema as install_peer_schema
from bct.core.bridge_pr3f_binding_lifecycle import BindingLifecycle
from bct.core.bridge_pr3h_dpapi_file_store import DpapiFileSecretStore
from bct.core.bridge_pr3k_pipe_frame import encode_peer_frame
from bct.core.bridge_pr3l_pipe_relay import PipeRelayUnknownEffect
from bct.core.bridge_pr3o_listener import ListenerConfig, ProductionDisabledListener
from bct.core.models import ConflictError
import test_bridge_pr3e_peer_adapter as peer_fixture


class _Connection:
    def __init__(self, digest, frame, *, publish_failure=None):
        self.digest = digest
        self.frame = frame
        self.publish_failure = publish_failure
        self.reads = 0
        self.published = []
        self.closed = 0

    def read_frame(self, *, timeout_seconds):
        if timeout_seconds <= 0:
            raise TimeoutError()
        self.reads += 1
        return self.frame

    def publish_result(self, result, *, timeout_seconds):
        if timeout_seconds <= 0:
            raise TimeoutError()
        self.published.append(result)
        if self.publish_failure is not None:
            raise self.publish_failure

    def close(self):
        self.closed += 1


class _Verifier:
    def verified_client_sha256(self, connection):
        return connection.digest


class _Endpoint:
    def __init__(self, connections=(), *, start_failure=None, stop_failure=None):
        self.connections = list(connections)
        self.start_failure = start_failure
        self.stop_failure = stop_failure
        self.events = []

    def start(self, *, timeout_seconds):
        self.events.append(("start", timeout_seconds))
        failure, self.start_failure = self.start_failure, None
        if failure is not None:
            raise failure

    def accept(self, *, timeout_seconds):
        self.events.append(("accept", timeout_seconds))
        return self.connections.pop(0)

    def stop(self, *, timeout_seconds):
        self.events.append(("stop", timeout_seconds))
        failure, self.stop_failure = self.stop_failure, None
        if failure is not None:
            raise failure


class ProductionDisabledListenerTests(unittest.TestCase):
    LAUNCHER = peer_fixture.PeerAdapterTests.LAUNCHER
    grant = peer_fixture.PeerAdapterTests.grant
    completion = peer_fixture.PeerAdapterTests.completion
    frame = peer_fixture.PeerAdapterTests.frame

    def setUp(self):
        peer_fixture.PeerAdapterTests.setUp(self)
        install_peer_schema(self.s)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.credential_root = Path(self.temp.name) / "bridge-owned"
        self.credential_root.mkdir()
        self.secret_store = DpapiFileSecretStore(self.credential_root)
        self.lifecycle = BindingLifecycle(self.s, self.secret_store)
        self.peer_id = "fixture-listener-host"
        self.secret = secrets.token_bytes(32)
        self.lifecycle.provision(
            self.peer_id, binding_generation=1,
            launcher_sha256=self.LAUNCHER, secret=self.secret,
        )

    def _request(self, *, sequence=1, binding=None):
        binding = binding or self.lifecycle.resolve_peer_binding(self.peer_id)
        envelope = peer_fixture.PeerAdapterTests.frame(
            self, peer_fixture.PeerAdapterTests.grant(self)
        )
        peer = peer_fixture.PeerAdapterTests.signed(
            self, envelope, sequence=sequence, binding=binding,
        )
        return encode_peer_frame(peer)

    def _listener(self, endpoint, **changes):
        values = dict(enabled=True, fixture_only=True, peer_id=self.peer_id,
                      startup_timeout_seconds=2, accept_timeout_seconds=3,
                      shutdown_timeout_seconds=4)
        values.update(changes)
        return ProductionDisabledListener(
            ListenerConfig(**values), binding_lifecycle=self.lifecycle,
            secret_store=self.secret_store, client_verifier=_Verifier(),
            endpoint=endpoint,
        )

    def test_disabled_by_default_and_requires_exact_injected_store(self):
        endpoint = _Endpoint()
        listener = self._listener(endpoint, enabled=False)
        with self.assertRaisesRegex(RuntimeError, "BRIDGE_LISTENER_DISABLED"):
            listener.start()
        self.assertEqual([], endpoint.events)
        other = DpapiFileSecretStore(self.credential_root)
        with self.assertRaisesRegex(ValueError, "STORE_MISMATCH"):
            ProductionDisabledListener(
                ListenerConfig(True, True, self.peer_id),
                binding_lifecycle=self.lifecycle, secret_store=other,
                client_verifier=_Verifier(), endpoint=endpoint,
            )
        self.lifecycle.revoke(self.peer_id)
        with self.assertRaisesRegex(RuntimeError, "BINDING_DENIED"):
            self._listener(endpoint).start()
        self.assertEqual([], endpoint.events)

    def test_bounded_start_stop_restart_and_partial_failure_cleanup(self):
        endpoint = _Endpoint(start_failure=OSError("collision"))
        listener = self._listener(endpoint)
        with self.assertRaisesRegex(RuntimeError, "START_DENIED"):
            listener.start()
        self.assertEqual([("start", 2), ("stop", 4)], endpoint.events)
        self.assertFalse(listener.started)

        poisoned_endpoint = _Endpoint(
            start_failure=OSError("collision"), stop_failure=OSError("leaked"))
        poisoned = self._listener(poisoned_endpoint)
        with self.assertRaisesRegex(RuntimeError, "CLEANUP_UNKNOWN"):
            poisoned.start()
        with self.assertRaisesRegex(RuntimeError, "CLEANUP_UNKNOWN"):
            poisoned.start()
        listener.start(); listener.stop(); listener.start(); listener.stop()
        self.assertEqual(3, endpoint.events.count(("stop", 4)))
        self.assertFalse(listener.started)

    def test_verified_connection_dispatches_once_and_revocation_prevents_read(self):
        first = _Connection(self.LAUNCHER, self._request())
        revoked = _Connection(self.LAUNCHER, self._request(sequence=2))
        endpoint = _Endpoint((first, revoked))
        listener = self._listener(endpoint); listener.start()
        result = listener.dispatch_once(self.s)
        self.assertEqual([result], first.published)
        self.assertEqual(1, first.closed)
        self.lifecycle.revoke(self.peer_id)
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            listener.dispatch_once(self.s)
        self.assertEqual(0, revoked.reads)
        self.assertEqual(1, revoked.closed)
        listener.stop()

    def test_stale_generation_and_executable_tamper_fail_closed(self):
        stale_binding = self.lifecycle.resolve_peer_binding(self.peer_id)
        stale = self._request(binding=stale_binding)
        self.lifecycle.rotate(
            self.peer_id, binding_generation=2,
            launcher_sha256=self.LAUNCHER, secret=secrets.token_bytes(32),
        )
        wrong_process = _Connection("0" * 64, self._request(sequence=1))
        stale_connection = _Connection(self.LAUNCHER, stale)
        listener = self._listener(_Endpoint((wrong_process, stale_connection)))
        listener.start()
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            listener.dispatch_once(self.s)
        self.assertEqual(0, wrong_process.reads)
        self.assertEqual(1, wrong_process.closed)
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            listener.dispatch_once(self.s)
        self.assertEqual(1, stale_connection.reads)
        self.assertEqual(1, stale_connection.closed)
        listener.stop()

    def test_post_dispatch_unknown_is_not_retried(self):
        request = self._request()
        failed = _Connection(self.LAUNCHER, request,
                             publish_failure=OSError("disconnected"))
        replay = _Connection(self.LAUNCHER, request)
        listener = self._listener(_Endpoint((failed, replay))); listener.start()
        with self.assertRaisesRegex(PipeRelayUnknownEffect, "EFFECT_UNKNOWN"):
            listener.dispatch_once(self.s)
        self.assertEqual(1, failed.reads)
        self.assertEqual(1, len(failed.published))
        self.assertEqual(1, failed.closed)
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            listener.dispatch_once(self.s)
        self.assertEqual([], replay.published)
        self.assertEqual(1, replay.closed)
        listener.stop()


if __name__ == "__main__":
    unittest.main()
