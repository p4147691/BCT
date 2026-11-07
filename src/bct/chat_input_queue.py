"""Durable per-conversation instruction inbox, without any delivery side effects.

Queue transitions are storage-only. A later trusted adapter must separately
prove target identity and non-duplicated external effects before dispatch.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

_SCHEMA = "bct.chat-input-queue.v1"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STATES = ("QUEUED", "CLAIMED", "HELD_PRE_DISPATCH", "HELD_UNKNOWN", "DONE")


def _valid_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("CHAT_QUEUE_" + label + "_INVALID")
    return value


def _conversation(value: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("CHAT_QUEUE_TARGET_INVALID")
    try:
        ident = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("CHAT_QUEUE_TARGET_INVALID") from exc
    if ident != value:
        raise ValueError("CHAT_QUEUE_TARGET_NOT_CANONICAL")
    return ident


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("CHAT_QUEUE_RESULT_SHA_INVALID")
    return value


@dataclass(frozen=True)
class QueueIdentity:
    """Canonical queue partition identity; it grants no execution authority."""

    work_id: str
    target_conversation_key: str


def validate_queue_identity(*, work_id: str,
                            target_conversation_key: str) -> QueueIdentity:
    """Validate the durable Work and Conversation identifiers shared by every action."""
    return QueueIdentity(
        work_id=_valid_id(work_id, "WORK"),
        target_conversation_key=_conversation(target_conversation_key),
    )


class ChatInputQueue:
    """Atomic FIFO ledger partitioned by owning Work and conversation UUID.

    No method sends, auto-retries, launches work, or assumes that a claim
    means the worker was idle. The caller must attest readiness externally.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def _ensure_schema(self) -> None:
        # Create tables only on a state-changing operation. status() stays pure read.
        with self.store.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_input_queue (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    work_id TEXT NOT NULL,
                    target_conversation_key TEXT NOT NULL,
                    origin_conversation_key TEXT NOT NULL DEFAULT '',
                    instruction TEXT NOT NULL,
                    instruction_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    current_claim_id TEXT NOT NULL DEFAULT '',
                    attempt INTEGER NOT NULL DEFAULT 0,
                    held_reason TEXT NOT NULL DEFAULT '',
                    completion_sha256 TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_input_queue_fifo
                    ON chat_input_queue(work_id,target_conversation_key,sequence);
                CREATE TABLE IF NOT EXISTS chat_input_queue_claims (
                    claim_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)

    @staticmethod
    def _row(row: Any, *, include_text: bool = False,
             duplicate: bool = False) -> dict[str, Any]:
        item = {
            "sequence": row["sequence"],
            "message_id": row["message_id"],
            "work_id": row["work_id"],
            "target_conversation_key": row["target_conversation_key"],
            "origin_conversation_key": row["origin_conversation_key"],
            "instruction_sha256": row["instruction_sha256"],
            "state": row["state"],
            "attempt": row["attempt"],
            "claim_id": row["current_claim_id"],
            "held_reason": row["held_reason"],
            "completion_sha256": row["completion_sha256"],
            "duplicate": duplicate,
        }
        if include_text:
            item["instruction"] = row["instruction"]
        return item

    @staticmethod
    def _event(store: Any, db: Any, kind: str, key: str, metadata: dict[str, Any]) -> None:
        # BCT's established append-only event ledger; no raw instruction text.
        store._event(db, kind, key, metadata)

    @staticmethod
    def _get(db: Any, message_id: str, work_id: str, target: str) -> Any:
        row = db.execute(
            "SELECT * FROM chat_input_queue WHERE message_id=?", (message_id,)
        ).fetchone()
        if row is None:
            raise ValueError("CHAT_QUEUE_MESSAGE_NOT_FOUND")
        if row["work_id"] != work_id or row["target_conversation_key"] != target:
            raise ValueError("CHAT_QUEUE_IDENTITY_CONFLICT")
        return row

    def enqueue(self, *, work_id: str, target_conversation_key: str,
                message_id: str, instruction: str,
                origin_conversation_key: str = "") -> dict[str, Any]:
        identity = validate_queue_identity(
            work_id=work_id, target_conversation_key=target_conversation_key)
        work_id, target = identity.work_id, identity.target_conversation_key
        message_id = _valid_id(message_id, "MESSAGE_ID")
        origin = _conversation(origin_conversation_key) if origin_conversation_key else ""
        if (not isinstance(instruction, str) or not instruction.strip()
                or len(instruction.encode("utf-8")) > 24000 or "\x00" in instruction):
            raise ValueError("CHAT_QUEUE_INSTRUCTION_INVALID")
        digest = _digest(instruction)
        now = time.time()
        self._ensure_schema()
        with self.store.transaction() as db:
            old = db.execute(
                "SELECT * FROM chat_input_queue WHERE message_id=?", (message_id,)
            ).fetchone()
            if old is not None:
                if (old["work_id"], old["target_conversation_key"],
                    old["origin_conversation_key"], old["instruction_sha256"]
                    ) != (work_id, target, origin, digest):
                    raise ValueError("CHAT_QUEUE_MESSAGE_ID_CONFLICT")
                return {"status": "OK", "message": self._row(old, duplicate=True),
                        "effect": "QUEUE_STATE_ONLY"}
            db.execute("""
                INSERT INTO chat_input_queue(
                    message_id,work_id,target_conversation_key,origin_conversation_key,
                    instruction,instruction_sha256,state,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,'QUEUED',?,?)
            """, (message_id, work_id, target, origin, instruction, digest, now, now))
            row = self._get(db, message_id, work_id, target)
            self._event(self.store, db, "CHAT_QUEUE_ENQUEUED", message_id,
                        {"work_id": work_id, "target": target, "sequence": row["sequence"],
                         "instruction_sha256": digest})
            return {"status": "OK", "message": self._row(row),
                    "effect": "QUEUE_STATE_ONLY"}

    def status(self, *, work_id: str, target_conversation_key: str,
               limit: int = 30) -> dict[str, Any]:
        identity = validate_queue_identity(
            work_id=work_id, target_conversation_key=target_conversation_key)
        work_id, target = identity.work_id, identity.target_conversation_key
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("CHAT_QUEUE_LIMIT_INVALID")
        # A read never claims, releases, creates tables or alters worker state.
        with self.store._readonly() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_input_queue'").fetchone()
            if exists is None:
                return {"schema": _SCHEMA, "status": "OK",
                        "target_conversation_key": target, "work_id": work_id,
                        "counts": {state: 0 for state in _STATES}, "head": None,
                        "messages": [], "read_only": True, "delivery_enabled": False}
            counts = {state: 0 for state in _STATES}
            for r in db.execute("""
                SELECT state,COUNT(*) AS n FROM chat_input_queue
                WHERE work_id=? AND target_conversation_key=?
                GROUP BY state
            """, (work_id, target)):
                counts[r["state"]] = r["n"]
            rows = db.execute("""
                SELECT * FROM chat_input_queue
                WHERE work_id=? AND target_conversation_key=?
                ORDER BY sequence ASC LIMIT ?
            """, (work_id, target, limit)).fetchall()
            head = db.execute("""
                SELECT * FROM chat_input_queue
                WHERE work_id=? AND target_conversation_key=? AND state != 'DONE'
                ORDER BY sequence ASC LIMIT 1
            """, (work_id, target)).fetchone()
        return {"schema": _SCHEMA, "status": "OK",
                "target_conversation_key": target, "work_id": work_id,
                "counts": counts,
                "head": self._row(head) if head is not None else None,
                "messages": [self._row(row) for row in rows],
                "read_only": True, "delivery_enabled": False}

    def claim(self, *, work_id: str, target_conversation_key: str,
              claim_id: str) -> dict[str, Any]:
        identity = validate_queue_identity(
            work_id=work_id, target_conversation_key=target_conversation_key)
        work_id, target = identity.work_id, identity.target_conversation_key
        claim_id = _valid_id(claim_id, "CLAIM_ID")
        self._ensure_schema()
        with self.store.transaction() as db:
            previous = db.execute(
                "SELECT * FROM chat_input_queue_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            if previous is not None:
                old = self._get(db, previous["message_id"], work_id, target)
                if old["current_claim_id"] == claim_id and old["state"] == "CLAIMED":
                    return {"status": "CLAIMED", "message": self._row(
                        old, include_text=True, duplicate=True),
                        "effect": "QUEUE_STATE_ONLY"}
                raise ValueError("CHAT_QUEUE_CLAIM_ID_REUSED")
            head = db.execute("""
                SELECT * FROM chat_input_queue
                WHERE work_id=? AND target_conversation_key=? AND state != 'DONE'
                ORDER BY sequence ASC LIMIT 1
            """, (work_id, target)).fetchone()
            if head is None:
                return {"status": "EMPTY", "message": None, "effect": "NONE"}
            if head["state"] != "QUEUED":
                return {"status": "BLOCKED", "head": self._row(head),
                        "reason": "CHAT_QUEUE_HEAD_" + head["state"], "effect": "NONE"}
            now = time.time()
            db.execute("""
                INSERT INTO chat_input_queue_claims
                (claim_id,message_id,attempt,state,created_at,updated_at)
                VALUES(?,?,?,'CLAIMED',?,?)
            """, (claim_id, head["message_id"], head["attempt"] + 1, now, now))
            db.execute("""
                UPDATE chat_input_queue SET state='CLAIMED',
                current_claim_id=?,attempt=attempt+1,updated_at=?
                WHERE sequence=? AND state='QUEUED'
            """, (claim_id, now, head["sequence"]))
            updated = self._get(db, head["message_id"], work_id, target)
            self._event(self.store, db, "CHAT_QUEUE_CLAIMED", updated["message_id"],
                        {"claim_id": claim_id, "sequence": updated["sequence"]})
            return {"status": "CLAIMED", "message": self._row(
                updated, include_text=True), "effect": "QUEUE_STATE_ONLY"}

    def complete(self, *, work_id: str, target_conversation_key: str,
                 message_id: str, claim_id: str,
                 result_sha256: str) -> dict[str, Any]:
        identity = validate_queue_identity(
            work_id=work_id, target_conversation_key=target_conversation_key)
        work_id, target = identity.work_id, identity.target_conversation_key
        _valid_id(message_id, "MESSAGE_ID")
        _valid_id(claim_id, "CLAIM_ID")
        digest = _sha(result_sha256)
        self._ensure_schema()
        with self.store.transaction() as db:
            row = self._get(db, message_id, work_id, target)
            if row["current_claim_id"] != claim_id:
                raise ValueError("CHAT_QUEUE_CLAIM_MISMATCH")
            if row["state"] == "DONE" and row["completion_sha256"] == digest:
                return {"status": "DONE", "message": self._row(row, duplicate=True)}
            if row["state"] != "CLAIMED":
                raise ValueError("CHAT_QUEUE_NOT_CLAIMED")
            now = time.time()
            db.execute("""UPDATE chat_input_queue SET state='DONE',
                completion_sha256=?,updated_at=? WHERE message_id=?""",
                       (digest, now, message_id))
            db.execute("""UPDATE chat_input_queue_claims
                SET state='DONE',result_sha256=?,updated_at=?
                WHERE claim_id=?""", (digest, now, claim_id))
            updated = self._get(db, message_id, work_id, target)
            self._event(self.store, db, "CHAT_QUEUE_COMPLETE_ATTESTED", message_id,
                        {"claim_id": claim_id, "result_sha256": digest,
                         "external_completion_verified": False})
            return {"status": "DONE", "message": self._row(updated),
                    "external_completion_verified": False}

    def hold(self, *, work_id: str, target_conversation_key: str,
             message_id: str, claim_id: str, reason: str,
             kind: str = "UNKNOWN") -> dict[str, Any]:
        identity = validate_queue_identity(
            work_id=work_id, target_conversation_key=target_conversation_key)
        work_id, target = identity.work_id, identity.target_conversation_key
        _valid_id(message_id, "MESSAGE_ID")
        _valid_id(claim_id, "CLAIM_ID")
        if kind not in {"UNKNOWN", "PRE_DISPATCH"}:
            raise ValueError("CHAT_QUEUE_HOLD_KIND_INVALID")
        if (not isinstance(reason, str) or not reason.strip()
                or len(reason) > 500 or "\x00" in reason):
            raise ValueError("CHAT_QUEUE_HOLD_REASON_INVALID")
        state = "HELD_" + kind
        self._ensure_schema()
        with self.store.transaction() as db:
            row = self._get(db, message_id, work_id, target)
            if row["current_claim_id"] != claim_id:
                raise ValueError("CHAT_QUEUE_CLAIM_MISMATCH")
            if row["state"] == state and row["held_reason"] == reason:
                return {"status": state, "message": self._row(row, duplicate=True)}
            if row["state"] != "CLAIMED":
                raise ValueError("CHAT_QUEUE_NOT_CLAIMED")
            now = time.time()
            db.execute("""UPDATE chat_input_queue SET state=?,held_reason=?,
                updated_at=? WHERE message_id=?""",
                       (state, reason, now, message_id))
            db.execute("""UPDATE chat_input_queue_claims
                SET state=?,updated_at=? WHERE claim_id=?""", (state, now, claim_id))
            updated = self._get(db, message_id, work_id, target)
            self._event(self.store, db, "CHAT_QUEUE_HELD", message_id,
                        {"claim_id": claim_id, "kind": kind})
            return {"status": state, "message": self._row(updated)}

    def resume(self, *, work_id: str, target_conversation_key: str,
               message_id: str, claim_id: str) -> dict[str, Any]:
        identity = validate_queue_identity(
            work_id=work_id, target_conversation_key=target_conversation_key)
        work_id, target = identity.work_id, identity.target_conversation_key
        _valid_id(message_id, "MESSAGE_ID")
        _valid_id(claim_id, "CLAIM_ID")
        self._ensure_schema()
        with self.store.transaction() as db:
            row = self._get(db, message_id, work_id, target)
            old_claim = db.execute(
                "SELECT state FROM chat_input_queue_claims WHERE claim_id=? AND message_id=?",
                (claim_id, message_id),
            ).fetchone()
            if old_claim is not None and old_claim["state"] == "RESUMED":
                return {"status": "ALREADY_RESUMED", "message": self._row(row, duplicate=True)}
            if row["current_claim_id"] != claim_id:
                raise ValueError("CHAT_QUEUE_CLAIM_MISMATCH")
            if row["state"] == "HELD_UNKNOWN":
                raise ValueError("CHAT_QUEUE_UNKNOWN_REQUIRES_TRUSTED_RECONCILIATION")
            if row["state"] != "HELD_PRE_DISPATCH":
                raise ValueError("CHAT_QUEUE_NOT_SAFE_TO_RESUME")
            now = time.time()
            db.execute("""UPDATE chat_input_queue
                SET state='QUEUED',current_claim_id='',held_reason='',
                    updated_at=? WHERE message_id=?""", (now, message_id))
            db.execute("""UPDATE chat_input_queue_claims SET state='RESUMED',
                updated_at=? WHERE claim_id=?""", (now, claim_id))
            updated = self._get(db, message_id, work_id, target)
            self._event(self.store, db, "CHAT_QUEUE_RESUMED_PRE_DISPATCH", message_id,
                        {"prior_claim_id": claim_id})
            return {"status": "QUEUED", "message": self._row(updated)}
