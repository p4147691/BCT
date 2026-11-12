"""Work-scoped read-only Code Block Scan composition."""
from __future__ import annotations

import asyncio
from typing import Any

from bct.code_block_scan import resolve_scan_root, scan as run_code_block_scan
from .runtime import ChainRecipeRuntime


async def scan_work_code_blocks(
    runtime: ChainRecipeRuntime, *, work_id: str, root: str = "",
    max_files: int = 1000, max_bytes_per_file: int = 1_000_000, max_blocks: int = 4000,
) -> dict[str, Any]:
    bct, principal = runtime.bct, runtime.principal
    if not hasattr(bct, "store"):
        raise RuntimeError("CODE_BLOCK_SCAN_STORE_REQUIRED")
    work = await asyncio.to_thread(bct.store.get_work, work_id)
    if work.owner_principal_id != principal.principal_id:
        raise PermissionError("CODE_BLOCK_SCAN_WORK_ACCESS_DENIED")
    scan_root = resolve_scan_root(work, root)
    return await asyncio.to_thread(
        run_code_block_scan,
        scan_root,
        max_files=max_files,
        max_bytes_per_file=max_bytes_per_file,
        max_blocks=max_blocks,
    )
