"""MCP command logic for exact Code Block Scan replacements."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .code_block_organize import plan_block_replacement, prepare_block_apply
from .code_block_scan import resolve_scan_root


async def organize_code_blocks_command(
    store: Any,
    *,
    principal_id: str,
    write_execute: Callable[..., Awaitable[dict[str, Any]]],
    work_id: str,
    action: str,
    path: str,
    block_id: str,
    replacement: str,
    root: str = "",
    operation_id: str = "",
    expected_file_sha256: str = "",
    expected_block_sha256: str = "",
    expected_after_sha256: str = "",
    plan_sha256: str = "",
) -> dict[str, Any]:
    """Plan or apply exactly one hash-fenced block replacement."""
    if store is None:
        raise RuntimeError("CODE_BLOCK_ORGANIZE_STORE_REQUIRED")
    work = await asyncio.to_thread(store.get_work, work_id)
    if work.owner_principal_id != principal_id:
        raise PermissionError("CODE_BLOCK_ORGANIZE_WORK_ACCESS_DENIED")
    scan_root = resolve_scan_root(work, root)
    selected = str(action or "").strip().casefold()
    if selected == "plan":
        return await asyncio.to_thread(
            plan_block_replacement,
            scan_root,
            path=path,
            block_id=block_id,
            replacement=replacement,
            expected_file_sha256=expected_file_sha256,
            expected_block_sha256=expected_block_sha256,
        )
    if selected != "apply":
        raise ValueError("CODE_BLOCK_ORGANIZE_ACTION_INVALID")
    if not operation_id.strip():
        raise ValueError("CODE_BLOCK_ORGANIZE_OPERATION_ID_REQUIRED")
    prepared = await asyncio.to_thread(
        prepare_block_apply,
        scan_root,
        path=path,
        block_id=block_id,
        replacement=replacement,
        expected_file_sha256=expected_file_sha256,
        expected_block_sha256=expected_block_sha256,
        expected_after_sha256=expected_after_sha256,
        plan_sha256=plan_sha256,
    )
    result = await write_execute(
        work_id,
        operation_id,
        {key: prepared[key] for key in ("path", "content", "expected_sha256", "expected_absent")},
        None,
    )
    result["block_replacement"] = {
        "schema": prepared["plan"].get("schema"),
        "path": prepared["plan"].get("path"),
        "block_id": prepared["plan"].get("block_id"),
        "plan_sha256": plan_sha256,
        "after_file_sha256": expected_after_sha256,
    }
    return result
