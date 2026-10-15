"""PR3-e: production-disabled Host/Core peer-frame adapter boundary.

This module deliberately exposes no listener and has no default credential
source. A caller must provide a narrow peer-binding provider backed by a
separately provisioned OS credential boundary before an outer Host frame can
reach the PR3-c strict ingress contract.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Protocol

from .bridge_pr3b_auth import ORIGIN
from .bridge_pr3c_ingress import MAX_BYTES, ingress as strict_ingress
from .models import ConflictError


MAX_PEER_FRAME_BYTES = MAX_BYTES * 3
_FIELDS = frozenset(("version", "peer_id", "binding_generation", "launcher_sha256",
                     "origin", "sequence", "envelope_b64", "proof"))


@dataclass(frozen=True)
class PeerBinding:
    """One provisioned Host identity resolved outside the request payload.

    ``secret`` must originate in an OS-backed credential boundary in a real
    deployment. It is never written to SQLite, a receipt, or an error.
    """

    peer_id: str
    binding_generation: int
    launcher_sha256: str
    origin: str
    secret: bytes


class PeerBindingProvider(Protocol):
    """Resolve only the pre-provisioned binding for an already parsed peer ID."""

    def resolve_peer_binding(self, peer_id: str) -> PeerBinding | None:
        """Return the current binding, or ``None`` when the peer is not allowed."""


@dataclass(frozen=True)
class _PeerFrame:
    peer_id: str
    binding_generation: int
    launcher_sha256: str
    origin: str
    sequence: int
    envelope: bytes
    proof: str


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def _sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _proof_input(frame: _PeerFrame):
    return json.dumps(
        ["bct-bridge-peer-adapter-v1", frame.peer_id, frame.binding_generation,
         frame.launcher_sha256, frame.origin, frame.sequence, frame.envelope.hex()],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def make_peer_proof(secret: bytes, *, peer_id: str, binding_generation: int,
                    launcher_sha256: str, origin: str, sequence: int,
                    envelope: bytes) -> str:
    """Build a proof for a provisioned Host; callers retain the secret locally."""
    if not isinstance(secret, bytes) or len(secret) != 32 or not isinstance(envelope, bytes):
        raise ValueError("PEER_ARGUMENT_INVALID")
    frame = _PeerFrame(peer_id, binding_generation, launcher_sha256, origin, sequence,
                       envelope, "")
    return hmac.new(secret, _proof_input(frame), hashlib.sha256).hexdigest()


def parse_peer_frame(frame: bytes) -> _PeerFrame:
    """Strictly decode the outer Native-Host frame without authorizing it."""
    if not isinstance(frame, bytes) or not 0 < len(frame) <= MAX_PEER_FRAME_BYTES:
        raise ConflictError("PEER_ADAPTER_DENIED")
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE")))
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise ValueError("FRAME_FIELDS")
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("FRAME_VERSION")
        if (not isinstance(value["peer_id"], str) or not 0 < len(value["peer_id"]) <= 128
                or type(value["binding_generation"]) is not int
                or not 1 <= value["binding_generation"] <= 2 ** 63 - 1
                or not _sha256(value["launcher_sha256"]) or value["origin"] != ORIGIN
                or type(value["sequence"]) is not int or not 1 <= value["sequence"] <= 2 ** 63 - 1
                or not isinstance(value["envelope_b64"], str)
                or not isinstance(value["proof"], str) or len(value["proof"]) != 64
                or any(char not in "0123456789abcdef" for char in value["proof"])):
            raise ValueError("FRAME_VALUE")
        envelope = base64.b64decode(value["envelope_b64"].encode("ascii"), validate=True)
        if not 0 < len(envelope) <= MAX_BYTES:
            raise ValueError("ENVELOPE_LENGTH")
        if base64.b64encode(envelope).decode("ascii") != value["envelope_b64"]:
            raise ValueError("ENVELOPE_ENCODING")
        return _PeerFrame(value["peer_id"], value["binding_generation"],
                          value["launcher_sha256"], value["origin"], value["sequence"],
                          envelope, value["proof"])
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        raise ConflictError("PEER_ADAPTER_DENIED") from None


def install_schema(store):
    """Install replay fencing metadata; this never stores a peer secret."""
    with store.transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_peer_sequences(
            peer_id TEXT NOT NULL, binding_generation INTEGER NOT NULL,
            last_sequence INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(peer_id, binding_generation))""")


class PeerAdapter:
    """Transport-neutral adapter; a listener must opt in with a real provider."""

    def __init__(self, binding_provider: PeerBindingProvider):
        if binding_provider is None:
            raise ValueError("PEER_BINDING_PROVIDER_REQUIRED")
        self._binding_provider = binding_provider

    def ingress(self, store, frame: bytes):
        """Verify binding/proof, atomically consume sequence, then call PR3-c.

        The sequence is committed before PR3-c parsing. A malformed inner
        envelope is therefore not replayable through this outer frame.
        """
        peer_frame = parse_peer_frame(frame)
        binding = self._binding_provider.resolve_peer_binding(peer_frame.peer_id)
        if not _binding_matches(binding, peer_frame):
            raise ConflictError("PEER_ADAPTER_DENIED")
        expected = make_peer_proof(
            binding.secret, peer_id=peer_frame.peer_id,
            binding_generation=peer_frame.binding_generation,
            launcher_sha256=peer_frame.launcher_sha256, origin=peer_frame.origin,
            sequence=peer_frame.sequence, envelope=peer_frame.envelope,
        )
        if not hmac.compare_digest(expected, peer_frame.proof):
            raise ConflictError("PEER_ADAPTER_DENIED")
        with store.transaction() as db:
            row = db.execute(
                "SELECT last_sequence FROM bridge_peer_sequences "
                "WHERE peer_id=? AND binding_generation=?",
                (peer_frame.peer_id, peer_frame.binding_generation),
            ).fetchone()
            if row is not None and peer_frame.sequence <= row["last_sequence"]:
                raise ConflictError("PEER_ADAPTER_DENIED")
            if row is None:
                db.execute("INSERT INTO bridge_peer_sequences(peer_id,binding_generation,last_sequence) "
                           "VALUES(?,?,?)", (peer_frame.peer_id,
                                               peer_frame.binding_generation,
                                               peer_frame.sequence))
            else:
                db.execute("UPDATE bridge_peer_sequences SET last_sequence=? "
                           "WHERE peer_id=? AND binding_generation=?",
                           (peer_frame.sequence, peer_frame.peer_id,
                            peer_frame.binding_generation))
        return strict_ingress(store, peer_frame.envelope)


def ingress(store, frame: bytes, *, binding_provider: PeerBindingProvider | None = None):
    """Default-disabled entry point for a future local IPC listener."""
    if binding_provider is None:
        raise ConflictError("PEER_ENDPOINT_DISABLED")
    return PeerAdapter(binding_provider).ingress(store, frame)


def _binding_matches(binding, frame: _PeerFrame):
    return (isinstance(binding, PeerBinding) and binding.peer_id == frame.peer_id
            and binding.binding_generation == frame.binding_generation
            and binding.launcher_sha256 == frame.launcher_sha256
            and binding.origin == frame.origin == ORIGIN
            and isinstance(binding.secret, bytes) and len(binding.secret) == 32)
