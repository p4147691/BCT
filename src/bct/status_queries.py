"""Read-only status and conversation-network application queries.

Dependencies are supplied per call. This module neither registers MCP tools nor
creates an alternate execution or delivery path.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Callable

from .conversation_network import ConversationNetworkError, project_view, resolve_project_id
from .status_views import STATUS_SCOPES, status_view
from .trace_timing import TRACE_ID as _MCP_TRACE_ID, trace_stage as _trace_stage


async def read_status(
    bct: Any, *, principal_id: str,
    status_provider: Callable[[], dict[str, Any]] | None,
    browser_usage: str, compact: bool = True, scope: str = "bct", sort_by: str = "number",
) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    if status_provider is None:
        return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
    if scope not in STATUS_SCOPES:
        return {"status": "INVALID_REQUEST", "reason": "BCT_STATUS_SCOPE_INVALID"}
    snapshot = await asyncio.to_thread(status_provider)
    if scope != "bct":
        return status_view(snapshot, scope, sort_by=sort_by)
    # The default status is the common current-state block.  Include the
    # current node projection (network/roles/activity) from the same
    # snapshot rather than making callers request scope=node separately.
    from bct.status_views import with_current_node_details
    snapshot = with_current_node_details(snapshot, sort_by=sort_by)
    from bct.chain_execution_plan import ChainExecutionPlanLedger
    execute_plan_checks = await asyncio.to_thread(
        ChainExecutionPlanLedger.list_latest_execute_plan_checks,
        store=bct.store, limit=5 if compact else 20,
    )
    from bct.chain_direction import ChainDirectionLedger
    pending_chain_starts = await asyncio.to_thread(
        ChainDirectionLedger.list_pending_chain_starts,
        store=bct.store, principal_id=principal_id,
        limit=5 if compact else 20,
    )
    # A compact Manager attention list supplements, but never replaces,
    # the exact root-tree read. It is observation only and does not create
    # a branch, Direction, Work, Operation, or delivery.
    from bct.chain_direction import ChainBranchRequestLedger
    chain_branch_attention = []
    try:
        with bct.store._readonly() as db:
            roots = [str(row[0]) for row in db.execute(
                "SELECT work_id FROM works WHERE owner_principal_id=?", (principal_id,)
            ).fetchall()]
        for root in roots:
            tree = await asyncio.to_thread(ChainBranchRequestLedger.tree, store=bct.store, root_work_id=root)
            chain_branch_attention.extend({"root_work_id": root, **item}
                                          for item in tree["manager_attention"])
    except (sqlite3.OperationalError, AttributeError):
        # Status is a read-only summary even for legacy stores that do not
        # yet have the additive chain tables.
        chain_branch_attention = []
    snapshot = {
        **snapshot,
        "execute_plan_checks": execute_plan_checks,
        # A saved Direction is not a started Chain. Keep that handoff in
        # the normal Manager status view so it cannot disappear between
        # Set Direction and the exact start/send boundary.
        "pending_chain_starts": pending_chain_starts,
        "chain_branch_attention": chain_branch_attention[:5 if compact else 20],
    }
    if compact and isinstance(snapshot.get("monitor"), dict):
        monitor = dict(snapshot["monitor"])
        for key in (
            "works", "operations", "events", "nodes", "connections",
            "orchestration_sessions", "orchestration_assignments",
            "github_run_inbox",
        ):
            rows = monitor.get(key)
            if isinstance(rows, list):
                monitor[key] = rows[:5]
        snapshot = {**snapshot, "monitor": monitor, "compact": True}
    # Always expose the canonical RCC command contract during the required
    # status preflight; client-side MCP tool metadata may be stale.
    snapshot = {**snapshot, "browser_usage": browser_usage}
    current_trace_id = _MCP_TRACE_ID.get()
    if current_trace_id is not None:
        snapshot = {**snapshot, "mcp_trace_id": current_trace_id}
    handler_ms = (time.perf_counter_ns() - started_ns) / 1e6
    _trace_stage(
        "handler_done", tool_kind="status", handler_ms=handler_ms,
        wait_ms=0.0, execution_ms=handler_ms,
    )
    return snapshot


async def read_conversation_network(bct: Any, *, project: str) -> dict[str, Any]:
    """Read a user-facing conversation-network view without exposing route UUIDs."""
    started_ns = time.perf_counter_ns()
    try:
        project_id = await asyncio.to_thread(
            resolve_project_id, bct.store, project_reference=project,
        )
        view = await asyncio.to_thread(project_view, bct.store, project_id=project_id)
    except ConversationNetworkError as exc:
        reason = str(exc)
        value = {
            "status": "NOT_FOUND" if reason == "CONVERSATION_NETWORK_PROJECT_NOT_FOUND" else "INVALID_REQUEST",
            "reason": reason,
        }
    else:
        value = {"status": "OK", **view}
    handler_ms = (time.perf_counter_ns() - started_ns) / 1e6
    _trace_stage(
        "handler_done", tool_kind="conversation_network_get", handler_ms=handler_ms,
        wait_ms=0.0, execution_ms=handler_ms,
    )
    return value
