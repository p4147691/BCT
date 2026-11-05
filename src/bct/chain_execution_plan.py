"""Durable B-authored execution plans for a delivered Chain Message.

The plan is deliberately created only after its source Chain Direction has
started an exact Chain Message. BCT records the exact relationship and text
hash. A later SELF continuation may carry that one saved plan back to the
same Worker; BCT still never authors the plan or decides the next action.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from typing import Any

from bct.chain_direction import ChainDirectionLedger


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class ChainExecutionPlanLedger:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_execution_plans (
                    plan_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    direction_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    plan_text TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)

    @staticmethod
    def _valid_id(value: str) -> bool:
        return isinstance(value, str) and _ID.fullmatch(value) is not None

    def save(self, *, plan_id: str, work_id: str, direction_id: str,
             task_id: str, generation: int, plan_text: str) -> dict[str, Any]:
        if not all(self._valid_id(value) for value in
                   (plan_id, work_id, direction_id, task_id)):
            raise ValueError("CHAIN_EXECUTION_PLAN_ID_INVALID")
        if type(generation) is not int or generation < 1:
            raise ValueError("CHAIN_EXECUTION_PLAN_GENERATION_INVALID")
        if not isinstance(plan_text, str) or not plan_text.strip() or len(plan_text) > 12000:
            raise ValueError("CHAIN_EXECUTION_PLAN_TEXT_INVALID")
        direction = ChainDirectionLedger(self.store).get(direction_id=direction_id)
        if direction is None or direction["work_id"] != work_id:
            raise ValueError("CHAIN_DIRECTION_NOT_FOUND")
        if (direction["decision"] != "NEW_TASK"
                or direction["chain_state"] != "CHAIN_STARTED"
                or direction["chain_task_id"] != task_id):
            raise ValueError("CHAIN_EXECUTION_PLAN_SOURCE_NOT_STARTED")
        plan_sha = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
        proposed = (work_id, direction_id, task_id, generation, plan_text, plan_sha)
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chain_execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[key] for key in (
                    "work_id", "direction_id", "task_id", "generation",
                    "plan_text", "plan_sha256",
                ))
                if actual != proposed:
                    raise ValueError("CHAIN_EXECUTION_PLAN_CONFLICT")
                return {**dict(existing), "duplicate": True}
            # A single B turn has one declared Execute Plan. Selecting one
            # from two different plans during a later SELF continuation would
            # be an unsafe inference, so reject the second declaration.
            turn_existing = db.execute(
                "SELECT plan_id FROM chain_execution_plans "
                "WHERE work_id=? AND direction_id=? AND task_id=? AND generation=?",
                (work_id, direction_id, task_id, generation),
            ).fetchone()
            if turn_existing is not None:
                raise ValueError("CHAIN_EXECUTION_PLAN_TURN_CONFLICT")
            db.execute("""
                INSERT INTO chain_execution_plans(
                    plan_id,work_id,direction_id,task_id,generation,
                    plan_text,plan_sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
            """, (plan_id, *proposed, time.time()))
        return {**(self.get(plan_id=plan_id) or {}), "duplicate": False}

    def get(self, *, plan_id: str) -> dict[str, Any] | None:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def get_for_chain_turn(*, store, work_id: str, task_id: str,
                           generation: int) -> dict[str, Any] | None:
        """Return the one B plan eligible for this exact continuing turn.

        Older databases can contain more than one record for a turn because
        the original schema had no turn-level uniqueness rule. In that case
        preserve the ordinary SELF message; no plan is selected automatically.
        """
        try:
            with store._readonly() as db:
                rows = db.execute(
                    "SELECT * FROM chain_execution_plans "
                    "WHERE work_id=? AND task_id=? AND generation=? "
                    "ORDER BY created_at ASC LIMIT 2",
                    (work_id, task_id, generation),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return dict(rows[0]) if len(rows) == 1 else None
