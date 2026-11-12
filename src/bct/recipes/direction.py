"""Write/Save Direction R: preparation, validation, and durable records."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid

from typing import Any

from bct.core.models import PreconditionError, Work

from .input import input_recipe, manager_return_chain_link_recipe
from .runtime import ChainRecipeRuntime
from .state import state_recipe

def chain_recipe_entry_context_id(
    *, confirmed_input: dict[str, Any], state: dict[str, Any],
    report_target_conversation_key: str, return_chain_link: dict[str, Any],
) -> str:
    """Return a non-durable identity for one Manager-visible recipe entry.

    This is deliberately a continuity handle, not an authority token.  It
    is derived only from the exact input binding and the existing current
    work tree.  It lets Save Direction R reject a bypass or a changed
    branch/receipt state without introducing a second relationship store.
    """
    work = confirmed_input.get("work")
    payload = {
        "version": 1,
        "work_id": work.work_id if isinstance(work, Work) else "",
        "source_kind": confirmed_input.get("source_kind", ""),
        "source_task_id": confirmed_input.get("source_task_id", ""),
        "source_generation": confirmed_input.get("source_generation", 0),
        "source_result_sha256": confirmed_input.get("source_result_sha256", ""),
        "report_target_conversation_key": report_target_conversation_key,
        "return_chain_link": return_chain_link,
        "chain_work_context": state.get("chain_work_context", {}),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return "entry-" + hashlib.sha256(encoded).hexdigest()[:24]


async def prepare_direction_recipe(runtime: ChainRecipeRuntime,
    *, source_text: str, source_kind: str, work_id: str, source_task_id: str,
    source_generation: int, project: str, report_target_conversation_key: str = "",
) -> dict[str, Any]:
    """Compose Input R and State R before A writes a Direction."""
    confirmed = await input_recipe(runtime,
        work_id=work_id, source_kind=source_kind,
        source_task_id=source_task_id, source_generation=source_generation,
        source_text=source_text, allow_unbound_user=True, require_source_text=True,
    )
    if confirmed["status"] != "OK":
        return confirmed
    state = await state_recipe(runtime,
        project=project, source_kind=source_kind, work=confirmed["work"],
        source_return=confirmed["source_return"],
        report_target_conversation_key=report_target_conversation_key,
    )
    if state["status"] != "OK":
        return state
    return_chain_link = manager_return_chain_link_recipe(
        source_kind=source_kind, work=confirmed["work"], source_return=confirmed["source_return"],
    )
    if return_chain_link["status"] == "INVALID_REQUEST":
        return return_chain_link
    return {
        "status": "PREPARED",
        "recipe": {"name": "prepare_direction_recipe", "kind": "partial_recipe"},
        "completed_stages": [
            {"number": 0, "name": "Input R"},
            {"number": 1, "name": "State R"},
        ],
        "confirmed_input": confirmed,
        "state": state,
        "return_chain_link": return_chain_link,
        "entry_context_id": chain_recipe_entry_context_id(
            confirmed_input=confirmed, state=state,
            report_target_conversation_key=report_target_conversation_key,
            return_chain_link=return_chain_link,
        ),
    }


def write_direction_recipe(*, source_kind: str, work: Work | None) -> dict[str, Any]:
    """Prepare A's compact Direction R handoff without simulating A's judgment.

    The source text and State R card stay in the enclosing Chain Recipe
    result.  Repeating them here would make two competing direction cards.
    """
    save_gate = (
        {
            "status": "READY",
            "next": "bct_chain_recipe(action='save', entry_context_id=prepared entry_context_id)",
            "required": ["entry_context_id"],
        }
        if work is not None else
        {"status": "WORK_REQUIRED", "next": "A reuses or creates a bounded Work before save"}
    )
    return {
        "status": "A_DIRECTION_REQUIRED",
        "direction_text": None,
        "author": "A",
        "inputs": ["Input R", "State R"],
        "write": (
            "A writes one refined natural-language direction from the source and current facts. "
            "Keep the user goal, preserve stated constraints, and do not invent facts."
        ),
        "assumption_policy": (
            "Proceed with ordinary reversible assumptions. State only assumptions that materially "
            "change scope, result, or safety."
        ),
        "ask_user_only_when": [
            "an irreversible external effect is required",
            "current facts conflict and no safe interpretation exists",
            "materially different completion results remain equally plausible",
        ],
        "decision_options": ["COMPLETE", "NEW_TASK", "ASK_USER", "HOLD"],
        "save": {
            "tool": "bct_chain_recipe",
            "action": "save",
            "required": ["work_id", "entry_context_id", "decision", "direction_text"],
            "optional": {
                "direction_id": "omit to let BCT assign one new stable ID",
                "assessment": (
                    "only for machine-checked topology, target, role, or network-update details; "
                    "omit for an ordinary single-direction decision"
                ),
            },
            "source_binding": "preserve the Input R source_kind/task_id/generation and entry_context_id when saving",
        },
        "source_kind": source_kind,
        "save_gate": save_gate,
        "read_only": True,
        "authorizes_send": False,
    }


def validate_direction(
    *, work: Work, direction_id: str, source_kind: str, source_task_id: str,
    source_generation: int, source_result_sha256: str, decision: str,
    direction_text: str,
) -> dict[str, Any]:
    """Validate the Direction record fields without writing a record."""
    from bct.chain_direction import ChainDirectionLedger
    if not direction_id:
        direction_id = "direction-" + uuid.uuid4().hex[:24]
    try:
        ChainDirectionLedger._validate(
            direction_id=direction_id, work_id=work.work_id, source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_result_sha256=source_result_sha256, decision=decision,
            direction_text=direction_text,
        )
    except ValueError as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    return {"status": "VALID", "direction_id": direction_id}


def validate_assessment(
    *, assessment: dict[str, Any] | None, decision: str, source_kind: str, source_text: str,
) -> dict[str, Any]:
    """Validate optional machine-checked Direction details without writing them."""
    if assessment is None:
        return {"status": "NOT_PROVIDED", "assessment": None}
    from bct.chain_direction import direction_assessment_contract, validate_direction_assessment
    try:
        checked = validate_direction_assessment(assessment, decision=decision)
        if checked and source_kind == "USER" and (not source_text.strip() or len(source_text) > 12000):
            raise ValueError("CHAIN_DIRECTION_SOURCE_TEXT_REQUIRED")
    except (ValueError, PreconditionError) as exc:
        return {
            "status": "INVALID_REQUEST", "reason": str(exc),
            "assessment_contract": direction_assessment_contract(assessment, reason=str(exc)),
        }
    return {"status": "VALID", "assessment": checked}


async def record_direction(runtime: ChainRecipeRuntime,
    *, work: Work, direction_id: str, source_kind: str, source_task_id: str,
    source_generation: int, source_result_sha256: str, decision: str,
    direction_text: str, assessment: dict[str, Any] | None, source_text: str,
    parent_direction_id: str = "", parent_step_id: str = "",
    branch_kind: str = "PRIMARY", branch_reason: str = "", branch_request_id: str = "",
) -> dict[str, Any]:
    """Write one already-validated Direction record; never sends it."""
    from bct.chain_direction import ChainDirectionLedger
    if assessment is not None:
        # The ledger repeats validation as a final storage safety fence.
        # The visible recipe has already performed the user-facing validation.
        assessment = dict(assessment)
    try:
        direction = await asyncio.to_thread(
            ChainDirectionLedger(runtime.bct.store).save,
            direction_id=direction_id, work_id=work.work_id,
            source_kind=source_kind, source_task_id=source_task_id,
            source_generation=source_generation,
            source_result_sha256=source_result_sha256, decision=decision,
            direction_text=direction_text, assessment=assessment, source_text=source_text,
            parent_direction_id=parent_direction_id,
            parent_work_id=work.work_id if parent_direction_id else "",
            parent_step_id=parent_step_id, branch_kind=branch_kind,
            branch_reason=branch_reason, branch_request_id=branch_request_id,
        )
    except ValueError as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    return {"status": "OK", "chain_direction": direction}


async def save_direction_recipe(runtime: ChainRecipeRuntime,
    *, work: Work, direction_id: str, source_kind: str, source_task_id: str,
    source_generation: int, source_result_sha256: str, decision: str,
    direction_text: str, assessment: dict[str, Any] | None, source_text: str,
    parent_direction_id: str = "", parent_step_id: str = "",
    branch_kind: str = "PRIMARY", branch_reason: str = "", branch_request_id: str = "",
) -> dict[str, Any]:
    """Compose Direction validation and recording without changing the conversation network."""
    direction_check = validate_direction(
        work=work, direction_id=direction_id, source_kind=source_kind,
        source_task_id=source_task_id, source_generation=source_generation,
        source_result_sha256=source_result_sha256, decision=decision,
        direction_text=direction_text,
    )
    if direction_check["status"] != "VALID":
        return direction_check
    assessment_check = validate_assessment(
        assessment=assessment, decision=decision, source_kind=source_kind, source_text=source_text,
    )
    if assessment_check["status"] == "INVALID_REQUEST":
        return assessment_check
    checked_assessment = assessment_check["assessment"]
    return await record_direction(runtime,
        work=work, direction_id=direction_check["direction_id"], source_kind=source_kind,
        source_task_id=source_task_id, source_generation=source_generation,
        source_result_sha256=source_result_sha256, decision=decision,
        direction_text=direction_text, assessment=checked_assessment, source_text=source_text,
        parent_direction_id=parent_direction_id, parent_step_id=parent_step_id,
        branch_kind=branch_kind, branch_reason=branch_reason,
        branch_request_id=branch_request_id,
    )


async def read_saved_direction(runtime: ChainRecipeRuntime, *, work_id: str, direction_id: str) -> dict[str, Any]:
    """Read one saved Direction without creating schema or changing durable state."""
    if not hasattr(runtime.bct, "store"):
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_STORE_REQUIRED"}
    if not isinstance(direction_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", direction_id):
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_ID_INVALID"}
    def read_existing():
        with runtime.bct.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,),
            ).fetchone()
            return dict(row) if row is not None else None
    try:
        direction = await asyncio.to_thread(read_existing)
    except Exception:
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_READ_UNAVAILABLE"}
    if direction is None or direction.get("work_id") != work_id:
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_FOUND"}
    return {"status": "READY", "direction": direction}
