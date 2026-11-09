"""Read-only Chain Recipe caller preflight and optional output-format instruction.

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
    "[BCT Chain Recipe continuation output contract — requested by the caller]\n"
    "Finish with exactly one explicit continuation directive on your final line:\n"
    "NEXT TASK — SELF: <specific next action you independently chose>, or\n"
    "NEXT TASK — MANAGER: <specific review/acceptance action for A>.\n"
    "Choose SELF only when further work is actually needed and authorized. "
    "Use MANAGER when the task is complete or needs A's decision. "
    "Never invent a task or route. If you cannot determine an actionable next "
    "instruction, state that clearly rather than fabricating a marker. "
    "BCT will preserve the response for Manager review without sending again."
)


def execute_plan_progress_suffix(*, work_id: str, direction_id: str, task_id: str,
                                 generation: int) -> str:
    """Give the selected target the initial-plan and per-response contract.

    This is an instruction footer only. BCT neither writes the target's plan nor treats
    a progress fraction as proof that work was completed.
    """
    if not all(isinstance(value, str) and value for value in (work_id, direction_id, task_id)):
        raise ValueError("CHAIN_EXECUTION_PLAN_CONTEXT_INVALID")
    if type(generation) is not int or generation < 1:
        raise ValueError("CHAIN_EXECUTION_PLAN_CONTEXT_INVALID")
    return (
        "[BCT Execute Plan and progress contract — requested by A]\n"
        "Before performing the task, write one concrete Execute Plan and save it once with:\n"
        f'`bct_set_execute_plan(work_id="{work_id}", direction_id="{direction_id}", '
        f'task_id="{task_id}", generation={generation}, plan_text="...")`\n'
        "Each plan revision must use numbered bounded steps and its own total. In every response, include "
        "`PLAN REVISION: <current revision>` and "
        "`PROGRESS: <completed>/<total> — completed evidence; next step`.\n"
        "If the remaining plan needs adjustment, call `bct_update_execute_plan` with the returned plan_id, "
        "the revised remaining plan, and the reason; the initial saved plan stays in history. Also state "
        "`PLAN UPDATE: <reason and revised remaining steps>`. Reaching `<total>/<total>` does not "
        "automatically return to A: if the original Direction is still unfinished, revise this same plan "
        "and use NEXT TASK — SELF for its next bounded phase. Return with NEXT TASK — MANAGER only "
        "when the task is complete, unsafe, blocked, or needs A's decision."
    )


def check_chain_work(work: Any, *, principal_id: str) -> dict[str, Any]:
    """Observe Work state for Chain Recipe; this never authorizes or blocks a send."""
    if str(getattr(work, "owner_principal_id", "")) != principal_id:
        return {
            "status": "OBSERVED",
            "work_access": "MISMATCH",
            "reason": "CHAIN_MESSAGE_WORK_OWNER_MISMATCH",
        }
    if str(getattr(work, "state", "")) != "ACTIVE":
        return {
            "status": "OBSERVED",
            "work_access": "INACTIVE",
            "reason": "CHAIN_MESSAGE_WORK_NOT_ACTIVE",
        }
    actions = getattr(work, "actions", ())
    if not any(capability_matches(action, "browser") for action in actions):
        return {
            "status": "OBSERVED",
            "work_access": "BROWSER_ACTION_MISSING",
            "reason": "CHAIN_MESSAGE_BROWSER_ACTION_REQUIRED",
            "required_action": "browser",
        }
    return {
        "status": "OBSERVED",
        "work_access": "MATCHED",
        "required_action": "browser",
    }


def prepare_chain_instruction(
    instruction: str, *, output_contract: str = OUTPUT_CONTRACT_NONE,
    execution_plan_context: dict[str, Any] | None = None,
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
    plan_contract_appended = execution_plan_context is not None
    if execution_plan_context is not None:
        outgoing += "\n\n" + execute_plan_progress_suffix(**execution_plan_context)
    if len(outgoing) > 12000:
        raise ValueError("CHAIN_MESSAGE_OUTPUT_CONTRACT_TOO_LONG")
    return {
        "instruction": outgoing,
        "instruction_sha256": hashlib.sha256(outgoing.encode("utf-8")).hexdigest(),
        "instruction_characters": len(outgoing),
        "output_contract": output_contract,
        "output_contract_appended": output_contract == OUTPUT_CONTRACT_EXPLICIT,
        "execution_plan_contract_appended": plan_contract_appended,
    }
