"""Durable Work creation, scope update, and trusted successor handoff."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterable

from .core.models import Work
from .recipes.runtime import work_dict


async def create_or_update_work(
    store: Any, *, principal_id: str, capabilities: Iterable[str], work_id: str,
    request_summary: str, roots: list[str], actions: list[str],
) -> dict[str, Any]:
    requested_actions = frozenset(actions)
    allowed = frozenset(capabilities)
    if not work_id or not request_summary or not roots:
        raise ValueError("WORK_FIELDS_REQUIRED")
    if not requested_actions or not requested_actions.issubset(allowed):
        raise ValueError("WORK_ACTION_INVALID")
    normalized_roots = tuple(str(Path(root).resolve()) for root in roots)
    if any(not Path(root).is_absolute() for root in roots):
        raise ValueError("WORK_ROOT_ABSOLUTE_REQUIRED")
    expected = Work(work_id, request_summary, normalized_roots, requested_actions, principal_id)
    try:
        current = await asyncio.to_thread(store.get_work, work_id)
    except KeyError:
        current = await asyncio.to_thread(store.create_work, expected)
        duplicate = False
        updated = False
    else:
        if current.owner_principal_id != principal_id:
            current = await asyncio.to_thread(
                store.handoff_work, work_id=work_id,
                old_principal_id=current.owner_principal_id, new_principal_id=principal_id,
                expected_epoch=current.assignment_epoch,
            )
        current, updated = await asyncio.to_thread(
            store.update_work_scope, work_id=work_id, principal_id=principal_id,
            expected_epoch=current.assignment_epoch, request_summary=request_summary,
            roots=normalized_roots, actions=requested_actions,
        )
        duplicate = not updated
    return {"work": work_dict(current), "duplicate": duplicate, "updated": updated}
