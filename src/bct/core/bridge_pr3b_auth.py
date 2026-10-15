"""Isolated internal capability guard for a future authenticated bridge endpoint.

This module does not bind to HTTP/MCP/Native Messaging. Issuance is fixture-only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import math
import tempfile
import weakref
import time
from pathlib import Path
from .store import Store

from .models import ConflictError
from .bridge_pr3a_safe import completion_report, result_get, delivery_receipt_get, recipient_ack

class _FixtureIssuer:
    __slots__ = ("__weakref__",)


_FIXTURE_ISSUERS = weakref.WeakKeyDictionary()

def create_fake_issuer_fixture():
    """Build an isolated test DB and opaque issuer bound to this exact Store object."""
    directory=tempfile.TemporaryDirectory(prefix="bridge-auth-fixture-")
    store=Store(Path(directory.name) / "fixture.db")
    issuer=_FixtureIssuer()
    _FIXTURE_ISSUERS[issuer]=(store,directory)
    return store, issuer


OPERATIONS = frozenset({"completion_report", "result_get", "delivery_receipt_get", "recipient_ack"})
ORIGIN = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"
AUDIENCE = "bct-bridge-core-internal-v1"


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid(value):
    return isinstance(value, str) and 0 < len(value) <= 256


def install_schema(store):
    with store.transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_auth_grants(
            credential_digest TEXT PRIMARY KEY, session_id TEXT NOT NULL, node_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL, attachment_generation INTEGER NOT NULL,
            operation TEXT NOT NULL, origin TEXT NOT NULL, audience TEXT NOT NULL,
            expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_auth_requests(
            credential_digest TEXT NOT NULL, request_id TEXT NOT NULL, request_digest TEXT NOT NULL,
            PRIMARY KEY(credential_digest, request_id))""")


def issue_fake_grant(store, *, session_id, node_id, attachment_id, generation,
                     operation, expires_at, issuer=None, origin=ORIGIN, audience=AUDIENCE):
    """Requires the unforgeable in-process issuer for the exact fixture Store."""
    binding=_FIXTURE_ISSUERS.get(issuer) if isinstance(issuer,_FixtureIssuer) else None
    if binding is None or binding[0] is not store:
        raise ConflictError("FIXTURE_ONLY")
    if not all(_valid(v) for v in (session_id, node_id, attachment_id)):
        raise ValueError("GRANT_ARGUMENT_INVALID")
    if type(generation) is not int or generation < 1 or operation not in OPERATIONS:
        raise ValueError("GRANT_ARGUMENT_INVALID")
    if origin != ORIGIN or audience != AUDIENCE or type(expires_at) not in (int, float) or not math.isfinite(expires_at):
        raise ValueError("GRANT_ARGUMENT_INVALID")
    credential = secrets.token_hex(32)
    with store.transaction() as db:
        db.execute("INSERT INTO bridge_auth_grants VALUES(?,?,?,?,?,?,?,?,?,0)",
                   (_hash(credential),session_id,node_id,attachment_id,generation,
                    operation,origin,audience,expires_at))
    return credential


def revoke(store, *, credential):
    if not _valid(credential):
        raise ConflictError("CAPABILITY_DENIED")
    with store.transaction() as db:
        db.execute("UPDATE bridge_auth_grants SET revoked=1 WHERE credential_digest=?",(_hash(credential),))


def authorize(store, *, credential, request_id, operation, session_id, node_id,
              attachment_id, generation, origin, audience, now, arguments):
    """Fail-closed one-shot request reservation. Never echo credential in errors."""
    if not all(_valid(v) for v in (credential,request_id,session_id,node_id,attachment_id)):
        raise ConflictError("CAPABILITY_DENIED")
    if operation not in OPERATIONS or type(generation) is not int or generation < 1:
        raise ConflictError("CAPABILITY_DENIED")
    if not isinstance(arguments, dict):
        raise ConflictError("CAPABILITY_DENIED")
    try:
        request_digest=_hash(json.dumps([operation,session_id,node_id,attachment_id,generation,arguments],
                                         sort_keys=True,separators=(",",":"),allow_nan=False))
    except (TypeError, ValueError):
        raise ConflictError("CAPABILITY_DENIED") from None
    trusted_now=time.time()
    if not math.isfinite(trusted_now):
        raise ConflictError("CAPABILITY_DENIED")
    credential_digest=_hash(credential)
    with store.transaction() as db:
        row=db.execute("SELECT * FROM bridge_auth_grants WHERE credential_digest=?",
                       (credential_digest,)).fetchone()
        if (row is None or not hmac.compare_digest(row["credential_digest"],credential_digest)
            or row["revoked"] or row["expires_at"] <= trusted_now
            or row["operation"] != operation or row["session_id"] != session_id
            or row["node_id"] != node_id or row["attachment_id"] != attachment_id
            or row["attachment_generation"] != generation
            or origin != ORIGIN or audience != AUDIENCE
            or row["origin"] != origin or row["audience"] != audience):
            raise ConflictError("CAPABILITY_DENIED")
        attachment=db.execute("""SELECT active,node_id FROM orchestration_attachments
          WHERE attachment_id=? AND generation=?""",(attachment_id,generation)).fetchone()
        if attachment is None or not attachment["active"] or attachment["node_id"] != node_id:
            raise ConflictError("CAPABILITY_DENIED")
        old=db.execute("SELECT request_digest FROM bridge_auth_requests WHERE credential_digest=? AND request_id=?",
                       (credential_digest,request_id)).fetchone()
        if old is not None:
            raise ConflictError("CAPABILITY_REPLAY_CONFLICT" if old["request_digest"]!=request_digest
                                else "CAPABILITY_REPLAY_DENIED")
        db.execute("INSERT INTO bridge_auth_requests VALUES(?,?,?)",
                   (credential_digest,request_id,request_digest))
    return True


def call(store, *, credential, request_id, operation, session_id, node_id, attachment_id,
         generation, origin, audience, now, arguments):
    authorize(store,credential=credential,request_id=request_id,operation=operation,
              session_id=session_id,node_id=node_id,attachment_id=attachment_id,
              generation=generation,origin=origin,audience=audience,now=now,arguments=arguments)
    # The internal adapter retains its own Core provenance / generation / lease fencing.
    if operation == "completion_report":
        if arguments.get("session_id") != session_id or arguments.get("source_node_id") != node_id:
            raise ConflictError("CAPABILITY_SCOPE_DENIED")
        return completion_report(store,**arguments)
    if operation == "result_get":
        row=result_get(store,**arguments)
        if row["source_node_id"]!=node_id or row["session_id"]!=session_id:
            raise ConflictError("CAPABILITY_SCOPE_DENIED")
        return row
    if operation == "delivery_receipt_get":
        if arguments.get("session_id")!=session_id:
            raise ConflictError("CAPABILITY_SCOPE_DENIED")
        row=delivery_receipt_get(store,**arguments)
        if row is None or row["target_node_id"]!=node_id or row["attachment_id"]!=attachment_id or row["attachment_generation"]!=generation:
            raise ConflictError("CAPABILITY_SCOPE_DENIED")
        return row
    if operation == "recipient_ack":
        delivery = delivery_receipt_get(store,session_id=session_id,delivery_id=arguments.get("delivery_id"))
        if delivery is None or delivery["target_node_id"] != node_id:
            raise ConflictError("CAPABILITY_SCOPE_DENIED")
        if (arguments.get("target_node_id")!=node_id
            or arguments.get("attachment_id")!=attachment_id
            or arguments.get("attachment_generation")!=generation):
            raise ConflictError("CAPABILITY_SCOPE_DENIED")
        return recipient_ack(store,**arguments)
    raise ConflictError("CAPABILITY_DENIED")
