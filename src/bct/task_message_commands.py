"""Public Task Message command logic, separate from MCP registration."""
from __future__ import annotations

from typing import Any

from .task_message import prepare_task_message_instruction
from .recipes.delivery import send_chain_delivery


async def task_message_command(runtime: Any, **kwargs: Any) -> dict[str, Any]:
    action = kwargs["action"]
    max_rounds = kwargs["max_rounds"]
    if action in {"status", "cancel"}:
        result = await send_chain_delivery(
            runtime, work_id=kwargs["work_id"], task_id=kwargs["task_id"],
            operation_id=kwargs["operation_id"], action=action,
            generation=kwargs["generation"],
        )
        return {**result, "recipe": "Task Message", "max_rounds": result.get("max_generations", max_rounds)}
    if action not in {"start", "preflight"}:
        return {"status": "INVALID_REQUEST", "reason": "TASK_MESSAGE_ACTION_INVALID"}
    try:
        prepared = prepare_task_message_instruction(
            kwargs["instruction"], acceptance=kwargs["acceptance"], bb_rule=kwargs["bb_rule"],
            manager_return_rule=kwargs["manager_return_rule"], max_rounds=max_rounds,
        )
    except ValueError as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    result = await send_chain_delivery(
        runtime, work_id=kwargs["work_id"], task_id=kwargs["task_id"],
        operation_id=kwargs["operation_id"], action=action,
        instance_id=kwargs["instance_id"], session_id=kwargs["session_id"],
        target_tab_id=kwargs["target_tab_id"], target_window_id=kwargs["target_window_id"],
        target_conversation_key=kwargs["target_conversation_key"],
        origin_conversation_key=kwargs["origin_conversation_key"], origin_instance_id=kwargs["origin_instance_id"],
        instruction=str(prepared["instruction"]), generation=kwargs["generation"],
        continuation_output_contract="explicit-next-task-v1", max_generations=max_rounds,
    )
    return {**result, "recipe": "Task Message", "max_rounds": max_rounds,
            "task_instruction_sha256": prepared["instruction_sha256"]}
