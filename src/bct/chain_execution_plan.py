"""Durable target-authored execution plans for a delivered Chain Recipe direction.

The plan is deliberately created only after its source Chain Direction has
started an exact delivery. BCT records the exact relationship and text
hash. A later SELF continuation may carry that one saved plan back to the
same target; BCT still never authors the plan or decides the next action.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from typing import Any

from bct.chain_direction import ChainDirectionLedger


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


def check_execute_plan(*, plan: dict[str, Any] | None,
                       response_text: str) -> dict[str, Any]:
    """Check the target's declared plan, revision, and progress in one response.

    This is a pure primitive: it does not select a route, write a message, or
    change durable state.  Its result is suitable for later status display and
    for the separate observation-recording primitive.
    """
    # Normalize only this parsing view. Callers retain/hash the original bytes.
    response_text = response_text.replace("\r\n", "\n")
    issues: list[str] = []
    reported_revision: int | None = None
    completed_steps: int | None = None
    total_steps: int | None = None
    if plan is None:
        issues.append("PLAN_MISSING")
    else:
        revisions = re.findall(r"(?m)^PLAN REVISION:[ \t]*(\d+)[ \t]*$", response_text)
        if not revisions or len(revisions) != len(re.findall(r"(?m)^PLAN REVISION:", response_text)):
            issues.append("PLAN_REVISION_MISMATCH")
        else:
            reported_revision = int(revisions[-1])
            if any(int(value) != int(plan.get("revision", 0)) for value in revisions):
                issues.append("PLAN_REVISION_MISMATCH")
    # A captured terminal turn can contain an earlier progress update and the
    # final answer. Select the latest declaration only when all declarations
    # describe one consistent, monotonically advancing plan.
    progress = re.findall(r"(?m)^PROGRESS:[ \t]*(\d+)[ \t]*/[ \t]*(\d+)[ \t]*[-—]", response_text)
    if not progress or len(progress) != len(re.findall(r"(?m)^PROGRESS:", response_text)):
        issues.append("PROGRESS_MISSING")
    else:
        values = [(int(done), int(total)) for done, total in progress]
        completed_steps, total_steps = values[-1]
        if any(done > total or total < 1 for done, total in values):
            issues.append("PROGRESS_MISSING")
        if any(total != total_steps for _, total in values) or any(
                later[0] < earlier[0] for earlier, later in zip(values, values[1:])):
            issues.append("PROGRESS_CONFLICT")
    return {
        "plan_id": str((plan or {}).get("plan_id") or ""),
        "reported_revision": reported_revision,
        "completed_steps": completed_steps,
        "total_steps": total_steps,
        "issues": tuple(issues),
    }


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
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_execution_plan_updates (
                    plan_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    plan_text TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    update_reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(plan_id, revision)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_execution_plan_checks (
                    work_id TEXT NOT NULL,
                    direction_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    plan_id TEXT NOT NULL,
                    reported_revision INTEGER,
                    completed_steps INTEGER,
                    total_steps INTEGER,
                    issue_codes_json TEXT NOT NULL,
                    response_sha256 TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    PRIMARY KEY(work_id, direction_id, task_id, generation)
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
        chain_started = (
            direction["decision"] == "NEW_TASK"
            and direction["chain_state"] == "CHAIN_STARTED"
            and direction["chain_task_id"] == task_id
        )
        loop_started = False
        if not chain_started and direction["decision"] == "NEW_TASK":
            from bct.loop_store import LoopStore
            loop = LoopStore(self.store).get(work_id)
            loop_started = bool(
                loop and loop["direction_id"] == direction_id
                and loop["task_id"] == task_id
                and loop["state"] in {"LOOP_STARTED", "COMPLETED"}
            )
        review_started = False
        if not (chain_started or loop_started) and direction["decision"] == "NEW_TASK":
            with self.store._readonly() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='loop_review_handoffs'").fetchone()
                if exists:
                    review = db.execute("SELECT task_id,state FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
                    review_started = bool(review and review["task_id"] == task_id
                        and review["state"] in {"DISPATCHING", "DELIVERED"}
                        and loop and loop["direction_id"] == direction_id)
        if not (chain_started or loop_started or review_started):
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
            # One Chain Direction and Task own one Execute Plan across all
            # target→same-target generations.  A generation is an observation/history value,
            # not a new plan identity.  Selecting between two plans later
            # would be an unsafe inference, so reject a second declaration.
            chain_existing = db.execute(
                "SELECT plan_id FROM chain_execution_plans "
                "WHERE work_id=? AND direction_id=? AND task_id=?",
                (work_id, direction_id, task_id),
            ).fetchone()
            if chain_existing is not None:
                raise ValueError("CHAIN_EXECUTION_PLAN_CHAIN_CONFLICT")
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
            update = db.execute(
                "SELECT * FROM chain_execution_plan_updates WHERE plan_id=? "
                "ORDER BY revision DESC LIMIT 1", (plan_id,),
            ).fetchone()
        if row is None:
            return None
        plan = dict(row)
        if update is None:
            return {**plan, "revision": 0, "update_reason": ""}
        current = dict(update)
        return {
            **plan,
            "original_plan_text": plan["plan_text"],
            "original_plan_sha256": plan["plan_sha256"],
            "plan_text": current["plan_text"],
            "plan_sha256": current["plan_sha256"],
            "revision": current["revision"],
            "update_reason": current["update_reason"],
            "updated_at": current["created_at"],
        }

    def update(self, *, plan_id: str, plan_text: str, update_reason: str) -> dict[str, Any]:
        """Append a visible revision; the initial B plan is never overwritten."""
        if not self._valid_id(plan_id):
            raise ValueError("CHAIN_EXECUTION_PLAN_ID_INVALID")
        if not isinstance(plan_text, str) or not plan_text.strip() or len(plan_text) > 12000:
            raise ValueError("CHAIN_EXECUTION_PLAN_TEXT_INVALID")
        if not isinstance(update_reason, str) or not update_reason.strip() or len(update_reason) > 4000:
            raise ValueError("CHAIN_EXECUTION_PLAN_UPDATE_REASON_INVALID")
        digest = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT plan_id FROM chain_execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None:
                raise ValueError("CHAIN_EXECUTION_PLAN_NOT_FOUND")
            prior = db.execute(
                "SELECT revision,plan_text,plan_sha256,update_reason FROM chain_execution_plan_updates "
                "WHERE plan_id=? ORDER BY revision DESC LIMIT 1", (plan_id,),
            ).fetchone()
            if prior is not None and tuple(prior[1:]) == (plan_text, digest, update_reason):
                return {**(self.get(plan_id=plan_id) or {}), "duplicate": True}
            revision = int(prior[0]) + 1 if prior is not None else 1
            db.execute(
                "INSERT INTO chain_execution_plan_updates("
                "plan_id,revision,plan_text,plan_sha256,update_reason,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (plan_id, revision, plan_text, digest, update_reason, time.time()),
            )
        return {**(self.get(plan_id=plan_id) or {}), "duplicate": False}

    def record_execute_plan_check(
            self, *, work_id: str, direction_id: str, task_id: str,
            generation: int, response_sha256: str,
            assessment: dict[str, Any]) -> dict[str, Any]:
        """Persist one observed plan/progress status without steering the Chain.

        The first exact response observed for a generation is kept as evidence.
        A conflicting later observation is reported to the caller but never
        overwrites it or blocks the continuation.
        """
        if not all(self._valid_id(value) for value in (work_id, direction_id, task_id)):
            raise ValueError("CHAIN_EXECUTION_PLAN_ID_INVALID")
        if type(generation) is not int or generation < 1:
            raise ValueError("CHAIN_EXECUTION_PLAN_GENERATION_INVALID")
        if not isinstance(response_sha256, str) or not response_sha256:
            raise ValueError("CHAIN_EXECUTION_PLAN_RESPONSE_SHA_INVALID")
        plan_id = str(assessment.get("plan_id") or "")
        if plan_id and not self._valid_id(plan_id):
            raise ValueError("CHAIN_EXECUTION_PLAN_ID_INVALID")
        issues = tuple(str(issue) for issue in assessment.get("issues", ()))
        values = (
            plan_id, assessment.get("reported_revision"),
            assessment.get("completed_steps"), assessment.get("total_steps"),
            json.dumps(issues, ensure_ascii=True, separators=(",", ":")),
            response_sha256,
        )
        key = (work_id, direction_id, task_id, generation)
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chain_execution_plan_checks "
                "WHERE work_id=? AND direction_id=? AND task_id=? AND generation=?", key,
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[column] for column in (
                    "plan_id", "reported_revision", "completed_steps", "total_steps",
                    "issue_codes_json", "response_sha256",
                ))
                if actual == values:
                    return {**dict(existing), "duplicate": True, "conflict": False}
                return {**dict(existing), "duplicate": False, "conflict": True}
            db.execute(
                "INSERT INTO chain_execution_plan_checks("
                "work_id,direction_id,task_id,generation,plan_id,reported_revision,"
                "completed_steps,total_steps,issue_codes_json,response_sha256,observed_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*key, *values, time.time()),
            )
        return {**(self.get_latest_execute_plan_check(
            work_id=work_id, direction_id=direction_id, task_id=task_id,
        ) or {}), "duplicate": False, "conflict": False}

    def get_latest_execute_plan_check(
            self, *, work_id: str, direction_id: str, task_id: str) -> dict[str, Any] | None:
        """Read the latest recorded Execute Plan check for one Chain Task."""
        return self.read_latest_execute_plan_check(
            store=self.store, work_id=work_id, direction_id=direction_id,
            task_id=task_id,
        )

    @staticmethod
    def read_latest_execute_plan_check(
            *, store, work_id: str, direction_id: str, task_id: str) -> dict[str, Any] | None:
        """Read the latest check without creating tables or other state."""
        try:
            with store._readonly() as db:
                row = db.execute(
                    "SELECT * FROM chain_execution_plan_checks "
                    "WHERE work_id=? AND direction_id=? AND task_id=? "
                    "ORDER BY generation DESC LIMIT 1",
                    (work_id, direction_id, task_id),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        if row is None:
            return None
        result = dict(row)
        result["issues"] = tuple(json.loads(result.pop("issue_codes_json")))
        return result

    @staticmethod
    def read_chain_return_summary(
            *, store, work_id: str, direction_id: str, task_id: str,
            generation: int) -> dict[str, Any]:
        """Read the plan/check evidence for one exact target return.

        This is deliberately a compact, read-only card for A's State R.  It
        does not instantiate the ledger because instantiation creates tables;
        an older Chain therefore remains an ordinary "not recorded" case.
        """
        try:
            with store._readonly() as db:
                plan = db.execute(
                    "SELECT plan_id,plan_sha256 FROM chain_execution_plans "
                    "WHERE work_id=? AND direction_id=? AND task_id=? "
                    "ORDER BY created_at ASC LIMIT 2",
                    (work_id, direction_id, task_id),
                ).fetchall()
                check = db.execute(
                    "SELECT * FROM chain_execution_plan_checks "
                    "WHERE work_id=? AND direction_id=? AND task_id=? AND generation=?",
                    (work_id, direction_id, task_id, generation),
                ).fetchone()
                update = None
                if len(plan) == 1:
                    update = db.execute(
                        "SELECT revision,plan_sha256 FROM chain_execution_plan_updates "
                        "WHERE plan_id=? ORDER BY revision DESC LIMIT 1",
                        (plan[0]["plan_id"],),
                    ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return {"status": "NOT_RECORDED"}
            raise
        if len(plan) > 1:
            return {"status": "AMBIGUOUS_PLAN"}
        check_card = None
        if check is not None:
            check_card = dict(check)
            check_card["issues"] = tuple(json.loads(check_card.pop("issue_codes_json")))
            check_card["status"] = "OK" if not check_card["issues"] else "NEEDS_ATTENTION"
        if not plan:
            return {"status": "NOT_RECORDED", "return_check": check_card}
        plan_card = {
            "plan_id": str(plan[0]["plan_id"]),
            "current_revision": int(update["revision"]) if update is not None else 0,
            "current_plan_sha256": str(update["plan_sha256"] if update is not None else plan[0]["plan_sha256"]),
        }
        return {
            "status": "RECORDED" if check_card is not None else "PLAN_WITHOUT_RETURN_CHECK",
            "plan": plan_card,
            "return_check": check_card,
        }

    @staticmethod
    def list_latest_execute_plan_checks(*, store, limit: int = 20) -> list[dict[str, Any]]:
        """Read recent Chain-plan checks for a status card; creates no tables."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("CHAIN_EXECUTION_PLAN_CHECK_LIMIT_INVALID")
        try:
            with store._readonly() as db:
                rows = db.execute(
                    "SELECT check_row.* FROM chain_execution_plan_checks AS check_row "
                    "WHERE NOT EXISTS ("
                    "SELECT 1 FROM chain_execution_plan_checks AS newer "
                    "WHERE newer.work_id=check_row.work_id "
                    "AND newer.direction_id=check_row.direction_id "
                    "AND newer.task_id=check_row.task_id "
                    "AND newer.generation>check_row.generation"
                    ") ORDER BY check_row.observed_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                checks: list[dict[str, Any]] = []
                for row in rows:
                    check = dict(row)
                    check["issues"] = tuple(json.loads(check.pop("issue_codes_json")))
                    plan_id = str(check.get("plan_id") or "")
                    plan = db.execute(
                        "SELECT plan_sha256 FROM chain_execution_plans WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone() if plan_id else None
                    update = db.execute(
                        "SELECT revision,plan_sha256 FROM chain_execution_plan_updates "
                        "WHERE plan_id=? ORDER BY revision DESC LIMIT 1",
                        (plan_id,),
                    ).fetchone() if plan_id else None
                    check["current_plan_revision"] = int(update["revision"]) if update else (0 if plan else None)
                    check["current_plan_sha256"] = (
                        str(update["plan_sha256"]) if update else
                        (str(plan["plan_sha256"]) if plan else "")
                    )
                    check["status"] = "OK" if not check["issues"] else "NEEDS_ATTENTION"
                    checks.append(check)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return checks

    @staticmethod
    def get_for_chain(*, store, work_id: str, direction_id: str,
                      task_id: str) -> dict[str, Any] | None:
        """Return the one plan for a Chain Direction and Task.

        Generations are retained on the initial plan for audit/history, but a
        same-target continuation must carry the same plan into later generations.
        Legacy data with more than one candidate remains ambiguous: no plan is
        selected automatically.
        """
        try:
            with store._readonly() as db:
                rows = db.execute(
                    "SELECT * FROM chain_execution_plans "
                    "WHERE work_id=? AND direction_id=? AND task_id=? "
                    "ORDER BY created_at ASC LIMIT 2",
                    (work_id, direction_id, task_id),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return ChainExecutionPlanLedger(store).get(plan_id=rows[0]["plan_id"]) if len(rows) == 1 else None

    @staticmethod
    def get_for_chain_turn(*, store, work_id: str, task_id: str,
                           generation: int) -> dict[str, Any] | None:
        """Legacy exact-turn lookup; new continuations use :meth:`get_for_chain`."""
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
        return ChainExecutionPlanLedger(store).get(plan_id=rows[0]["plan_id"]) if len(rows) == 1 else None
