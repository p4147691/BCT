"""Public MCP command handlers for durable Chain Execute Plans.

The MCP server owns tool registration; this module owns the ledger-facing
behaviour so the public handlers remain thin entry points.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from .chain_execution_plan import ChainExecutionPlanLedger


class ExecutionPlanCommands:
    """Preserve the public Execute Plan command contracts outside MCP wiring."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def _ledger(self) -> ChainExecutionPlanLedger:
        return ChainExecutionPlanLedger(self._store)

    async def set(
        self,
        *,
        work_id: str,
        direction_id: str,
        task_id: str,
        plan_text: str,
        generation: int = 1,
        plan_id: str = "",
    ) -> dict[str, Any]:
        if not plan_id:
            plan_id = "chain-execution-plan-" + uuid.uuid4().hex[:18]
        try:
            plan = await asyncio.to_thread(
                self._ledger().save,
                plan_id=plan_id,
                work_id=work_id,
                direction_id=direction_id,
                task_id=task_id,
                generation=generation,
                plan_text=plan_text,
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "chain_execution_plan": plan}

    async def update(
        self,
        *,
        plan_id: str,
        plan_text: str,
        update_reason: str,
        work_id: str = "",
        task_id: str = "",
        generation: int | None = None,
    ) -> dict[str, Any]:
        ledger = self._ledger()
        existing = await asyncio.to_thread(ledger.get, plan_id=plan_id)
        if existing is None:
            return {"status": "NOT_FOUND", "reason": "CHAIN_EXECUTION_PLAN_NOT_FOUND"}
        plan = await asyncio.to_thread(
            ledger.update,
            plan_id=plan_id,
            plan_text=plan_text,
            update_reason=update_reason,
        )
        supplied = {"work_id": work_id, "task_id": task_id, "generation": generation}
        recorded = {key: existing[key] for key in supplied}
        mismatched = [
            key for key, value in supplied.items()
            if value not in {"", None} and value != recorded[key]
        ]
        return {
            "status": "OK",
            "chain_execution_plan": plan,
            "continuity": "CONTEXT_CHANGED" if mismatched else "CONTINUED",
            "context_mismatches": mismatched,
        }

    async def get(self, *, plan_id: str, work_id: str = "") -> dict[str, Any]:
        plan = await asyncio.to_thread(self._ledger().get, plan_id=plan_id)
        if plan is None:
            return {"status": "NOT_FOUND", "plan_id": plan_id}
        return {
            "status": "OK",
            "chain_execution_plan": plan,
            "continuity": "CONTEXT_CHANGED" if work_id and work_id != plan["work_id"] else "CONTINUED",
        }
