"""PR3-d fixture-only Host/Core peer proof before strict PR3-c ingress.

This module is deliberately not a listener, credential issuer, or Native Host
integration.  It defines the small proof that a future provisioned Host must
present before Core accepts a PR3-c envelope.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import weakref

from .bridge_pr3b_auth import ORIGIN, create_fake_issuer_fixture
from .bridge_pr3c_ingress import ingress as strict_ingress
from .models import ConflictError


class _FixtureIssuer:
    __slots__ = ("__weakref__",)


_FIXTURE_ISSUERS = weakref.WeakKeyDictionary()
_FIXTURE_SECRETS = weakref.WeakKeyDictionary()


def create_fake_peer_fixture():
    """Build an isolated Store plus opaque PR3-b and peer fixture issuers.

    The peer issuer cannot be created for an arbitrary caller-supplied Store.
    Plaintext proof material remains only in test-process memory, never SQLite.
    """
    store, grant_issuer = create_fake_issuer_fixture()
    issuer = _FixtureIssuer()
    _FIXTURE_ISSUERS[issuer] = (store, grant_issuer)
    _FIXTURE_SECRETS.setdefault(store, {})
    return store, grant_issuer, issuer


def install_schema(store):
    """Install additive fixture metadata only; callers must not run this on LIVE."""
    with store.transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_peer_fixtures(
            peer_id TEXT PRIMARY KEY, launcher_sha256 TEXT NOT NULL,
            origin TEXT NOT NULL, last_sequence INTEGER NOT NULL DEFAULT 0,
            revoked INTEGER NOT NULL DEFAULT 0)""")


def _sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _proof_input(peer_id, launcher_sha256, origin, sequence, envelope):
    return json.dumps(["bct-bridge-peer-v1", peer_id, launcher_sha256, origin, sequence, envelope.hex()],
                      separators=(",", ":"), ensure_ascii=True).encode("ascii")


def make_fake_proof(secret, *, peer_id, launcher_sha256, origin, sequence, envelope):
    """Test helper; production Hosts need an independently provisioned secret."""
    if not isinstance(secret, str) or not secret or not isinstance(envelope, bytes):
        raise ValueError("PEER_ARGUMENT_INVALID")
    return hmac.new(secret.encode("ascii"), _proof_input(peer_id, launcher_sha256, origin, sequence, envelope), hashlib.sha256).hexdigest()


def issue_fake_peer(store, *, issuer, peer_id, launcher_sha256, origin=ORIGIN):
    """Fixture-only peer registration with an in-memory 256-bit proof secret."""
    binding = _FIXTURE_ISSUERS.get(issuer)
    if binding is None or binding[0] is not store:
        raise ConflictError("FIXTURE_ONLY")
    if not isinstance(peer_id, str) or not 0 < len(peer_id) <= 128 or not _sha256(launcher_sha256) or origin != ORIGIN:
        raise ValueError("PEER_ARGUMENT_INVALID")
    secret = secrets.token_hex(32)
    with store.transaction() as db:
        db.execute("INSERT INTO bridge_peer_fixtures(peer_id,launcher_sha256,origin) VALUES(?,?,?)",
                   (peer_id, launcher_sha256, origin))
    _FIXTURE_SECRETS[store][peer_id] = secret
    return secret


def revoke_peer(store, *, peer_id):
    if not isinstance(peer_id, str):
        raise ConflictError("PEER_DENIED")
    with store.transaction() as db:
        db.execute("UPDATE bridge_peer_fixtures SET revoked=1 WHERE peer_id=?", (peer_id,))


def authenticate(store, *, peer_id, launcher_sha256, origin, sequence, envelope, proof):
    """Atomically verify and consume a strictly increasing peer sequence number."""
    if (not isinstance(peer_id, str) or not _sha256(launcher_sha256) or origin != ORIGIN
            or type(sequence) is not int or not 1 <= sequence <= 2**63 - 1 or not isinstance(envelope, bytes)
            or not isinstance(proof, str) or len(proof) != 64):
        raise ConflictError("PEER_DENIED")
    secret = _FIXTURE_SECRETS.get(store, {}).get(peer_id)
    if secret is None:
        raise ConflictError("PEER_DENIED")
    expected = make_fake_proof(secret, peer_id=peer_id, launcher_sha256=launcher_sha256,
                               origin=origin, sequence=sequence, envelope=envelope)
    if not hmac.compare_digest(expected, proof):
        raise ConflictError("PEER_DENIED")
    with store.transaction() as db:
        row = db.execute("SELECT * FROM bridge_peer_fixtures WHERE peer_id=?", (peer_id,)).fetchone()
        if (row is None or row["revoked"] or row["launcher_sha256"] != launcher_sha256
                or row["origin"] != origin or sequence <= row["last_sequence"]):
            raise ConflictError("PEER_DENIED")
        db.execute("UPDATE bridge_peer_fixtures SET last_sequence=? WHERE peer_id=?", (sequence, peer_id))


def ingress(store, *, peer_id, launcher_sha256, origin, sequence, envelope, proof):
    """Reserve peer sequence first, then pass exact bytes to PR3-c strict ingress.

    A rejected inner envelope still consumes its sequence: a Host must construct
    a new request rather than replay an ambiguous peer frame.
    """
    authenticate(store, peer_id=peer_id, launcher_sha256=launcher_sha256, origin=origin,
                 sequence=sequence, envelope=envelope, proof=proof)
    return strict_ingress(store, envelope)
