"""Apply Conversation Network R through the authorized operation gateway."""
from __future__ import annotations

import asyncio
import re

from typing import Any

from bct.core.capabilities import capability_matches
from bct.core.models import PreconditionError, Work

from .runtime import ChainRecipeRuntime

async def set_conversation_network(runtime: ChainRecipeRuntime,
    work_id: str, operation_id: str, arguments: dict[str, Any],
    approval_ref: str | None = None,
) -> dict[str, Any]:
    if arguments.get("operation") not in {"project-upsert", "membership-assign", "role-patch", "set-node-info", "node-info-set", "network-name-set"}:
        return {"status": "INVALID_REQUEST", "reason": "NETWORK_SET_OPERATION_INVALID"}
    return await runtime.make_executor("conversation_network_update")(
        work_id, operation_id, arguments, approval_ref
    )


def validate_conversation_network_updates(runtime: ChainRecipeRuntime, *, work: Work, updates: list[Any]) -> dict[str, Any]:
    """Validate every saved conversation-network change before any one is applied."""
    from bct.features.conversation_network import ConversationNetworkUpdateFeature
    try:
        for arguments in updates:
            if not isinstance(arguments, dict):
                raise ValueError("DIRECTION_NETWORK_UPDATE_INVALID")
            if arguments.get("operation") in {"set-node-info", "node-info-set"} and (
                    "expected_scope_id" not in arguments
                    or not re.fullmatch(r"[0-9a-f]{64}", str(arguments.get("expected_role_tags_sha256", "")))):
                raise ValueError("DIRECTION_NETWORK_OBSERVATION_REQUIRED")
            ConversationNetworkUpdateFeature(runtime.bct.store).prepare(work=work, arguments=arguments)
    except (ValueError, PreconditionError) as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    return {"status": "VALID"}


async def apply_conversation_network_recipe(runtime: ChainRecipeRuntime,
    *, direction: dict[str, Any], assessment: dict[str, Any], work: Work,
    targets: list[tuple[int, dict[str, Any]]], action: str,
) -> dict[str, Any]:
    """Apply saved network metadata, then reacquire only A's return route.

    Target routes are deliberately resolved one at a time in Send Direction
    R.  A disappeared target must not prevent an unrelated declared target
    from receiving its own exact message.
    """
    import hashlib
    from bct.chain_direction import resolve_direction_network, resolve_direction_target

    updates = assessment.get("network_updates", [])
    updates_check = validate_conversation_network_updates(runtime, work=work, updates=updates)
    if updates_check["status"] != "VALID":
        return updates_check
    if updates and not any(capability_matches(item, "conversation_network_update") for item in work.actions):
        return {"status": "BLOCKED", "reason": "DIRECTION_NETWORK_ACTION_REQUIRED"}
    before = await asyncio.to_thread(runtime.status_provider)
    try:
        resolve_direction_target(
            snapshot=before, conversation_key=assessment["manager_conversation_key"],
        )
    except ValueError as exc:
        return {
            "status": "NETWORK_PREPARATION_REQUIRED", "reason": str(exc),
            "stage": "BEFORE_NETWORK_EFFECTS", "network_results": [],
            "network_preparation_applied": False, "all_targets_started": False,
            "direction_id": direction["direction_id"],
        }
    results = []
    for index, arguments in enumerate(updates, 1):
        if action == "preflight":
            continue
        operation_id = (
            "direction-" + hashlib.sha256(direction["direction_id"].encode()).hexdigest()[:24]
            + f"-network-{index}"
        )
        result = await set_conversation_network(runtime, work.work_id, operation_id, arguments)
        results.append(result)
        if result.get("outcome") != "APPLIED":
            return {
                "status": "NETWORK_PREPARATION_INCOMPLETE", "network_results": results,
                "stage": "NETWORK_EFFECTS",
                "network_preparation_applied": any(item.get("outcome") == "APPLIED" for item in results),
                "all_targets_started": False, "reason": "REVIEW_ORIGINAL_RECEIPT",
                "direction_id": direction["direction_id"],
            }
    snapshot = await asyncio.to_thread(runtime.status_provider)
    try:
        origin, resolved = resolve_direction_network(
            snapshot=snapshot, assessment=assessment, targets=[],
        )
    except ValueError as exc:
        return {
            "status": "NETWORK_PREPARATION_REQUIRED", "reason": str(exc),
            "stage": "AFTER_NETWORK_EFFECTS" if results else "READINESS",
            "network_preparation_applied": bool(results), "all_targets_started": False,
            "next_tool": "bct_set_conversation_network", "network_results": results,
            "network_updates": updates, "direction_id": direction["direction_id"],
            "instructions_for_a": "기록된 판단에 따라 기존 생성·복구·대화망 설정 부품으로 준비하고 같은 Direction을 다시 확인한다.",
        }
    return {
        "status": "READY", "origin": origin, "resolved": resolved,
        "network_updates": updates, "network_results": results,
        "effects": "NONE_READ_ONLY" if action == "preflight" else "APPLIED_OR_NONE",
    }
