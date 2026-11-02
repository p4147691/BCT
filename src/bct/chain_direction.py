"""Durable A-authored direction records for the next 1:1 Chain Message.

The direction text is deliberately free-form.  BCT stores and links it; it
does not infer user intent, write the direction, or decide whether a task is
complete.
"""
from __future__ import annotations

import time
import re
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_DECISIONS = {"COMPLETE", "NEW_TASK", "ASK_USER", "HOLD"}
_SOURCES = {"USER", "MANAGER_RETURN"}


class ChainDirectionLedger:
    """Store an A decision and its free-form direction without sending."""

    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_directions (
                    direction_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    source_generation INTEGER NOT NULL,
                    source_result_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    direction_text TEXT NOT NULL,
                    chain_task_id TEXT NOT NULL DEFAULT '',
                    chain_operation_id TEXT NOT NULL DEFAULT '',
                    chain_send_operation_id TEXT NOT NULL DEFAULT '',
                    chain_state TEXT NOT NULL DEFAULT 'NOT_PLANNED',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    @staticmethod
    def _validate(*, direction_id: str, work_id: str, source_kind: str,
                  source_task_id: str, source_generation: int,
                  source_result_sha256: str, decision: str,
                  direction_text: str) -> None:
        if not all(isinstance(value, str) and _ID.fullmatch(value)
                   for value in (direction_id, work_id)):
            raise ValueError("CHAIN_DIRECTION_ID_INVALID")
        if source_kind not in _SOURCES or decision not in _DECISIONS:
            raise ValueError("CHAIN_DIRECTION_STATE_INVALID")
        if not isinstance(direction_text, str) or not direction_text.strip() or len(direction_text) > 12000:
            raise ValueError("CHAIN_DIRECTION_TEXT_INVALID")
        if source_kind == "MANAGER_RETURN":
            if (not isinstance(source_task_id, str) or not _ID.fullmatch(source_task_id)
                    or type(source_generation) is not int or source_generation < 1
                    or not isinstance(source_result_sha256, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", source_result_sha256)):
                raise ValueError("CHAIN_DIRECTION_RETURN_SOURCE_INVALID")
        elif source_task_id or source_generation or source_result_sha256:
            raise ValueError("CHAIN_DIRECTION_USER_SOURCE_INVALID")

    def save(self, *, direction_id: str, work_id: str, source_kind: str,
             source_task_id: str = "", source_generation: int = 0,
             source_result_sha256: str = "", decision: str,
             direction_text: str) -> dict[str, Any]:
        self._validate(
            direction_id=direction_id, work_id=work_id, source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_result_sha256=source_result_sha256, decision=decision,
            direction_text=direction_text,
        )
        proposed = (
            work_id, source_kind, source_task_id, source_generation,
            source_result_sha256, decision, direction_text,
        )
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[key] for key in (
                    "work_id", "source_kind", "source_task_id", "source_generation",
                    "source_result_sha256", "decision", "direction_text",
                ))
                if actual != proposed:
                    raise ValueError("CHAIN_DIRECTION_CONFLICT")
                return {**dict(existing), "duplicate": True}
            db.execute("""
                INSERT INTO chain_directions(
                    direction_id,work_id,source_kind,source_task_id,source_generation,
                    source_result_sha256,decision,direction_text,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (direction_id, *proposed, now, now))
        return {**(self.get(direction_id=direction_id) or {}), "duplicate": False}

    def get(self, *, direction_id: str) -> dict[str, Any] | None:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def plan_chain(self, *, direction_id: str, work_id: str, task_id: str,
                   operation_id: str, instruction_text: str = "") -> dict[str, Any]:
        if not all(isinstance(value, str) and _ID.fullmatch(value)
                   for value in (direction_id, work_id, task_id, operation_id)):
            raise ValueError("CHAIN_DIRECTION_ID_INVALID")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if row is None or row["work_id"] != work_id:
                raise ValueError("CHAIN_DIRECTION_NOT_FOUND")
            if row["decision"] != "NEW_TASK":
                raise ValueError("CHAIN_DIRECTION_NOT_A_NEW_TASK")
            if instruction_text and instruction_text != row["direction_text"]:
                raise ValueError("CHAIN_DIRECTION_TEXT_MISMATCH")
            current = (row["chain_task_id"], row["chain_operation_id"])
            wanted = (task_id, operation_id)
            if current != ("", "") and current != wanted:
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
            if current == ("", ""):
                db.execute("""
                    UPDATE chain_directions
                    SET chain_task_id=?,chain_operation_id=?,chain_state='CHAIN_PLANNED',updated_at=?
                    WHERE direction_id=?
                """, (task_id, operation_id, time.time(), direction_id))
        return self.get(direction_id=direction_id) or {}

    def mark_chain_started(self, *, direction_id: str, work_id: str,
                           task_id: str, operation_id: str) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if (row is None or row["work_id"] != work_id
                    or row["chain_task_id"] != task_id
                    or row["chain_operation_id"] != operation_id):
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
            if row["chain_state"] == "CHAIN_STARTED":
                return {**dict(row), "duplicate": True}
            if row["chain_state"] != "CHAIN_PLANNED":
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
            updated = db.execute("""
                UPDATE chain_directions
                SET chain_state='CHAIN_STARTED',chain_send_operation_id=?,updated_at=?
                WHERE direction_id=? AND chain_state='CHAIN_PLANNED'
            """, (operation_id + "-send", time.time(), direction_id))
            if updated.rowcount != 1:
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
        return {**(self.get(direction_id=direction_id) or {}), "duplicate": False}
