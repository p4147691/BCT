"""Recover Node R and shared exact-node observation/send fences."""
from __future__ import annotations

import asyncio
import hashlib

from typing import Any

from bct.core.models import Work
from bct.status_views import status_view

from .runtime import ChainRecipeRuntime
from .state import state_recipe

def _assert_node_send_allowed(runtime: ChainRecipeRuntime, work_id: str, conversation_key: str) -> None:
    # Transport-only contract tests do not construct a Store. The real
    # runtime always does and therefore always enforces this durable fence.
    if not conversation_key or not hasattr(runtime.bct, "store"):
        return
    from bct.node_recovery import NodeRecoveryLedger
    NodeRecoveryLedger(runtime.bct.store).assert_send_allowed(
        work_id=work_id, conversation_key=conversation_key,
    )


def _current_node_evidence(runtime: ChainRecipeRuntime, conversation_key: str) -> dict[str, Any]:
    if runtime.status_provider is None:
        raise ValueError("NODE_RECOVERY_STATUS_UNAVAILABLE")
    from bct.node_recovery import observe_node
    return observe_node(status_view(runtime.status_provider(), "node"), conversation_key)


async def recover_node_recipe(runtime: ChainRecipeRuntime,
    *, direction: dict[str, Any], assessment: dict[str, Any], work: Work,
) -> dict[str, Any]:
    """Run the declared Recover Node R boundary without choosing a repair.

    This composes Check Node R with a fresh State R read.  Pause, Replace,
    and Reset remain separately chosen recipes because they can affect an
    existing watch, a successor conversation, or a browser tab.
    """
    recovery = assessment.get("node_recovery")
    if not recovery:
        return {"status": "SKIPPED", "reason": "NODE_RECOVERY_NOT_DECLARED"}
    if runtime.status_provider is None:
        return {"status": "UNAVAILABLE", "reason": "NODE_RECOVERY_STATUS_UNAVAILABLE"}
    from bct.node_recovery import NodeRecoveryLedger
    key = str(recovery["conversation_key"])
    case_id = "node-recovery-" + hashlib.sha256(
        (str(direction["direction_id"]) + ":" + key).encode("utf-8")
    ).hexdigest()[:24]
    try:
        checked = await asyncio.to_thread(
            NodeRecoveryLedger(runtime.bct.store).check,
            work=work, case_id=case_id, task_id="", conversation_key=key,
            evidence=_current_node_evidence(runtime, key), kind="CHECK",
        )
    except ValueError as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    refreshed_state = await state_recipe(runtime,
        project="", source_kind="USER", work=work, source_return=None,
    )
    return {
        "status": "CHECKED",
        "recipe": {"name": "recover_node_recipe", "kind": "partial_recipe"},
        "recover_node": checked,
        "state": refreshed_state,
        "does_not": ["pause", "replace", "reset", "send"],
        "next": "Continue to Prepare Send Direction R; choose Pause/Replace/Reset explicitly if needed.",
    }
