"""Durable concrete plans derived from an A-authored Chain Direction.

The AI authors both records.  BCT only preserves the distinction and proves
that the exact plan text is the text reserved and delivered by Chain Message.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from bct.chain_direction import ChainDirectionLedger


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class ChainMessagePlanLedger:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_message_plans (
                    plan_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    direction_id TEXT NOT NULL,
                    plan_text TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    chain_task_id TEXT NOT NULL DEFAULT '',
                    chain_operation_id TEXT NOT NULL DEFAULT '',
                    chain_send_operation_id TEXT NOT NULL DEFAULT '',
                    chain_state TEXT NOT NULL DEFAULT 'NOT_STARTED',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    @staticmethod
    def _validate_id(value: str) -> bool:
        return isinstance(value, str) and _ID.fullmatch(value) is not None

    def save(self, *, plan_id: str, work_id: str, direction_id: str,
             plan_text: str) -> dict[str, Any]:
        if not all(self._validate_id(value) for value in
                   (plan_id, work_id, direction_id)):
            raise ValueError("CHAIN_MESSAGE_PLAN_ID_INVALID")
        if not isinstance(plan_text, str) or not plan_text.strip() or len(plan_text) > 12000:
            raise ValueError("CHAIN_MESSAGE_PLAN_TEXT_INVALID")
        direction = ChainDirectionLedger(self.store).get(direction_id=direction_id)
        if direction is None or direction["work_id"] != work_id:
            raise ValueError("CHAIN_DIRECTION_NOT_FOUND")
        if direction["decision"] != "NEW_TASK":
            raise ValueError("CHAIN_DIRECTION_NOT_A_NEW_TASK")
        plan_sha = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
        proposed = (work_id, direction_id, plan_text, plan_sha)
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chain_message_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[key] for key in
                               ("work_id", "direction_id", "plan_text", "plan_sha256"))
                if actual != proposed:
                    raise ValueError("CHAIN_MESSAGE_PLAN_CONFLICT")
                return {**dict(existing), "duplicate": True}
            db.execute("""
                INSERT INTO chain_message_plans(
                    plan_id,work_id,direction_id,plan_text,plan_sha256,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)
            """, (plan_id, *proposed, now, now))
        return {**(self.get(plan_id=plan_id) or {}), "duplicate": False}

    def get(self, *, plan_id: str) -> dict[str, Any] | None:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_message_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def bind_chain(self, *, plan_id: str, work_id: str, task_id: str,
                   operation_id: str, instruction_text: str = "") -> dict[str, Any]:
        if not all(self._validate_id(value) for value in
                   (plan_id, work_id, task_id, operation_id)):
            raise ValueError("CHAIN_MESSAGE_PLAN_ID_INVALID")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_message_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None or row["work_id"] != work_id:
                raise ValueError("CHAIN_MESSAGE_PLAN_NOT_FOUND")
            if instruction_text and instruction_text != row["plan_text"]:
                raise ValueError("CHAIN_MESSAGE_PLAN_TEXT_MISMATCH")
            current = (row["chain_task_id"], row["chain_operation_id"])
            wanted = (task_id, operation_id)
            if current != ("", "") and current != wanted:
                raise ValueError("CHAIN_MESSAGE_PLAN_CHAIN_CONFLICT")
            if current == ("", ""):
                db.execute("""
                    UPDATE chain_message_plans
                    SET chain_task_id=?,chain_operation_id=?,chain_state='CHAIN_PLANNED',updated_at=?
                    WHERE plan_id=?
                """, (task_id, operation_id, time.time(), plan_id))
        return self.get(plan_id=plan_id) or {}

    def mark_chain_started(self, *, plan_id: str, work_id: str,
                           task_id: str, operation_id: str) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_message_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if (row is None or row["work_id"] != work_id
                    or row["chain_task_id"] != task_id
                    or row["chain_operation_id"] != operation_id):
                raise ValueError("CHAIN_MESSAGE_PLAN_CHAIN_CONFLICT")
            if row["chain_state"] == "CHAIN_STARTED":
                return {**dict(row), "duplicate": True}
            if row["chain_state"] != "CHAIN_PLANNED":
                raise ValueError("CHAIN_MESSAGE_PLAN_CHAIN_CONFLICT")
            updated = db.execute("""
                UPDATE chain_message_plans
                SET chain_state='CHAIN_STARTED',chain_send_operation_id=?,updated_at=?
                WHERE plan_id=? AND chain_state='CHAIN_PLANNED'
            """, (operation_id + "-send", time.time(), plan_id))
            if updated.rowcount != 1:
                raise ValueError("CHAIN_MESSAGE_PLAN_CHAIN_CONFLICT")
        return {**(self.get(plan_id=plan_id) or {}), "duplicate": False}
