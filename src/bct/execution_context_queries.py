"""Read-only durable execution-context command logic."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .send_delayed_message import DurableWatchLedger


async def read_execution_context(
    store: Any,
    *,
    work_id: str,
    task_id: str,
    generation: int = 0,
) -> dict[str, Any]:
    """Return one fenced continuation context without creating or waking work."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id) or generation < 0:
        return {"status": "INVALID_REQUEST", "reason": "EXECUTION_CONTEXT_INPUT_INVALID"}
    try:
        work = await asyncio.to_thread(store.get_work, work_id)
        context = await asyncio.to_thread(
            DurableWatchLedger(store).read_execution_context,
            task_id=task_id,
            generation=None if generation == 0 else generation,
        )
    except KeyError:
        return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
    if context is None:
        return {"status": "NOT_FOUND", "task_id": task_id, "generation": generation or None}
    binding = context.get("binding") or {}
    if (
        binding.get("work_id") != work.work_id
        or binding.get("principal_id") != work.owner_principal_id
        or binding.get("assignment_epoch") != work.assignment_epoch
    ):
        return {"status": "NOT_FOUND", "task_id": task_id, "generation": context["generation"]}
    return {"status": "OK", "execution": context}
