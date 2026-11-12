"""Owned operation and GitHub inbox queries without MCP registration."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Callable


async def read_operation(
    store: Any, *, principal_id: str, work_id: str, operation_id: str,
    wait_seconds: float = 0, trace_stage: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read one exact receipt, waiting only within the public bounded window."""
    if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 25:
        raise ValueError("OPERATION_WAIT_INVALID")
    started_ns = time.perf_counter_ns()
    wait_ms = 0.0
    deadline = time.monotonic() + wait_seconds
    while True:
        result = await asyncio.to_thread(
            store.get_operation_for, operation_id=operation_id, work_id=work_id,
            principal_id=principal_id,
        )
        if result.state.value == "FINISHED" or time.monotonic() >= deadline:
            value = result.as_dict()
            steps = await asyncio.to_thread(
                store.get_operation_steps_for, operation_id=operation_id,
                work_id=work_id, principal_id=principal_id,
            )
            if steps:
                value["step_journal"] = steps
            effect_journal = await asyncio.to_thread(
                store.get_effect_journal_for, operation_id=operation_id,
                work_id=work_id, principal_id=principal_id,
            )
            if effect_journal:
                value["effect_journal"] = effect_journal
            if trace_stage is not None:
                handler_ms = (time.perf_counter_ns() - started_ns) / 1e6
                trace_stage(
                    "handler_done", tool_kind="operation_get", handler_ms=handler_ms,
                    wait_ms=wait_ms, execution_ms=max(0.0, handler_ms - wait_ms),
                )
            return value
        sleep_start = time.perf_counter_ns()
        await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
        wait_ms += (time.perf_counter_ns() - sleep_start) / 1e6


async def read_github_inbox(
    store: Any, *, principal_id: str, initiator_node_id: str = "", work_id: str = "",
    acknowledge: bool = False, limit: int = 80,
) -> dict[str, Any]:
    """Read the caller-owned Work inbox; acknowledgement is its existing ledger action."""
    if not work_id:
        raise ValueError("INBOX_WORK_REQUIRED")
    work = await asyncio.to_thread(store.get_work, work_id)
    if work.owner_principal_id != principal_id:
        raise PermissionError("INBOX_WORK_ACCESS_DENIED")
    rows = await asyncio.to_thread(
        store.get_github_run_inbox, node_id=initiator_node_id, work_id=work_id,
        acknowledge=acknowledge, limit=limit,
    )
    return {"items": rows, "wake": "AUTO_WAKE_NOT_CONFIGURED"}
