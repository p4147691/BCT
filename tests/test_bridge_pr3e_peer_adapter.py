import base64
import hashlib
import json
import secrets
import unittest
from unittest.mock import patch

from bct.core.models import ConflictError
from bct.core.bridge_pr3b_auth import ORIGIN, create_fake_issuer_fixture
from bct.core.bridge_pr3a_safe import install_schema as install_pr3a
from bct.core.bridge_pr3b_auth import install_schema as install_pr3b
from bct.core.bridge_pr3e_peer_adapter import (PeerAdapter, PeerBinding, ingress,
                                                install_schema, make_peer_proof)
from test_bridge_pr3b_auth import PR3BAuthTests
from test_bridge_pr3c_ingress import IngressTests
from test_durable_pr2 import PR2Tests


class _Bindings:
    def __init__(self, binding):
        self.binding = binding

    def resolve_peer_binding(self, peer_id):
        return self.binding if peer_id == self.binding.peer_id else None


class _BrokenBindings:
    def __init__(self, secret):
        self.secret = secret

    def resolve_peer_binding(self, peer_id):
        raise RuntimeError(self.secret.hex())


class PeerAdapterTests(unittest.TestCase):
    LAUNCHER = hashlib.sha256(b"adapter-fixture-launcher").hexdigest()
    grant = PR3BAuthTests.grant
    completion = PR3BAuthTests.completion
    frame = IngressTests.frame

    def setUp(self):
        self.clock = patch("bct.core.bridge_pr3b_auth.time.time", return_value=100.)
        self.clock.start(); self.addCleanup(self.clock.stop)
        PR2Tests.setUp(self)
        # Copy the durable fixture into the opaque Store bound to the fake
        # PR3-b grant issuer. The issuer must never target the original Store.
        fixture, self.issuer = create_fake_issuer_fixture()
        source = self.s._connect()
        target = fixture._connect()
        try:
            source.backup(target)
        finally:
            target.close(); source.close()
        self.s = fixture
        install_pr3a(self.s); install_pr3b(self.s); install_schema(self.s)
        self.binding = PeerBinding("fixture-adapter", 1, self.LAUNCHER, ORIGIN,
                                   secrets.token_bytes(32))
        self.adapter = PeerAdapter(_Bindings(self.binding))

    def signed(self, envelope, *, sequence=1, binding=None, **changes):
        binding = binding or self.binding
        values = dict(version=1, peer_id=binding.peer_id,
                      binding_generation=binding.binding_generation,
                      launcher_sha256=binding.launcher_sha256, origin=binding.origin,
                      sequence=sequence,
                      envelope_b64=base64.b64encode(envelope).decode("ascii"))
        values.update(changes)
        proof_envelope = base64.b64decode(values["envelope_b64"])
        values["proof"] = make_peer_proof(
            binding.secret, peer_id=values["peer_id"],
            binding_generation=values["binding_generation"],
            launcher_sha256=values["launcher_sha256"], origin=values["origin"],
            sequence=values["sequence"], envelope=proof_envelope,
        )
        return json.dumps(values, separators=(",", ":")).encode("utf-8")

    def test_provisioned_adapter_reaches_pr3c_once(self):
        request = self.signed(self.frame(self.grant()))
        self.assertFalse(self.adapter.ingress(self.s, request)["duplicate"])
        with self.assertRaises(ConflictError):
            self.adapter.ingress(self.s, request)

    def test_default_entrypoint_is_disabled(self):
        with self.assertRaisesRegex(ConflictError, "PEER_ENDPOINT_DISABLED"):
            ingress(self.s, b"{}")

    def test_binding_and_proof_cannot_be_forged_or_broadened(self):
        envelope = self.frame(self.grant())
        request = json.loads(self.signed(envelope))
        request["launcher_sha256"] = "0" * 64
        with self.assertRaises(ConflictError):
            self.adapter.ingress(self.s, json.dumps(request).encode())
        request = json.loads(self.signed(envelope))
        request["proof"] = "0" * 64
        with self.assertRaises(ConflictError):
            self.adapter.ingress(self.s, json.dumps(request).encode())
        newer = PeerBinding(self.binding.peer_id, 2, self.LAUNCHER, ORIGIN,
                            secrets.token_bytes(32))
        with self.assertRaises(ConflictError):
            self.adapter.ingress(self.s, self.signed(envelope, binding=newer))

    def test_bad_inner_envelope_consumes_authenticated_sequence(self):
        request = self.signed(b"{}")
        with self.assertRaises(ConflictError):
            self.adapter.ingress(self.s, request)
        with self.assertRaises(ConflictError):
            self.adapter.ingress(self.s, request)

    def test_outer_encoding_is_strict_and_secret_is_not_in_error(self):
        request = json.loads(self.signed(self.frame(self.grant())))
        request["envelope_b64"] += "="
        with self.assertRaisesRegex(ConflictError, "PEER_ADAPTER_DENIED") as caught:
            self.adapter.ingress(self.s, json.dumps(request).encode())
        self.assertNotIn(self.binding.secret.hex(), str(caught.exception))

    def test_provider_failure_is_denied_without_leaking_provider_detail(self):
        request = self.signed(self.frame(self.grant()))
        with self.assertRaisesRegex(ConflictError, "PEER_ADAPTER_DENIED") as caught:
            PeerAdapter(_BrokenBindings(self.binding.secret)).ingress(self.s, request)
        self.assertNotIn(self.binding.secret.hex(), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
