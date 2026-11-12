"""Small public command adapters over already-authorized capabilities."""
from __future__ import annotations
import uuid
from typing import Any, Awaitable, Callable
from .project_plan import prepare_project_plan

async def run_project_plan(execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    prepared = prepare_project_plan(**{key: v[key] for key in ("work_id","plan_id","project","objective","acceptance","steps","author","expected_revision","discretion","assumptions")})
    if prepared["status"] != "READY": return prepared
    return await execute(v["work_id"], v["operation_id"], prepared["arguments"], v["approval_ref"])

async def run_task(execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    if v["arguments"].get("operation", "dispatch") != "dispatch":
        return {"status":"INVALID_REQUEST","reason":"TASK_RUN_OPERATION_MISMATCH"}
    return await execute(v["work_id"], v["operation_id"], {**v["arguments"], "operation":"dispatch"}, v["approval_ref"])

async def cancel_delayed_send(execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    operation_id = v["operation_id"] or ("delayed-cancel-" + uuid.uuid4().hex[:24])
    return await execute(v["work_id"], operation_id, {"command":"delayed-send-cancel", "task_id":v["task_id"], "generation":v["generation"]})
