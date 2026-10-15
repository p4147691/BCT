"""PR3-h: explicit Bridge-only DPAPI file secret store.

There is no default directory, no automatic directory creation and no listener.
Callers must explicitly choose a pre-created, separately ACL-verified directory
before this store can create a file.  It is compatible with PR3-f's create-only
secret-store contract.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import bridge_pr3g_dpapi as dpapi


_PREFIX = b"bct-bridge-peer-secret-v1\0"


def _valid(peer_id: object, binding_generation: object) -> bool:
    return (isinstance(peer_id, str) and 0 < len(peer_id) <= 128
            and type(binding_generation) is int and 1 <= binding_generation <= 2 ** 63 - 1)


def _context(peer_id: str, binding_generation: int) -> bytes:
    return _PREFIX + peer_id.encode("utf-8") + b"\0" + str(binding_generation).encode("ascii")


def _filename(peer_id: str, binding_generation: int) -> str:
    # Do not expose an opaque peer ID in an OS path or a directory listing.
    return hashlib.sha256(_context(peer_id, binding_generation)).hexdigest() + ".dpapi"


class DpapiFileSecretStore:
    """An injected, create-only store; never construct it as a runtime default."""

    def __init__(self, directory: str | Path):
        self._directory = Path(directory)

    def put_secret(self, peer_id: str, binding_generation: int, secret: bytes) -> None:
        self._validate(peer_id, binding_generation)
        if not isinstance(secret, bytes) or len(secret) != 32:
            raise ValueError("PEER_SECRET_STORE_ARGUMENT_INVALID")
        path = self._path(peer_id, binding_generation)
        protected = dpapi.protect(secret, context=_context(peer_id, binding_generation))
        created = False
        try:
            # CREATE_EXCL is the storage half of PR3-f's single-use generation
            # contract: an existing value is never overwritten.
            # Python's exclusive binary mode performs the whole bytes write as
            # one file operation.  It avoids partial low-level writes becoming
            # a malformed DPAPI blob on Windows.
            with path.open("xb") as handle:
                created = True
                handle.write(protected)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # A just-created partial file must not become a future secret. Do
            # not touch a pre-existing generation when O_EXCL rejects it.
            if created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def get_secret(self, peer_id: str, binding_generation: int) -> bytes | None:
        try:
            self._validate(peer_id, binding_generation)
            path = self._path(peer_id, binding_generation)
            if path.is_symlink() or not path.is_file():
                return None
            protected = path.read_bytes()
            return dpapi.unprotect(protected, context=_context(peer_id, binding_generation))
        except Exception:
            return None

    def delete_secret(self, peer_id: str, binding_generation: int) -> None:
        self._validate(peer_id, binding_generation)
        path = self._path(peer_id, binding_generation)
        if path.is_symlink():
            raise RuntimeError("PEER_SECRET_STORE_DENIED")
        path.unlink(missing_ok=True)

    def _validate(self, peer_id: object, binding_generation: object) -> None:
        if not _valid(peer_id, binding_generation):
            raise ValueError("PEER_SECRET_STORE_ARGUMENT_INVALID")
        if not self._directory.is_dir() or self._directory.is_symlink():
            raise RuntimeError("PEER_SECRET_STORE_UNAVAILABLE")

    def _path(self, peer_id: str, binding_generation: int) -> Path:
        return self._directory / _filename(peer_id, binding_generation)
