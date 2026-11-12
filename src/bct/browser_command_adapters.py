"""Exact-identity browser command adapters used by public MCP tools."""
from __future__ import annotations
from typing import Any, Awaitable, Callable

async def send_message(execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    arguments = {"command":"send-message", "instance_id":v["instance_id"], "session_id":v["session_id"],
                 "tab_id":v["tab_id"], "window_id":v["window_id"], "conversation_key":v["conversation_key"], "text":v["text"]}
    if v["create_operation_id"]:
        arguments["create_operation_id"] = v["create_operation_id"]
    return await execute(v["work_id"], v["operation_id"], arguments, v["approval_ref"])

async def move_tab(execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    return await execute(v["work_id"], v["operation_id"], {"command":"move-tab", "instance_id":v["instance_id"],
        "session_id":v["session_id"], "tab_id":v["tab_id"], "window_id":v["window_id"], "target_window_id":v["target_window_id"],
        "index":v["index"], "conversation_key":v["conversation_key"], "create_operation_id":v["create_operation_id"]}, v["approval_ref"])

async def close_tab(execute: Callable[..., Awaitable[dict[str, Any]]], **v: Any) -> dict[str, Any]:
    return await execute(v["work_id"], v["operation_id"], {"command":"close-conversation-tab", "instance_id":v["instance_id"],
        "session_id":v["session_id"], "tab_id":v["tab_id"], "window_id":v["window_id"], "conversation_key":v["conversation_key"]}, v["approval_ref"])
