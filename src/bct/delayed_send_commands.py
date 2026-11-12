"""Fenced delayed-send command assembly outside MCP registration."""
from __future__ import annotations
import asyncio
import uuid
from typing import Any, Awaitable, Callable
from .node_recovery import NodeRecoveryLedger
from .recipes.recovery import _assert_node_send_allowed

async def send_delayed_message_command(store: Any, runtime: Any, browser_execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    try:
        if v["conversation_key"]:
            await asyncio.to_thread(_assert_node_send_allowed, runtime, v["work_id"], v["conversation_key"])
        elif store is not None:
            await asyncio.to_thread(NodeRecoveryLedger(store).assert_task_send_allowed, work_id=v["work_id"], task_id=v["task_id"])
    except ValueError as exc:
        return {"status": "PAUSED", "reason": str(exc)}
    operation_id = v["operation_id"] or ("send-delayed-" + uuid.uuid4().hex[:24])
    return await browser_execute(v["work_id"], operation_id, {
        "command":"send-delayed-message", "task_id":v["task_id"], "instance_id":v["instance_id"],
        "conversation_key":v["conversation_key"], "manager_conversation_key":v["manager_conversation_key"],
        "manager_instance_id":v["manager_instance_id"], "planned_send_operation_id":v["planned_send_operation_id"],
        "planned_send_text":v["planned_send_text"], "bootstrap_create_operation_id":v["bootstrap_create_operation_id"],
    })
