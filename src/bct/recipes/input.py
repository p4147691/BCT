"""Input R: exact request and Manager-return evidence."""
from __future__ import annotations

import asyncio
import re

from typing import Any

from bct.core.models import Work

from .runtime import ChainRecipeRuntime

async def input_recipe(runtime: ChainRecipeRuntime,
    *,
    work_id: str,
    source_kind: str,
    source_task_id: str,
    source_generation: int,
    source_text: str,
    allow_unbound_user: bool,
    require_source_text: bool,
) -> dict[str, Any]:
    """Run the read-only input-confirmation part of the Chain Recipe.

    This deliberately does not observe runtime state, create a Direction,
    or send a message.  A returned report is accepted only when its exact
    delayed-watch evidence belongs to the supplied Work.
    """
    if source_kind not in {"USER", "MANAGER_RETURN"}:
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_STATE_INVALID"}
    if require_source_text and source_kind == "USER" and (
        not source_text.strip() or len(source_text) > 12000
    ):
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_SOURCE_TEXT_REQUIRED"}

    work = None
    if not (allow_unbound_user and source_kind == "USER" and not work_id):
        try:
            work = await asyncio.to_thread(runtime.bct.store.get_work, work_id)
        except KeyError:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        if work.owner_principal_id != runtime.principal.principal_id:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}

    result_sha = ""
    context = None
    if source_kind == "MANAGER_RETURN":
        # A return cannot be unbound: its Work, Task, generation, and
        # durable response hash are the evidence that it is a real BA/CA
        # return rather than caller-supplied prose.
        if work is None:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_RETURN_NOT_EXACT"}
        from bct.send_delayed_message import DurableWatchLedger
        delayed_ledger = DurableWatchLedger(runtime.bct.store)
        context = await asyncio.to_thread(
            delayed_ledger.read_execution_context,
            task_id=source_task_id,
            generation=source_generation,
        )
        binding = (context or {}).get("binding") or {}
        prior = (context or {}).get("decision") or {}
        if (context is not None and binding.get("work_id") == work.work_id
                and binding.get("principal_id") == work.owner_principal_id
                and binding.get("assignment_epoch") == work.assignment_epoch
                and prior.get("route") == "MANAGER"):
            result_sha = str(prior.get("response_sha256") or "")
        else:
            row = await asyncio.to_thread(
                delayed_ledger.get, source_task_id, source_generation,
            )
            import json
            try:
                legacy = json.loads(str((row or {}).get("context_json") or "{}"))
            except ValueError:
                legacy = {}
            result_sha = str(legacy.get("observed_response_sha") or "")
            if (not row or row.get("state") != "RETURNED_TO_MANAGER"
                    or legacy.get("work_id") != work.work_id
                    or legacy.get("principal_id") != work.owner_principal_id
                    or legacy.get("assignment_epoch") != work.assignment_epoch
                    or not re.fullmatch(r"[0-9a-f]{64}", result_sha)):
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_RETURN_NOT_EXACT"}
    return {
        "status": "OK", "work": work, "source_return": context,
        "source_kind": source_kind, "source_task_id": source_task_id,
        "source_generation": source_generation,
        "source_result_sha256": result_sha,
    }


def manager_return_chain_link_recipe(
    *, source_kind: str, work: Work | None, source_return: dict[str, Any] | None,
) -> dict[str, Any]:
    """Describe the exact parent link carried by one Manager return.

    A Manager return is already bound to its source Task/generation by
    Input R.  When that Task was sent through a declared Direction, retain
    that Direction as the parent of the next Manager-authored Direction.
    This is relationship evidence, not a decision about what A sends next.
    """
    if source_kind != "MANAGER_RETURN":
        return {"status": "NOT_APPLICABLE"}
    binding = (source_return or {}).get("binding") or {}
    parent_direction_id = str(binding.get("chain_direction_id") or "")
    if not parent_direction_id:
        return {
            "status": "NOT_DECLARED",
            "reason": "The exact return has no declared Chain Direction to link.",
        }
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", parent_direction_id):
        return {
            "status": "INVALID_REQUEST",
            "reason": "CHAIN_RETURN_PARENT_DIRECTION_INVALID",
        }
    if work is None or binding.get("work_id") != work.work_id:
        return {
            "status": "INVALID_REQUEST",
            "reason": "CHAIN_RETURN_PARENT_WORK_MISMATCH",
        }
    return {
        "status": "BOUND",
        "parent_direction_id": parent_direction_id,
        "parent_work_id": work.work_id,
        "parent_step_id": "MANAGER_RETURN",
        "default_branch_kind": "RESUME",
        "reason": "The next Direction is linked to the exact Task/generation return observed by Input R.",
    }


def manager_return_save_context(
    *, return_chain_link: dict[str, Any], parent_direction_id: str,
    parent_step_id: str, branch_kind: str, branch_reason: str,
    branch_request_id: str,
) -> dict[str, Any]:
    """Resolve one save's parent fields without letting a return drift."""
    if return_chain_link.get("status") != "BOUND" or branch_request_id:
        return {
            "status": "OK", "parent_direction_id": parent_direction_id,
            "parent_step_id": parent_step_id, "branch_kind": branch_kind,
            "branch_reason": branch_reason,
        }
    expected_parent = str(return_chain_link["parent_direction_id"])
    expected_step = str(return_chain_link["parent_step_id"])
    if parent_direction_id and parent_direction_id != expected_parent:
        return {
            "status": "INVALID_REQUEST",
            "reason": "CHAIN_RETURN_PARENT_DIRECTION_MISMATCH",
            "expected_parent_direction_id": expected_parent,
        }
    if parent_step_id and parent_step_id != expected_step:
        return {
            "status": "INVALID_REQUEST",
            "reason": "CHAIN_RETURN_PARENT_STEP_MISMATCH",
            "expected_parent_step_id": expected_step,
        }
    return {
        "status": "OK",
        "parent_direction_id": expected_parent,
        "parent_step_id": expected_step,
        # PRIMARY describes a new root.  A bound Manager return is always
        # a continuation unless A explicitly classifies its next child.
        "branch_kind": "RESUME" if branch_kind == "PRIMARY" else branch_kind,
        "branch_reason": branch_reason or str(return_chain_link["reason"]),
    }
