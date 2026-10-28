"""Verifier for one-shot, externally signed, user-confirmed P2 approvals.

There is deliberately NO approval-issuance entrypoint in BCT/MCP.
A separately authenticated trusted UI must sign the exact immutable claim.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import time
import tomllib
from pathlib import Path

from bct.core.models import AuthorizationError


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def request_hash(work_id: str, capability: str, target: str,
                 arguments: dict, preconditions: dict) -> str:
    payload = {"work_id": work_id, "capability": capability,
               "target": target, "arguments": arguments,
               "preconditions": preconditions}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                   separators=(",", ":")).encode("utf8")).hexdigest()


class ApprovalVerifier:
    """Verify Ed25519 signature, scope, TTL, and consume token once in SQLite."""

    ALLOWED = frozenset({"file_action_apply", "process_stop_apply"})

    def __init__(self, *, policy_path: str | Path, state_path: str | Path):
        self.policy_path = Path(policy_path)
        self.state_path = str(state_path)

    def _public_key(self):
        data = tomllib.loads(self.policy_path.read_text(encoding="utf8"))
        config = data.get("approval_verifier", {})
        if not isinstance(config, dict) or config.get("enabled") is not True:
            raise AuthorizationError("APPROVAL_VERIFIER_DISABLED")
        encoded = config.get("ed25519_public_key")
        if not isinstance(encoded, str):
            raise AuthorizationError("APPROVAL_PUBLIC_KEY_UNCONFIGURED")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            key = Ed25519PublicKey.from_public_bytes(_decode(encoded))
        except (ValueError, ImportError) as exc:
            raise AuthorizationError("APPROVAL_PUBLIC_KEY_INVALID") from exc
        return key

    def inspect(self, token: str | None, *, principal_id: str, work_id: str,
                operation_id: str, capability: str, target: str,
                digest: str) -> str:
        if capability not in self.ALLOWED:
            raise AuthorizationError("APPROVAL_CAPABILITY_NOT_ELIGIBLE")
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise AuthorizationError("APPROVAL_SIGNED_GRANT_REQUIRED")
        try:
            encoded, signature = token.split(".", 1)
            signed = _decode(encoded)
            claims = json.loads(signed)
            if not isinstance(claims, dict):
                raise ValueError("bad claims")
            self._public_key().verify(_decode(signature), signed)
        except (ValueError, TypeError, KeyError, UnicodeError, IndexError) as exc:
            raise AuthorizationError("APPROVAL_GRANT_INVALID") from exc
        except Exception as exc:
            if isinstance(exc, AuthorizationError):
                raise
            raise AuthorizationError("APPROVAL_SIGNATURE_INVALID") from exc
        expected = {
            "aud": "bct-p2-action-v1", "user_confirmed": True,
            "principal_id": principal_id, "work_id": work_id,
            "operation_id": operation_id, "capability": capability,
            "target": target, "request_sha256": digest,
        }
        for key, value in expected.items():
            if claims.get(key) != value:
                raise AuthorizationError("APPROVAL_SCOPE_MISMATCH")
        nonce = claims.get("nonce")
        issued, expires = claims.get("issued_at"), claims.get("expires_at")
        now = time.time()
        if (not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce)
                or type(issued) not in (int, float)
                or type(expires) not in (int, float)
                or expires <= issued or expires - issued > 600
                or issued > now + 15 or expires <= now):
            raise AuthorizationError("APPROVAL_EXPIRED_OR_INVALID")
        return hashlib.sha256(nonce.encode("ascii")).hexdigest()

    def consumed_for(self, nonce_hash: str, *, principal_id: str,
                     work_id: str, operation_id: str, digest: str) -> bool:
        """Only an exact previously consumed token may resume its operation."""
        connection = sqlite3.connect(self.state_path, timeout=15)
        try:
            try:
                row = connection.execute(
                    "SELECT principal_id, work_id, operation_id, request_digest "
                    "FROM p2_approval_consumption WHERE nonce_hash=?",
                    (nonce_hash,),
                ).fetchone()
            except sqlite3.OperationalError:
                return False
            if row is None:
                return False
            if row != (principal_id, work_id, operation_id, digest):
                raise AuthorizationError("APPROVAL_ALREADY_CONSUMED_BY_OTHER_REQUEST")
            return True
        finally:
            connection.close()

    def consume(self, nonce_hash: str, *, principal_id: str,
                work_id: str, operation_id: str, digest: str) -> None:
        connection = sqlite3.connect(self.state_path, timeout=15, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE IF NOT EXISTS p2_approval_consumption (
                nonce_hash TEXT PRIMARY KEY, principal_id TEXT NOT NULL,
                work_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                request_digest TEXT NOT NULL, consumed_at REAL NOT NULL)""")
            try:
                connection.execute("""INSERT INTO p2_approval_consumption
                    (nonce_hash,principal_id,work_id,operation_id,request_digest,consumed_at)
                    VALUES (?,?,?,?,?,?)""",
                    (nonce_hash, principal_id, work_id, operation_id,
                     digest, time.time()))
            except sqlite3.IntegrityError as exc:
                raise AuthorizationError("APPROVAL_ALREADY_CONSUMED") from exc
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise AuthorizationError("APPROVAL_STORE_UNAVAILABLE") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
