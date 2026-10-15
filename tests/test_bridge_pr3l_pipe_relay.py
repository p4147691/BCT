import unittest

from bct.core.bridge_pr3e_peer_adapter import install_schema as install_peer_schema
from bct.core.bridge_pr3k_pipe_frame import encode_peer_frame
from bct.core.bridge_pr3l_pipe_relay import PipeRelay, PipeRelayUnknownEffect
from bct.core.models import ConflictError
import test_bridge_pr3e_peer_adapter as peer_fixture


class _Verifier:
    def __init__(self, digest, *, failure=None):
        self.digest = digest
        self.failure = failure
        self.calls = []

    def verified_client_sha256(self, connection):
        self.calls.append(connection)
        if self.failure is not None:
            raise self.failure
        return self.digest


class PipeRelayTests(unittest.TestCase):
    LAUNCHER = peer_fixture.PeerAdapterTests.LAUNCHER
    grant = peer_fixture.PeerAdapterTests.grant
    completion = peer_fixture.PeerAdapterTests.completion
    frame = peer_fixture.PeerAdapterTests.frame

    def setUp(self):
        # Reuse the accepted PR3-e durable fixture without subclassing its test
        # case (which would duplicate the inherited regression suite).
        peer_fixture.PeerAdapterTests.setUp(self)
        install_peer_schema(self.s)
        self.provider = peer_fixture._Bindings(self.binding)
        self.connection = object()

    def _request(self, *, sequence=1):
        envelope = peer_fixture.PeerAdapterTests.frame(
            self, peer_fixture.PeerAdapterTests.grant(self)
        )
        peer = peer_fixture.PeerAdapterTests.signed(
            self, envelope, sequence=sequence
        )
        return encode_peer_frame(peer)

    def _relay(self, verifier=None):
        return PipeRelay(
            peer_id=self.binding.peer_id,
            binding_provider=self.provider,
            client_verifier=verifier or _Verifier(self.binding.launcher_sha256.upper()),
        )

    def test_verified_pipe_frame_reaches_authenticated_ingress_once(self):
        request = self._request()
        published = []
        result = self._relay().dispatch(
            self.s, connection=self.connection,
            read_frame=lambda: request, publish_result=published.append,
        )
        self.assertFalse(result["duplicate"])
        self.assertEqual([result], published)
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            self._relay().dispatch(
                self.s, connection=self.connection,
                read_frame=lambda: request, publish_result=published.append,
            )
        self.assertEqual([result], published)

    def test_client_is_verified_before_request_bytes_are_read(self):
        events = []
        verifier = _Verifier("0" * 64)

        def read_frame():
            events.append("read")
            return self._request()

        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            self._relay(verifier).dispatch(
                self.s, connection=self.connection,
                read_frame=read_frame, publish_result=lambda _: None,
            )
        self.assertEqual([self.connection], verifier.calls)
        self.assertEqual([], events)

    def test_verifier_failure_is_generic_and_does_not_read(self):
        secret_detail = "private verifier detail"
        read = []
        verifier = _Verifier(None, failure=RuntimeError(secret_detail))
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED") as caught:
            self._relay(verifier).dispatch(
                self.s, connection=self.connection,
                read_frame=lambda: read.append(True), publish_result=lambda _: None,
            )
        self.assertNotIn(secret_detail, str(caught.exception))
        self.assertEqual([], read)

    def test_malformed_transport_and_wrong_proof_fail_closed(self):
        cases = (b"not-a-frame", encode_peer_frame(b"{}"))
        for request in cases:
            with self.subTest(request=request[:12]):
                with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
                    self._relay().dispatch(
                        self.s, connection=self.connection,
                        read_frame=lambda request=request: request,
                        publish_result=lambda _: self.fail("must not publish"),
                    )

    def test_binding_change_after_process_check_is_fenced_by_peer_adapter(self):
        request = self._request()

        def revoke_before_ingress():
            self.provider.binding = None
            return request

        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            self._relay().dispatch(
                self.s, connection=self.connection,
                read_frame=revoke_before_ingress,
                publish_result=lambda _: self.fail("must not publish"),
            )

    def test_post_dispatch_publish_failure_is_unknown_and_never_retried(self):
        request = self._request()
        attempts = []

        def fail_publish(_):
            attempts.append("publish")
            raise OSError("disconnected")

        with self.assertRaisesRegex(PipeRelayUnknownEffect,
                                    "PIPE_RELAY_EFFECT_UNKNOWN"):
            self._relay().dispatch(
                self.s, connection=self.connection,
                read_frame=lambda: request, publish_result=fail_publish,
            )
        self.assertEqual(["publish"], attempts)
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            self._relay().dispatch(
                self.s, connection=self.connection,
                read_frame=lambda: request, publish_result=fail_publish,
            )
        self.assertEqual(["publish"], attempts)

    def test_dependencies_are_required_and_callbacks_are_fail_closed(self):
        verifier = _Verifier(self.binding.launcher_sha256)
        with self.assertRaisesRegex(ValueError, "BINDING_PROVIDER_REQUIRED"):
            PipeRelay(peer_id=self.binding.peer_id,
                      binding_provider=None, client_verifier=verifier)
        with self.assertRaisesRegex(ValueError, "CLIENT_VERIFIER_REQUIRED"):
            PipeRelay(peer_id=self.binding.peer_id,
                      binding_provider=self.provider, client_verifier=None)
        with self.assertRaisesRegex(ValueError, "PEER_ID_REQUIRED"):
            PipeRelay(peer_id="", binding_provider=self.provider,
                      client_verifier=verifier)
        with self.assertRaisesRegex(ConflictError, "PIPE_RELAY_DENIED"):
            self._relay().dispatch(
                self.s, connection=self.connection,
                read_frame=None, publish_result=lambda _: None,
            )


if __name__ == "__main__":
    unittest.main()
