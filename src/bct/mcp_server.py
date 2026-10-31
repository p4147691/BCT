from __future__ import annotations

import asyncio
import hmac
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from mcp.server.fastmcp import FastMCP, Image
from starlette.responses import JSONResponse

from .background_operations import BACKGROUND_CAPABILITIES, launch_background_operation
from .conversation_network import ConversationNetworkError, project_view, resolve_project_id
from .core.models import Principal, Work
from .mcp_catalogue_config import CatalogueSettings
from .status_views import status_view, STATUS_SCOPES


from .trace_timing import TRACE_ID as _MCP_TRACE_ID, trace_stage as _trace_stage

MCP_PRINCIPAL_ID = "bct-mcp-local"

_GENERAL_TOOLS = (
    "bct_capabilities", "bct_status", "bct_conversation_network_get", "bct_network_get", "bct_run_check",
    "bct_work_create", "bct_operation_get",
)
_CAPABILITY_USAGE = {
    "test": "Run existing py_compile/unittest checks. Cached catalogues can submit a bounded verification recipe using arguments.operation=verify plus steps; this requires verify and every child capability in work scope.",
    "verify": "Run up to 8 read metadata, test, or github_pr_status steps, or a fixed versioned recipe. Each step is durably journaled. Requires each child action in work scope. Background operation; retrieve receipt and step_journal with bct_operation_get(wait_seconds=25). No file bodies or test output are persisted.",
    "github_pr_status": "Exact expected_head and required_checks required. Optional wait_seconds (0..300) waits server-side; positive waits run in background. Retrieve receipt with bct_operation_get.",
    "github_run_watch": "Register one exact Actions run for a detached, advisory-only Inbox completion. It never merges, pushes, deploys, or changes Work state; retrieve terminal results with bct_inbox_get.",
    "read": "Read a scoped file or directory with operation=file|directory_tree|batch|snapshot. Read-only discovery: operation=search with path, query, depth, max_entries, limit; operation=duplicates with path and bounded SHA-256 verification (max_hash_bytes, timeout_seconds); operation=compare with path_a and path_b. Partial searches/hash budgets report complete=false. Never deletes files.",
    "system_inspect": "Read process_list, process by pid, or port owners. For one bounded read-only diagnosis use operation=diagnose with query and/or up to 8 ports, optional limit. Never terminates a process.",
    "approval_challenge": "Read-only exact Work/Operation request challenge for independent human approval UI. Accept capability, operation_id and full arguments of a pre-approved P2 action. Returns full prepared request, target and SHA256; never issues approvals or executes effects.",
    "file_local_action": "Normal local file operation within an exact user-scoped Work: move/rename/restore require source and destination. recoverable_delete takes source only, moves to .bct-recovery after an interactive Windows YES/NO confirmation; headless and declines fail closed. Never overwrites, permanently deletes or touches BCT/OS protected paths; high security available separately via file_action_apply.",
    "process_local_stop": "Graceful close only of a process_session.start-proven owned GUI child by session_id,start_operation_id,expected_fingerprint. Never force, kill or terminate operating BCT/RCC/Chrome/Monitor. High security process_stop_apply remains separate.",
    "file_action_apply": "Approve-only one-file same-device move, recoverable quarantine or restore. Requires Work/Operation, exact signed Ed25519 user grant and 1-use consumption. No permanent deletion or recursion; feature disabled until external trusted signer is configured.",
    "process_stop_apply": "Approve-only stop of exact owned process-session child. Requires session_id, original start_operation_id, expected_fingerprint and mode. Verifies exact original durable process_session.start receipt. Graceful WM_CLOSE or separately signed force request; protected-process and descendants fences. External trusted human signer required.",
    "file_action_plan": "Read-only preview of one exact reversible file move or quarantine: operation=move_preview|quarantine_preview, source and destination in same Work root/device. Validates full SHA256 and produces restore plan. No file changes; apply disabled until approval verifier exists.",
    "process_stop_plan": "Read-only exact PID/process-birth/executable inspection. No process signals; use existing owned process_session.stop where authorized, and require verified approval for any new stop capability.",
    "monitor": "Use arguments.operation as status or validate.",
    "conversation_network_update": "Update advisory conversation-network membership or role tags. For an existing member use arguments={\"operation\":\"role-patch\",\"project\":\"scope name or id\",\"node_label\":\"N14\",\"add\":[\"CI\"],\"remove\":[],\"expected_role_tags_sha256\":\"digest from bct_conversation_network_get\"}. To place an observed chat in a scope use operation=membership-assign with project, conversation_key, role_tags, and expected_scope_id (empty only when the chat is currently unassigned). This changes no tool permission, browser route, or current Delivery and applies to newly composed messages only.",
    "project_context": "Shared, bounded context records; this does not capture browser text or send a message. Use central-get/central-save for the one current project context, worklog-get/worklog-save for a project plus journal_work_id, and overview for central context plus compact worklog records. Saves require expected_revision and author. A work log must link its exact journal_work_id as links:[{type:'bct_work',id:'...'}].",
    "cdp_inspect": "Read-only existing Chrome tab listing via a single approved Chrome DevTools MCP connection. Use arguments={\\\"operation\\\":\\\"list_pages\\\"}. Requires a work with cdp_inspect permission and locally enabled CDP policy; does not send messages, create tabs, or bypass Chrome consent.",
    "browser_extension_manage": "Read-only Chrome extension inventory via CDP. arguments={\\\"operation\\\":\\\"inventory\\\"} (or pages). Work-scoped; create/update/delete not enabled in this initial common MCP adapter. CDP only. Do not infer Tampermonkey CRUD support from this tool yet.",
    "relay_browser": (
        "RCC contract rcc-send-message-v1. For ChatGPT messages use ONLY command=send-message "
        "with exact instance_id, session_id, tab_id, window_id, text, and either "
        "conversation_key (empty string for an existing blank tab) OR create_operation_id "
        "(from a verified BCT-created window/tab in the SAME Work). The Core resolves "
        "send-to-tab vs send-to-created-tab under ONE BCT Operation. Never select a tab "
        "by title or order, never fall back to another send command, and NEVER retry "
        "UNKNOWN using a new operation. Use original receipt/result for recovery. "
        "create-chat-window and create-chat-tab are independent creation commands. "
        "send-to-tab, send-to-created-tab, send-to-self, node-continue, legacy send, "
        "and create-and-send are deprecated internal compatibility only; never invoke them for new public requests. Read-only command=state remains supported."
    ),
    "relay_control": "Execute one enabled hot-read relay purpose using arguments={\"purpose\":\"selected purpose\",\"scope_id\":\"project scope\",\"context\":{...},\"expected_settings_sha256\":\"preview revision\"}. The fixed registry permits one existing BCT operation step per invocation. Settings never grant authority: the Work must contain the delegated capability such as relay_browser or cdp_inspect. Reuse operation_id only for the exact same frozen request and never retry UNKNOWN with a new ID.",
    "orchestrate": "Durable read-evidence manager/worker sessions. Use project-run-plan to select one advisory Manager conversation from an existing conversation scope, then start and sync a session, select a manager epoch, and project-run-bind the exact active RCC attachment. A later attachment generation for the same conversation may be rebound; stale generations are rejected only at the effect boundary. Use dispatch, tool-build-request, or chain-run for work. dispatch is one exact immediate target, not a fallback scheduler. Durable Manager FOLLOW_UP successors may instead include routing={affinity: REQUIRED|PREFERRED|ANY, fallbacks:[{node_id,attachment_id,attachment_generation}], allow_provision:boolean}; it is evaluated only before a send. REQUIRED holds then escalates, PREFERRED/ANY may use an idle fallback after policy wait, and allow_provision records PROVISION_REQUIRED for Manager judgment rather than creating a node automatically. tool-build-request is usable from any ordinary connected ChatGPT conversation: give session_id, assignment_id, tool_name, problem, required_behaviors, acceptance, and actions including read/write/test. It auto-resolves exactly one active Worker when unambiguous; otherwise pass worker_node_id or attachment_id. manager_epoch is optional internal fencing. It may implement, test, and use a tool only within the existing Work authority, then records PENDING_USER_REPORT. Read that report with tool-build-report; user later chooses KEEP, CHANGE, or RETIRE. Browser mutations run in background; recover with bct_operation_get. Recovery never resends an UNKNOWN effect.",
    "desktop_session_status": "Return the exact current interactive user-session Agent identity, foreground window, monitor geometry, and capture readiness.",
    "desktop_capture": "Capture the current virtual screen, one monitor, or one exact HWND. The MCP result contains both metadata and an image content block.",
    "desktop_explore": "List exact current-session processes with their desktop windows, or discover the logged-in user's known folders and drives. Use work-scoped read for file contents.",
    "desktop_application_target": "List Chrome or Explorer windows by semantic identity, or acquire one exact matching window Lease. Chrome supports read-only profile_query plus active/any tab_title_query without focus or browser mutation. Explorer supports exact absolute folder_path. Bind fails closed on unavailable inspection, zero, multiple, or truncated matches.",
    "desktop_chrome_content_list": "List bounded edit/button metadata inside the one visible active RootWebArea of an exact existing Chrome HWND. This excludes the omnibox and does not read field values, focus, activate, navigate, or mutate the browser.",
    "desktop_chrome_content_action": "Set one exact writable web ValuePattern or invoke one exact web InvokePattern using a fresh element ID under the active Chrome Window Lease. set_value requires that leased Chrome window to already be foreground; use desktop_window_activate explicitly first. The action never activates implicitly. Text is represented in receipts only by length and SHA-256; foreground is preserved and UNKNOWN is never retried.",
    "desktop_uia_elements_list": "List bounded actionable Windows UI Automation metadata inside one exact visible HWND without reading field values or changing foreground. Raw labels are returned only in the direct result; durable evidence stores aggregate counts and a sanitized metadata digest.",
    "desktop_uia_element_action": "Invoke, set a value, toggle, select, expand, or collapse one exact fresh UI Automation element under the active Window Lease. set_value requires the leased window to already be foreground; all actions preserve foreground and UNKNOWN is never retried.",
    "desktop_chrome_tab_select": "Select one exact existing Chrome tab by ordinal and exact observed title under the active Chrome window Lease. The action preserves foreground, revalidates the window before and after, and never opens, closes, navigates, focuses, or sends global input.",
    "desktop_chrome_tab_reconcile": "Read-only proof for one exact changed-foreground UNKNOWN tab action after compensation. Requires the exact original operation, window fingerprint, active tab, restored foreground, no Lease, and no emergency stop; never repeats the tab effect.",
    "desktop_control_lease": "Status, acquire, renew, release, or generation-fenced reset of the one current-session control lease. This does not inject input.",
    "desktop_emergency_stop": "Latch the current-session emergency stop and immediately revoke its active control lease. This remains callable independently of normal control claims.",
    "desktop_input": "Move, click, scroll, or left-drag the mouse, or send one bounded key/text batch to an exact window lease. Every effect is fenced by the active lease and emergency stop.",
    "desktop_clipboard": "Read or replace Unicode text in the exact logged-in session clipboard under an active session Lease. Raw text is returned only in the direct result; durable evidence stores length and SHA-256 metadata.",
    "desktop_window_list": "List bounded visible top-level windows on the current virtual desktop with exact HWND/process fingerprints.",
    "desktop_window_activate": "Bring the exact non-minimized window bound to the active lease to the foreground. This does not launch, restore, move, or resize a window.",
    "desktop_window_activate_reconcile": "Release one exact window-activation UNKNOWN only after read-only proof that its Lease is gone, emergency stop is clear, the exact target fingerprint is absent, and that HWND is not foreground. The original UNKNOWN receipt is preserved and the activation is never repeated.",
    "desktop_window_manage": "Restore, minimize, maximize, or move/resize only the exact window bound to the active lease. Close is not supported.",
    "desktop_explorer_folder_open": "Open one existing absolute folder in Explorer under a work-scoped operation and current-session lease; reconcile exact Shell folder window, optionally activate, and release control.",
    "desktop_program_launch": "Launch one exact absolute .exe with an argument array under an active session lease, capture the new PID identity, and bind that same lease only if the PID creates a visible window on the current virtual desktop.",
    "vtl_validate": "Run a project-owned browser or profile scenario directly through the exact immutable local VTL release. Returns PASS/FAIL and durable evidence without dispatching GitHub Actions.",
    "claim_reconcile": "Record a read-only reconciliation of one FINISHED UNKNOWN receipt when its no-effect proof is available. Claims never gate new operations, so this is not required to unlock a resource. Never retry original effects; preserve the original receipt.",
}
_SPECIAL_CAPABILITIES = frozenset({"desktop_session_status", "desktop_capture"})


def _work_dict(work: Work) -> dict[str, Any]:
    return {
        "work_id": work.work_id,
        "request_summary": work.request_summary,
        "roots": list(work.roots),
        "actions": sorted(work.actions),
        "owner_principal_id": work.owner_principal_id,
        "assignment_epoch": work.assignment_epoch,
        "state": work.state,
    }


def build_mcp(
    bct: Any,
    *,
    status_provider: Callable[[], dict[str, Any]] | None = None,
    compact_catalogue: bool = False,
    hybrid_catalogue: bool = False,
) -> FastMCP:
    """Build the public MCP catalogue from the registered BCT capabilities."""
    if compact_catalogue and hybrid_catalogue:
        raise ValueError("MCP_CATALOGUE_MODES_MUTUALLY_EXCLUSIVE")
    compact_catalogue = compact_catalogue or hybrid_catalogue
    capabilities = tuple(bct.operations.capabilities)
    principal = Principal(MCP_PRINCIPAL_ID, "local-bearer", frozenset(capabilities))
    server = FastMCP(
        "BCT",
        instructions=(
            "Create one bounded work record, then call the matching bct_<capability> tool. "
            "Reuse operation_id only for the exact same request."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )

    @server.tool(description="List the exact BCT capabilities exposed by this runtime.", structured_output=True)
    async def bct_capabilities() -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        value = {
            "capabilities": list(capabilities),
            "tools": [tool.name for tool in await server.list_tools()],
            # The live runtime contract takes precedence over client-cached tool descriptions.
            "relay_browser_usage": _CAPABILITY_USAGE["relay_browser"],
            "relay_browser_contract_version": "rcc-send-message-v1",
            "relay_browser_public_commands": ["create-chat-window", "create-chat-tab", "send-message"],
        }
        settings = getattr(server, "catalogue_settings", None)
        if settings is not None and settings.last_error:
            value["catalogue_warning"] = settings.last_error
        handler_ms = (time.perf_counter_ns() - started_ns) / 1e6
        _trace_stage(
            "handler_done", tool_kind="capabilities", handler_ms=handler_ms,
            wait_ms=0.0, execution_ms=handler_ms,
        )
        return value

    @server.tool(
        description=(
            "Return the current read-only BCT summary: Core release/health, Monitor projection, "
            "RCC instances, and active process sessions. Optional compact defaults true; creates no work or mutation."
        ),
        structured_output=True,
    )
    async def bct_status(compact: bool = True, scope: str = "bct", sort_by: str = "number") -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        if scope not in STATUS_SCOPES:
            return {"status": "INVALID_REQUEST", "reason": "BCT_STATUS_SCOPE_INVALID"}
        snapshot = await asyncio.to_thread(status_provider)
        if scope != "bct":
            return status_view(snapshot, scope, sort_by=sort_by)
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
        snapshot = {**snapshot, "relay_browser_usage": _CAPABILITY_USAGE["relay_browser"]}
        current_trace_id = _MCP_TRACE_ID.get()
        if current_trace_id is not None:
            snapshot = {**snapshot, "mcp_trace_id": current_trace_id}
        handler_ms = (time.perf_counter_ns() - started_ns) / 1e6
        _trace_stage(
            "handler_done", tool_kind="status", handler_ms=handler_ms,
            wait_ms=0.0, execution_ms=handler_ms,
        )
        return snapshot

    @server.tool(
        description=(
            "Read one registered BCT conversation-network project. Returns display names, advisory tags, "
            "activity, literal Monitor labels, observation state, and Monitor-only rows. "
            "This creates no work and does not call Monitor, RCC, Chrome, or relay delivery."
        ),
        structured_output=True,
    )
    async def bct_conversation_network_get(project: str) -> dict[str, Any]:
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

    @server.tool(description="Read a registered project network. Canonical short name for bct_conversation_network_get.", structured_output=True)
    async def bct_network_get(project: str) -> dict[str, Any]:
        return await bct_conversation_network_get(project)

    @server.tool(description="Read-only preflight for planning: current node/RCC state and optional registered network. Does not create plans, networks or messages.", structured_output=True)
    async def bct_run_check(project: str = "", sort_by: str = "number", work_id: str = "", operation_id: str = "") -> dict[str, Any]:
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        snapshot = await asyncio.to_thread(status_provider)
        nodes = status_view(snapshot, "node", sort_by=sort_by)
        rcc = status_view(snapshot, "rcc", sort_by=sort_by)
        # Candidates come from confirmed current nodes, never from guessed project IDs.
        # Historical projects need a separately authorized directory/summary lookup.
        candidates: dict[str, dict[str, str]] = {}
        for node in nodes.get("items", []) if isinstance(nodes, dict) else []:
            if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
                continue
            name = str(node.get("network") or "").strip()
            scope_id = str(node.get("network_id") or "").strip()
            if name:
                key = scope_id or name.casefold()
                candidates.setdefault(key, {"title": name, "network_id": scope_id})
        network = None
        context = None
        context_status = "NOT_REQUESTED"
        historical_contexts = []
        historical_contexts_status = "AUTH_CONTEXT_REQUIRED"
        if not project and work_id and operation_id:
            try:
                directory = await make_executor("project_context")(
                    work_id, operation_id,
                    {"operation": "directory-get"},
                )
                if directory.get("outcome") == "APPLIED":
                    payload = directory.get("output") or {}
                    historical_contexts = payload.get("items", []) if isinstance(payload, dict) else []
                    historical_contexts_status = "OK" if historical_contexts else "NO_CONTEXT"
                    # Combine authorized central summaries with the existing BCT network DB.
                    summaries = {str(item["project_id"]): item for item in historical_contexts
                                 if isinstance(item, dict) and item.get("project_id")}
                    with bct.store.transaction() as db:
                        rows = db.execute(
                            "SELECT project_id,display_name,active FROM conversation_network_projects "
                            "ORDER BY display_name,project_id LIMIT 200"
                        ).fetchall()
                    for row in rows:
                        key = str(row["project_id"])
                        candidates[key] = {"title": str(row["display_name"]), "network_id": key,
                                           "active": bool(row["active"]),
                                           "context_summary": summaries.get(key)}
                    # A stored project can outlive its network: return evidence, not a selection.
                    for key, item in summaries.items():
                        if key not in candidates:
                            candidates[key] = {"title": str(item.get("title") or key),
                                               "network_id": key, "active": False,
                                               "context_summary": item}
                else:
                    historical_contexts_status = "ACCESS_DENIED" if directory.get("error") and any(
                        marker in str(directory.get("error")).upper()
                        for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                    ) else "QUERY_ERROR"
            except Exception as exc:
                historical_contexts_status = "ACCESS_DENIED" if any(
                    marker in (type(exc).__name__ + ":" + str(exc)).upper()
                    for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                ) else "QUERY_ERROR"
        elif project:
            historical_contexts_status = "NOT_REQUESTED"
        if project:
            try:
                network = await bct_network_get(project)
            except (ConversationNetworkError, ValueError) as exc:
                network = {"status": "NOT_FOUND", "reason": str(exc)}
            if not work_id or not operation_id:
                context_status = "AUTH_CONTEXT_REQUIRED"
            else:
                try:
                    context = await make_executor("project_context")(
                        work_id, operation_id, {"operation": "overview-get", "project": project}
                    )
                    if context.get("outcome") == "APPLIED":
                        payload = context.get("output")
                        context_status = ("NO_CONTEXT" if not isinstance(payload, dict)
                                          or (payload.get("central") is None and not payload.get("worklogs"))
                                          else "OK")
                    else:
                        reason = str(context.get("error") or "").upper()
                        context_status = "ACCESS_DENIED" if any(
                            marker in reason for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                        ) else "QUERY_ERROR"
                except Exception as exc:
                    context_status = "ACCESS_DENIED" if any(
                        marker in (type(exc).__name__ + ":" + str(exc)).upper()
                        for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                    ) else "QUERY_ERROR"
                    context = {"status": "UNAVAILABLE", "reason_type": type(exc).__name__}
        return {"status": "OK", "nodes": nodes, "rcc": rcc,
                "network": network, "network_candidates": list(candidates.values()),
                "candidates_scope": ("CURRENT_AND_HISTORICAL_AUTHORIZED"
                                     if historical_contexts_status in {"OK", "NO_CONTEXT"}
                                     else "CURRENT_CONFIRMED_NODES_ONLY"),
                "historical_contexts": historical_contexts,
                "historical_contexts_status": historical_contexts_status,
                "project_context": context, "context_status": context_status,
                "context_requires_work": bool(project and (not work_id or not operation_id)),
                "read_only": True}

    @server.tool(description="Persist an AI-authored execution plan as a versioned, Work-authorized project-context ledger. No AI planning or execution is performed.", structured_output=True)
    async def bct_run_plan(
        work_id: str, operation_id: str, plan_id: str, project: str,
        objective: str, acceptance: str, steps: list[dict[str, Any]],
        author: str, expected_revision: int = 0, discretion: str = "normal",
        assumptions: list[str] | None = None,
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", plan_id):
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_ID_INVALID"}
        if not project.strip() or not objective.strip() or not acceptance.strip():
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_REQUIRED_FIELDS"}
        if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_STEPS_INVALID"}
        if discretion not in {"limited", "normal", "extended"}:
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_DISCRETION_INVALID"}
        checked = []
        for idx, step in enumerate(steps):
            if not isinstance(step, dict) or not {"instruction", "acceptance"} <= step.keys():
                return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_STEP_INVALID"}
            instruction = step["instruction"]
            criterion = step["acceptance"]
            if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 4000 or not isinstance(criterion, str) or not criterion.strip() or len(criterion) > 4000:
                return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_STEP_INVALID"}
            checked.append({"text": f"{idx + 1}/{len(steps)}: {instruction} | 완료: {criterion}", "evidence": []})
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_REVISION_INVALID"}
        assumptions = assumptions or []
        if not isinstance(assumptions, list) or len(assumptions) > 30 or any(not isinstance(x, str) or len(x) > 2000 for x in assumptions):
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_ASSUMPTIONS_INVALID"}
        record = {
            "title": "Run plan " + plan_id, "goal": objective,
            "scope_note": "Project: " + project + "; discretion: " + discretion,
            "summary": acceptance, "links": [{"type": "bct_work", "id": work_id}],
            "items": checked,
            "decisions": [{"text": "재량: " + discretion, "evidence": []}],
            "next_actions": [{"text": "가정: " + x, "evidence": []} for x in assumptions],
            "checkpoints": {"external": {"plan_id": plan_id, "project": project, "stage": "PLANNED"}},
        }
        return await make_executor("project_context")(
            work_id, operation_id, {"operation": "central-save",
            "project": "run-plan-" + plan_id.lower(), "record": record,
            "author": author, "expected_revision": expected_revision}, approval_ref
        )

    @server.tool(description="Set existing project membership or role tags through the authorized conversation_network_update capability; supports project-upsert, membership-assign and role-patch.", structured_output=True)
    async def bct_network_set(
        work_id: str, operation_id: str, arguments: dict[str, Any],
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        if arguments.get("operation") not in {"project-upsert", "membership-assign", "role-patch", "node-info-set", "network-name-set"}:
            return {"status": "INVALID_REQUEST", "reason": "NETWORK_SET_OPERATION_INVALID"}
        return await make_executor("conversation_network_update")(
            work_id, operation_id, arguments, approval_ref
        )

    @server.tool(
        name="bct_delayed_send_message",
        description=(
            "Prearm one Delayed Send Message for the worker's current response. "
            "On the first turn supply the exact RCC instance, worker conversation "
            "and manager conversation. Later SELF turns need only work_id, "
            "operation_id and task_id. The Core waits for a completed response "
            "then sends its final NEXT TASK — SELF/MANAGER instruction."
        ),
        structured_output=True,
    )
    async def bct_delayed_send_message(
        work_id: str, task_id: str, operation_id: str = "",
        instance_id: str = "", conversation_key: str = "",
        manager_conversation_key: str = "", manager_instance_id: str = "",
    ) -> dict[str, Any]:
        generated = operation_id or ("delayed-arm-" + uuid.uuid4().hex[:24])
        return await make_executor("relay_browser")(
            work_id, generated,
            {"command":"delayed-send-message","task_id":task_id,
             "instance_id":instance_id,"conversation_key":conversation_key,
             "manager_conversation_key":manager_conversation_key,
             "manager_instance_id":manager_instance_id},
        )

    @server.tool(description="Create or recover an exact user-scoped BCT work record.", structured_output=True)
    async def bct_work_create(
        work_id: str,
        request_summary: str,
        roots: list[str],
        actions: list[str],
    ) -> dict[str, Any]:
        requested_actions = frozenset(actions)
        if not work_id or not request_summary or not roots:
            raise ValueError("WORK_FIELDS_REQUIRED")
        if not requested_actions or not requested_actions.issubset(principal.capabilities):
            raise ValueError("WORK_ACTION_INVALID")
        normalized_roots = tuple(str(Path(root).resolve()) for root in roots)
        if any(not Path(root).is_absolute() for root in roots):
            raise ValueError("WORK_ROOT_ABSOLUTE_REQUIRED")
        expected = Work(
            work_id,
            request_summary,
            normalized_roots,
            requested_actions,
            principal.principal_id,
        )
        try:
            current = bct.store.get_work(work_id)
        except KeyError:
            current = bct.store.create_work(expected)
            duplicate = False
        else:
            if current != expected:
                raise ValueError("WORK_ID_CONFLICT")
            duplicate = True
        return {"work": _work_dict(current), "duplicate": duplicate}

    @server.tool(description="Read one exact operation receipt owned by the current MCP work.", structured_output=True)
    async def bct_operation_get(work_id: str, operation_id: str, wait_seconds: float = 0) -> dict[str, Any]:
        if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 25:
            raise ValueError("OPERATION_WAIT_INVALID")
        started_ns = time.perf_counter_ns()
        wait_ms = 0.0
        deadline = time.monotonic() + wait_seconds
        while True:
            result = await asyncio.to_thread(bct.store.get_operation_for,
                operation_id=operation_id, work_id=work_id, principal_id=principal.principal_id)
            if result.state.value == "FINISHED" or time.monotonic() >= deadline:
                value = result.as_dict()
                steps = await asyncio.to_thread(
                    bct.store.get_operation_steps_for,
                    operation_id=operation_id, work_id=work_id,
                    principal_id=principal.principal_id,
                )
                if steps:
                    value["step_journal"] = steps
                effect_journal = await asyncio.to_thread(
                    bct.store.get_effect_journal_for,
                    operation_id=operation_id, work_id=work_id,
                    principal_id=principal.principal_id,
                )
                if effect_journal:
                    value["effect_journal"] = effect_journal
                handler_ms = (time.perf_counter_ns()-started_ns)/1e6
                _trace_stage("handler_done", tool_kind="operation_get", handler_ms=handler_ms, wait_ms=wait_ms, execution_ms=max(0.0, handler_ms-wait_ms))
                return value
            sleep_start = time.perf_counter_ns()
            await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
            wait_ms += (time.perf_counter_ns()-sleep_start)/1e6

    @server.tool(description="Read GitHub CI/completion notifications for an owned BCT Work. acknowledge marks returned notifications read.", structured_output=True)
    async def bct_github_inbox_get(initiator_node_id: str = "", work_id: str = "",
                                   acknowledge: bool = False, limit: int = 80) -> dict[str, Any]:
        if not work_id:
            raise ValueError("INBOX_WORK_REQUIRED")
        # MCP has one local principal.  Requiring an owned Work keeps this read
        # scoped to the caller's Work rather than exposing a node-wide inbox.
        work = await asyncio.to_thread(bct.store.get_work, work_id)
        if work.owner_principal_id != principal.principal_id:
            raise PermissionError("INBOX_WORK_ACCESS_DENIED")
        rows = await asyncio.to_thread(
            bct.store.get_github_run_inbox, node_id=initiator_node_id,
            work_id=work_id, acknowledge=acknowledge, limit=limit,
        )
        return {"items": rows, "wake": "AUTO_WAKE_NOT_CONFIGURED"}

    @server.tool(description="Legacy compatibility alias for bct_github_inbox_get; GitHub completion notifications only.", structured_output=True)
    async def bct_inbox_get(initiator_node_id: str = "", work_id: str = "",
                            acknowledge: bool = False, limit: int = 80) -> dict[str, Any]:
        return await bct_github_inbox_get(
            initiator_node_id=initiator_node_id, work_id=work_id,
            acknowledge=acknowledge, limit=limit,
        )

    @server.tool(
        description="Return the verified current Windows interactive-session Agent status.",
        structured_output=True,
    )
    async def bct_desktop_session_status(work_id: str, operation_id: str) -> dict[str, Any]:
        result = await asyncio.to_thread(
            bct.operations.run,
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability="desktop_session_status", arguments={}, approval_ref=None,
        )
        value = result.as_dict()
        if result.duplicate and "output" not in value:
            value["output"] = {
                "instanceId": result.evidence.get("instance_id"),
                "session": result.evidence.get("session"),
                "monitors": result.evidence.get("monitors"),
            }
        return value

    @server.tool(
        description="Capture the verified current Windows virtual screen, monitor, or exact HWND and return the PNG as MCP image content.",
        structured_output=False,
    )
    async def bct_desktop_capture(
        work_id: str,
        operation_id: str,
        target_type: str = "virtual_screen",
        monitor_index: int | None = None,
        hwnd: str = "",
        max_width: int = 1600,
        max_height: int = 1200,
    ) -> Any:
        result = await asyncio.to_thread(
            bct.operations.run,
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability="desktop_capture",
            arguments={
                "target_type": target_type, "monitor_index": monitor_index,
                "hwnd": hwnd, "max_width": max_width, "max_height": max_height,
            },
            approval_ref=None,
        )
        value = result.as_dict()
        capture = result.output.get("capture") if isinstance(result.output, dict) else None
        if not isinstance(capture, dict):
            capture = result.evidence.get("capture")
        if result.outcome is not None and result.outcome.value == "APPLIED" and isinstance(capture, dict):
            path = Path(str(capture.get("path") or ""))
            if path.is_file():
                value.pop("output", None)
                return value, Image(path=path, format="png")
        return value

    def make_executor(capability: str) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        async def execute(
            work_id: str,
            operation_id: str,
            arguments: dict[str, Any],
            approval_ref: str | None = None,
        ) -> dict[str, Any]:
            selected = capability
            if selected == "relay_browser" and str(arguments.get("command") or "").strip().lower() in {"send", "create-and-send"}:
                raise ValueError("RCC_LEGACY_PUBLIC_COMMAND_REMOVED:use send-message and create-chat-tab/create-chat-window")
            if capability == "test" and arguments.get("operation") == "verify":
                selected = "verify"
                arguments = {key: value for key, value in arguments.items() if key != "operation"}
            background = (
                selected == "github_run_watch"
                or
                selected == "deploy"
                or selected == "verify"
                or selected == "vtl_validate"
                or (
                    selected == "orchestrate"
                    and str(arguments.get("operation") or "")
                    in {
                        "dispatch", "tool-build-request", "worker-replace", "chain-run", "chain-resume",
                        "reconcile", "recover-not-dispatched", "recover-node-sync",
                    }
                )
                or (selected == "github_pr_status" and float(arguments.get("wait_seconds", 0)) > 0)
                or (selected == "service_control" and str(arguments.get("action") or "") != "status")
            )
            started_ns = time.perf_counter_ns()
            if background:
                result = await asyncio.to_thread(
                    launch_background_operation,
                    bct,
                    principal=principal,
                    work_id=work_id,
                    operation_id=operation_id,
                    capability=selected,
                    arguments=arguments,
                    approval_ref=approval_ref,
                )
                handler_ms = (time.perf_counter_ns()-started_ns)/1e6
                _trace_stage("handler_done", tool_kind=selected, handler_ms=handler_ms, wait_ms=0.0, execution_ms=handler_ms)
                return result.as_dict()
            if selected in {"desktop_window_manage", "relay_browser"}:
                # Reuse the existing authenticated Work/Operation/Claim/Lease gateway.
                # No second executor or automatic retry of UNKNOWN effects.
                from bct.features.window_layout_commands import make_bct_operation_invoke
                invoke = make_bct_operation_invoke(
                    operations=bct.operations, principal=principal,
                    work_id=work_id, approval_ref=approval_ref,
                )
                value = await asyncio.to_thread(invoke, selected, operation_id, arguments)
                handler_ms = (time.perf_counter_ns()-started_ns)/1e6
                _trace_stage("handler_done", tool_kind=selected, handler_ms=handler_ms,
                             wait_ms=0.0, execution_ms=handler_ms)
                return value
            result = await asyncio.to_thread(
                bct.operations.run,
                principal=principal,
                work_id=work_id,
                operation_id=operation_id,
                capability=selected,
                arguments=arguments,
                approval_ref=approval_ref,
            )
            inbox_registration = None
            if selected in {"github_pr_create", "github_push"} and result.outcome.value == "APPLIED":
                try:
                    from .github_inbox_autofollow import (
                        schedule_pr_ci_inbox, schedule_main_ci_inbox,
                    )
                    scheduler = (schedule_pr_ci_inbox if selected == "github_pr_create"
                                 else schedule_main_ci_inbox)
                    inbox_registration = await asyncio.to_thread(
                        scheduler, bct, principal, work_id,
                        {**result.evidence, "repository": arguments.get("repository")},
                    )
                except Exception as exc:
                    inbox_registration = {"status": "UNAVAILABLE",
                                          "reason": type(exc).__name__}
            handler_ms = (time.perf_counter_ns()-started_ns)/1e6
            _trace_stage("handler_done", tool_kind=selected, handler_ms=handler_ms, wait_ms=0.0, execution_ms=handler_ms)
            value = result.as_dict()
            if inbox_registration is not None:
                value["inbox_registration"] = inbox_registration
            return value

        execute.__name__ = "bct_" + capability
        execute.__doc__ = f"Execute the registered BCT {capability!r} capability."
        return execute

    if compact_catalogue:
        @server.tool(
            name="bct_dispatch",
            description=(
                "Dispatch one explicitly named BCT capability through its existing "
                "Work authorization, durable Operation receipt and UNKNOWN/Claim contracts. "
                "Use bct_capabilities to discover exact names. Desktop image capture "
                "requires the original full endpoint."
            ),
            structured_output=True,
        )
        async def bct_dispatch(
            capability: str,
            work_id: str,
            operation_id: str,
            arguments: dict[str, Any],
            approval_ref: str | None = None,
        ) -> dict[str, Any]:
            if capability not in capabilities or capability in _SPECIAL_CAPABILITIES:
                return {"error": "CAPABILITY_NOT_AVAILABLE_IN_COMPACT_CATALOGUE"}
            return await make_executor(capability)(
                work_id, operation_id, arguments, approval_ref
            )
        if hybrid_catalogue:
            for exposed in ("execute", "read"):
                if exposed in capabilities:
                    server.tool(
                        name="bct_" + exposed,
                        description=(
                            f"Run BCT capability {exposed} with an exact work and operation ID. "
                            + _CAPABILITY_USAGE.get(exposed, "")
                        ),
                        structured_output=True,
                    )(make_executor(exposed))
        settings_path = getattr(bct, "mcp_catalogue_path", None)
        if settings_path is not None:
            CatalogueSettings(settings_path).attach(server)
        return server

    for capability in capabilities:
        if capability in _SPECIAL_CAPABILITIES:
            continue
        server.tool(
            name="bct_" + capability,
            description=(
                f"Run BCT capability {capability} with an exact work and operation ID. "
                + _CAPABILITY_USAGE.get(capability, "")
            ),
            structured_output=True,
        )(make_executor(capability))
    settings_path = getattr(bct, "mcp_catalogue_path", None)
    if settings_path is not None:
        CatalogueSettings(settings_path).attach(server)
    return server


class LocalBearerMiddleware:
    """Require the runtime bearer token only for the MCP protocol endpoint."""

    def __init__(self, app: Any, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and str(scope.get("path") or "").rstrip("/") == "/mcp":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            bearer = headers.get(b"authorization", b"").decode("latin-1")
            exact_token = headers.get(b"x-bct-token", b"").decode("latin-1")
            authenticated = (
                hmac.compare_digest(bearer, "Bearer " + self.token)
                or hmac.compare_digest(exact_token, self.token)
            )
            if not authenticated:
                response = JSONResponse(
                    {"error": "MCP_BEARER_TOKEN_INVALID"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        if scope.get("type") != "http" or str(scope.get("path") or "").rstrip("/") != "/mcp":
            await self.app(scope, receive, send)
            return

        # Independent random ID: no trust in caller-supplied trace headers.
        # Do not parse or log request bodies, authentication, or user content.
        trace_id = uuid.uuid4().hex
        token = _MCP_TRACE_ID.set(trace_id)
        ingress_ns = time.perf_counter_ns()
        first_response_ns = None
        if str(scope.get("method") or "").upper() == "POST":
            _trace_stage("request_ingress")

        async def traced_send(message: dict[str, Any]) -> None:
            nonlocal first_response_ns
            if message.get("type") == "http.response.start" and first_response_ns is None:
                first_response_ns = time.perf_counter_ns()
            await send(message)
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                finished_ns = time.perf_counter_ns()
                _trace_stage(
                    "response_complete",
                    asgi_total_ms=(finished_ns-ingress_ns)/1e6,
                    asgi_to_headers_ms=((first_response_ns or finished_ns)-ingress_ns)/1e6,
                )
        try:
            await self.app(scope, receive, traced_send)
        finally:
            _MCP_TRACE_ID.reset(token)
