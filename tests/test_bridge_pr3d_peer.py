import hashlib
import unittest
from unittest.mock import patch

from bct.core.models import ConflictError
from bct.core.bridge_pr3b_auth import ORIGIN
from bct.core.bridge_pr3a_safe import install_schema as install_pr3a
from bct.core.bridge_pr3b_auth import install_schema as install_pr3b
from bct.core.bridge_pr3c_ingress import ingress as pr3c_ingress
from bct.core.bridge_pr3d_peer import (create_fake_peer_fixture, ingress, install_schema,
                                       issue_fake_peer, make_fake_proof, revoke_peer)
from test_bridge_pr3c_ingress import IngressTests
from test_bridge_pr3b_auth import PR3BAuthTests
from test_durable_pr2 import PR2Tests


class PeerTests(unittest.TestCase):
    LAUNCHER = hashlib.sha256(b"fixture-launcher").hexdigest()
    grant = PR3BAuthTests.grant
    completion = PR3BAuthTests.completion
    frame = IngressTests.frame

    def setUp(self):
        self.clock = patch("bct.core.bridge_pr3b_auth.time.time", return_value=100.)
        self.clock.start(); self.addCleanup(self.clock.stop)
        # Seed the peer factory's own isolated Store with the durable fixture.
        PR2Tests.setUp(self)
        source = self.s._connect()
        fixture, self.issuer, self.peer_issuer = create_fake_peer_fixture()
        target = fixture._connect()
        try:
            source.backup(target)
        finally:
            target.close(); source.close()
        self.s = fixture
        install_pr3a(self.s); install_pr3b(self.s)
        install_schema(self.s)
        self.peer_id = "fixture-host"
        self.secret = issue_fake_peer(self.s, issuer=self.peer_issuer, peer_id=self.peer_id,
                                      launcher_sha256=self.LAUNCHER)

    def signed(self, envelope, sequence=1, **changes):
        request = dict(peer_id=self.peer_id, launcher_sha256=self.LAUNCHER, origin=ORIGIN,
                       sequence=sequence, envelope=envelope)
        request.update(changes)
        request["proof"] = make_fake_proof(self.secret, peer_id=request["peer_id"],
                                            launcher_sha256=request["launcher_sha256"], origin=request["origin"],
                                            sequence=request["sequence"], envelope=request["envelope"])
        return request

    def test_authenticated_peer_reaches_strict_pr3c(self):
        credential = self.grant()
        request = self.signed(self.frame(credential))
        self.assertFalse(ingress(self.s, **request)["duplicate"])

    def test_tamper_wrong_identity_replay_and_revocation_are_denied(self):
        credential = self.grant()
        envelope = self.frame(credential)
        good = self.signed(envelope)
        tampered = dict(good, envelope=envelope + b" ")
        with self.assertRaises(ConflictError):
            ingress(self.s, **tampered)
        wrong_sha = self.signed(envelope, launcher_sha256="0" * 64)
        with self.assertRaises(ConflictError):
            ingress(self.s, **wrong_sha)
        with self.assertRaises(ConflictError):
            ingress(self.s, **self.signed(envelope, origin="chrome-extension://other/"))
        self.assertFalse(ingress(self.s, **good)["duplicate"])
        with self.assertRaises(ConflictError):
            ingress(self.s, **good)
        revoke_peer(self.s, peer_id=self.peer_id)
        with self.assertRaises(ConflictError):
            ingress(self.s, **self.signed(self.frame(self.grant()), sequence=2))

    def test_peer_sequence_is_consumed_before_bad_inner_envelope(self):
        credential = self.grant()
        malformed = self.signed(b"{}")
        with self.assertRaises(ConflictError):
            ingress(self.s, **malformed)
        # The same authenticated wrapper is never replayed, even after a local reject.
        with self.assertRaises(ConflictError):
            ingress(self.s, **malformed)

    def test_fixture_peer_is_not_an_alternate_pr3c_auth_path(self):
        with self.assertRaises(ConflictError):
            pr3c_ingress(self.s, self.frame("not-a-grant"))

    def test_peer_issuer_cannot_be_retargeted_to_another_store(self):
        from bct.core.store import Store
        lookalike = Store(self.s.path)
        with self.assertRaises(ConflictError):
            issue_fake_peer(lookalike, issuer=self.peer_issuer, peer_id="other",
                            launcher_sha256=self.LAUNCHER)


if __name__ == "__main__":
    unittest.main()
