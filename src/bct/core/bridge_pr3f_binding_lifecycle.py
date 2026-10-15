"""PR3-f: disabled-by-default Bridge peer-binding lifecycle.

This is deliberately a metadata/lifecycle boundary, not a Windows credential
provider or an IPC listener.  A future activation must inject an OS-backed
secret store after its own approval and acceptance evidence.  No secret is
ever stored in the BCT Store.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .bridge_pr3b_auth import ORIGIN
from .bridge_pr3e_peer_adapter import PeerBinding
from .models import ConflictError


_STATES = frozenset(("ACTIVE", "RETIRED", "REVOKED"))


class PeerSecretStore(Protocol):
    """External secret boundary; implementations must never log raw secrets."""

    def put_secret(self, peer_id: str, binding_generation: int, secret: bytes) -> None:
        """Create a new secret; it must fail rather than overwrite an existing key."""

    def get_secret(self, peer_id: str, binding_generation: int) -> bytes | None:
        """Resolve a secret for an already-authorized active binding."""

    def delete_secret(self, peer_id: str, binding_generation: int) -> None:
        """Delete only the named Bridge-only secret."""


@dataclass(frozen=True)
class BindingRecord:
    peer_id: str
    binding_generation: int
    launcher_sha256: str
    origin: str
    state: str


def _sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _arguments_valid(peer_id: object, binding_generation: object,
                     launcher_sha256: object, secret: object) -> bool:
    return (isinstance(peer_id, str) and 0 < len(peer_id) <= 128
            and type(binding_generation) is int and 1 <= binding_generation <= 2 ** 63 - 1
            and _sha256(launcher_sha256) and isinstance(secret, bytes) and len(secret) == 32)


def install_schema(store) -> None:
    """Install non-secret metadata only; safe only for an isolated Store test."""
    with store.transaction() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS bridge_peer_bindings (
                peer_id TEXT NOT NULL,
                binding_generation INTEGER NOT NULL,
                launcher_sha256 TEXT NOT NULL,
                origin TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('ACTIVE','RETIRED','REVOKED')),
                created_at REAL NOT NULL,
                revoked_at REAL,
                PRIMARY KEY(peer_id, binding_generation)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS bridge_peer_bindings_one_active
                ON bridge_peer_bindings(peer_id) WHERE state='ACTIVE';
        """)


class BindingLifecycle:
    """Provision, rotate and revoke explicit bindings without a default store."""

    def __init__(self, store, secret_store: PeerSecretStore):
        if secret_store is None:
            raise ValueError("PEER_SECRET_STORE_REQUIRED")
        self._store = store
        self._secret_store = secret_store
        install_schema(store)

    def provision(self, peer_id: str, *, binding_generation: int,
                  launcher_sha256: str, secret: bytes) -> BindingRecord:
        if not _arguments_valid(peer_id, binding_generation, launcher_sha256, secret):
            raise ValueError("PEER_BINDING_ARGUMENT_INVALID")
        if self._active_row(peer_id) is not None or self._generation_exists(peer_id, binding_generation):
            raise ConflictError("PEER_BINDING_DENIED")
        # ``put_secret`` is create-only by protocol.  This prevents a losing
        # concurrent provisioner from overwriting (or later deleting) another
        # process's generation before SQLite can reject its duplicate row.
        try:
            self._secret_store.put_secret(peer_id, binding_generation, secret)
        except Exception:
            raise ConflictError("PEER_BINDING_DENIED") from None
        try:
            with self._store.transaction() as db:
                db.execute("INSERT INTO bridge_peer_bindings("
                           "peer_id,binding_generation,launcher_sha256,origin,state,created_at,revoked_at) "
                           "VALUES(?,?,?,?,?,?,NULL)",
                           (peer_id, binding_generation, launcher_sha256, ORIGIN, "ACTIVE", time.time()))
        except Exception:
            self._delete_quietly(peer_id, binding_generation)
            raise ConflictError("PEER_BINDING_DENIED") from None
        return BindingRecord(peer_id, binding_generation, launcher_sha256, ORIGIN, "ACTIVE")

    def rotate(self, peer_id: str, *, binding_generation: int,
               launcher_sha256: str, secret: bytes) -> BindingRecord:
        if not _arguments_valid(peer_id, binding_generation, launcher_sha256, secret):
            raise ValueError("PEER_BINDING_ARGUMENT_INVALID")
        active = self._active_row(peer_id)
        if active is None or binding_generation != active["binding_generation"] + 1:
            raise ConflictError("PEER_BINDING_DENIED")
        try:
            self._secret_store.put_secret(peer_id, binding_generation, secret)
        except Exception:
            raise ConflictError("PEER_BINDING_DENIED") from None
        try:
            with self._store.transaction() as db:
                current = db.execute("SELECT binding_generation FROM bridge_peer_bindings "
                                     "WHERE peer_id=? AND state='ACTIVE'", (peer_id,)).fetchone()
                if current is None or current["binding_generation"] != active["binding_generation"]:
                    raise ConflictError("PEER_BINDING_DENIED")
                db.execute("UPDATE bridge_peer_bindings SET state='RETIRED' "
                           "WHERE peer_id=? AND binding_generation=? AND state='ACTIVE'",
                           (peer_id, active["binding_generation"]))
                db.execute("INSERT INTO bridge_peer_bindings("
                           "peer_id,binding_generation,launcher_sha256,origin,state,created_at,revoked_at) "
                           "VALUES(?,?,?,?,?,?,NULL)",
                           (peer_id, binding_generation, launcher_sha256, ORIGIN, "ACTIVE", time.time()))
        except Exception:
            self._delete_quietly(peer_id, binding_generation)
            raise ConflictError("PEER_BINDING_DENIED") from None
        return BindingRecord(peer_id, binding_generation, launcher_sha256, ORIGIN, "ACTIVE")

    def revoke(self, peer_id: str) -> BindingRecord:
        active = self._active_row(peer_id)
        if active is None:
            raise ConflictError("PEER_BINDING_DENIED")
        with self._store.transaction() as db:
            changed = db.execute("UPDATE bridge_peer_bindings SET state='REVOKED', revoked_at=? "
                                 "WHERE peer_id=? AND binding_generation=? AND state='ACTIVE'",
                                 (time.time(), peer_id, active["binding_generation"])).rowcount
            if changed != 1:
                raise ConflictError("PEER_BINDING_DENIED")
        # Deletion is intentionally after fail-closed metadata revocation.  A
        # failed external delete cannot reactivate a peer.
        self._delete_quietly(peer_id, active["binding_generation"])
        return BindingRecord(peer_id, active["binding_generation"], active["launcher_sha256"],
                             ORIGIN, "REVOKED")

    def resolve_peer_binding(self, peer_id: str) -> PeerBinding | None:
        if not isinstance(peer_id, str) or not 0 < len(peer_id) <= 128:
            return None
        row = self._active_row(peer_id)
        if row is None:
            return None
        try:
            secret = self._secret_store.get_secret(peer_id, row["binding_generation"])
        except Exception:
            return None
        if not isinstance(secret, bytes) or len(secret) != 32:
            return None
        return PeerBinding(peer_id, row["binding_generation"], row["launcher_sha256"],
                           row["origin"], secret)

    def _active_row(self, peer_id: str):
        connection = self._store._connect()
        try:
            return connection.execute("SELECT peer_id,binding_generation,launcher_sha256,origin,state "
                                      "FROM bridge_peer_bindings WHERE peer_id=? AND state='ACTIVE'",
                                      (peer_id,)).fetchone()
        finally:
            connection.close()

    def _generation_exists(self, peer_id: str, binding_generation: int) -> bool:
        connection = self._store._connect()
        try:
            return connection.execute("SELECT 1 FROM bridge_peer_bindings "
                                      "WHERE peer_id=? AND binding_generation=?",
                                      (peer_id, binding_generation)).fetchone() is not None
        finally:
            connection.close()

    def _delete_quietly(self, peer_id: str, binding_generation: int) -> None:
        try:
            self._secret_store.delete_secret(peer_id, binding_generation)
        except Exception:
            pass
