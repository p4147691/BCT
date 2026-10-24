"""Opt-in, encrypted, persistent Browser Bridge mailbox. No ChatGPT page effects.

CLAIMED/ACKED are *mailbox* receipts, never evidence that ChatGPT submitted
or completed a prompt. A claimed item is never automatically delivered again.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
import re

_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z")
_NODE = re.compile(r"N(?:[1-9]|[1-9][0-9]{1,2})\Z")
_ID = re.compile(r"[a-f0-9]{32}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")


def _valid(value, pattern, code):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(code)
    return value


def _payload(text, supplied_hash):
    if not isinstance(text, str) or not 0 < len(text) <= 2000:
        raise ValueError("BRIDGE_PAYLOAD_INVALID")
    raw = text.encode("utf-8")
    if len(raw) > 8192 or hashlib.sha256(raw).hexdigest() != supplied_hash:
        raise ValueError("BRIDGE_PAYLOAD_SHA_INVALID")
    return raw


class NodeRelayStore:
    """Caller provisions an existing, separately ACL-approved DB location and codec.

    Codec must provide protect(bytes, context=bytes) / unprotect(...).
    No default plaintext or secret/key implementation is permitted.
    """

    def __init__(self, path, codec):
        self.path = Path(path)
        if (not self.path.is_absolute() or not self.path.parent.is_dir()
                or self.path.parent.is_symlink() or self.path.is_symlink()
                or codec is None):
            raise ValueError("BRIDGE_MAILBOX_STORAGE_NOT_APPROVED")
        self.codec = codec
        self.lock = threading.RLock()
        db = self._open()
        try:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS relay_messages(
                delivery_id TEXT PRIMARY KEY,
                sender_node TEXT NOT NULL, sender_key TEXT NOT NULL,
                receiver_node TEXT NOT NULL, receiver_key TEXT NOT NULL,
                original_sha TEXT NOT NULL, ciphertext BLOB NOT NULL,
                state TEXT NOT NULL, ack_id TEXT, response_sha TEXT,
                response_blob BLOB, created_at REAL NOT NULL
            );
            """)
        finally:
            db.close()

    def _open(self):
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _context(delivery_id, kind):
        return ("bct-independent-node-relay-v1:" + kind + ":" + delivery_id).encode("ascii")

    @staticmethod
    def _identity(m):
        did = _valid(m.get("delivery_id"), _ID, "BRIDGE_DELIVERY_ID_INVALID")
        sender = _valid(m.get("sender_node"), _NODE, "BRIDGE_NODE_INVALID")
        receiver = _valid(m.get("receiver_node"), _NODE, "BRIDGE_NODE_INVALID")
        if sender == receiver:
            raise ValueError("BRIDGE_SELF_RELAY_DENIED")
        skey = _valid(m.get("sender_key"), _UUID, "BRIDGE_CONVERSATION_UUID_INVALID")
        rkey = _valid(m.get("receiver_key"), _UUID, "BRIDGE_CONVERSATION_UUID_INVALID")
        if skey == rkey:
            raise ValueError("BRIDGE_SAME_CONVERSATION_DENIED")
        digest = _valid(m.get("original_sha"), _HASH, "BRIDGE_HASH_INVALID")
        return did, sender, skey, receiver, rkey, digest

    @staticmethod
    def _receipt(row, replayed=False):
        return {"delivery_id": row["delivery_id"],
                "sender_node":row["sender_node"],"sender_key":row["sender_key"],
                "receiver_node":row["receiver_node"],"receiver_key":row["receiver_key"],
                "original_sha":row["original_sha"],"state":row["state"],
                "ack_id":row["ack_id"],"response_sha":row["response_sha"],
                "replayed":replayed,"will_resend":False,
                "chatgpt_submitted":False,"chatgpt_reply_verified":False}

    def enqueue(self, m):
        did, sender, skey, receiver, rkey, digest = self._identity(m)
        raw = _payload(m.get("text"), digest)
        with self.lock:
            db = self._open()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM relay_messages WHERE delivery_id=?", (did,)).fetchone()
                if row:
                    if ((row["sender_node"],row["sender_key"],row["receiver_node"],
                         row["receiver_key"],row["original_sha"]) !=
                        (sender,skey,receiver,rkey,digest)):
                        raise ValueError("BRIDGE_DELIVERY_ID_COLLISION")
                    # Verify original plaintext too: impossible to replay a hash collision
                    # or changed payload through an existing record.
                    existing = self.codec.unprotect(row["ciphertext"],context=self._context(did,"request"))
                    if existing != raw:
                        raise ValueError("BRIDGE_DELIVERY_CONTENT_COLLISION")
                    db.commit()
                    return self._receipt(row, True)
                protected = self.codec.protect(raw,context=self._context(did,"request"))
                if not isinstance(protected,bytes) or len(protected)>16384:
                    raise ValueError("BRIDGE_ENCRYPTION_FAILED")
                db.execute("""INSERT INTO relay_messages VALUES(
                    ?,?,?,?,?,?,?,'QUEUED',NULL,NULL,NULL,?)""",
                    (did,sender,skey,receiver,rkey,digest,protected,time.time()))
                db.commit()
                return self._receipt(db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone())
            except:
                db.rollback()
                raise
            finally:
                db.close()

    def claim(self, *, delivery_id, receiver_node, receiver_key):
        did = _valid(delivery_id,_ID,"BRIDGE_DELIVERY_ID_INVALID")
        node = _valid(receiver_node,_NODE,"BRIDGE_NODE_INVALID")
        key = _valid(receiver_key,_UUID,"BRIDGE_CONVERSATION_UUID_INVALID")
        with self.lock:
            db = self._open()
            try:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone()
                if row is None or row["receiver_node"]!=node or row["receiver_key"]!=key:
                    raise ValueError("BRIDGE_CLAIM_IDENTITY_DENIED")
                if row["state"]!="QUEUED":
                    raise ValueError("BRIDGE_CLAIM_ALREADY_ISSUED_NO_RETRY")
                # Decode before changing state. Once CLAIMED, even a lost result
                # is ambiguous and is not automatically retransmitted.
                text=self.codec.unprotect(row["ciphertext"],context=self._context(did,"request")).decode("utf-8")
                if hashlib.sha256(text.encode("utf-8")).hexdigest()!=row["original_sha"]:
                    raise ValueError("BRIDGE_CLAIM_HASH_MISMATCH")
                db.execute("UPDATE relay_messages SET state='CLAIMED' WHERE delivery_id=?",(did,))
                db.commit()
                receipt=self._receipt(db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone())
                return {**receipt,"text":text}
            except:
                db.rollback()
                raise
            finally:
                db.close()

    def acknowledge(self, *, delivery_id, receiver_node, receiver_key, ack_id):
        did=_valid(delivery_id,_ID,"BRIDGE_DELIVERY_ID_INVALID")
        node=_valid(receiver_node,_NODE,"BRIDGE_NODE_INVALID")
        key=_valid(receiver_key,_UUID,"BRIDGE_CONVERSATION_UUID_INVALID")
        ack=_valid(ack_id,_ID,"BRIDGE_ACK_ID_INVALID")
        with self.lock:
            db=self._open()
            try:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone()
                if row is None or (row["receiver_node"],row["receiver_key"])!=(node,key):
                    raise ValueError("BRIDGE_ACK_IDENTITY_DENIED")
                if row["state"]=="CLAIMED":
                    db.execute("UPDATE relay_messages SET state='ACKED',ack_id=? WHERE delivery_id=?",(ack,did))
                elif row["state"] not in ("ACKED","REPLIED") or row["ack_id"]!=ack:
                    raise ValueError("BRIDGE_ACK_CONFLICT")
                db.commit()
                return self._receipt(db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone(),
                                     replayed=row["state"]!="CLAIMED")
            except:
                db.rollback()
                raise
            finally:
                db.close()

    def reply(self, *, delivery_id, receiver_node, receiver_key, ack_id, text, response_sha):
        did=_valid(delivery_id,_ID,"BRIDGE_DELIVERY_ID_INVALID")
        node=_valid(receiver_node,_NODE,"BRIDGE_NODE_INVALID")
        key=_valid(receiver_key,_UUID,"BRIDGE_CONVERSATION_UUID_INVALID")
        ack=_valid(ack_id,_ID,"BRIDGE_ACK_ID_INVALID")
        digest=_valid(response_sha,_HASH,"BRIDGE_REPLY_HASH_INVALID")
        raw=_payload(text,digest)
        with self.lock:
            db=self._open()
            try:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone()
                if row is None or (row["receiver_node"],row["receiver_key"],row["ack_id"])!=(node,key,ack):
                    raise ValueError("BRIDGE_REPLY_IDENTITY_DENIED")
                if row["state"]=="REPLIED":
                    prior=self.codec.unprotect(row["response_blob"],context=self._context(did,"reply"))
                    if row["response_sha"]!=digest or prior!=raw:
                        raise ValueError("BRIDGE_REPLY_CONFLICT")
                    db.commit()
                    return self._receipt(row, True)
                if row["state"]!="ACKED":
                    raise ValueError("BRIDGE_REPLY_ACK_REQUIRED")
                encrypted=self.codec.protect(raw,context=self._context(did,"reply"))
                if not isinstance(encrypted,bytes) or len(encrypted)>16384:
                    raise ValueError("BRIDGE_ENCRYPTION_FAILED")
                db.execute("UPDATE relay_messages SET state='REPLIED',response_sha=?,response_blob=? WHERE delivery_id=?",
                           (digest,encrypted,did))
                db.commit()
                return self._receipt(db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone())
            except:
                db.rollback()
                raise
            finally:
                db.close()

    def inspect(self, *, delivery_id, sender_node, sender_key):
        did=_valid(delivery_id,_ID,"BRIDGE_DELIVERY_ID_INVALID")
        node=_valid(sender_node,_NODE,"BRIDGE_NODE_INVALID")
        key=_valid(sender_key,_UUID,"BRIDGE_CONVERSATION_UUID_INVALID")
        db=self._open()
        try:
            row=db.execute("SELECT * FROM relay_messages WHERE delivery_id=?",(did,)).fetchone()
            if row is None or (row["sender_node"],row["sender_key"])!=(node,key):
                raise ValueError("BRIDGE_INSPECT_IDENTITY_DENIED")
            result=self._receipt(row)
            if row["state"]=="REPLIED":
                raw=self.codec.unprotect(row["response_blob"],context=self._context(did,"reply"))
                if hashlib.sha256(raw).hexdigest()!=row["response_sha"]:
                    raise ValueError("BRIDGE_STORED_RESPONSE_INVALID")
                result["response_text"]=raw.decode("utf-8")
            return result
        finally:
            db.close()
