"""Read-only Chain Message caller preflight and optional output-format instruction.

This component neither expands a Work nor sends, prearms, or decides a NEXT TASK
route. Exact RCC identity and durable Operation receipt gates remain elsewhere.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .core.capabilities import capability_matches


OUTPUT_CONTRACT_NONE = "none"
OUTPUT_CONTRACT_EXPLICIT = "explicit-next-task-v1"
OUTPUT_CONTRACTS = frozenset({OUTPUT_CONTRACT_NONE, OUTPUT_CONTRACT_EXPLICIT})

# This is a request to the worker, NOT a synthesized continuation decision.
# A response without a complete explicit marker must still end in Manager review.
EXPLICIT_NEXT_TASK_SUFFIX = (
    "[BCT Chain Message continuation output contract — requested by the caller]\n"
    "Finish with exactly one explicit continuation directive on your final line:\n"
    "NEXT TASK — SELF: <specific next action you independently chose>, or\n"
    "NEXT TASK — MANAGER: <specific review/acceptance action for A>.\n"
    "Choose SELF only when further work is actually needed and authorized. "
    "Use MANAGER when the task is complete or needs A's decision. "
    "Never invent a task or route. If you cannot determine an actionable next "
    "instruction, state that clearly rather than fabricating a marker. "
    "BCT will preserve the response for Manager review without sending again."
)


def check_chain_work(work: Any, *, principal_id: str) -> dict[str, Any]:
    """Check existing Work authority without adding or assuming capabilities."""
    if str(getattr(work, "owner_principal_id", "")) != principal_id:
        return {"status": "BLOCKED", "reason": "CHAIN_MESSAGE_WORK_OWNER_MISMATCH"}
    if str(getattr(work, "state", "")) != "ACTIVE":
        return {"status": "BLOCKED", "reason": "CHAIN_MESSAGE_WORK_NOT_ACTIVE"}
    actions = getattr(work, "actions", ())
    if not any(capability_matches(action, "browser") for action in actions):
        return {
            "status": "BLOCKED",
            "reason": "CHAIN_MESSAGE_BROWSER_ACTION_REQUIRED",
            "required_action": "browser",
            "guidance": (
                "Use an already authorized ACTIVE Work with browser action "
                "or request a separately approved new Work. "
                "The existing Work is never upgraded automatically."
            ),
        }
    return {"status": "READY", "required_action": "browser"}


def prepare_chain_instruction(
    instruction: str, *, output_contract: str = OUTPUT_CONTRACT_NONE
) -> dict[str, Any]:
    """Return the exact authorized outgoing bytes or an explicit validation error.

    Default mode retains the exact original string. The opt-in footer is added
    to both prearm source proof and single send, never only at dispatch.
    """
    if output_contract not in OUTPUT_CONTRACTS:
        raise ValueError("CHAIN_MESSAGE_OUTPUT_CONTRACT_INVALID")
    if not isinstance(instruction, str) or not instruction or len(instruction) > 12000:
        raise ValueError("CHAIN_MESSAGE_INPUT_INVALID")
    outgoing = instruction
    if output_contract == OUTPUT_CONTRACT_EXPLICIT:
        outgoing += "\n\n" + EXPLICIT_NEXT_TASK_SUFFIX
    if len(outgoing) > 12000:
        raise ValueError("CHAIN_MESSAGE_OUTPUT_CONTRACT_TOO_LONG")
    return {
        "instruction": outgoing,
        "instruction_sha256": hashlib.sha256(outgoing.encode("utf-8")).hexdigest(),
        "instruction_characters": len(outgoing),
        "output_contract": output_contract,
        "output_contract_appended": output_contract == OUTPUT_CONTRACT_EXPLICIT,
    }
