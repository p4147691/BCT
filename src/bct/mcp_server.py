from __future__ import annotations

import asyncio
import hmac
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from mcp.server.fastmcp import FastMCP, Image
from starlette.responses import JSONResponse

from .background_operations import BACKGROUND_CAPABILITIES, launch_background_operation
from .chat_input_queue import ChatInputQueue
from .chain_entry_policy import public_entry_policy
from .component_library import DISCOVERY_GUIDE, discover
from .chain_message_preflight import (
    EXPLICIT_NEXT_TASK_SUFFIX, check_chain_work, prepare_chain_instruction,
)
from .code_block_scan import resolve_scan_root, scan as run_code_block_scan
from .code_block_organize import plan_block_replacement, prepare_block_apply
from .conversation_network import (
    ConversationNetworkError, project_view, resolve_project_id, scope_directory,
)
from .core.models import Principal, Work, PreconditionError
from .core.capabilities import capability_matches
from .mcp_catalogue_config import CatalogueSettings
from .status_views import status_view, STATUS_SCOPES
from .task_message import prepare_task_message_instruction


from .trace_timing import TRACE_ID as _MCP_TRACE_ID, trace_stage as _trace_stage

MCP_PRINCIPAL_ID = "bct-mcp-local"

_GENERAL_TOOLS = (
    "bct_capabilities", "bct_status", "queue_message", "bct_get_conversation_network", "bct_check_conversation_network", "scan_code_blocks", "organize_code_blocks",
    "bct_execution_context", "bct_set_direction", "bct_get_direction",
    "bct_prepare_supervisor_chain",
    "bct_set_execute_plan", "bct_get_execute_plan", "bct_set_project_plan",
    "bct_check_node", "bct_recheck_node", "bct_pause_node", "bct_replace_node", "bct_reset_node",
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
    "conversation_network_update": "Update advisory conversation-network membership or role tags. For an existing member use arguments={\"operation\":\"role-patch\",\"project\":\"scope name or id\",\"node_label\":\"N14\",\"add\":[\"CI\"],\"remove\":[],\"expected_role_tags_sha256\":\"digest from bct_get_conversation_network\"}. To place an observed chat in a scope use operation=membership-assign with project, conversation_key, role_tags, and expected_scope_id (empty only when the chat is currently unassigned). This changes no tool permission or browser route; it applies to newly composed messages only.",
    "project_context": "Shared, bounded context records; this does not capture browser text or send a message. Use central-get/central-save for the one current project context, worklog-get/worklog-save for a project plus journal_work_id, and overview for central context plus compact worklog records. Saves require expected_revision and author. A work log must link its exact journal_work_id as links:[{type:'bct_work',id:'...'}].",
    "cdp_inspect": "Read-only existing Chrome tab listing via a single approved Chrome DevTools MCP connection. Use arguments={\\\"operation\\\":\\\"list_pages\\\"}. Requires a work with cdp_inspect permission and locally enabled CDP policy; does not send messages, create tabs, or bypass Chrome consent.",
    "browser_extension_manage": "Read-only Chrome extension inventory via CDP. arguments={\\\"operation\\\":\\\"inventory\\\"} (or pages). Work-scoped; create/update/delete not enabled in this initial common MCP adapter. CDP only. Do not infer Tampermonkey CRUD support from this tool yet.",
    "owned_extension_action": (
        "Reload only a BCT-owned Chrome extension through an allowlisted existing contract. "
        "Monitor: arguments={\"target\":\"monitor\",\"action\":\"reload\"}. "
        "RCC: arguments={\"target\":\"rcc\",\"action\":\"reload\","
        "\"instance_id\":\"exact current RCC instance\"}. No URL, extension ID, "
        "JavaScript, DevTools method, function name, or arbitrary command is accepted. "
        "Use one operation_id and never retry UNKNOWN with a new ID."
    ),
    "browser": (
        "RCC contract rcc-send-message-v1. For ChatGPT messages use ONLY command=send-message "
        "with exact instance_id, session_id, tab_id, window_id, text, and either "
        "conversation_key (empty string for an existing blank tab) OR create_operation_id "
        "(from a verified BCT-created window/tab in the SAME Work). The Core selects the "
        "exact existing- or newly-created-target implementation under ONE BCT Operation. Never select a tab "
        "by title or order, never fall back to another send command, and NEVER retry "
        "UNKNOWN using a new operation. Use original receipt/result for recovery. "
        "create-chat-window and create-chat-tab are independent creation commands. "
        "The only caller-facing relay commands are create-chat-window, create-chat-tab, "
        "and send-message. Lower-level compatibility commands, including raw state "
        "inspection, are internal and unavailable through this tool. Use bct_status "
        "for the current BCT state."
    ),
    "relay_control": "Execute one enabled hot-read relay purpose using arguments={\"purpose\":\"selected purpose\",\"scope_id\":\"project scope\",\"context\":{...},\"expected_settings_sha256\":\"preview revision\"}. The fixed registry permits one existing BCT operation step per invocation. Settings never grant authority: the Work must contain the delegated capability such as browser or cdp_inspect. Reuse operation_id only for the exact same frozen request and never retry UNKNOWN with a new ID.",
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

# These RCC commands remain implemented only so older internal paths can be
# inspected or retired deliberately.  They are not part of the caller-facing
# MCP contract: new message work goes through the public tools below.
_SEALED_BROWSER_COMMANDS = frozenset({
    "send", "create-and-send", "result-of-create-and-send",
    "send-to-tab", "send-to-created-tab", "send-to-self", "node-continue",
    "read-latest-assistant", "state", "result", "presence",
    "tab-get", "window-get", "windows-list",
    "tab-groups-list", "tab-group-get",
    "simple-relay-bind", "simple-relay-send", "simple-relay-return",
    "reconcile-send", "reconcile-send-to-created-tab", "reconcile-create-and-send",
    "target-discover", "retire-composer-draft", "retire-recovered-execution",
    "delivery-start", "delivery-status", "delivery-response-read",
    "delivery-return", "delivery-manager-status", "delivery-cancel",
    "delivery-recovery-inspect", "delivery-preview",
})
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
            "For ordinary assigned work, begin with bct_chain_message(instruction=the request) "
            "to read current reality and enter Set Direction. Answer its internal questions as A; "
            "do not delegate that questionnaire to the user. Reuse an appropriate bounded Work "
            "or create one before effects, then use the matching bct_<capability> tools. "
            "Use bct_capabilities(query=...) to find existing parts, tool_name for the current input schema, "
            "and include_manual=true for the shared source manual. Discovery never executes tools. "
            "Reuse operation_id only for the exact same request."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )

    def _assert_node_send_allowed(work_id: str, conversation_key: str) -> None:
        # Transport-only contract tests do not construct a Store. The real
        # runtime always does and therefore always enforces this durable fence.
        if not conversation_key or not hasattr(bct, "store"):
            return
        from bct.node_recovery import NodeRecoveryLedger
        NodeRecoveryLedger(bct.store).assert_send_allowed(
            work_id=work_id, conversation_key=conversation_key,
        )

    @server.tool(description=(
        "List this runtime's actual tools and capabilities. Optional query searches reusable parts and tools; "
        "tool_name returns the exact current input schema; component_id reads one part; include_manual "
        "returns the shared Chain Message manual. Read-only, no Work required. limit/offset paginate search results."
    ), structured_output=True)
    async def bct_capabilities(query: str = "", tool_name: str = "", component_id: str = "",
                               include_manual: bool = False, limit: int = 8, offset: int = 0) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        tool_metadata = [tool.model_dump(mode="json", exclude_none=True) for tool in await server.list_tools()]
        value = {
            "capabilities": list(capabilities),
            "tools": [tool["name"] for tool in tool_metadata],
            # The live runtime contract takes precedence over client-cached tool descriptions.
            "browser_usage": _CAPABILITY_USAGE["browser"],
            "browser_contract_version": "rcc-send-message-v1",
            "browser_public_commands": ["create-chat-window", "create-chat-tab", "send-message"],
            "message_entry_policy": public_entry_policy(),
            **discover(tools=tool_metadata, capabilities=capabilities, usage=_CAPABILITY_USAGE,
                       query=query, tool_name=tool_name, component_id=component_id,
                       include_manual=include_manual, limit=limit, offset=offset),
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
        # The default status is the common current-state block.  Include the
        # current node projection (network/roles/activity) from the same
        # snapshot rather than making callers request scope=node separately.
        from bct.status_views import with_current_node_details
        snapshot = with_current_node_details(snapshot, sort_by=sort_by)
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
        snapshot = {**snapshot, "browser_usage": _CAPABILITY_USAGE["browser"]}
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
    async def bct_get_conversation_network(project: str) -> dict[str, Any]:
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

    @server.tool(description="Check Conversation Network with read-only current node/RCC evidence, durable active and closed scope directory, current supervisor readiness, and optionally authorized project-context summaries. Does not create plans, conversation networks, or messages.", structured_output=True)
    async def bct_check_conversation_network(project: str = "", sort_by: str = "number", work_id: str = "", operation_id: str = "") -> dict[str, Any]:
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        snapshot = await asyncio.to_thread(status_provider)
        nodes = status_view(snapshot, "node", sort_by=sort_by)
        rcc = status_view(snapshot, "rcc", sort_by=sort_by)
        scopes = await asyncio.to_thread(scope_directory, bct.store)
        # Candidates come from confirmed current nodes, never from guessed project IDs.
        # Historical projects need a separately authorized directory/summary lookup.
        candidates: dict[str, dict[str, str]] = {}
        current_node_items = (
            nodes.get("current_nodes", {}).get("items", [])
            if isinstance(nodes, dict) and isinstance(nodes.get("current_nodes"), dict)
            else []
        )
        supervisor_candidates: list[dict[str, Any]] = []
        for node in current_node_items:
            if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
                continue
            name = str(node.get("network") or "").strip()
            scope_id = str(node.get("network_id") or "").strip()
            if name:
                key = scope_id or name.casefold()
                candidates.setdefault(key, {"title": name, "network_id": scope_id})
            roles = node.get("roles") if isinstance(node.get("roles"), list) else []
            if any(str(role).strip().casefold() == "supervisor" for role in roles):
                supervisor_candidates.append({
                    "node_number": str(node.get("node_number") or ""),
                    "name": str(node.get("name") or ""),
                    "conversation_uuid": str(node.get("conversation_uuid") or ""),
                    "network": name,
                    "network_id": scope_id,
                    "roles": list(roles),
                    "active": node.get("active") is True,
                })
        supervisor_status = (
            "MISSING" if not supervisor_candidates else
            "PRESENT" if len(supervisor_candidates) == 1 else
            "MULTIPLE"
        )
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
                project_id = await asyncio.to_thread(
                    resolve_project_id, bct.store, project_reference=project,
                )
                raw_network = await asyncio.to_thread(
                    project_view, bct.store, project_id=project_id,
                    include_internal_identity=True,
                )
                current_keys: dict[str, list[dict[str, Any]]] = {}
                for node in current_node_items:
                    if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
                        continue
                    key = str(node.get("conversation_uuid") or "").strip()
                    if key:
                        current_keys.setdefault(key, []).append(node)
                for member in raw_network.get("members", []):
                    if not isinstance(member, dict):
                        continue
                    key = str(member.pop("_conversation_key", ""))
                    matches = current_keys.get(key, [])
                    member["current_node_presence"] = (
                        "NOT_OPEN" if not matches else
                        "CONFIRMED" if len(matches) == 1 else
                        "AMBIGUOUS"
                    )
                    if len(matches) == 1:
                        member["current_node"] = {
                            "node_number": str(matches[0].get("node_number") or ""),
                            "active": matches[0].get("active") is True,
                            "generating": matches[0].get("generating") is True,
                        }
                    else:
                        member["current_node"] = None
                network = {"status": "OK", **raw_network}
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
                "scope_directory": scopes,
                "supervisor": {
                    "status": supervisor_status,
                    "role_tag": "supervisor",
                    "candidates": supervisor_candidates,
                    "scope": "CURRENT_CONFIRMED_NODES_ONLY",
                },
                "candidates_scope": ("CURRENT_AND_HISTORICAL_AUTHORIZED"
                                     if historical_contexts_status in {"OK", "NO_CONTEXT"}
                                     else "CURRENT_CONFIRMED_NODES_ONLY"),
                "historical_contexts": historical_contexts,
                "historical_contexts_status": historical_contexts_status,
                "project_context": context, "context_status": context_status,
                "context_requires_work": bool(project and (not work_id or not operation_id)),
                "read_only": True}

    @server.tool(
        description=(
            "Store instructions in an isolated per-target FIFO inbox; never sends to ChatGPT. "
            "action=enqueue registers one stable message_id; status reads without consuming; "
            "claim returns only the next eligible instruction for a verified idle Worker; "
            "complete acknowledges that claim, hold fences uncertain work, resume only "
            "requeues a PRE_DISPATCH hold. No automatic retransmission or lease expiry. "
            "The future delivery adapter must verify exact RCC identity and its own effects."
        ),
        structured_output=True,
    )
    async def queue_message(
        work_id: str,
        target_conversation_key: str,
        action: str = "status",
        message_id: str = "",
        instruction: str = "",
        origin_conversation_key: str = "",
        claim_id: str = "",
        result_sha256: str = "",
        reason: str = "",
        hold_kind: str = "UNKNOWN",
        limit: int = 30,
    ) -> dict[str, Any]:
        work = await asyncio.to_thread(bct.store.get_work, work_id)
        if work.owner_principal_id != principal.principal_id:
            raise PermissionError("CHAT_QUEUE_WORK_OWNER_INVALID")
        if work.state != "ACTIVE":
            raise PermissionError("CHAT_QUEUE_WORK_INACTIVE")
        selected = str(action or "").strip().lower()
        if selected not in {"enqueue", "status", "claim", "complete", "hold", "resume"}:
            raise ValueError("CHAT_QUEUE_ACTION_INVALID")
        permission = "read" if selected == "status" else "orchestrate"
        if permission not in work.actions:
            raise PermissionError("CHAT_QUEUE_" + permission.upper() + "_REQUIRED")
        ledger = await asyncio.to_thread(ChatInputQueue, bct.store)
        common = {"work_id": work_id, "target_conversation_key": target_conversation_key}
        if selected == "status":
            return await asyncio.to_thread(ledger.status, **common, limit=limit)
        if selected == "enqueue":
            return await asyncio.to_thread(
                ledger.enqueue, **common, message_id=message_id,
                instruction=instruction, origin_conversation_key=origin_conversation_key,
            )
        if selected == "claim":
            return await asyncio.to_thread(ledger.claim, **common, claim_id=claim_id)
        if selected == "complete":
            return await asyncio.to_thread(
                ledger.complete, **common, message_id=message_id, claim_id=claim_id,
                result_sha256=result_sha256,
            )
        if selected == "hold":
            return await asyncio.to_thread(
                ledger.hold, **common, message_id=message_id, claim_id=claim_id,
                reason=reason, kind=hold_kind,
            )
        return await asyncio.to_thread(
            ledger.resume, **common, message_id=message_id, claim_id=claim_id,
        )

    @server.tool(
        description=(
            "Run the read-only Code Block Scan recipe inside one owned Work root. "
            "Returns a Block Map, Block Candidates, Refactor Targets, Block Cards, "
            "component-catalog candidates and a risk-ordered work list. It never edits code, "
            "registers components, runs tests, or performs organize_code_blocks."
        ),
        structured_output=True,
    )
    async def scan_code_blocks(
        work_id: str,
        root: str = "",
        max_files: int = 1000,
        max_bytes_per_file: int = 1_000_000,
        max_blocks: int = 4000,
    ) -> dict[str, Any]:
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

    @server.tool(
        description=(
            "Plan or apply one exact Code Block Scan replacement. action=plan is read-only "
            "and returns an exact block/file hash, review diff and plan hash. action=apply "
            "requires those exact hashes plus operation_id, then delegates the assembled "
            "file to BCT's existing Work-authorized atomic write primitive. It never guesses "
            "a block, rewrites on source drift, or applies more than one block."
        ),
        structured_output=True,
    )
    async def organize_code_blocks(
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
        if not hasattr(bct, "store"):
            raise RuntimeError("CODE_BLOCK_ORGANIZE_STORE_REQUIRED")
        work = await asyncio.to_thread(bct.store.get_work, work_id)
        if work.owner_principal_id != principal.principal_id:
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
        result = await make_executor("write")(
            work_id,
            operation_id,
            {key: prepared[key] for key in (
                "path", "content", "expected_sha256", "expected_absent",
            )},
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

    @server.tool(description="Compatibility name for saving an AI-authored project plan as a versioned, Work-authorized project-context ledger. This is not B's Chain Execute Plan and does not plan or execute work. Prefer bct_set_project_plan.", structured_output=True)
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
    async def bct_set_conversation_network(
        work_id: str, operation_id: str, arguments: dict[str, Any],
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        if arguments.get("operation") not in {"project-upsert", "membership-assign", "role-patch", "node-info-set", "network-name-set"}:
            return {"status": "INVALID_REQUEST", "reason": "NETWORK_SET_OPERATION_INVALID"}
        return await make_executor("conversation_network_update")(
            work_id, operation_id, arguments, approval_ref
        )

    async def _run_direction_targets(
        *, direction: dict, assessment: dict, work: Work, task_id: str,
        operation_id: str, action: str, target_conversation_key: str,
        max_generations: int,
    ) -> dict[str, Any]:
        """Compose the existing network setter and exact per-target Chain paths."""
        import hashlib
        from bct.chain_direction import (
            ChainDirectionLedger, compose_target_direction, resolve_direction_network,
            resolve_direction_target, validate_direction_assessment,
        )
        if status_provider is None:
            return {"status":"UNAVAILABLE","reason":"STATUS_PROVIDER_NOT_CONFIGURED"}
        try:
            assessment = validate_direction_assessment(assessment, decision=direction["decision"])
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        if type(max_generations) is not int or not 0 <= max_generations <= 12:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_MAX_GENERATIONS_INVALID"}
        targets = [(i, t) for i, t in enumerate(assessment["targets"], 1)
                   if not target_conversation_key or t["conversation_key"] == target_conversation_key]
        if not targets:
            return {"status":"INVALID_REQUEST","reason":"DIRECTION_TARGET_NOT_DECLARED"}
        if len(task_id) > 70 or len(operation_id) > 65:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_OPERATION_TOO_LONG"}
        try:
            for i, target in targets:
                compose_target_direction(direction=direction, target=target, task_id=f"{task_id}-{i}")
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        updates = assessment.get("network_updates", [])
        if updates and not any(capability_matches(action, "conversation_network_update") for action in work.actions):
            return {"status":"BLOCKED","reason":"DIRECTION_NETWORK_ACTION_REQUIRED"}
        # Check every required attachment BEFORE changing metadata. Role/network checks
        # follow the recorded updates, since preparing those roles is their purpose.
        before = await asyncio.to_thread(status_provider)
        try:
            required_keys = {assessment["manager_conversation_key"], assessment["supervisor_conversation_key"],
                             *(target["conversation_key"] for _, target in targets)}
            for key in required_keys:
                resolve_direction_target(snapshot=before, conversation_key=key)
        except ValueError as exc:
            return {"status":"NETWORK_PREPARATION_REQUIRED", "reason":str(exc),
                    "stage":"BEFORE_NETWORK_EFFECTS", "network_results":[],
                    "network_preparation_applied":False, "all_targets_started":False,
                    "direction_id":direction["direction_id"]}
        preparation = []
        for i, arguments in enumerate(updates, 1):
            if action == "preflight":
                continue
            # Stable across partial resumes and caller operation prefixes.
            update_id = "direction-" + hashlib.sha256(direction["direction_id"].encode()).hexdigest()[:24] + f"-network-{i}"
            result = await bct_set_conversation_network(work.work_id, update_id, arguments)
            preparation.append(result)
            if result.get("outcome") != "APPLIED":
                return {"status":"NETWORK_PREPARATION_INCOMPLETE", "network_results":preparation,
                        "stage":"NETWORK_EFFECTS", "network_preparation_applied":any(
                            item.get("outcome") == "APPLIED" for item in preparation), "all_targets_started":False,
                        "reason":"REVIEW_ORIGINAL_RECEIPT", "direction_id":direction["direction_id"]}
        snapshot = await asyncio.to_thread(status_provider)
        try:
            origin, resolved = resolve_direction_network(snapshot=snapshot, assessment=assessment, targets=targets)
        except ValueError as exc:
            return {"status":"NETWORK_PREPARATION_REQUIRED","reason":str(exc),
                    "stage":"AFTER_NETWORK_EFFECTS" if preparation else "READINESS",
                    "network_preparation_applied":bool(preparation), "all_targets_started":False,
                    "next_tool":"bct_set_conversation_network", "network_results":preparation,
                    "network_updates":updates, "direction_id":direction["direction_id"],
                    "instructions_for_a":"기록된 판단에 따라 기존 생성·복구·대화망 설정 부품으로 준비하고 같은 Direction을 다시 확인한다."}
        if action == "preflight":
            return {"status":"READY","direction_id":direction["direction_id"],
                    "targets":[{"conversation_key":target["conversation_key"], **route}
                               for _, target, route in resolved],
                    "network_updates":updates, "effects":"NONE_READ_ONLY","authorizes_send":False}
        results = []
        ledger = ChainDirectionLedger(bct.store)
        for i, target, _ in resolved:
            child_task, child_op = f"{task_id}-{i}", f"{operation_id}-{i}"
            try:
                child = await asyncio.to_thread(ledger.target_direction, direction=direction,
                                               target=target, task_id=child_task)
                if child["chain_state"] == "CHAIN_STARTED":
                    results.append({"status":"ALREADY_STARTED", "target_conversation_key":target["conversation_key"],
                                    "direction_id":child["direction_id"], "task_id":child["chain_task_id"],
                                    "operation_id":child["chain_operation_id"], "resent":False})
                    continue
                if child["chain_state"] != "NOT_PLANNED":
                    results.append({"status":"RECEIPT_REVIEW_REQUIRED", "direction_id":child["direction_id"],
                                    "task_id":child["chain_task_id"],"operation_id":child["chain_operation_id"]})
                    continue
                # A tab may have moved since other targets were prepared/sent.
                fresh = await asyncio.to_thread(status_provider)
                origin, current_targets = resolve_direction_network(
                    snapshot=fresh, assessment=assessment, targets=[(i, target)],
                )
                route = current_targets[0][2]
                if route["node_info"].get("generating") is True:
                    results.append({"status":"TARGET_BUSY","target_conversation_key":target["conversation_key"]})
                    continue
                result = await bct_chain_message(
                    work_id=work.work_id, task_id=child_task, operation_id=child_op, action="start",
                    chain_direction_id=child["direction_id"],
                    instance_id=route["instance_id"], session_id=route["session_id"],
                    target_tab_id=route["tab_id"], target_window_id=route["window_id"],
                    target_conversation_key=target["conversation_key"],
                    origin_conversation_key=assessment["manager_conversation_key"],
                    origin_instance_id=origin["instance_id"],
                    continuation_output_contract="explicit-next-task-v1", max_generations=max_generations,
                )
                results.append({**result,"target_conversation_key":target["conversation_key"],
                                "direction_id":child["direction_id"]})
            except ValueError as exc:
                results.append({"status":"BLOCKED","reason":str(exc),
                                "target_conversation_key":target["conversation_key"]})
        all_started = all(r["status"] in {"WATCHING","ALREADY_STARTED"} for r in results)
        return {"status":"STARTED" if all_started else "PARTIAL", "stage":"TARGET_DISPATCH",
                "network_preparation_applied":bool(preparation), "all_targets_started":all_started,
                "direction_id":direction["direction_id"],"network_results":preparation,"targets":results}

    @server.tool(
        name="bct_chain_message",
        description=(
            "DEFAULT ENTRY for ordinary assigned work: call with instruction only or action=prepare "
            "to read reality and conversation networks and enter the question-guided Set Direction stage. "
            "After A saves an assessment, action=start with chain_direction_id prepares its declared "
            "network updates and sends each distinct target instruction through the existing exact path. "
            "Work/task/operation identifiers are required for effects, not the initial read. Use this route "
            "unless the user explicitly asks for Task Message or Send Message. "
            "Start/status/cancel a durable one-target message continuation using "
            "existing BCT send-message, Delayed Send and their exact receipts. "
            "For start supply task_id, a unique operation_id prefix, exact RCC "
            "instance/session and canonical target_/origin_ identity fields, "
            "and the work instruction text. When chain_direction_id is supplied, "
            "its saved direction_text is the exact instruction; instruction may "
            "be omitted, and any supplied copy must match exactly. The command PREARMS BEFORE sending, "
            "then submits the reserved text under the exact planned operation ID. "
            "Status reads the owning Work's exact durable watch. "
            "Use action=preflight to verify existing Work browser authority and exact "
            "outgoing instruction digest without sending or recording an Operation. "
            "An opt-in continuation_output_contract=explicit-next-task-v1 appends an "
            "explicit SELF/MANAGER marker request to both prearm and sent text; it "
            "never creates a follow-up or relaxes response parsing. "
            "A must supply the decisions; this recipe does not contain an LLM. "
            "Existing exact-target calls still use the same send/watch path. Legacy worker_/manager_ "
            "identity fields remain accepted only for compatibility. No UNKNOWN replay."
        ),
        structured_output=True,
    )
    async def bct_chain_message(
        work_id: str = "", task_id: str = "", operation_id: str = "",
        action: str = "start",
        instance_id: str = "", session_id: str = "",
        worker_tab_id: int = 0, worker_window_id: int = 0,
        worker_conversation_key: str = "",
        manager_conversation_key: str = "",
        instruction: str = "", manager_instance_id: str = "",
        generation: int = 1, chain_direction_id: str = "",
        target_tab_id: int = 0, target_window_id: int = 0,
        target_conversation_key: str = "", origin_conversation_key: str = "",
        origin_instance_id: str = "",
        continuation_output_contract: str = "none",
        max_generations: int = 0,
        source_kind: str = "USER", source_task_id: str = "",
        source_generation: int = 0, project: str = "",
    ) -> dict[str, Any]:
        # An ordinary request can enter here before Work or targets exist.
        # The same reusable Set Direction stage also handles an exact BA/CA report.
        if action == "prepare" or (action == "start" and not task_id and not chain_direction_id):
            return await bct_set_direction(
                work_id=work_id, action="prepare", source_text=instruction,
                source_kind=source_kind, source_task_id=source_task_id,
                source_generation=source_generation, project=project,
            )
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_ID_INVALID"}
        if action == "status":
            from bct.send_delayed_message import (
                DurableWatchLedger, watch_diagnostic_for_status,
            )
            work=await asyncio.to_thread(bct.store.get_work,work_id)
            watch=await asyncio.to_thread(DurableWatchLedger(bct.store).get,task_id,generation)
            if watch is None:
                return {"status":"NOT_FOUND","task_id":task_id,"generation":generation}
            import json
            ctx=json.loads(watch.get("context_json") or "{}")
            if (ctx.get("work_id") != work.work_id
                    or ctx.get("principal_id") != work.owner_principal_id
                    or ctx.get("assignment_epoch") != work.assignment_epoch):
                return {"status":"NOT_FOUND","task_id":task_id,"generation":generation}
            planned_source = ctx.get("source_proof_kind") == "BCT_PLANNED_SOURCE_SEND"
            response_key = str(ctx.get("observed_response_turn_key") or "")
            manager_decision = watch["state"] == "MANAGER_DECISION_REQUIRED"
            return {"status":watch["state"],"task_id":task_id,
                    "generation":generation,
                    "response_turn_id":watch["response_turn_id"],
                    "observed_response_turn_key":response_key,
                    "source_send_operation_id":ctx.get("source_send_operation_id",""),
                    "source_turn_key_state": (
                        "DEFERRED_TO_VERIFIED_SEND_RECEIPT" if planned_source
                        else "BOUND" if ctx.get("source_user_turn_key") else "UNAVAILABLE"),
                    "response_turn_key_state": (
                        "BOUND" if response_key else
                        "AWAITING_VERIFIED_RESPONSE" if watch["state"] == "WATCHING"
                        else "UNAVAILABLE"),
                    "terminal_reason":ctx.get("watch_terminal_reason", ""),
                    "manager_action":ctx.get("manager_action", "") if manager_decision else "",
                    "recipe":ctx.get("recipe", ""),
                    "max_generations":ctx.get("max_generations", 0),
                    "requested_continuation_route":ctx.get(
                        "requested_continuation_route", ""),
                    "effective_continuation_route":ctx.get(
                        "effective_continuation_route", ""),
                    "continuation_route_override_reason":ctx.get(
                        "continuation_route_override_reason", ""),
                    "watch_diagnostic_reason": watch_diagnostic_for_status(
                        str(watch["state"]), ctx,
                    )}
        if action == "cancel":
            return await make_executor("browser")(
                work_id,operation_id,{"command":"delayed-send-cancel",
                 "task_id":task_id,"generation":generation})
        if action not in {"start", "preflight"}:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_ACTION_INVALID"}
        def select_identity(canonical, legacy):
            if canonical and legacy and canonical != legacy:
                return None
            return canonical or legacy
        target_tab = select_identity(target_tab_id, worker_tab_id)
        target_window = select_identity(target_window_id, worker_window_id)
        target_conversation = select_identity(target_conversation_key, worker_conversation_key)
        origin_conversation = select_identity(origin_conversation_key, manager_conversation_key)
        origin_instance = select_identity(origin_instance_id, manager_instance_id)
        if None in {target_tab, target_window, target_conversation, origin_conversation, origin_instance}:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_IDENTITY_CONFLICT"}
        send_id=operation_id+"-send"
        arm_id=operation_id+"-arm"
        if len(send_id)>80 or len(arm_id)>80:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_OPERATION_TOO_LONG"}

        # Read-only Work authority check BEFORE direction planning or prearm.
        # It never adds browser (or any other) action to an existing Work.
        if not hasattr(bct, "store"):
            if action == "preflight":
                return {"status":"UNAVAILABLE","reason":"CHAIN_MESSAGE_WORK_STORE_UNAVAILABLE"}
            # Historical transport-only unit tests instantiate no Store. A
            # production BCT runtime always has one and enforces this fence.
        else:
            try:
                work = await asyncio.to_thread(bct.store.get_work, work_id)
            except (KeyError, ValueError):
                return {"status":"BLOCKED","reason":"CHAIN_MESSAGE_WORK_NOT_FOUND"}
            permission = check_chain_work(work, principal_id=principal.principal_id)
            if permission["status"] != "READY":
                return permission

        direction = None
        supervisor_route = None
        if chain_direction_id:
            if not hasattr(bct, "store"):
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_STORE_REQUIRED"}
            if (not isinstance(chain_direction_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", chain_direction_id)):
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_ID_INVALID"}
            # Do not construct ChainDirectionLedger here: its constructor
            # creates tables. Preflight must be a pure read even for a missing
            # direction schema; start plans only after every earlier gate.
            def read_existing_direction():
                with bct.store._readonly() as db:
                    row = db.execute(
                        "SELECT * FROM chain_directions WHERE direction_id=?",
                        (chain_direction_id,),
                    ).fetchone()
                    return dict(row) if row is not None else None
            try:
                direction = await asyncio.to_thread(read_existing_direction)
            except Exception:
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_READ_UNAVAILABLE"}
            if direction is None or direction.get("work_id") != work_id:
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_NOT_FOUND"}
            if direction.get("decision") != "NEW_TASK":
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_NOT_A_NEW_TASK"}
            if (direction.get("target_conversation_key")
                    and direction["target_conversation_key"] != target_conversation):
                return {"status":"INVALID_REQUEST","reason":"DIRECTION_TARGET_IDENTITY_MISMATCH"}
            import json
            assessment = json.loads(direction.get("assessment_json") or "{}")
            if assessment:
                if (instruction or target_tab or target_window or instance_id or session_id
                        or origin_conversation or origin_instance):
                    return {"status":"INVALID_REQUEST","reason":"DIRECTION_USES_RECORDED_IDENTITIES"}
                return await _run_direction_targets(
                    direction=direction, assessment=assessment, work=work,
                    task_id=task_id, operation_id=operation_id, action=action,
                    target_conversation_key=str(target_conversation or ""),
                    max_generations=max_generations,
                )
            if instruction and instruction != direction.get("direction_text"):
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_TEXT_MISMATCH"}
            if (direction.get("chain_task_id",""), direction.get("chain_operation_id","")) not in {
                    ("",""), (task_id,operation_id)}:
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_CHAIN_CONFLICT"}
            instruction = str(direction["direction_text"])
            # A Supervisor route is prepared separately from transport.  It
            # binds a BA-derived Direction to one fresh C attachment, and the
            # normal 1:1 Chain primitive merely consumes that exact binding.
            from bct.chain_supervisor_route import ChainSupervisorRouteLedger
            try:
                supervisor_route = await asyncio.to_thread(
                    ChainSupervisorRouteLedger(bct.store).get,
                    direction_id=chain_direction_id, work_id=work_id,
                )
            except ValueError as exc:
                return {"status":"INVALID_REQUEST","reason":str(exc)}
            if supervisor_route is not None:
                # A tab/window may move between A's first preparation and the
                # eventual send.  Re-observe C at the effect boundary.  A
                # route may refresh only for the same conversation before a
                # chain has been planned; a different candidate is never an
                # implicit successor.
                if status_provider is None:
                    return {"status":"BLOCKED","reason":"SUPERVISOR_ROUTE_STATUS_UNAVAILABLE"}
                from bct.chain_supervisor_route import resolve_confirmed_supervisor
                route_snapshot = await asyncio.to_thread(status_provider)
                route_rcc_scope = status_view(route_snapshot, "rcc")
                current_target = resolve_confirmed_supervisor(
                    node_view=status_view(route_snapshot, "node"),
                    rcc_view=route_rcc_scope.get("rcc") if isinstance(route_rcc_scope, dict) else {},
                )
                if current_target.get("status") != "READY":
                    return current_target
                current_tuple = (
                    str(current_target["conversation_key"]), str(current_target["instance_id"]),
                    str(current_target["session_id"]), int(current_target["tab_id"]),
                    int(current_target["window_id"]),
                )
                bound_tuple = (
                    str(supervisor_route["conversation_key"]), str(supervisor_route["instance_id"]),
                    str(supervisor_route["session_id"]), int(supervisor_route["tab_id"]),
                    int(supervisor_route["window_id"]),
                )
                if current_tuple != bound_tuple:
                    if action == "preflight":
                        return {"status":"BLOCKED","reason":"SUPERVISOR_ROUTE_STALE_REPREPARE"}
                    try:
                        supervisor_route = await asyncio.to_thread(
                            ChainSupervisorRouteLedger(bct.store).bind,
                            direction_id=chain_direction_id, work_id=work_id,
                            target=current_target,
                        )
                    except ValueError as exc:
                        return {"status":"BLOCKED","reason":str(exc)}
                expected_origin = ""
                if direction.get("source_kind") == "MANAGER_RETURN":
                    from bct.send_delayed_message import DurableWatchLedger
                    context = await asyncio.to_thread(
                        DurableWatchLedger(bct.store).read_execution_context,
                        task_id=str(direction.get("source_task_id") or ""),
                        generation=int(direction.get("source_generation") or 0),
                    )
                    expected_origin = str(((context or {}).get("binding") or {}).get(
                        "manager_conversation_key") or "").lower()
                if expected_origin and str(origin_conversation or "").lower() != expected_origin:
                    return {"status":"INVALID_REQUEST","reason":"CHAIN_SUPERVISOR_ROUTE_ORIGIN_MISMATCH"}
                supplied = any((target_tab, target_window, target_conversation, instance_id, session_id))
                if supplied:
                    try:
                        await asyncio.to_thread(
                            ChainSupervisorRouteLedger(bct.store).assert_target,
                            direction_id=chain_direction_id, work_id=work_id,
                            conversation_key=str(target_conversation or ""),
                            instance_id=str(instance_id or ""), session_id=str(session_id or ""),
                            tab_id=target_tab, window_id=target_window,
                        )
                    except ValueError as exc:
                        return {"status":"INVALID_REQUEST","reason":str(exc)}
                target_tab = int(supervisor_route["tab_id"])
                target_window = int(supervisor_route["window_id"])
                target_conversation = str(supervisor_route["conversation_key"])
                instance_id = str(supervisor_route["instance_id"])
                session_id = str(supervisor_route["session_id"])
        if (not re.fullmatch(r"[a-f0-9]{32}",str(session_id or "")) or
                not isinstance(target_tab, int) or target_tab <= 0 or
                not isinstance(target_window, int) or target_window <= 0):
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_INPUT_INVALID"}
        try:
            prepared_text = prepare_chain_instruction(
                instruction, output_contract=continuation_output_contract,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        if type(max_generations) is not int or not 0 <= max_generations <= 12:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_MAX_GENERATIONS_INVALID"}
        outgoing_instruction = prepared_text["instruction"]
        if action == "preflight":
            return {
                "status": "READY", "work_id": work_id, "task_id": task_id,
                "target_conversation_key": target_conversation,
                "required_action": "browser",
                "continuation_output_contract": continuation_output_contract,
                "contract_appended": prepared_text["output_contract_appended"],
                "contract_suffix": EXPLICIT_NEXT_TASK_SUFFIX
                    if prepared_text["output_contract_appended"] else "",
                "outgoing_instruction_sha256": prepared_text["instruction_sha256"],
                "outgoing_instruction_characters": prepared_text["instruction_characters"],
                "max_generations": max_generations,
                "effects": "NONE_READ_ONLY", "authorizes_send": False,
            }
        if chain_direction_id:
            from bct.chain_direction import ChainDirectionLedger
            try:
                direction = await asyncio.to_thread(
                    ChainDirectionLedger(bct.store).plan_chain,
                    direction_id=chain_direction_id, work_id=work_id,
                    task_id=task_id, operation_id=operation_id,
                    instruction_text=instruction,
                )
            except ValueError as exc:
                return {"status":"INVALID_REQUEST","reason":str(exc)}
        try:
            await asyncio.to_thread(
                _assert_node_send_allowed, work_id, str(target_conversation),
            )
        except ValueError as exc:
            return {"status":"PAUSED","reason":str(exc)}
        armed=await make_executor("browser")(
            work_id,arm_id,{"command":"send-delayed-message",
             "task_id":task_id,"instance_id":instance_id,
             "conversation_key":target_conversation,
             "manager_conversation_key":origin_conversation,
             "manager_instance_id":origin_instance or instance_id,
             "planned_send_operation_id":send_id,
             "planned_send_text":outgoing_instruction,
             "exclusive_conversation_watch":True,
             "max_generations":max_generations})
        if armed.get("outcome") != "APPLIED":
            return {"status":"PREARM_FAILED","prearm":armed}
        sent=await make_executor("browser")(
            work_id,send_id,{"command":"send-message",
             "instance_id":instance_id,"session_id":session_id,
             "tab_id":target_tab,"window_id":target_window,
             "conversation_key":target_conversation,
             "text":outgoing_instruction})
        if sent.get("outcome") != "APPLIED":
            return {"status":"SEND_UNCONFIRMED","prearm":armed,
                    "send":sent,"warning":"NO_UNKNOWN_REPLAY"}
        if chain_direction_id:
            from bct.chain_direction import ChainDirectionLedger
            direction = await asyncio.to_thread(
                ChainDirectionLedger(bct.store).mark_chain_started,
                direction_id=chain_direction_id, work_id=work_id,
                task_id=task_id, operation_id=operation_id,
            )
        return {"status":"WATCHING","task_id":task_id,"generation":generation,
                "max_generations":max_generations,
                "prearm":armed,"send":sent,
                **({"chain_direction": direction} if direction is not None else {}),
                **({"supervisor_route": supervisor_route} if supervisor_route is not None else {})}

    @server.tool(
        name="bct_task_message",
        description=(
            "EXPLICIT REQUEST ONLY: Optional technical envelope for one already-planned Manager-to-Worker "
            "instruction. It composes exact Chain Message send/watch with explicit "
            "SELF/MANAGER continuation, but it does not replace A's user direction "
            "or overall plan recorded by bct_set_direction. The normal "
            "max_rounds=0 policy has no fixed limit: Worker continues only while real "
            "progress and a safe next step exist, then returns to Manager on BA. A positive "
            "max_rounds is an explicit budget. This is a 1:1 message recipe, not the overall "
            "Chain Message lifecycle, multi-worker orchestration, or automatic Manager election."
        ),
        structured_output=True,
    )
    async def bct_task_message(
        work_id: str, task_id: str, operation_id: str,
        action: str = "start",
        instance_id: str = "", session_id: str = "",
        target_tab_id: int = 0, target_window_id: int = 0,
        target_conversation_key: str = "",
        origin_conversation_key: str = "", origin_instance_id: str = "",
        instruction: str = "", acceptance: str = "",
        bb_rule: str = "Continue only with one safe, bounded next step.",
        manager_return_rule: str = "Return on completion, blockage, risk, or need for judgment.",
        max_rounds: int = 0, generation: int = 1,
    ) -> dict[str, Any]:
        if action in {"status", "cancel"}:
            result = await bct_chain_message(
                work_id=work_id, task_id=task_id, operation_id=operation_id,
                action=action, generation=generation,
            )
            return {
                **result, "recipe": "Task Message",
                "max_rounds": result.get("max_generations", max_rounds),
            }
        if action not in {"start", "preflight"}:
            return {"status":"INVALID_REQUEST","reason":"TASK_MESSAGE_ACTION_INVALID"}
        try:
            prepared = prepare_task_message_instruction(
                instruction, acceptance=acceptance, bb_rule=bb_rule,
                manager_return_rule=manager_return_rule, max_rounds=max_rounds,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        result = await bct_chain_message(
            work_id=work_id, task_id=task_id, operation_id=operation_id,
            action=action, instance_id=instance_id, session_id=session_id,
            target_tab_id=target_tab_id, target_window_id=target_window_id,
            target_conversation_key=target_conversation_key,
            origin_conversation_key=origin_conversation_key,
            origin_instance_id=origin_instance_id,
            instruction=str(prepared["instruction"]), generation=generation,
            continuation_output_contract="explicit-next-task-v1",
            max_generations=max_rounds,
        )
        return {
            **result,
            "recipe": "Task Message",
            "max_rounds": max_rounds,
            "task_instruction_sha256": prepared["instruction_sha256"],
        }

    @server.tool(
        name="bct_task_run",
        description=(
            "Dispatch ONE worker task in an already prepared orchestration session. "
            "Uses existing authorized orchestrate dispatch and durable receipts. "
            "Requires exact session_id, manager_epoch, assignment_id, "
            "worker_node_id, attachment_id, instruction and acceptance. "
            "Run session-start and node-sync separately first. "
            "Chain Run remains a separate unfinished feature."
        ),
        structured_output=True,
    )
    async def bct_task_run(
        work_id: str, operation_id: str, arguments: dict[str, Any],
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        if arguments.get("operation", "dispatch") != "dispatch":
            return {"status": "INVALID_REQUEST", "reason": "TASK_RUN_OPERATION_MISMATCH"}
        return await make_executor("orchestrate")(
            work_id, operation_id, {**arguments, "operation": "dispatch"}, approval_ref
        )

    @server.tool(
        name="bct_send_delayed_message",
        description=(
            "Prearm one Send Delayed Message for the worker's current response. "
            "On the first turn supply the exact RCC instance, worker conversation "
            "and manager conversation. Later SELF turns need only work_id, "
            "operation_id and task_id. The Core waits for a completed response "
            "then sends its final NEXT TASK — SELF/MANAGER instruction. "
            "For a BCT-initiated message, first prearm with "
            "planned_send_operation_id and planned_send_text, then submit "
            "that exact text once using send-message and the reserved ID. "
            "A late prearm after the matching reply is terminal is rejected."
        ),
        structured_output=True,
    )
    async def bct_send_delayed_message(
        work_id: str, task_id: str, operation_id: str = "",
        instance_id: str = "", conversation_key: str = "",
        manager_conversation_key: str = "", manager_instance_id: str = "",
        planned_send_operation_id: str = "", planned_send_text: str = "",
    ) -> dict[str, Any]:
        guarded_conversation = conversation_key
        try:
            if guarded_conversation:
                await asyncio.to_thread(
                    _assert_node_send_allowed, work_id, guarded_conversation,
                )
            elif hasattr(bct, "store"):
                from bct.node_recovery import NodeRecoveryLedger
                await asyncio.to_thread(
                    NodeRecoveryLedger(bct.store).assert_task_send_allowed,
                    work_id=work_id, task_id=task_id,
                )
        except ValueError as exc:
            return {"status":"PAUSED","reason":str(exc)}
        generated = operation_id or ("send-delayed-" + uuid.uuid4().hex[:24])
        return await make_executor("browser")(
            work_id, generated,
            {"command":"send-delayed-message","task_id":task_id,
             "instance_id":instance_id,"conversation_key":conversation_key,
             "manager_conversation_key":manager_conversation_key,
             "manager_instance_id":manager_instance_id,
             "planned_send_operation_id":planned_send_operation_id,
             "planned_send_text":planned_send_text},
        )

    @server.tool(
        name="bct_send_message",
        description=(
            "EXPLICIT REQUEST ONLY: send one exact message to an existing ChatGPT conversation or to a "
            "BCT-created chat target. This is an exact-message transport component, "
            "not the default route for ordinary work, A's user-direction, or whole Chain Message recipe. It preserves the "
            "existing exact identity, receipt, and UNKNOWN-no-replay contract; "
            "internally it uses the browser capability."
        ),
        structured_output=True,
    )
    async def bct_send_message(
        work_id: str, operation_id: str, instance_id: str, session_id: str,
        tab_id: int, window_id: int, conversation_key: str, text: str,
        create_operation_id: str = "", approval_ref: str | None = None,
    ) -> dict[str, Any]:
        arguments = {
            "command": "send-message", "instance_id": instance_id,
            "session_id": session_id, "tab_id": tab_id, "window_id": window_id,
            "conversation_key": conversation_key, "text": text,
        }
        if create_operation_id:
            arguments["create_operation_id"] = create_operation_id
        return await make_executor("browser")(
            work_id, operation_id, arguments, approval_ref,
        )

    @server.tool(
        name="bct_move_tab",
        description=(
            "Move one exact ChatGPT tab to an exact target Chrome window and "
            "position. Requires the current tab identity plus either its "
            "conversation UUID or its verified BCT creation receipt."
        ),
        structured_output=True,
    )
    async def bct_move_tab(
        work_id: str, operation_id: str, instance_id: str, session_id: str,
        tab_id: int, window_id: int, target_window_id: int, index: int,
        conversation_key: str = "", create_operation_id: str = "",
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        return await make_executor("browser")(
            work_id, operation_id,
            {
                "command": "move-tab", "instance_id": instance_id,
                "session_id": session_id, "tab_id": tab_id, "window_id": window_id,
                "target_window_id": target_window_id, "index": index,
                "conversation_key": conversation_key,
                "create_operation_id": create_operation_id,
            }, approval_ref,
        )

    @server.tool(
        name="bct_close_tab",
        description=(
            "Close one exact ChatGPT conversation tab. Requires exact RCC "
            "instance, session, window, tab, and conversation UUID. UNKNOWN is "
            "preserved and never retried as a new close."
        ),
        structured_output=True,
    )
    async def bct_close_tab(
        work_id: str, operation_id: str, instance_id: str, session_id: str,
        tab_id: int, window_id: int, conversation_key: str,
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        return await make_executor("browser")(
            work_id, operation_id,
            {
                "command": "close-conversation-tab", "instance_id": instance_id,
                "session_id": session_id, "tab_id": tab_id, "window_id": window_id,
                "conversation_key": conversation_key,
            }, approval_ref,
        )

    @server.tool(
        name="bct_execution_context",
        description=(
            "Read one exact 1:1 continuation's durable execution context without "
            "sending, waking, or re-deciding it. The result contains the prior B "
            "turn's recorded SELF/MANAGER direction, its result evidence, and the "
            "same Work/assignment binding. Use generation=0 for the latest recorded "
            "decision, or name one exact generation."
        ),
        structured_output=True,
    )
    async def bct_execution_context(
        work_id: str, task_id: str, generation: int = 0,
    ) -> dict[str, Any]:
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or generation < 0):
            return {"status": "INVALID_REQUEST", "reason": "EXECUTION_CONTEXT_INPUT_INVALID"}
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
            from bct.send_delayed_message import DurableWatchLedger
            context = await asyncio.to_thread(
                DurableWatchLedger(bct.store).read_execution_context,
                task_id=task_id,
                generation=None if generation == 0 else generation,
            )
        except KeyError:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        if context is None:
            return {"status": "NOT_FOUND", "task_id": task_id,
                    "generation": generation or None}
        binding = context.get("binding") or {}
        if (binding.get("work_id") != work.work_id
                or binding.get("principal_id") != work.owner_principal_id
                or binding.get("assignment_epoch") != work.assignment_epoch):
            return {"status": "NOT_FOUND", "task_id": task_id,
                    "generation": context["generation"]}
        # The full binding contains only the exact existing target identity and
        # is needed by a later, separately authorized wake-delivery adapter.
        return {"status": "OK", "execution": context}

    def _current_node_evidence(conversation_key: str) -> dict[str, Any]:
        if status_provider is None:
            raise ValueError("NODE_RECOVERY_STATUS_UNAVAILABLE")
        from bct.node_recovery import observe_node
        return observe_node(status_view(status_provider(), "node"), conversation_key)

    async def _recovery_work(work_id: str):
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except KeyError as exc:
            raise ValueError("WORK_NOT_FOUND") from exc
        if work.owner_principal_id != principal.principal_id:
            raise ValueError("WORK_NOT_FOUND")
        return work

    @server.tool(
        name="bct_check_node",
        description=(
            "Check one exact node without sending or changing it. Stores a bounded "
            "observation case and returns OK, WAIT, or CHECK plus exact evidence. "
            "BCT does not decide replacement."
        ),
        structured_output=True,
    )
    async def bct_check_node(
        work_id: str, conversation_key: str, task_id: str = "", case_id: str = "",
    ) -> dict[str, Any]:
        from bct.node_recovery import NodeRecoveryLedger
        work = await _recovery_work(work_id)
        case_id = case_id or ("node-recovery-" + uuid.uuid4().hex[:24])
        try:
            result = await asyncio.to_thread(
                NodeRecoveryLedger(bct.store).check,
                work=work, case_id=case_id, task_id=task_id,
                conversation_key=conversation_key,
                evidence=_current_node_evidence(conversation_key), kind="CHECK",
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "check_node": result}

    @server.tool(
        name="bct_recheck_node",
        description=(
            "Recheck the same exact node case after the caller's Delayed Send/wait "
            "boundary. Compares durable evidence and suggests CONTINUE, RECHECK, or "
            "PAUSE_REVIEW; it does not send, pause, or replace by itself."
        ),
        structured_output=True,
    )
    async def bct_recheck_node(work_id: str, case_id: str) -> dict[str, Any]:
        from bct.node_recovery import NodeRecoveryLedger
        work = await _recovery_work(work_id)
        ledger = NodeRecoveryLedger(bct.store)
        case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
        if case is None:
            return {"status": "NOT_FOUND", "case_id": case_id}
        try:
            result = await asyncio.to_thread(
                ledger.check, work=work, case_id=case_id,
                task_id=str(case["task_id"]),
                conversation_key=str(case["conversation_key"]),
                evidence=_current_node_evidence(str(case["conversation_key"])),
                kind="RECHECK",
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "recheck_node": result}

    @server.tool(
        name="bct_pause_node",
        description=(
            "Pause one checked node recovery case. Fences new Chain/Delayed Send "
            "delivery to the exact old conversation and pauses its WATCHING/RESERVED "
            "continuations while preserving plans, receipts, identities, and UNKNOWN evidence."
        ),
        structured_output=True,
    )
    async def bct_pause_node(work_id: str, case_id: str, reason: str) -> dict[str, Any]:
        from bct.node_recovery import NodeRecoveryLedger
        work = await _recovery_work(work_id)
        try:
            result = await asyncio.to_thread(
                NodeRecoveryLedger(bct.store).pause,
                work=work, case_id=case_id, reason=reason,
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "pause_node": result}

    @server.tool(
        name="bct_replace_node",
        description=(
            "Stage or commit replacement of one PAUSED node. action=prepare records an "
            "exact healthy successor and returns an inheritance instruction; action=start "
            "also sends that instruction through Chain Message using exact RCC identities; "
            "action=commit succeeds only after the successor's inheritance watch exists. "
            "No UNKNOWN effect is replayed and BCT never chooses the successor."
        ),
        structured_output=True,
    )
    async def bct_replace_node(
        work_id: str, case_id: str, successor_conversation_key: str = "",
        inheritance_task_id: str = "", action: str = "status",
        operation_id: str = "", instance_id: str = "", session_id: str = "",
        target_tab_id: int = 0, target_window_id: int = 0,
        origin_conversation_key: str = "", origin_instance_id: str = "",
    ) -> dict[str, Any]:
        from bct.node_recovery import NodeRecoveryLedger
        work = await _recovery_work(work_id)
        ledger = NodeRecoveryLedger(bct.store)
        if action == "status":
            case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
            return ({"status": "NOT_FOUND", "case_id": case_id} if case is None
                    else {"status": "OK", "replace_node": case})
        if action not in {"prepare", "start", "commit"}:
            return {"status": "INVALID_REQUEST", "reason": "NODE_REPLACEMENT_ACTION_INVALID"}
        if action == "start" and not operation_id:
            return {"status": "INVALID_REQUEST", "reason": "NODE_REPLACEMENT_OPERATION_REQUIRED"}
        try:
            if action in {"prepare", "start"}:
                prepared = await asyncio.to_thread(
                    ledger.prepare_replace, work=work, case_id=case_id,
                    successor_conversation_key=successor_conversation_key,
                    inheritance_task_id=inheritance_task_id,
                    successor_evidence=_current_node_evidence(successor_conversation_key),
                )
                if action == "prepare":
                    return {"status": "OK", "replace_node": prepared}
                sent = await bct_chain_message(
                    work_id=work_id, task_id=inheritance_task_id,
                    operation_id=operation_id, action="start", instance_id=instance_id,
                    session_id=session_id, target_tab_id=target_tab_id,
                    target_window_id=target_window_id,
                    target_conversation_key=successor_conversation_key,
                    origin_conversation_key=origin_conversation_key,
                    origin_instance_id=origin_instance_id,
                    instruction=str(prepared["inheritance_instruction"]),
                )
                return {"status": "INHERITANCE_SENT" if sent.get("status") == "WATCHING"
                        else "INHERITANCE_UNCONFIRMED",
                        "replace_node": prepared, "chain_message": sent}
            if action == "commit":
                current_case = await asyncio.to_thread(
                    ledger.get, work=work, case_id=case_id,
                )
                successor_key = successor_conversation_key or str(
                    (current_case or {}).get("replacement_conversation_key") or ""
                )
                result = await asyncio.to_thread(
                    ledger.commit_replace, work=work, case_id=case_id,
                    successor_evidence=_current_node_evidence(successor_key),
                )
                return {"status": "OK", "replace_node": result}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}

    @server.tool(
        name="bct_reset_node",
        description=(
            "Finish cleanup of a PAUSED or REPLACED node. action=plan stores its "
            "recoverable context before any external effect. action=apply then closes the "
            "exact tab once through the existing close contract and records RESET, "
            "RESET_FAILED, or RESET_UNKNOWN. UNKNOWN is preserved and never retried."
        ),
        structured_output=True,
    )
    async def bct_reset_node(
        work_id: str, case_id: str, action: str = "status", operation_id: str = "",
        instance_id: str = "", session_id: str = "", tab_id: int = 0,
        window_id: int = 0, conversation_key: str = "",
    ) -> dict[str, Any]:
        from bct.node_recovery import NodeRecoveryLedger
        work = await _recovery_work(work_id)
        ledger = NodeRecoveryLedger(bct.store)
        case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
        if case is None:
            return {"status": "NOT_FOUND", "case_id": case_id}
        if action == "status":
            return {"status": "OK", "reset_node": case}
        if action not in {"plan", "apply"}:
            return {"status": "INVALID_REQUEST", "reason": "NODE_RESET_ACTION_INVALID"}
        if action == "apply" and not operation_id:
            return {"status": "INVALID_REQUEST", "reason": "NODE_RESET_OPERATION_REQUIRED"}
        key = str(case["conversation_key"])
        if conversation_key and conversation_key.lower() != key:
            return {"status": "INVALID_REQUEST", "reason": "NODE_RESET_CONVERSATION_CONFLICT"}
        try:
            planned = await asyncio.to_thread(
                ledger.prepare_reset, work=work, case_id=case_id,
                node_evidence=_current_node_evidence(key),
            )
            if action == "plan":
                return {"status": "OK", "reset_node": planned}
            closed = await make_executor("browser")(
                work_id, operation_id,
                {"command": "close-conversation-tab", "instance_id": instance_id,
                 "session_id": session_id, "tab_id": tab_id, "window_id": window_id,
                 "conversation_key": key},
            )
            outcome = str(closed.get("outcome") or "UNKNOWN")
            finished = await asyncio.to_thread(
                ledger.finish_reset, work=work, case_id=case_id,
                close_outcome=outcome, operation_id=operation_id,
            )
            return {"status": "OK" if outcome == "APPLIED" else "CLOSE_" + outcome,
                    "reset_node": finished, "close": closed}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}

    @server.tool(
        name="bct_set_direction",
        description=(
            "Prepare and save A's direction. action=prepare automatically reads current BCT "
            "status, Node Info and stored conversation networks, then supplies questions for "
            "A about user intent, completion, topology, roles, multiple recipients, resources, "
            "recovery and Supervisor integration. A answers them in assessment and writes "
            "direction_text; action=save validates and records those decisions and each target's "
            "distinct instruction. B later authors its concrete Execute Plan. No send at this stage. Use "
            "source_kind=MANAGER_RETURN only with the exact BA task/generation that "
            "supplied the report."
        ),
        structured_output=True,
    )
    async def bct_set_direction(
        work_id: str = "", direction_text: str = "", decision: str = "",
        source_kind: str = "USER", source_task_id: str = "",
        source_generation: int = 0, direction_id: str = "",
        action: str = "save", source_text: str = "", project: str = "",
        assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from bct.chain_direction import ChainDirectionLedger, prepare_direction_review
        if action not in {"prepare", "save"}:
            return {"status":"INVALID_REQUEST","reason":"DIRECTION_ACTION_INVALID"}
        if action == "prepare" and source_kind == "USER" and not work_id:
            work = None
        else:
            try:
                work = await asyncio.to_thread(bct.store.get_work, work_id)
            except KeyError:
                return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
            if work.owner_principal_id != principal.principal_id:
                return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        if not direction_id:
            direction_id = "direction-" + uuid.uuid4().hex[:24]
        result_sha = ""
        context = None
        if source_kind == "MANAGER_RETURN":
            from bct.send_delayed_message import DurableWatchLedger
            delayed_ledger = DurableWatchLedger(bct.store)
            context = await asyncio.to_thread(
                delayed_ledger.read_execution_context,
                task_id=source_task_id,
                generation=source_generation,
            )
            binding = (context or {}).get("binding") or {}
            prior = (context or {}).get("decision") or {}
            if (context is not None and binding.get("work_id") == work.work_id
                    and binding.get("principal_id") == work.owner_principal_id
                    and binding.get("assignment_epoch") == work.assignment_epoch
                    and prior.get("route") == "MANAGER"):
                result_sha = str(prior.get("response_sha256") or "")
            else:
                # Older Delayed Send returns predate the explicit B-decision
                # ledger.  They can still anchor a Chain Direction, but only
                # when the exact watch itself is durably RETURNED_TO_MANAGER
                # and carries the observed response hash.  This is a targeted
                # compatibility bridge, not natural-language reconstruction.
                row = await asyncio.to_thread(
                    delayed_ledger.get, source_task_id, source_generation,
                )
                import json
                try:
                    legacy = json.loads(str((row or {}).get("context_json") or "{}"))
                except ValueError:
                    legacy = {}
                result_sha = str(legacy.get("observed_response_sha") or "")
                if (not row or row.get("state") != "RETURNED_TO_MANAGER"
                        or legacy.get("work_id") != work.work_id
                        or legacy.get("principal_id") != work.owner_principal_id
                        or legacy.get("assignment_epoch") != work.assignment_epoch
                        or not re.fullmatch(r"[0-9a-f]{64}", result_sha)):
                    return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_RETURN_NOT_EXACT"}
        if action == "prepare":
            if status_provider is None:
                return {"status":"UNAVAILABLE","reason":"STATUS_PROVIDER_NOT_CONFIGURED"}
            snapshot = await asyncio.to_thread(status_provider)
            network = await bct_check_conversation_network(project=project)
            monitor = snapshot.get("monitor", {})
            reality = {
                "core": snapshot.get("core", {}), "runtime": snapshot.get("runtime", {}),
                "observed_at": monitor.get("generated_at"),
                "available_works": [entry for entry in monitor.get("works", [])
                                    if entry.get("owner_principal_id") == principal.principal_id],
                "work": ({"work_id": work.work_id, "state": work.state,
                          "request_summary": work.request_summary, "roots": list(work.roots),
                          "actions": sorted(work.actions)} if work else None),
                "operations": monitor.get("operations", []),
                "unresolved_claims": monitor.get("unresolved_claims", []),
                "github_run_inbox": monitor.get("github_run_inbox", []),
            }
            try:
                review = prepare_direction_review(
                    source_text=source_text, source_kind=source_kind, reality=reality,
                    network=network, source_return=context,
                    available_tools=[tool.name for tool in await server.list_tools()],
                )
                review["resource_discovery"] = DISCOVERY_GUIDE
            except (ValueError, PreconditionError) as exc:
                return {"status":"INVALID_REQUEST","reason":str(exc)}
            return {**review, "work_id": work_id, "direction_id": direction_id,
                    "source_task_id": source_task_id, "source_generation": source_generation,
                    "source_result_sha256": result_sha}
        if assessment is not None:
            from bct.chain_direction import validate_direction_assessment
            from bct.features.conversation_network import ConversationNetworkUpdateFeature
            try:
                assessment = validate_direction_assessment(assessment, decision=decision)
                for arguments in assessment.get("network_updates", []):
                    if not isinstance(arguments, dict):
                        raise ValueError("DIRECTION_NETWORK_UPDATE_INVALID")
                    if arguments.get("operation") == "node-info-set" and (
                            "expected_scope_id" not in arguments
                            or not re.fullmatch(r"[0-9a-f]{64}", str(arguments.get("expected_role_tags_sha256", "")))):
                        raise ValueError("DIRECTION_NETWORK_OBSERVATION_REQUIRED")
                    ConversationNetworkUpdateFeature(bct.store).prepare(work=work, arguments=arguments)
            except (ValueError, PreconditionError) as exc:
                return {"status":"INVALID_REQUEST","reason":str(exc)}
        try:
            direction = await asyncio.to_thread(
                ChainDirectionLedger(bct.store).save,
                direction_id=direction_id, work_id=work_id,
                source_kind=source_kind, source_task_id=source_task_id,
                source_generation=source_generation,
                source_result_sha256=result_sha, decision=decision,
                direction_text=direction_text,
                assessment=assessment,
                source_text=source_text,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        return {"status":"OK","chain_direction":direction}

    @server.tool(
        name="bct_get_direction",
        description="Read one exact A-authored Chain Direction from its owning Work. Does not send or decide.",
        structured_output=True,
    )
    async def bct_get_direction(work_id: str, direction_id: str) -> dict[str, Any]:
        from bct.chain_direction import ChainDirectionLedger
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except KeyError:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        if work.owner_principal_id != principal.principal_id:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        direction = await asyncio.to_thread(
            ChainDirectionLedger(bct.store).get, direction_id=direction_id,
        )
        if direction is None or direction.get("work_id") != work.work_id:
            return {"status":"NOT_FOUND","direction_id":direction_id}
        return {"status":"OK","chain_direction":direction}

    @server.tool(
        name="bct_prepare_supervisor_chain",
        description=(
            "Prepare A→C only after A has saved a NEW_TASK Direction anchored to an exact BA "
            "Manager return. Reads the fresh current node/RCC observation, requires exactly one "
            "open global Supervisor, and binds that exact C conversation/tab/session to the Direction. "
            "It never creates a role, elects a Supervisor, sends a message, or guesses a stopped node. "
            "Call bct_chain_message with this direction afterward; a changed tab can be prepared again "
            "before sending, but a different C requires a new A Direction."
        ),
        structured_output=True,
    )
    async def bct_prepare_supervisor_chain(work_id: str, direction_id: str) -> dict[str, Any]:
        if status_provider is None:
            return {"status":"UNAVAILABLE","reason":"SUPERVISOR_ROUTE_STATUS_UNAVAILABLE"}
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except KeyError:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        if work.owner_principal_id != principal.principal_id:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        from bct.chain_supervisor_route import (
            ChainSupervisorRouteLedger, resolve_confirmed_supervisor,
        )
        snapshot = await asyncio.to_thread(status_provider)
        rcc_scope = status_view(snapshot, "rcc")
        target = resolve_confirmed_supervisor(
            node_view=status_view(snapshot, "node"),
            rcc_view=rcc_scope.get("rcc") if isinstance(rcc_scope, dict) else {},
        )
        if target.get("status") != "READY":
            return target
        try:
            route = await asyncio.to_thread(
                ChainSupervisorRouteLedger(bct.store).bind,
                direction_id=direction_id, work_id=work_id, target=target,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        return {"status":"READY","supervisor_route":route}

    @server.tool(
        name="bct_set_execute_plan",
        description=(
            "Save B's concrete execution plan after an exact A Direction has already "
            "been delivered by Chain Message. A's direction supplies the goal and "
            "boundaries; B's plan supplies the files, tools, checks, and safe next "
            "steps. BCT stores it but never writes or executes it."
        ),
        structured_output=True,
    )
    async def bct_set_execute_plan(
        work_id: str, direction_id: str, task_id: str, plan_text: str,
        generation: int = 1, plan_id: str = "",
    ) -> dict[str, Any]:
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        if not plan_id:
            plan_id = "chain-execution-plan-" + uuid.uuid4().hex[:18]
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except KeyError:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        if work.owner_principal_id != principal.principal_id:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        try:
            plan = await asyncio.to_thread(
                ChainExecutionPlanLedger(bct.store).save,
                plan_id=plan_id, work_id=work_id, direction_id=direction_id,
                task_id=task_id, generation=generation, plan_text=plan_text,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        return {"status":"OK","chain_execution_plan":plan}

    @server.tool(
        name="bct_get_execute_plan",
        description="Read one exact B-authored Chain Execution Plan. Does not send, plan, or decide.",
        structured_output=True,
    )
    async def bct_get_execute_plan(work_id: str, plan_id: str) -> dict[str, Any]:
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except KeyError:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        if work.owner_principal_id != principal.principal_id:
            return {"status":"NOT_FOUND","reason":"WORK_NOT_FOUND"}
        plan = await asyncio.to_thread(
            ChainExecutionPlanLedger(bct.store).get, plan_id=plan_id,
        )
        if plan is None or plan.get("work_id") != work.work_id:
            return {"status":"NOT_FOUND","plan_id":plan_id}
        return {"status":"OK","chain_execution_plan":plan}

    @server.tool(
        name="bct_delayed_send_cancel",
        description="Cancel exactly one WATCHING Delayed Send task generation in its owning Work.",
        structured_output=True,
    )
    async def bct_delayed_send_cancel(
        work_id: str, task_id: str, generation: int, operation_id: str = "",
    ) -> dict[str, Any]:
        generated = operation_id or ("delayed-cancel-" + uuid.uuid4().hex[:24])
        return await make_executor("browser")(
            work_id, generated,
            {"command":"delayed-send-cancel","task_id":task_id,
             "generation":generation},
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
        name="bct_set_project_plan",
        description=(
            "Save a generic project-plan ledger. This is separate from B's Chain "
            "Execute Plan and does not execute work."
        ),
        structured_output=True,
    )
    async def bct_set_project_plan(
        work_id: str, operation_id: str, plan_id: str, project: str,
        objective: str, acceptance: str, steps: list[dict[str, Any]],
        author: str, expected_revision: int = 0, discretion: str = "normal",
        assumptions: list[str] | None = None, approval_ref: str | None = None,
    ) -> dict[str, Any]:
        return await bct_run_plan(
            work_id=work_id, operation_id=operation_id, plan_id=plan_id,
            project=project, objective=objective, acceptance=acceptance,
            steps=steps, author=author, expected_revision=expected_revision,
            discretion=discretion, assumptions=assumptions, approval_ref=approval_ref,
        )

    # Remaining compatibility aliases are outside the current naming cleanup.
    _canonical_command_aliases = (
        ("bct_plan_run", bct_run_plan,
         "Compatibility name for bct_set_project_plan. It saves a generic project-plan ledger; it does not run a plan."),
        ("bct_run_task", bct_task_run,
         "Run one task in a prepared session. Canonical name; bct_task_run remains a compatibility alias."),
        ("bct_context", bct_execution_context,
         "Show one execution's complete continuation context. Canonical name; bct_execution_context remains a compatibility alias."),
        ("bct_cancel_delayed_send", bct_delayed_send_cancel,
         "Cancel one delayed send. Canonical name; bct_delayed_send_cancel remains a compatibility alias."),
        ("bct_create_work", bct_work_create,
         "Create or recover one Work. Canonical name; bct_work_create remains a compatibility alias."),
        ("bct_operation", bct_operation_get,
         "Show one operation receipt. Canonical name; bct_operation_get remains a compatibility alias."),
        ("bct_github_inbox", bct_github_inbox_get,
         "Show GitHub completion notifications. Canonical name; bct_github_inbox_get remains a compatibility alias."),
        ("bct_inbox", bct_inbox_get,
         "Show inbox notifications. Canonical name; bct_inbox_get remains a compatibility alias."),
    )
    for _canonical_name, _legacy_handler, _canonical_description in _canonical_command_aliases:
        server.tool(
            name=_canonical_name, description=_canonical_description,
            structured_output=True,
        )(_legacy_handler)

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
            if selected == "browser" and str(arguments.get("command") or "").strip().lower() in _SEALED_BROWSER_COMMANDS:
                raise ValueError("RCC_INTERNAL_COMMAND_UNAVAILABLE:use create-chat-window, create-chat-tab, send-message, or bct_send_delayed_message")
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
            if selected in {"desktop_window_manage", "browser"}:
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
