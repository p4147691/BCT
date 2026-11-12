"""Ledger-backed public Chain Direction and branch command handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from .chain_direction import ChainBranchRequestLedger, ChainDirectionLedger


class ChainDirectionCommands:
    """Keep direction/branch persistence behaviour outside MCP registration."""

    def __init__(self, store: Any, *, principal_id: str) -> None:
        self._store = store
        self._principal_id = principal_id

    async def _work(self, work_id: str, *, invalid_as_missing: bool = False) -> Any | None:
        try:
            work = await asyncio.to_thread(self._store.get_work, work_id)
        except KeyError:
            return None
        except ValueError:
            if invalid_as_missing:
                return None
            raise
        return work if work.owner_principal_id == self._principal_id else None

    async def get_direction(self, *, work_id: str, direction_id: str) -> dict[str, Any]:
        work = await self._work(work_id)
        if work is None:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        direction = await asyncio.to_thread(
            ChainDirectionLedger(self._store).get,
            direction_id=direction_id,
        )
        if direction is None or direction.get("work_id") != work.work_id:
            return {"status": "NOT_FOUND", "direction_id": direction_id}
        return {"status": "OK", "chain_direction": direction}

    async def branch(
        self,
        *,
        action: str = "tree",
        work_id: str = "",
        request_id: str = "",
        parent_work_id: str = "",
        parent_direction_id: str = "",
        parent_step_id: str = "",
        parent_task_id: str = "",
        parent_generation: int = 1,
        kind: str = "DIAGNOSIS",
        reason: str = "",
        exact_refs: dict[str, Any] | None = None,
        required: bool = True,
        state: str = "",
        next_safe_step: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action not in {"request", "report", "tree"}:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_BRANCH_ACTION_INVALID"}
        work = await self._work(work_id, invalid_as_missing=True)
        if work is None:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        if action == "tree":
            tree = await asyncio.to_thread(
                ChainBranchRequestLedger.tree,
                store=self._store,
                root_work_id=work.work_id,
            )
            return {"status": "OK", "effects": "NONE_READ_ONLY", "chain_tree": tree}
        ledger = ChainBranchRequestLedger(self._store)
        try:
            if action == "request":
                branch = await asyncio.to_thread(
                    ledger.request,
                    request_id=request_id,
                    root_work_id=work.work_id,
                    parent_work_id=parent_work_id or work.work_id,
                    parent_direction_id=parent_direction_id,
                    parent_step_id=parent_step_id,
                    parent_task_id=parent_task_id,
                    parent_generation=parent_generation,
                    kind=kind,
                    reason=reason,
                    exact_refs=exact_refs,
                    required=required,
                )
                return {
                    "status": "WAITING_INPUT",
                    "branch_request": branch,
                    "next_safe_step": "MANAGER_REVIEW_BRANCH_REQUEST",
                    "does_not": ["create_child_direction", "send_message", "create_operation"],
                }
            branch = await asyncio.to_thread(
                ledger.report,
                request_id=request_id,
                state=state,
                reason=reason,
                next_safe_step=next_safe_step,
                evidence=evidence,
            )
            return {
                "status": branch["state"],
                "branch_request": branch,
                "next_safe_step": branch["next_safe_step"],
            }
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
