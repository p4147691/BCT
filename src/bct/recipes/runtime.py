"""Explicit runtime ports shared by Chain recipes and their MCP adapter.

The adapter supplies the authenticated capability executor. Recipes do not
create a second execution path, own mutable global runtime, or register tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from bct.core.models import Principal, Work
CapabilityExecutor = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


@dataclass(frozen=True)
class ChainRecipeRuntime:
    bct: Any
    principal: Principal
    status_provider: Callable[[], dict[str, Any]] | None
    make_executor: Callable[[str], CapabilityExecutor]


def work_dict(work: Work) -> dict[str, Any]:
    return {
        "work_id": work.work_id,
        "request_summary": work.request_summary,
        "roots": list(work.roots),
        "actions": sorted(work.actions),
        "owner_principal_id": work.owner_principal_id,
        "assignment_epoch": work.assignment_epoch,
        "state": work.state,
    }
