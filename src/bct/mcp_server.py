from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from mcp.server.fastmcp import FastMCP, Image
from starlette.responses import JSONResponse

from .background_operations import BACKGROUND_CAPABILITIES, launch_background_operation
from .chat_input_queue import ChatInputQueue
from .chain_entry_policy import public_entry_policy
from .component_library import DISCOVERY_GUIDE, discover, get_manual_guidance
from .chain_message_preflight import (
    EXPLICIT_NEXT_TASK_SUFFIX, check_chain_work, prepare_chain_instruction,
)
from .code_block_scan import resolve_scan_root, scan as run_code_block_scan
from .code_block_organize import plan_block_replacement, prepare_block_apply
from .conversation_network import (
    ConversationNetworkError, conversation_scope_directory, project_view,
    resolve_project_id, scope_directory,
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
    "bct_execution_context", "bct_set_direction", "bct_get_direction", "bct_chain_branch",
    "bct_set_execute_plan", "bct_get_execute_plan", "bct_set_project_plan",
    "bct_check_node", "bct_recheck_node", "bct_pause_node", "bct_replace_node", "bct_reset_node",
    "bct_work_create", "bct_operation_get",
)
_CAPABILITY_USAGE = {
    "test": "Run existing py_compile/unittest checks. Cached catalogues can submit a bounded verification recipe using arguments.operation=verify plus steps; each child is checked against the authenticated principal and current policy.",
    "verify": "Run up to 8 read metadata, test, or github_pr_status steps, or a fixed versioned recipe. Each step is durably journaled and authorized against the authenticated principal and current policy. Background operation; retrieve receipt and step_journal with bct_operation_get(wait_seconds=25). No file bodies or test output are persisted.",
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
        "RCC direct-command contract rcc-browser-command-v2. Discover every callable command with "
        "bct_rcc_command_catalog and visible command sequences with bct_rcc_recipe_catalog; invoke each "
        "step explicitly through bct_browser(arguments.command=...). Commands are not hidden by role or "
        "ownership. Effects still require their exact target identity and one Operation receipt: never select "
        "a tab by title or order, never substitute another conversation UUID, and NEVER retry UNKNOWN using "
        "a new operation. Use the original receipt/result for reconciliation."
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
            "For ordinary assigned work, begin with bct_chain_recipe(instruction=the request) "
            "to read current reality and enter the Chain Recipe Direction R stage. A writes the "
            "refined direction; do not delegate its internal judgment to the user. Reuse an appropriate bounded Work "
            "or create one before effects, then use the matching bct_<capability> tools. "
            "Use bct_capabilities(query=...) to find existing parts, tool_name for the current input schema, "
            "and include_manual=true for the shared source manual. Before using unfamiliar commands, "
            "read their current tool_name contract instead of asking the user to explain BCT. "
            "Chain prepare and capabilities include manual_guidance; "
            "tool_name=bct_chain_recipe also returns the full shared manual. Discovery never executes tools. "
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

    async def input_recipe(
        *,
        work_id: str,
        source_kind: str,
        source_task_id: str,
        source_generation: int,
        source_text: str,
        allow_unbound_user: bool,
        require_source_text: bool,
    ) -> dict[str, Any]:
        """Run the read-only input-confirmation part of the Chain Recipe.

        This deliberately does not observe runtime state, create a Direction,
        or send a message.  A returned report is accepted only when its exact
        delayed-watch evidence belongs to the supplied Work.
        """
        if source_kind not in {"USER", "MANAGER_RETURN"}:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_STATE_INVALID"}
        if require_source_text and source_kind == "USER" and (
            not source_text.strip() or len(source_text) > 12000
        ):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_SOURCE_TEXT_REQUIRED"}

        work = None
        if not (allow_unbound_user and source_kind == "USER" and not work_id):
            try:
                work = await asyncio.to_thread(bct.store.get_work, work_id)
            except KeyError:
                return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
            if work.owner_principal_id != principal.principal_id:
                return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}

        result_sha = ""
        context = None
        if source_kind == "MANAGER_RETURN":
            # A return cannot be unbound: its Work, Task, generation, and
            # durable response hash are the evidence that it is a real BA/CA
            # return rather than caller-supplied prose.
            if work is None:
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_RETURN_NOT_EXACT"}
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
                    return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_RETURN_NOT_EXACT"}
        return {
            "status": "OK", "work": work, "source_return": context,
            "source_kind": source_kind, "source_task_id": source_task_id,
            "source_generation": source_generation,
            "source_result_sha256": result_sha,
        }

    def manager_return_chain_link_recipe(
        *, source_kind: str, work: Work | None, source_return: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Describe the exact parent link carried by one Manager return.

        A Manager return is already bound to its source Task/generation by
        Input R.  When that Task was sent through a declared Direction, retain
        that Direction as the parent of the next Manager-authored Direction.
        This is relationship evidence, not a decision about what A sends next.
        """
        if source_kind != "MANAGER_RETURN":
            return {"status": "NOT_APPLICABLE"}
        binding = (source_return or {}).get("binding") or {}
        parent_direction_id = str(binding.get("chain_direction_id") or "")
        if not parent_direction_id:
            return {
                "status": "NOT_DECLARED",
                "reason": "The exact return has no declared Chain Direction to link.",
            }
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", parent_direction_id):
            return {
                "status": "INVALID_REQUEST",
                "reason": "CHAIN_RETURN_PARENT_DIRECTION_INVALID",
            }
        if work is None or binding.get("work_id") != work.work_id:
            return {
                "status": "INVALID_REQUEST",
                "reason": "CHAIN_RETURN_PARENT_WORK_MISMATCH",
            }
        return {
            "status": "BOUND",
            "parent_direction_id": parent_direction_id,
            "parent_work_id": work.work_id,
            "parent_step_id": "MANAGER_RETURN",
            "default_branch_kind": "RESUME",
            "reason": "The next Direction is linked to the exact Task/generation return observed by Input R.",
        }

    def manager_return_save_context(
        *, return_chain_link: dict[str, Any], parent_direction_id: str,
        parent_step_id: str, branch_kind: str, branch_reason: str,
        branch_request_id: str,
    ) -> dict[str, Any]:
        """Resolve one save's parent fields without letting a return drift."""
        if return_chain_link.get("status") != "BOUND" or branch_request_id:
            return {
                "status": "OK", "parent_direction_id": parent_direction_id,
                "parent_step_id": parent_step_id, "branch_kind": branch_kind,
                "branch_reason": branch_reason,
            }
        expected_parent = str(return_chain_link["parent_direction_id"])
        expected_step = str(return_chain_link["parent_step_id"])
        if parent_direction_id and parent_direction_id != expected_parent:
            return {
                "status": "INVALID_REQUEST",
                "reason": "CHAIN_RETURN_PARENT_DIRECTION_MISMATCH",
                "expected_parent_direction_id": expected_parent,
            }
        if parent_step_id and parent_step_id != expected_step:
            return {
                "status": "INVALID_REQUEST",
                "reason": "CHAIN_RETURN_PARENT_STEP_MISMATCH",
                "expected_parent_step_id": expected_step,
            }
        return {
            "status": "OK",
            "parent_direction_id": expected_parent,
            "parent_step_id": expected_step,
            # PRIMARY describes a new root.  A bound Manager return is always
            # a continuation unless A explicitly classifies its next child.
            "branch_kind": "RESUME" if branch_kind == "PRIMARY" else branch_kind,
            "branch_reason": branch_reason or str(return_chain_link["reason"]),
        }

    def compare_current_and_stored_networks_recipe(
        *, nodes: dict[str, Any], stored_scopes: list[dict[str, object]],
        stored_nodes: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        """Compare current Node Info with durable scope metadata; never decide a topology."""
        current_items = (
            nodes.get("current_nodes", {}).get("items", [])
            if isinstance(nodes.get("current_nodes"), dict) else []
        )
        node_cards: list[dict[str, Any]] = []
        observed_by_scope: dict[str, list[str]] = {}
        for node in current_items:
            if not isinstance(node, dict):
                continue
            key = str(node.get("conversation_uuid") or "").strip().lower()
            node_number = str(node.get("node_number") or "")
            if node.get("status") != "CONFIRMED" or not key:
                node_cards.append({
                    "node_number": node_number, "conversation_key": key,
                    "comparison": "UNCONFIRMED_CURRENT_NODE",
                })
                continue
            current_scope = str(node.get("network_id") or "")
            stored = stored_nodes.get(key)
            if stored is None:
                node_cards.append({
                    "node_number": node_number, "conversation_key": key,
                    "current_scope_id": current_scope,
                    "comparison": "CURRENT_ONLY",
                })
                continue
            differences = []
            checks = (
                ("scope_id", current_scope, str(stored.get("scope_id") or "")),
                ("scope_name", str(node.get("network") or ""), str(stored.get("scope_name") or "")),
                ("roles", sorted(str(x).casefold() for x in node.get("roles", []) if str(x).strip()),
                 sorted(str(x).casefold() for x in stored.get("role_tags", []) if str(x).strip())),
                ("node_memo", str(node.get("node_memo") or ""), str(stored.get("node_memo") or "")),
                ("assigned_task", str(node.get("assigned_task") or ""), str(stored.get("assigned_task") or "")),
            )
            for field, current, durable in checks:
                if current != durable:
                    differences.append(field)
            scope_id = str(stored.get("scope_id") or current_scope)
            if scope_id:
                observed_by_scope.setdefault(scope_id, []).append(key)
            node_cards.append({
                "node_number": node_number, "conversation_key": key,
                "scope_id": scope_id,
                "comparison": "MATCH" if not differences else "MISMATCH",
                "different_fields": differences,
            })
        scope_cards = [
            {
                "scope_id": str(scope.get("scope_id") or ""),
                "scope_name": str(scope.get("scope_name") or ""),
                "stored_state": str(scope.get("state") or ""),
                "stored_member_count": int(scope.get("member_count") or 0),
                "open_member_keys": observed_by_scope.get(str(scope.get("scope_id") or ""), []),
                "current_presence": (
                    "OPEN_OBSERVED" if observed_by_scope.get(str(scope.get("scope_id") or ""))
                    else "NOT_OPEN"
                ),
            }
            for scope in stored_scopes
        ]
        return {"nodes": node_cards, "scopes": scope_cards}

    def build_current_node_info_recipe(*, snapshot: dict[str, Any], sort_by: str = "number") -> dict[str, Any]:
        """Build current-only Node/RCC evidence from one already-read snapshot."""
        nodes = status_view(snapshot, "node", sort_by=sort_by)
        rcc = status_view(snapshot, "rcc", sort_by=sort_by)
        current_node_items = (
            nodes.get("current_nodes", {}).get("items", [])
            if isinstance(nodes.get("current_nodes"), dict) else []
        )
        candidates: dict[str, dict[str, Any]] = {}
        supervisor_candidates: list[dict[str, Any]] = []
        for node in current_node_items:
            if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
                continue
            name = str(node.get("network") or "").strip()
            scope_id = str(node.get("network_id") or "").strip()
            if name:
                candidates.setdefault(scope_id or name.casefold(), {"title": name, "network_id": scope_id})
            roles = node.get("roles") if isinstance(node.get("roles"), list) else []
            if any(str(role).strip().casefold() == "supervisor" for role in roles):
                supervisor_candidates.append({
                    "node_number": str(node.get("node_number") or ""),
                    "name": str(node.get("name") or ""),
                    "conversation_uuid": str(node.get("conversation_uuid") or ""),
                    "network": name, "network_id": scope_id, "roles": list(roles),
                    "active": node.get("active") is True,
                })
        return {
            "nodes": nodes, "rcc": rcc, "current_node_items": current_node_items,
            "candidates": candidates,
            "supervisor": {
                "status": ("MISSING" if not supervisor_candidates else
                           "PRESENT" if len(supervisor_candidates) == 1 else "MULTIPLE"),
                "role_tag": "supervisor", "candidates": supervisor_candidates,
                "scope": "CURRENT_CONFIRMED_NODES_ONLY",
            },
        }

    async def read_stored_networks_recipe(
        *, current_node_items: list[dict[str, Any]], candidates: dict[str, dict[str, Any]],
        project: str = "", work_id: str = "", operation_id: str = "",
        stored_scope_directory: list[dict[str, object]] | None = None,
    ) -> dict[str, Any]:
        """Read durable network records and authorized historical context; no runtime observation."""
        scopes = (stored_scope_directory if stored_scope_directory is not None
                  else await asyncio.to_thread(scope_directory, bct.store))
        network = None
        context = None
        context_status = "NOT_REQUESTED"
        historical_contexts: list[Any] = []
        historical_contexts_status = "AUTH_CONTEXT_REQUIRED"
        if not project and work_id and operation_id:
            try:
                directory = await make_executor("project_context")(
                    work_id, operation_id, {"operation": "directory-get"},
                )
                if directory.get("outcome") == "APPLIED":
                    payload = directory.get("output") or {}
                    historical_contexts = payload.get("items", []) if isinstance(payload, dict) else []
                    historical_contexts_status = "OK" if historical_contexts else "NO_CONTEXT"
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
                project_id = await asyncio.to_thread(resolve_project_id, bct.store, project_reference=project)
                raw_network = await asyncio.to_thread(
                    project_view, bct.store, project_id=project_id, include_internal_identity=True,
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
                        "NOT_OPEN" if not matches else "CONFIRMED" if len(matches) == 1 else "AMBIGUOUS"
                    )
                    member["current_node"] = ({
                        "node_number": str(matches[0].get("node_number") or ""),
                        "active": matches[0].get("active") is True,
                        "generating": matches[0].get("generating") is True,
                    } if len(matches) == 1 else None)
                network = {"status": "OK", **raw_network}
            except (ConversationNetworkError, ValueError) as exc:
                network = {"status": "NOT_FOUND", "reason": str(exc)}
            if not work_id or not operation_id:
                context_status = "AUTH_CONTEXT_REQUIRED"
            else:
                try:
                    context = await make_executor("project_context")(
                        work_id, operation_id, {"operation": "overview-get", "project": project},
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
        return {
            "scope_directory": scopes, "network": network,
            "historical_contexts": historical_contexts,
            "historical_contexts_status": historical_contexts_status,
            "project_context": context, "context_status": context_status,
            "context_requires_work": bool(project and (not work_id or not operation_id)),
        }

    async def check_conversation_network_recipe(
        *, snapshot: dict[str, Any], project: str = "", sort_by: str = "number",
        work_id: str = "", operation_id: str = "",
    ) -> dict[str, Any]:
        """Compatibility composition of current and stored network recipes."""
        current = build_current_node_info_recipe(snapshot=snapshot, sort_by=sort_by)
        stored = await read_stored_networks_recipe(
            current_node_items=current["current_node_items"], candidates=current["candidates"],
            project=project, work_id=work_id, operation_id=operation_id,
        )
        return {
            "status": "OK", "nodes": current["nodes"], "rcc": current["rcc"],
            "network": stored["network"], "network_candidates": list(current["candidates"].values()),
            "scope_directory": stored["scope_directory"], "supervisor": current["supervisor"],
            "candidates_scope": ("CURRENT_AND_HISTORICAL_AUTHORIZED"
                                 if stored["historical_contexts_status"] in {"OK", "NO_CONTEXT"}
                                 else "CURRENT_CONFIRMED_NODES_ONLY"),
            "historical_contexts": stored["historical_contexts"],
            "historical_contexts_status": stored["historical_contexts_status"],
            "project_context": stored["project_context"], "context_status": stored["context_status"],
            "context_requires_work": stored["context_requires_work"], "read_only": True,
        }

    async def return_execute_plan_check_recipe(
        *, source_kind: str, work: Work | None, source_return: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Read plan evidence for this exact return; never create or repair it."""
        if source_kind != "MANAGER_RETURN":
            return {"status": "NOT_APPLICABLE"}
        binding = (source_return or {}).get("binding") or {}
        direction_id = str(binding.get("chain_direction_id") or "")
        task_id = str((source_return or {}).get("task_id") or "")
        generation = (source_return or {}).get("generation")
        if work is None or not direction_id or not task_id or type(generation) is not int:
            return {"status": "NOT_DECLARED"}
        if str(binding.get("work_id") or "") != work.work_id:
            return {"status": "UNAVAILABLE", "reason": "RETURN_WORK_BINDING_MISMATCH"}
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        summary = await asyncio.to_thread(
            ChainExecutionPlanLedger.read_chain_return_summary,
            store=bct.store, work_id=work.work_id, direction_id=direction_id,
            task_id=task_id, generation=generation,
        )
        return {
            "chain": {
                "work_id": work.work_id, "direction_id": direction_id,
                "task_id": task_id, "generation": generation,
            },
            **summary,
        }

    def chain_topology_preparation_recipe(*, current_items: list[dict[str, Any]]) -> dict[str, Any]:
        """Expose a deterministic, read-only candidate order for a new chain.

        This deliberately does not repurpose an active role.  It tells the
        Manager which existing conversation can safely be reused and when a
        new conversation must be created through the existing browser recipe.
        """
        global_supervisors: list[dict[str, str]] = []
        reusable_workers: list[dict[str, str]] = []
        reserved: list[dict[str, str]] = []
        for node in current_items:
            if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
                continue
            key = str(node.get("conversation_uuid") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", key):
                continue
            roles = {
                str(role).strip().casefold() for role in (node.get("roles") or [])
                if str(role).strip()
            }
            scope = str(node.get("network_id") or node.get("network") or "").strip()
            summary = {
                "conversation_key": key,
                "node_number": str(node.get("node_number") or ""),
            }
            # A global Supervisor is reusable only when it is not also an
            # operational Manager/Worker and is not tied to a project network.
            if roles == {"supervisor"} and not scope:
                global_supervisors.append(summary)
                continue
            # A Worker may be drawn only from a genuinely unassigned, idle
            # conversation.  A named task, active generation, role, or network
            # makes the node unavailable for implicit reassignment.
            if (not roles and not scope and not str(node.get("assigned_task") or "").strip()
                    and node.get("generating") is not True):
                reusable_workers.append(summary)
                continue
            if roles or scope:
                reserved.append({
                    **summary,
                    "roles": sorted(roles),
                    "scope": scope,
                    "reason": "ROLE_OR_NETWORK_ALREADY_ASSIGNED",
                })
        return {
            "status": "READY",
            "read_only": True,
            "selection_order": [
                "reuse one existing global Supervisor",
                "otherwise create one new global Supervisor",
                "reuse one unassigned idle conversation as Worker and apply the Manager's network",
                "otherwise create one new Worker and apply the Manager's network",
            ],
            "global_supervisor_candidates": global_supervisors,
            "unassigned_worker_candidates": reusable_workers,
            "reserved_nodes": reserved,
            "required_creation": {
                "supervisor": not bool(global_supervisors),
                "worker": not bool(reusable_workers),
            },
            "prohibitions": [
                "Never reuse a Manager as Worker or Supervisor.",
                "Never take a node from another conversation network as an implicit Worker.",
                "Never use a network-bound Supervisor; Supervisor is global.",
            ],
        }

    async def state_recipe(
        *, project: str = "", source_kind: str = "USER", work: Work | None = None,
        source_return: dict[str, Any] | None = None,
        report_target_conversation_key: str = "",
    ) -> dict[str, Any]:
        """Run State R with exactly one current runtime snapshot."""
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        snapshot = await asyncio.to_thread(status_provider)
        current = build_current_node_info_recipe(snapshot=snapshot)
        nodes = current["nodes"]
        monitor = snapshot.get("monitor") if isinstance(snapshot.get("monitor"), dict) else {}
        current_items = (
            nodes.get("current_nodes", {}).get("items", [])
            if isinstance(nodes.get("current_nodes"), dict) else []
        )
        current_keys = [
            str(node.get("conversation_uuid") or "").strip().lower()
            for node in current_items
            if isinstance(node, dict) and node.get("status") == "CONFIRMED"
        ]
        stored_scopes, stored_nodes = await asyncio.gather(
            asyncio.to_thread(scope_directory, bct.store),
            asyncio.to_thread(conversation_scope_directory, bct.store, conversation_keys=current_keys),
        )
        stored = await read_stored_networks_recipe(
            current_node_items=current_items, candidates=current["candidates"], project=project,
            stored_scope_directory=stored_scopes,
        )
        return_plan_check = await return_execute_plan_check_recipe(
            source_kind=source_kind, work=work, source_return=source_return,
        )
        recovery_notices: dict[str, Any] = {"status": "NOT_REQUESTED", "notices": []}
        github_ci_notices: dict[str, Any] = {"status": "NOT_REQUESTED", "notices": []}
        if report_target_conversation_key:
            if not re.fullmatch(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    report_target_conversation_key):
                return {"status": "INVALID_REQUEST", "reason": "STATE_REPORT_TARGET_ID_INVALID"}
            if work is None:
                recovery_notices = {"status": "WORK_UNAVAILABLE", "notices": []}
            else:
                from bct.send_delayed_message import DurableWatchLedger
                notices = await asyncio.to_thread(
                    DurableWatchLedger(bct.store).recovery_notices,
                    work_id=work.work_id,
                    report_target_conversation_key=report_target_conversation_key,
                )
                recovery_notices = {
                    "status": "OK", "report_target_conversation_key": report_target_conversation_key,
                    "notices": notices,
                    "next_action": "AUTHOR_RECOVER_NODE_DIRECTION" if notices else "NONE",
                }
                ci_notices = await asyncio.to_thread(
                    bct.store.get_github_run_inbox,
                    work_id=work.work_id,
                    conversation_uuid=report_target_conversation_key,
                    limit=20,
                )
                terminal_notices = [
                    notice for notice in ci_notices
                    if notice.get("state") != "WAITING_EXTERNAL"
                ]
                github_ci_notices = {
                    "status": "OK",
                    "report_target_conversation_key": report_target_conversation_key,
                    "notices": ci_notices,
                    "next_action": (
                        "REVIEW_CI_RESULT_AND_AUTHOR_NEXT_DIRECTION"
                        if terminal_notices else "NONE"
                    ),
                }
        topology_preparation = chain_topology_preparation_recipe(current_items=current_items)
        # The Manager needs a compact, receipt-backed view of the work already
        # in motion before authoring another Direction.  It is information, not
        # an authorization or a request for BCT to choose a branch.  The
        # existing Direction/branch/watch ledgers remain the only durable
        # relationship records.
        chain_work_context: dict[str, Any] = {
            "status": "NOT_APPLICABLE",
            "root_work_id": "",
            "nodes": [],
            "branch_requests": [],
            "manager_attention": [],
            "effects": "NONE_READ_ONLY",
        }
        if work is not None:
            from bct.chain_direction import ChainBranchRequestLedger
            tree = await asyncio.to_thread(
                ChainBranchRequestLedger.tree, store=bct.store,
                root_work_id=work.work_id,
            )
            chain_work_context = {"status": "OK", **tree, "effects": "NONE_READ_ONLY"}
        return {
            "status": "OK",
            "observed_at": monitor.get("generated_at"),
            "current_nodes": nodes,
            "stored_networks": stored_scopes,
            "network_comparison": compare_current_and_stored_networks_recipe(
                nodes=nodes, stored_scopes=stored_scopes, stored_nodes=stored_nodes,
            ),
            "selected_network": stored["network"],
            "project_context": stored["project_context"],
            "context_status": stored["context_status"],
            "return_execute_plan_check": return_plan_check,
            "recovery_notices": recovery_notices,
            "github_ci_notices": github_ci_notices,
            "chain_work_context": chain_work_context,
            "chain_topology_preparation": topology_preparation,
            "read_only": True,
        }

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

    async def prepare_direction_recipe(
        *, source_text: str, source_kind: str, work_id: str, source_task_id: str,
        source_generation: int, project: str, report_target_conversation_key: str = "",
    ) -> dict[str, Any]:
        """Compose Input R and State R before A writes a Direction."""
        confirmed = await input_recipe(
            work_id=work_id, source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_text=source_text, allow_unbound_user=True, require_source_text=True,
        )
        if confirmed["status"] != "OK":
            return confirmed
        state = await state_recipe(
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
            # A fresh USER NEW_TASK without structured recipients cannot ever
            # enter Send Direction R. Reject before persisting an orphaned
            # NOT_PLANNED Direction. Preserve legacy Manager-return compatibility.
            if decision == "NEW_TASK" and source_kind == "USER":
                from bct.chain_direction import direction_assessment_contract
                reason = "CHAIN_DIRECTION_ASSESSMENT_REQUIRED"
                return {
                    "status": "INVALID_REQUEST", "reason": reason,
                    "assessment_contract": direction_assessment_contract(
                        {}, reason=reason,
                    ),
                }
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

    async def record_direction(
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
                ChainDirectionLedger(bct.store).save,
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

    async def save_direction_recipe(
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
        return await record_direction(
            work=work, direction_id=direction_check["direction_id"], source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_result_sha256=source_result_sha256, decision=decision,
            direction_text=direction_text, assessment=checked_assessment, source_text=source_text,
            parent_direction_id=parent_direction_id, parent_step_id=parent_step_id,
            branch_kind=branch_kind, branch_reason=branch_reason,
            branch_request_id=branch_request_id,
        )

    @server.tool(description=(
        "List this runtime's actual tools and capabilities. Optional query searches reusable parts and tools; "
        "tool_name returns the exact current input schema; component_id reads one part; include_manual "
        "returns the shared Chain Recipe manual. manual_guidance is always included; "
        "tool_name=bct_chain_recipe automatically includes the full manual. "
        "Read-only, no Work required. limit/offset paginate search results."
    ), structured_output=True)
    async def bct_capabilities(query: str = "", tool_name: str = "", component_id: str = "",
                               include_manual: bool = False, limit: int = 8, offset: int = 0) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        tool_metadata = [tool.model_dump(mode="json", exclude_none=True) for tool in await server.list_tools()]
        from bct.features.rcc import command_catalog
        value = {
            "capabilities": list(capabilities),
            "tools": [tool["name"] for tool in tool_metadata],
            # The live runtime contract takes precedence over client-cached tool descriptions.
            "browser_usage": _CAPABILITY_USAGE["browser"],
            "browser_contract_version": "rcc-browser-command-v2",
            "browser_public_commands": [item["command"] for item in command_catalog()],
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

    def chain_recipe_outline() -> list[dict[str, Any]]:
        """One visible, non-executing map of the Chain Recipe's fixed composition."""
        return [
            {"number": 0, "name": "Input R", "kind": "partial_recipe"},
            {"number": 1, "name": "State R", "kind": "partial_recipe"},
            {"number": 2, "name": "Write Direction R", "kind": "partial_recipe"},
            {"number": 3, "name": "Save Direction R", "kind": "partial_recipe"},
            {
                "number": 4,
                "name": "Recover Node R",
                "kind": "partial_recipe",
                "optional": True,
                "effect": "runs only when A saved node_recovery with one exact node UUID; Check Node R then rereads State R",
            },
            {"number": 5, "name": "Prepare Send Direction R", "kind": "partial_recipe"},
            {
                "number": 6,
                "name": "Apply Conversation Network R",
                "kind": "partial_recipe",
                "effect": "applies only declared network updates; otherwise rechecks the current route",
            },
            {
                "number": 7,
                "name": "Send Direction R",
                "kind": "partial_recipe",
                "contains": [
                    {"name": "Check Chain Work", "kind": "block", "effect": "advisory observation only"},
                    {"name": "Read Saved Direction", "kind": "block"},
                    {"name": "Send Delayed Message", "kind": "block", "effect": "prearms the response Watch"},
                    {"name": "Send Direction Message", "kind": "block"},
                ],
                "after_response": {
                    "name": "Watch·Alarm Continuation R",
                    "kind": "partial_recipe",
                    "contains": [
                        {"name": "Watch Alarm R", "kind": "partial_recipe"},
                        {
                            "name": "Continuation R",
                            "kind": "partial_recipe",
                            "contains": [
                                {"name": "Interpret Next Task", "kind": "block"},
                                {"name": "SELF / MANAGER follow-up", "kind": "branch"},
                            ],
                        },
                    ],
                },
            },
        ]

    def chain_recipe_progress(*, completed_through: int, next_number: int | None) -> dict[str, Any]:
        """Describe recipe progress only; it never executes or selects a step."""
        outline = chain_recipe_outline()
        return {
            "completed": [stage for stage in outline if stage["number"] <= completed_through],
            "next": next((stage for stage in outline if stage["number"] == next_number), None),
        }

    async def recover_node_recipe(
        *, direction: dict[str, Any], assessment: dict[str, Any], work: Work,
    ) -> dict[str, Any]:
        """Run the declared Recover Node R boundary without choosing a repair.

        This composes Check Node R with a fresh State R read.  Pause, Replace,
        and Reset remain separately chosen recipes because they can affect an
        existing watch, a successor conversation, or a browser tab.
        """
        recovery = assessment.get("node_recovery")
        if not recovery:
            return {"status": "SKIPPED", "reason": "NODE_RECOVERY_NOT_DECLARED"}
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "NODE_RECOVERY_STATUS_UNAVAILABLE"}
        from bct.node_recovery import NodeRecoveryLedger
        key = str(recovery["conversation_key"])
        case_id = "node-recovery-" + hashlib.sha256(
            (str(direction["direction_id"]) + ":" + key).encode("utf-8")
        ).hexdigest()[:24]
        try:
            checked = await asyncio.to_thread(
                NodeRecoveryLedger(bct.store).check,
                work=work, case_id=case_id, task_id="", conversation_key=key,
                evidence=_current_node_evidence(key), kind="CHECK",
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        refreshed_state = await state_recipe(
            project="", source_kind="USER", work=work, source_return=None,
        )
        return {
            "status": "CHECKED",
            "recipe": {"name": "recover_node_recipe", "kind": "partial_recipe"},
            "recover_node": checked,
            "state": refreshed_state,
            "does_not": ["pause", "replace", "reset", "send"],
            "next": "Continue to Prepare Send Direction R; choose Pause/Replace/Reset explicitly if needed.",
        }

    @server.tool(
        name="bct_chain_recipe",
        description=(
            "Chain Recipe (full recipe). Read its manual_guidance. This entry runs Input R and State R, then presents Write Direction R "
            "plus the remaining visible recipe sequence. action=send runs the declared "
            "Send Direction R after its saved Direction and target records are available. "
            "action=provision_worker composes the existing create-chat-tab/window, "
            "send-message, delayed-response watch, set-node-info, and optional move-tab "
            "operations for one Manager-declared additional Worker. "
            "Classifies a new USER request or verifies one exact MANAGER_RETURN, then reads one current "
            "snapshot, current Node Info, durable conversation-network directory, their comparison, and "
            "an optional selected project's stored network. "
            "When report_target_conversation_key is supplied, State R also reads that exact A return "
            "conversation's Recovery Notices. action=recovery_inbox reads durable Worker MANAGER "
            "returns collected for the bound A or S, including their last execution and delivery "
            "receipts, without sending or replaying anything."
        ),
        structured_output=True,
    )
    async def bct_chain_recipe(
        source_text: str = "", source_kind: str = "USER", work_id: str = "",
        source_task_id: str = "", source_generation: int = 0, project: str = "",
        action: str = "prepare", direction_text: str = "", decision: str = "",
        direction_id: str = "", assessment: dict[str, Any] | None = None,
        task_id: str = "", operation_id: str = "", target_conversation_key: str = "",
        max_generations: int = 0, report_target_conversation_key: str = "",
        generation: int = 0,
        entry_context_id: str = "",
        worker_preparation_id: str = "",
        parent_direction_id: str = "", parent_step_id: str = "",
        branch_kind: str = "PRIMARY", branch_reason: str = "", branch_request_id: str = "",
    ) -> dict[str, Any]:
        """Run one explicit boundary of the Chain Recipe."""
        if action not in {"prepare", "save", "recover_node", "prepare_send", "apply_network", "send", "preflight", "provision_worker", "recovery_inbox", "bind_recovery_collector", "resume_manager", "ack_recovery"}:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ACTION_INVALID"}
        if action == "recovery_inbox":
            if not report_target_conversation_key:
                return {"status": "INVALID_REQUEST",
                        "reason": "CHAIN_RECOVERY_REPORT_TARGET_REQUIRED"}
            try:
                work = await asyncio.to_thread(bct.store.get_work, work_id)
            except KeyError:
                return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
            if work.owner_principal_id != principal.principal_id:
                return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
            from bct.chain_manager_recovery import ChainManagerRecoveryLedger
            from bct.send_delayed_message import DurableWatchLedger
            records = await asyncio.to_thread(
                ChainManagerRecoveryLedger(bct.store, initialize=False).inbox,
                work_id=work.work_id,
                report_target_conversation_key=report_target_conversation_key.lower(),
            )
            items = []
            for record in records:
                execution = await asyncio.to_thread(
                    DurableWatchLedger(bct.store).read_execution_context,
                    task_id=record["task_id"], generation=record["generation"],
                )
                operation = None
                if record.get("delivery_operation_id"):
                    try:
                        receipt = await asyncio.to_thread(
                            bct.store.get_operation_for,
                            operation_id=record["delivery_operation_id"],
                            work_id=work.work_id,
                            principal_id=work.owner_principal_id,
                        )
                        operation = receipt.as_dict()
                    except (KeyError, ValueError):
                        operation = None
                items.append({
                    "checkpoint": record,
                    "last_execution_result": execution,
                    "delivery_receipt": operation,
                })
            return {
                "status": "OK", "effects": "NONE_READ_ONLY",
                "collector_role": "HANDOFF_INFORMATION_ONLY",
                "does_not": ["act_as_manager", "send_message", "replay_unknown"],
                "items": items,
            }
        if action == "ack_recovery":
            if (not report_target_conversation_key
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                    or generation < 1):
                return {"status": "INVALID_REQUEST",
                        "reason": "CHAIN_RECOVERY_ACK_INPUT_REQUIRED"}
            try:
                work = await asyncio.to_thread(bct.store.get_work, work_id)
                if work.owner_principal_id != principal.principal_id:
                    raise KeyError(work_id)
                from bct.chain_manager_recovery import ChainManagerRecoveryLedger
                checkpoint = await asyncio.to_thread(
                    ChainManagerRecoveryLedger(bct.store).acknowledge,
                    work_id=work.work_id, task_id=task_id,
                    generation=generation,
                    manager_conversation_key=report_target_conversation_key.lower(),
                )
            except KeyError:
                return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
            except ValueError as exc:
                return {"status": "INVALID_REQUEST", "reason": str(exc)}
            return {
                "status": "ACKNOWLEDGED", "checkpoint": checkpoint,
                "next_safe_step": "STATE_R_THEN_MANAGER_DECIDES_NEXT_DIRECTION",
                "does_not": ["send_message", "replay_worker_task"],
            }
        if action == "resume_manager":
            if not report_target_conversation_key:
                return {"status": "INVALID_REQUEST",
                        "reason": "CHAIN_RECOVERY_MANAGER_REQUIRED"}
            try:
                work = await asyncio.to_thread(bct.store.get_work, work_id)
                if work.owner_principal_id != principal.principal_id:
                    raise KeyError(work_id)
                from bct.chain_direction import resolve_direction_target
                snapshot = await asyncio.to_thread(status_provider)
                manager = resolve_direction_target(
                    snapshot=snapshot,
                    conversation_key=report_target_conversation_key.lower(),
                )
                roles = {
                    str(value).strip().casefold()
                    for value in manager["node_info"].get("roles", [])
                }
                if "manager" not in roles or roles & {"worker", "supervisor"}:
                    raise ValueError("CHAIN_RECOVERY_MANAGER_ROLE_NOT_CONFIRMED")
                from bct.send_delayed_message import DurableWatchLedger
                watch_ledger = DurableWatchLedger(bct.store)
                active = [row for row in watch_ledger.watching(limit=100)
                          if row["context"].get("work_id") == work.work_id]
                from bct.chain_manager_recovery import ChainManagerRecoveryLedger
                recovery_ledger = ChainManagerRecoveryLedger(bct.store)
                checkpoints = await asyncio.to_thread(
                    recovery_ledger.for_work, work_id=work.work_id,
                )
                manager_scope = str(
                    manager["node_info"].get("network_id")
                    or manager["node_info"].get("network") or ""
                ).strip()
                predecessor_keys = {
                    str(row["context"].get("manager_conversation_key") or "")
                    for row in active
                }
                predecessor_keys.update(
                    str(row["active_manager_conversation_key"])
                    for row in checkpoints
                )
                worker_keys = {row["conversation_key"] for row in active}
                worker_keys.update(str(row["worker_conversation_key"])
                                   for row in checkpoints)
                supervisor_keys = {
                    str(row["context"].get("supervisor_conversation_key") or "")
                    for row in active
                }
                supervisor_keys.update(str(row["supervisor_conversation_key"])
                                       for row in checkpoints)
                if report_target_conversation_key.lower() in supervisor_keys:
                    raise ValueError("CHAIN_RECOVERY_MANAGER_IS_SUPERVISOR")
                for worker_key in worker_keys:
                    worker = resolve_direction_target(
                        snapshot=snapshot, conversation_key=worker_key,
                    )
                    worker_scope = str(
                        worker["node_info"].get("network_id")
                        or worker["node_info"].get("network") or ""
                    ).strip()
                    if not manager_scope or manager_scope != worker_scope:
                        raise ValueError("CHAIN_RECOVERY_MANAGER_WORKER_NETWORK_MISMATCH")
                succession_proofs = []
                from bct.conversation_network import manager_role_transfer_receipt
                for predecessor in sorted(predecessor_keys - {
                        "", report_target_conversation_key.lower()}):
                    proof = await asyncio.to_thread(
                        manager_role_transfer_receipt, bct.store,
                        project_id=manager_scope,
                        predecessor_conversation_key=predecessor,
                        successor_conversation_key=report_target_conversation_key.lower(),
                    )
                    if proof is None:
                        raise ValueError(
                            "CHAIN_RECOVERY_MANAGER_SUCCESSION_PROOF_REQUIRED"
                        )
                    succession_proofs.append(proof)
                binding = await asyncio.to_thread(
                    watch_ledger.resume_manager,
                    work_id=work.work_id,
                    manager_conversation_key=report_target_conversation_key.lower(),
                    manager_instance_id=manager["instance_id"],
                    succession_proofs=succession_proofs,
                )
                rebound = await asyncio.to_thread(
                    recovery_ledger.rebind_active_manager,
                    work_id=work.work_id,
                    manager_conversation_key=report_target_conversation_key.lower(),
                    succession_proofs=succession_proofs,
                )
            except KeyError:
                return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
            except ValueError as exc:
                return {"status": "INVALID_REQUEST", "reason": str(exc)}
            return {
                "status": "MANAGER_RESUMED", "binding": binding,
                "rebound_checkpoints": rebound,
                "next_safe_step": "READ_RECOVERY_INBOX_THEN_ACK_EACH_CHECKPOINT",
                "does_not": ["send_message", "replay_unknown", "act_as_supervisor"],
            }
        if action == "bind_recovery_collector":
            loaded_direction = await read_saved_direction(
                work_id=work_id, direction_id=direction_id,
            )
            if loaded_direction["status"] != "READY":
                return loaded_direction
            import json
            saved_assessment = json.loads(
                loaded_direction["direction"].get("assessment_json") or "{}"
            )
            if not saved_assessment:
                return {"status": "INVALID_REQUEST",
                        "reason": "CHAIN_RECOVERY_DIRECTION_ASSESSMENT_REQUIRED"}
            from bct.chain_direction import (
                resolve_direction_network, resolve_direction_target,
            )
            try:
                snapshot = await asyncio.to_thread(status_provider)
                resolve_direction_network(
                    snapshot=snapshot, assessment=saved_assessment, targets=[],
                )
                supervisor = resolve_direction_target(
                    snapshot=snapshot,
                    conversation_key=saved_assessment[
                        "supervisor_conversation_key"
                    ],
                )
                from bct.send_delayed_message import DurableWatchLedger
                binding = await asyncio.to_thread(
                    DurableWatchLedger(bct.store).bind_recovery_collector,
                    work_id=work_id, direction_id=direction_id,
                    manager_conversation_key=saved_assessment[
                        "manager_conversation_key"
                    ],
                    supervisor_conversation_key=saved_assessment[
                        "supervisor_conversation_key"
                    ],
                    supervisor_instance_id=supervisor["instance_id"],
                )
            except (KeyError, ValueError) as exc:
                return {"status": "INVALID_REQUEST", "reason": str(exc)}
            return {
                "status": "OK", "binding": binding,
                "does_not": ["send_message", "replay_unknown", "act_as_manager"],
            }
        if action == "provision_worker":
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,60}", worker_preparation_id)):
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_WORKER_PREPARATION_REQUIRED"}
            loaded_direction = await read_saved_direction(
                work_id=work_id, direction_id=direction_id,
            )
            if loaded_direction["status"] != "READY":
                return loaded_direction
            direction = loaded_direction["direction"]
            if direction.get("decision") != "NEW_TASK":
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
            import json
            saved_assessment = json.loads(direction.get("assessment_json") or "{}")
            matches = [item for item in saved_assessment.get("worker_preparations", [])
                       if item.get("preparation_id") == worker_preparation_id]
            if len(matches) != 1:
                return {"status": "INVALID_REQUEST",
                        "reason": "CHAIN_WORKER_PREPARATION_NOT_DECLARED"}
            work_access = await check_chain_work_access(work_id=work_id, action="start")
            work = work_access["work"]
            if work is None:
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_WORK_REQUIRED"}
            from bct.chain_worker_provision import ChainWorkerProvisionRecipe
            try:
                return await asyncio.to_thread(
                    ChainWorkerProvisionRecipe(
                        bct=bct, principal=principal, status_provider=status_provider,
                    ).run,
                    direction=direction, assessment=saved_assessment, work=work,
                    task_id=task_id, worker_preparation=matches[0],
                    max_generations=max_generations,
                )
            except ValueError as exc:
                return {"status": "INVALID_REQUEST", "reason": str(exc)}
        if action == "save":
            # Saving a Direction is not an independent ingress.  Re-run the
            # mandatory current-state read and require the continuity handle
            # returned by the same Chain Recipe entry.  No record is created
            # here when the Manager did not enter (or the relevant work tree
            # changed) first.
            if not isinstance(entry_context_id, str) or not re.fullmatch(r"entry-[0-9a-f]{24}", entry_context_id):
                return {
                    "status": "CHAIN_RECIPE_REENTER_REQUIRED",
                    "reason": "CHAIN_RECIPE_ENTRY_CONTEXT_REQUIRED",
                    "next_safe_step": "REENTER_CHAIN_RECIPE_PREPARE",
                    "does_not": ["save_direction", "send_message", "create_operation"],
                }
            prepared = await prepare_direction_recipe(
                source_text=source_text, source_kind=source_kind, work_id=work_id,
                source_task_id=source_task_id, source_generation=source_generation,
                project=project,
                report_target_conversation_key=report_target_conversation_key,
            )
            if prepared["status"] != "PREPARED":
                return prepared
            confirmed_input = prepared["confirmed_input"]
            expected_entry_context_id = prepared["entry_context_id"]
            if not hmac.compare_digest(entry_context_id, expected_entry_context_id):
                return {
                    "status": "CHAIN_RECIPE_REENTER_REQUIRED",
                    "reason": "CHAIN_RECIPE_ENTRY_CONTEXT_CHANGED",
                    "next_safe_step": "REVIEW_CURRENT_STATE_THEN_AUTHOR_DIRECTION",
                    "entry_context_id": expected_entry_context_id,
                    "input": {
                        "source_kind": source_kind,
                        "source_result_sha256": confirmed_input["source_result_sha256"],
                        "work": _work_dict(confirmed_input["work"]),
                    },
                    "state": prepared["state"],
                    "does_not": ["save_direction", "send_message", "create_operation"],
                }
            resolved_parent = manager_return_save_context(
                return_chain_link=prepared["return_chain_link"],
                parent_direction_id=parent_direction_id, parent_step_id=parent_step_id,
                branch_kind=branch_kind, branch_reason=branch_reason,
                branch_request_id=branch_request_id,
            )
            if resolved_parent["status"] != "OK":
                return resolved_parent
            saved = await save_direction_recipe(
                work=confirmed_input["work"], direction_id=direction_id, source_kind=source_kind,
                source_task_id=source_task_id, source_generation=source_generation,
                source_result_sha256=str(confirmed_input["source_result_sha256"]),
                decision=decision, direction_text=direction_text, assessment=assessment,
                source_text=source_text, parent_direction_id=resolved_parent["parent_direction_id"],
                parent_step_id=resolved_parent["parent_step_id"], branch_kind=resolved_parent["branch_kind"],
                branch_reason=resolved_parent["branch_reason"], branch_request_id=branch_request_id,
            )
            if saved.get("status") != "OK":
                return saved
            has_recovery = bool((saved["chain_direction"].get("assessment") or {}).get("node_recovery"))
            next_number = 4 if has_recovery else 5 if decision == "NEW_TASK" else None
            return {
                **saved,
                "recipe_progress": chain_recipe_progress(
                    completed_through=3,
                    next_number=next_number,
                ),
            }
        if action == "recover_node":
            loaded_direction = await read_saved_direction(work_id=work_id, direction_id=direction_id)
            if loaded_direction["status"] != "READY":
                return loaded_direction
            direction = loaded_direction["direction"]
            import json
            saved_assessment = json.loads(direction.get("assessment_json") or "{}")
            if not saved_assessment.get("node_recovery"):
                return {"status": "NOT_APPLICABLE", "reason": "NODE_RECOVERY_NOT_DECLARED"}
            work_access = await check_chain_work_access(work_id=work_id, action="start")
            work = work_access["work"]
            if work is None:
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_RECOVERY_WORK_REQUIRED"}
            recovered = await recover_node_recipe(
                direction=direction, assessment=saved_assessment, work=work,
            )
            return {
                **recovered,
                "direction_id": direction_id,
                "recipe_progress": chain_recipe_progress(completed_through=4, next_number=5),
            }
        if action == "prepare_send":
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ID_INVALID"}
            loaded_direction = await read_saved_direction(
                work_id=work_id, direction_id=direction_id,
            )
            if loaded_direction["status"] != "READY":
                return loaded_direction
            direction = loaded_direction["direction"]
            if direction.get("decision") != "NEW_TASK":
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
            import json
            saved_assessment = json.loads(direction.get("assessment_json") or "{}")
            if not saved_assessment:
                return {"status": "NOT_APPLICABLE", "reason": "CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS"}
            prepared_send = await prepare_send_direction_recipe(
                direction=direction, assessment=saved_assessment, task_id=task_id,
                operation_id=operation_id, target_conversation_key=target_conversation_key,
                max_generations=max_generations,
            )
            if prepared_send["status"] != "READY":
                return prepared_send
            return {
                "status": "READY", "direction_id": direction_id,
                "targets": [target for _, target in prepared_send["targets"]],
                "derived_dispatch": prepared_send.get("derived_dispatch"),
                "effects": "NONE_READ_ONLY", "authorizes_send": False,
                "recipe_progress": chain_recipe_progress(completed_through=5, next_number=6),
            }
        if action == "apply_network":
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ID_INVALID"}
            loaded_direction = await read_saved_direction(
                work_id=work_id, direction_id=direction_id,
            )
            if loaded_direction["status"] != "READY":
                return loaded_direction
            direction = loaded_direction["direction"]
            if direction.get("decision") != "NEW_TASK":
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
            import json
            saved_assessment = json.loads(direction.get("assessment_json") or "{}")
            if not saved_assessment:
                return {"status": "NOT_APPLICABLE", "reason": "CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS"}
            prepared_send = await prepare_send_direction_recipe(
                direction=direction, assessment=saved_assessment, task_id=task_id,
                operation_id=operation_id, target_conversation_key=target_conversation_key,
                max_generations=max_generations,
            )
            if prepared_send["status"] != "READY":
                return prepared_send
            work_access = await check_chain_work_access(work_id=work_id, action="start")
            work = work_access["work"]
            if work is None:
                return {
                    "status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_NETWORK_WORK_REQUIRED",
                    "work_observation": {key: value for key, value in work_access.items() if key != "work"},
                }
            network = await apply_conversation_network_recipe(
                direction=direction, assessment=prepared_send["assessment"], work=work,
                targets=prepared_send["targets"], action="start",
            )
            if network["status"] != "READY":
                return network
            return {
                "status": "READY", "direction_id": direction_id,
                "targets": [{"conversation_key": target["conversation_key"], **route}
                            for _, target, route in network["resolved"]],
                "network_updates": network["network_updates"],
                "network_results": network["network_results"],
                "effects": network["effects"],
                "recipe_progress": chain_recipe_progress(completed_through=6, next_number=7),
            }
        if action in {"send", "preflight"}:
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ID_INVALID"}
            loaded_direction = await read_saved_direction(
                work_id=work_id, direction_id=direction_id,
            )
            if loaded_direction["status"] != "READY":
                return loaded_direction
            direction = loaded_direction["direction"]
            if direction.get("decision") != "NEW_TASK":
                return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
            import json
            saved_assessment = json.loads(direction.get("assessment_json") or "{}")
            if not saved_assessment:
                return {"status": "NOT_APPLICABLE", "reason": "CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS"}
            work_access = await check_chain_work_access(work_id=work_id, action="start")
            work = work_access["work"]
            if work is None:
                return {
                    "status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_SEND_WORK_REQUIRED",
                    "work_observation": {key: value for key, value in work_access.items() if key != "work"},
                }
            recovered = {"status": "SKIPPED", "reason": "PREFLIGHT_READ_ONLY"}
            if action == "send":
                recovered = await recover_node_recipe(
                    direction=direction, assessment=saved_assessment, work=work,
                )
                if recovered["status"] not in {"CHECKED", "SKIPPED"}:
                    return recovered
            sent = await _run_direction_targets(
                direction=direction, assessment=saved_assessment, work=work,
                task_id=task_id, operation_id=operation_id, action=action,
                target_conversation_key=target_conversation_key,
                max_generations=max_generations,
            )
            return {
                **sent,
                "recover_node": recovered,
                "recipe_progress": chain_recipe_progress(completed_through=7, next_number=None),
            }
        prepared = await prepare_direction_recipe(
            source_text=source_text, source_kind=source_kind, work_id=work_id,
            source_task_id=source_task_id, source_generation=source_generation, project=project,
            report_target_conversation_key=report_target_conversation_key,
        )
        if prepared["status"] != "PREPARED":
            return prepared
        confirmed = prepared["confirmed_input"]
        state = prepared["state"]
        work = confirmed["work"]
        direction = write_direction_recipe(source_kind=source_kind, work=work)
        return {
            "status": "RECIPE_READY",
            "recipe": {"name": "chain_recipe", "kind": "full_recipe"},
            "recipe_outline": chain_recipe_outline(),
            "completed_stages": [
                {"number": 0, "name": "Input R"},
                {"number": 1, "name": "State R"},
                {"number": 2, "name": "Write Direction R", "status": "A_REQUIRED"},
            ],
            "next_stage": {"number": 2, "name": "Write Direction R", "status": "A_REQUIRED"},
            "input": {
                "source_kind": source_kind,
                "source_evidence": (
                    "VERIFIED_MANAGER_RETURN" if source_kind == "MANAGER_RETURN"
                    else "CALLER_PROVIDED_TEXT"
                ),
                "source_text": source_text if source_kind == "USER" else "",
                "source_return": confirmed["source_return"],
                "source_result_sha256": confirmed["source_result_sha256"],
                "work": _work_dict(work) if work is not None else None,
                "connection": "EXACT_RETURN_BOUND" if source_kind == "MANAGER_RETURN"
                              else ("WORK_BOUND" if work is not None else "UNCONNECTED"),
            },
            "state": state,
            "return_chain_link": prepared["return_chain_link"],
            "entry_context_id": prepared["entry_context_id"],
            "direction": direction,
            "read_only": True,
            "authorizes_send": False,
        }

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
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        execute_plan_checks = await asyncio.to_thread(
            ChainExecutionPlanLedger.list_latest_execute_plan_checks,
            store=bct.store, limit=5 if compact else 20,
        )
        from bct.chain_direction import ChainDirectionLedger
        pending_chain_starts = await asyncio.to_thread(
            ChainDirectionLedger.list_pending_chain_starts,
            store=bct.store, principal_id=principal.principal_id,
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
                    "SELECT work_id FROM works WHERE owner_principal_id=?", (principal.principal_id,)
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
        return await check_conversation_network_recipe(
            snapshot=snapshot, project=project, sort_by=sort_by,
            work_id=work_id, operation_id=operation_id,
        )

    @server.tool(
        description=(
            "Store instructions in an isolated per-target FIFO inbox; never sends to ChatGPT. "
            "It is a state-only ledger, not an authority or role gate: an existing active "
            "Work ID and canonical target Conversation UUID identify its partition. "
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
        if work.state != "ACTIVE":
            raise ValueError("CHAT_QUEUE_WORK_INACTIVE")
        selected = str(action or "").strip().lower()
        if selected not in {"enqueue", "status", "claim", "complete", "hold", "resume"}:
            raise ValueError("CHAT_QUEUE_ACTION_INVALID")
        # Queue operations alter only the durable queue ledger. Work actions,
        # principal ownership, and Manager/Worker role tags are not permissions
        # for that ledger. External dispatch remains separately fenced by its
        # exact target identity, operation receipt, and UNKNOWN-effect rules.
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

    @server.tool(description="Compatibility name for saving an AI-authored project plan as a versioned, Work-authorized project-context ledger. This is not a target's Chain Execute Plan and does not plan or execute work. Prefer bct_set_project_plan.", structured_output=True)
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
        if arguments.get("operation") not in {"project-upsert", "membership-assign", "role-patch", "set-node-info", "node-info-set", "network-name-set"}:
            return {"status": "INVALID_REQUEST", "reason": "NETWORK_SET_OPERATION_INVALID"}
        return await make_executor("conversation_network_update")(
            work_id, operation_id, arguments, approval_ref
        )

    def validate_conversation_network_updates(*, work: Work, updates: list[Any]) -> dict[str, Any]:
        """Validate every saved conversation-network change before any one is applied."""
        from bct.features.conversation_network import ConversationNetworkUpdateFeature
        try:
            for arguments in updates:
                if not isinstance(arguments, dict):
                    raise ValueError("DIRECTION_NETWORK_UPDATE_INVALID")
                if arguments.get("operation") in {"set-node-info", "node-info-set"} and (
                        "expected_scope_id" not in arguments
                        or not re.fullmatch(r"[0-9a-f]{64}", str(arguments.get("expected_role_tags_sha256", "")))):
                    raise ValueError("DIRECTION_NETWORK_OBSERVATION_REQUIRED")
                ConversationNetworkUpdateFeature(bct.store).prepare(work=work, arguments=arguments)
        except (ValueError, PreconditionError) as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "VALID"}

    async def apply_conversation_network_recipe(
        *, direction: dict[str, Any], assessment: dict[str, Any], work: Work,
        targets: list[tuple[int, dict[str, Any]]], action: str,
    ) -> dict[str, Any]:
        """Apply saved network metadata, then reacquire only A's return route.

        Target routes are deliberately resolved one at a time in Send Direction
        R.  A disappeared target must not prevent an unrelated declared target
        from receiving its own exact message.
        """
        import hashlib
        from bct.chain_direction import resolve_direction_network, resolve_direction_target

        updates = assessment.get("network_updates", [])
        updates_check = validate_conversation_network_updates(work=work, updates=updates)
        if updates_check["status"] != "VALID":
            return updates_check
        if updates and not any(capability_matches(item, "conversation_network_update") for item in work.actions):
            return {"status": "BLOCKED", "reason": "DIRECTION_NETWORK_ACTION_REQUIRED"}
        before = await asyncio.to_thread(status_provider)
        try:
            resolve_direction_target(
                snapshot=before, conversation_key=assessment["manager_conversation_key"],
            )
        except ValueError as exc:
            return {
                "status": "NETWORK_PREPARATION_REQUIRED", "reason": str(exc),
                "stage": "BEFORE_NETWORK_EFFECTS", "network_results": [],
                "network_preparation_applied": False, "all_targets_started": False,
                "direction_id": direction["direction_id"],
            }
        results = []
        for index, arguments in enumerate(updates, 1):
            if action == "preflight":
                continue
            operation_id = (
                "direction-" + hashlib.sha256(direction["direction_id"].encode()).hexdigest()[:24]
                + f"-network-{index}"
            )
            result = await bct_set_conversation_network(work.work_id, operation_id, arguments)
            results.append(result)
            if result.get("outcome") != "APPLIED":
                return {
                    "status": "NETWORK_PREPARATION_INCOMPLETE", "network_results": results,
                    "stage": "NETWORK_EFFECTS",
                    "network_preparation_applied": any(item.get("outcome") == "APPLIED" for item in results),
                    "all_targets_started": False, "reason": "REVIEW_ORIGINAL_RECEIPT",
                    "direction_id": direction["direction_id"],
                }
        snapshot = await asyncio.to_thread(status_provider)
        try:
            origin, resolved = resolve_direction_network(
                snapshot=snapshot, assessment=assessment, targets=[],
            )
        except ValueError as exc:
            return {
                "status": "NETWORK_PREPARATION_REQUIRED", "reason": str(exc),
                "stage": "AFTER_NETWORK_EFFECTS" if results else "READINESS",
                "network_preparation_applied": bool(results), "all_targets_started": False,
                "next_tool": "bct_set_conversation_network", "network_results": results,
                "network_updates": updates, "direction_id": direction["direction_id"],
                "instructions_for_a": "기록된 판단에 따라 기존 생성·복구·대화망 설정 부품으로 준비하고 같은 Direction을 다시 확인한다.",
            }
        return {
            "status": "READY", "origin": origin, "resolved": resolved,
            "network_updates": updates, "network_results": results,
            "effects": "NONE_READ_ONLY" if action == "preflight" else "APPLIED_OR_NONE",
        }

    def prepare_derived_dispatch_recipe(
        *, assessment: dict[str, Any], targets: list[tuple[int, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Select only Manager-declared, immediately independent targets.

        This is a Chain Recipe sub-recipe, not a public command and not an AI
        decision maker.  It turns the saved Direction assessment into either
        a target subset that may proceed to delivery or a durable deferred
        card.  It does not create a node, inspect a browser, or send anything.
        """
        from bct.chain_derived_tasks import dispatch_plan

        derived_dispatch = dispatch_plan(
            tasks=list(assessment.get("derived_tasks") or []),
            targets=[target for _, target in targets],
        )
        ready_targets = [
            (index, target) for index, target in targets
            if target["conversation_key"] in derived_dispatch["ready_target_keys"]
        ]
        dispatch_card = {
            "classification": derived_dispatch["classification"],
            "deferred": derived_dispatch["deferred"],
        }
        if not ready_targets:
            return {
                "status": "DEFERRED", "reason": "CHAIN_DERIVED_TASKS_NOT_READY",
                "derived_dispatch": dispatch_card, "authorizes_send": False,
            }
        return {
            "status": "READY", "targets": ready_targets,
            "derived_dispatch": dispatch_card,
        }

    async def prepare_send_direction_recipe(
        *, direction: dict[str, Any], assessment: dict[str, Any], task_id: str,
        operation_id: str, target_conversation_key: str, max_generations: int,
    ) -> dict[str, Any]:
        """Validate a saved Direction and select targets before any network effect or send."""
        from bct.chain_direction import (
            ChainDirectionLedger, compose_target_direction, validate_direction_assessment,
            target_direction_id,
        )
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        try:
            checked = validate_direction_assessment(assessment, decision=direction["decision"])
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        if type(max_generations) is not int or not 0 <= max_generations <= 12:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_MESSAGE_MAX_GENERATIONS_INVALID"}
        targets = [(index, target) for index, target in enumerate(checked["targets"], 1)
                   if not target_conversation_key or target["conversation_key"] == target_conversation_key]
        if not targets:
            return {"status": "INVALID_REQUEST", "reason": "DIRECTION_TARGET_NOT_DECLARED"}
        derived = prepare_derived_dispatch_recipe(assessment=checked, targets=targets)
        if derived["status"] != "READY":
            return derived
        targets = derived["targets"]
        if len(task_id) > 70 or len(operation_id) > 65:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_MESSAGE_OPERATION_TOO_LONG"}
        ledger = ChainDirectionLedger(bct.store)
        try:
            for index, target in targets:
                recorded = await asyncio.to_thread(
                    ledger.get, direction_id=target_direction_id(direction, target),
                )
                compose_target_direction(
                    direction=direction, target=target, task_id=f"{task_id}-{index}",
                    recorded_direction=recorded,
                )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {
            "status": "READY", "assessment": checked, "targets": targets,
            "derived_dispatch": derived["derived_dispatch"],
        }

    async def send_direction_recipe(
        *, direction: dict[str, Any], assessment: dict[str, Any], work: Work,
        targets: list[tuple[int, dict[str, Any]]], task_id: str, operation_id: str,
        network_results: list[dict[str, Any]], max_generations: int,
    ) -> dict[str, Any]:
        """Record each target Direction, recheck its live route, then send it."""
        from bct.chain_direction import (
            ChainDirectionLedger, resolve_direction_network,
            resolve_direction_target,
        )

        ledger = ChainDirectionLedger(bct.store)
        results = []
        for index, target in targets:
            child_task, child_op = f"{task_id}-{index}", f"{operation_id}-{index}"
            try:
                child = await asyncio.to_thread(
                    ledger.target_direction, direction=direction, target=target, task_id=child_task,
                )
                if child["chain_state"] == "CHAIN_STARTED":
                    results.append({"status": "ALREADY_STARTED", "target_conversation_key": target["conversation_key"],
                                    "direction_id": child["direction_id"], "task_id": child["chain_task_id"],
                                    "operation_id": child["chain_operation_id"], "resent": False})
                    continue
                if child["chain_state"] != "NOT_PLANNED":
                    results.append({"status": "RECEIPT_REVIEW_REQUIRED", "direction_id": child["direction_id"],
                                    "task_id": child["chain_task_id"], "operation_id": child["chain_operation_id"]})
                    continue
                fresh = await asyncio.to_thread(status_provider)
                origin, current_targets = resolve_direction_network(
                    snapshot=fresh, assessment=assessment, targets=[(index, target)],
                )
                supervisor = resolve_direction_target(
                    snapshot=fresh,
                    conversation_key=assessment["supervisor_conversation_key"],
                )
                route = current_targets[0][2]
                if route["node_info"].get("generating") is True:
                    results.append({"status": "TARGET_BUSY", "target_conversation_key": target["conversation_key"]})
                    continue
                result = await send_chain_delivery(
                    work_id=work.work_id, task_id=child_task, operation_id=child_op, action="start",
                    chain_direction_id=child["direction_id"],
                    instance_id=route["instance_id"], session_id=route["session_id"],
                    target_tab_id=route["tab_id"], target_window_id=route["window_id"],
                    target_conversation_key=target["conversation_key"],
                    origin_conversation_key=assessment["manager_conversation_key"],
                    origin_instance_id=origin["instance_id"],
                    supervisor_conversation_key=assessment[
                        "supervisor_conversation_key"
                    ],
                    supervisor_instance_id=supervisor["instance_id"],
                    continuation_output_contract="explicit-next-task-v1", max_generations=max_generations,
                )
                results.append({**result, "target_conversation_key": target["conversation_key"],
                                "direction_id": child["direction_id"]})
            except ValueError as exc:
                results.append({"status": "BLOCKED", "reason": str(exc),
                                "target_conversation_key": target["conversation_key"]})
        all_started = all(result["status"] in {"WATCHING", "ALREADY_STARTED"} for result in results)
        return {
            "status": "STARTED" if all_started else "PARTIAL", "stage": "TARGET_DISPATCH",
            "network_preparation_applied": bool(network_results), "all_targets_started": all_started,
            "direction_id": direction["direction_id"], "network_results": network_results,
            "targets": results,
        }

    async def _run_direction_targets(
        *, direction: dict, assessment: dict, work: Work, task_id: str,
        operation_id: str, action: str, target_conversation_key: str,
        max_generations: int,
    ) -> dict[str, Any]:
        """Compose prepare, apply-conversation-network, and send-direction recipes."""
        prepared = await prepare_send_direction_recipe(
            direction=direction, assessment=assessment, task_id=task_id, operation_id=operation_id,
            target_conversation_key=target_conversation_key, max_generations=max_generations,
        )
        if prepared["status"] != "READY":
            return prepared
        network = await apply_conversation_network_recipe(
            direction=direction, assessment=prepared["assessment"], work=work,
            targets=prepared["targets"], action=action,
        )
        if network["status"] != "READY":
            return network
        if action == "preflight":
            from bct.chain_direction import resolve_direction_target
            target_routes = []
            for _, target in prepared["targets"]:
                try:
                    route = resolve_direction_target(
                        snapshot=await asyncio.to_thread(status_provider),
                        conversation_key=target["conversation_key"],
                    )
                    target_routes.append({"conversation_key": target["conversation_key"], **route})
                except ValueError as exc:
                    target_routes.append({"conversation_key": target["conversation_key"],
                                          "status": "UNAVAILABLE", "reason": str(exc)})
            return {"status": "READY", "direction_id": direction["direction_id"],
                    "targets": target_routes,
                    "network_updates": network["network_updates"],
                    "effects": "NONE_READ_ONLY", "authorizes_send": False,
                    "recipe_progress": chain_recipe_progress(completed_through=5, next_number=6)}
        sent = await send_direction_recipe(
            direction=direction, assessment=prepared["assessment"], work=work,
            targets=prepared["targets"], task_id=task_id, operation_id=operation_id,
            network_results=network["network_results"], max_generations=max_generations,
        )
        return {
            "derived_dispatch": prepared.get("derived_dispatch"),
            **sent,
            "recipe_progress": chain_recipe_progress(completed_through=5, next_number=6),
        }

    async def check_chain_work_access(*, work_id: str, action: str) -> dict[str, Any]:
        """Read one Work as an advisory observation before chain preparation or sending."""
        if not hasattr(bct, "store"):
            return {
                "status": "OBSERVED", "work": None,
                "work_access": "UNAVAILABLE",
                "reason": "CHAIN_MESSAGE_WORK_STORE_UNAVAILABLE",
            }
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except (KeyError, ValueError):
            return {
                "status": "OBSERVED", "work": None,
                "work_access": "NOT_FOUND",
                "reason": "CHAIN_MESSAGE_WORK_NOT_FOUND",
            }
        observation = check_chain_work(work, principal_id=principal.principal_id)
        return {**observation, "work": work}

    async def read_saved_direction(*, work_id: str, direction_id: str) -> dict[str, Any]:
        """Read one saved Direction without creating schema or changing durable state."""
        if not hasattr(bct, "store"):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_STORE_REQUIRED"}
        if not isinstance(direction_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", direction_id):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_ID_INVALID"}
        def read_existing():
            with bct.store._readonly() as db:
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

    async def send_chain_delivery(
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
        supervisor_conversation_key: str = "",
        supervisor_instance_id: str = "",
        continuation_output_contract: str = "none",
        max_generations: int = 0,
        source_kind: str = "USER", source_task_id: str = "",
        source_generation: int = 0, project: str = "",
    ) -> dict[str, Any]:
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
                    ),
                    "recovery_needed": ctx.get("recovery_needed"),
                    "execution_path": ctx.get("execution_path") or "LEGACY_UNCLASSIFIED",
                    "chain_direction_id": ctx.get("chain_direction_id", "")}
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

        work_access = await check_chain_work_access(work_id=work_id, action=action)
        work = work_access["work"]

        direction = None
        execution_path = "DIRECTION_DECLARED" if chain_direction_id else "DIRECT_EXACT_TARGET"
        if chain_direction_id:
            loaded_direction = await read_saved_direction(
                work_id=work_id, direction_id=chain_direction_id,
            )
            if loaded_direction["status"] != "READY":
                return loaded_direction
            direction = loaded_direction["direction"]
            if direction.get("decision") != "NEW_TASK":
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_NOT_A_NEW_TASK"}
            if (direction.get("target_conversation_key")
                    and direction["target_conversation_key"] != target_conversation):
                return {"status":"INVALID_REQUEST","reason":"DIRECTION_TARGET_IDENTITY_MISMATCH"}
            import json
            assessment = json.loads(direction.get("assessment_json") or "{}")
            if assessment:
                return {"status":"INVALID_REQUEST","reason":"DIRECTION_REQUIRES_TARGET_DELIVERY"}
            if instruction and instruction != direction.get("direction_text"):
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_TEXT_MISMATCH"}
            if (direction.get("chain_task_id",""), direction.get("chain_operation_id","")) not in {
                    ("",""), (task_id,operation_id)}:
                return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_CHAIN_CONFLICT"}
            instruction = str(direction["direction_text"])
        if (not re.fullmatch(r"[a-f0-9]{32}",str(session_id or "")) or
                not isinstance(target_tab, int) or target_tab <= 0 or
                not isinstance(target_window, int) or target_window <= 0):
            return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_INPUT_INVALID"}
        try:
            prepared_text = prepare_chain_instruction(
                instruction, output_contract=continuation_output_contract,
                execution_plan_context=(
                    {
                        "work_id": work_id,
                        "direction_id": chain_direction_id,
                        "task_id": task_id,
                        "generation": generation,
                    }
                    if chain_direction_id else None
                ),
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
                "work_observation": {
                    key: value for key, value in work_access.items() if key != "work"
                },
                "continuation_output_contract": continuation_output_contract,
                "contract_appended": prepared_text["output_contract_appended"],
                "execution_plan_contract_appended": prepared_text[
                    "execution_plan_contract_appended"
                ],
                "contract_suffix": EXPLICIT_NEXT_TASK_SUFFIX
                    if prepared_text["output_contract_appended"] else "",
                "outgoing_instruction_sha256": prepared_text["instruction_sha256"],
                "outgoing_instruction_characters": prepared_text["instruction_characters"],
                "max_generations": max_generations,
                "execution_path": execution_path,
                "chain_direction_id": chain_direction_id,
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
             "supervisor_conversation_key":supervisor_conversation_key,
             "supervisor_instance_id":supervisor_instance_id,
             "planned_send_operation_id":send_id,
             "planned_send_text":outgoing_instruction,
             "execution_path":execution_path,
             "chain_direction_id":chain_direction_id,
             "exclusive_conversation_watch":True,
             "max_generations":max_generations,
             "watched_session_id":session_id,
             "watched_tab_id":target_tab,
             "watched_window_id":target_window})
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
                "execution_path":execution_path,
                "chain_direction_id":chain_direction_id,
                "prearm":armed,"send":sent,
                **({"chain_direction": direction} if direction is not None else {})}

    @server.tool(
        name="bct_task_message",
        description=(
            "EXPLICIT REQUEST ONLY: Optional technical envelope for one already-planned Manager-to-Worker "
            "instruction. It composes exact Chain Recipe delivery/watch with explicit "
            "SELF/MANAGER continuation, but it does not replace A's user direction "
            "or overall plan recorded inside Chain Recipe. The normal "
            "max_rounds=0 policy has no fixed limit: Worker continues only while real "
            "progress and a safe next step exist, then returns to Manager on BA. A positive "
            "max_rounds is an explicit budget. This is a 1:1 message recipe, not the overall "
            "Chain Recipe lifecycle, multi-worker orchestration, or automatic Manager election."
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
            result = await send_chain_delivery(
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
        result = await send_chain_delivery(
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
        bootstrap_create_operation_id: str = "",
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
             "planned_send_text":planned_send_text,
             "bootstrap_create_operation_id":bootstrap_create_operation_id},
        )

    @server.tool(
        name="bct_send_message",
        description=(
            "EXPLICIT REQUEST ONLY: send one exact message to an existing ChatGPT conversation or to a "
            "BCT-created chat target. This is an exact-message transport component, "
            "not the default route for ordinary work, A's user-direction, or the whole Chain Recipe. It preserves the "
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
            "Check one exact node without sending or changing it. Reuses the existing "
            "RCC DOM activity, connection, and task/operation progress signals and stores "
            "only the bounded comparison needed by Recheck Node. Returns OK, WAIT, or "
            "CHECK; BCT does not decide replacement."
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
            "Recheck the same exact node case and compare existing DOM activity, "
            "connection, and task/operation progress. Suggests CONTINUE, RECHECK, or "
            "RESTART. Active Chain watches record repeated signals as RECOVERY_NEEDED; "
            "they do not restart automatically."
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
            "also sends that instruction through the internal common delivery path using "
            "exact RCC identities; "
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
                sent = await send_chain_delivery(
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
                        "replace_node": prepared, "delivery": sent}
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
            "Compatibility read-only entry for Chain Recipe prepare only. It returns Input R, State R, "
            "the current linked Work tree, and the entry_context_id required by bct_chain_recipe(action='save'). "
            "It cannot save a Direction directly, so a Manager return or branch adoption cannot bypass the "
            "single Chain Recipe entry."
        ),
        structured_output=True,
    )
    async def bct_set_direction(
        work_id: str = "", direction_text: str = "", decision: str = "",
        source_kind: str = "USER", source_task_id: str = "",
        source_generation: int = 0, direction_id: str = "",
        action: str = "prepare", source_text: str = "", project: str = "",
        assessment: dict[str, Any] | None = None,
        parent_direction_id: str = "", parent_step_id: str = "",
        branch_kind: str = "PRIMARY", branch_reason: str = "", branch_request_id: str = "",
    ) -> dict[str, Any]:
        if action != "prepare":
            return {
                "status": "INVALID_REQUEST",
                "reason": "DIRECTION_DIRECT_SAVE_PROHIBITED_USE_CHAIN_RECIPE",
                "next_safe_step": "bct_chain_recipe(action='prepare')",
                "does_not": ["save_direction", "send_message", "create_operation"],
            }
        return await bct_chain_recipe(
            action="prepare", work_id=work_id, direction_text=direction_text, decision=decision,
            source_kind=source_kind, source_task_id=source_task_id,
            source_generation=source_generation, direction_id=direction_id,
            source_text=source_text, project=project, assessment=assessment,
            parent_direction_id=parent_direction_id, parent_step_id=parent_step_id,
            branch_kind=branch_kind, branch_reason=branch_reason,
            branch_request_id=branch_request_id,
        )

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
        name="bct_chain_branch",
        description=(
            "Record or read one Root Work's linked branch tree. action=request is a Worker observation "
            "that asks A Manager to consider a child Direction; it never creates a Direction, Work, "
            "Operation, browser message, or delivery. action=report records a check/identity/UNKNOWN "
            "state on that exact request. action=tree is read-only and shows the next safe step, exact "
            "references, unresolved attention, and no-resend warnings. A adopts a request only after "
            "re-entering bct_chain_recipe(action='prepare'), then saving a normal Chain Recipe Direction "
            "with branch_request_id and the returned entry_context_id."
        ),
        structured_output=True,
    )
    async def bct_chain_branch(
        action: str = "tree", work_id: str = "", request_id: str = "",
        parent_work_id: str = "", parent_direction_id: str = "", parent_step_id: str = "",
        parent_task_id: str = "", parent_generation: int = 1, kind: str = "DIAGNOSIS",
        reason: str = "", exact_refs: dict[str, Any] | None = None, required: bool = True,
        state: str = "", next_safe_step: str = "", evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from bct.chain_direction import ChainBranchRequestLedger
        if action not in {"request", "report", "tree"}:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_BRANCH_ACTION_INVALID"}
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
        except (KeyError, ValueError):
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        if work.owner_principal_id != principal.principal_id:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        if action == "tree":
            tree = await asyncio.to_thread(
                ChainBranchRequestLedger.tree, store=bct.store, root_work_id=work.work_id,
            )
            return {"status": "OK", "effects": "NONE_READ_ONLY", "chain_tree": tree}
        ledger = ChainBranchRequestLedger(bct.store)
        try:
            if action == "request":
                branch = await asyncio.to_thread(
                    ledger.request, request_id=request_id, root_work_id=work.work_id,
                    parent_work_id=parent_work_id or work.work_id,
                    parent_direction_id=parent_direction_id, parent_step_id=parent_step_id,
                    parent_task_id=parent_task_id, parent_generation=parent_generation,
                    kind=kind, reason=reason, exact_refs=exact_refs, required=required,
                )
                return {
                    "status": "WAITING_INPUT", "branch_request": branch,
                    "next_safe_step": "MANAGER_REVIEW_BRANCH_REQUEST",
                    "does_not": ["create_child_direction", "send_message", "create_operation"],
                }
            branch = await asyncio.to_thread(
                ledger.report, request_id=request_id, state=state, reason=reason,
                next_safe_step=next_safe_step, evidence=evidence,
            )
            return {"status": branch["state"], "branch_request": branch,
                    "next_safe_step": branch["next_safe_step"]}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}

    @server.tool(
        name="bct_set_execute_plan",
        description=(
            "Save the receiving target's concrete execution plan after an exact A Direction has already "
            "been delivered by Chain Recipe. A's direction supplies the goal and "
            "boundaries; the target's plan supplies the files, tools, checks, and safe next "
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
            plan = await asyncio.to_thread(
                ChainExecutionPlanLedger(bct.store).save,
                plan_id=plan_id, work_id=work_id, direction_id=direction_id,
                task_id=task_id, generation=generation, plan_text=plan_text,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
        return {"status":"OK","chain_execution_plan":plan}

    @server.tool(
        name="bct_update_execute_plan",
        description=(
            "Append the receiving target's revised remaining Execute Plan without erasing the initial plan. "
            "plan_id is the durable plan identity; supplied work/task/generation are optional "
            "continuity references and are reported when they differ. They never block a plan update."
        ),
        structured_output=True,
    )
    async def bct_update_execute_plan(
        plan_id: str, plan_text: str, update_reason: str,
        work_id: str = "", task_id: str = "", generation: int | None = None,
    ) -> dict[str, Any]:
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        ledger = ChainExecutionPlanLedger(bct.store)
        existing = await asyncio.to_thread(ledger.get, plan_id=plan_id)
        if existing is None:
            return {"status": "NOT_FOUND", "reason": "CHAIN_EXECUTION_PLAN_NOT_FOUND"}
        plan = await asyncio.to_thread(
            ledger.update, plan_id=plan_id, plan_text=plan_text, update_reason=update_reason,
        )
        supplied = {"work_id": work_id, "task_id": task_id, "generation": generation}
        recorded = {key: existing[key] for key in supplied}
        mismatched = [key for key, value in supplied.items() if value not in {"", None} and value != recorded[key]]
        return {
            "status": "OK", "chain_execution_plan": plan,
            "continuity": "CONTEXT_CHANGED" if mismatched else "CONTINUED",
            "context_mismatches": mismatched,
        }

    @server.tool(
        name="bct_get_execute_plan",
        description="Read one exact B-authored Chain Execution Plan. Does not send, plan, or decide.",
        structured_output=True,
    )
    async def bct_get_execute_plan(plan_id: str, work_id: str = "") -> dict[str, Any]:
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        plan = await asyncio.to_thread(
            ChainExecutionPlanLedger(bct.store).get, plan_id=plan_id,
        )
        if plan is None:
            return {"status":"NOT_FOUND","plan_id":plan_id}
        return {
            "status": "OK", "chain_execution_plan": plan,
            "continuity": "CONTEXT_CHANGED" if work_id and work_id != plan["work_id"] else "CONTINUED",
        }

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

    @server.tool(description="Create, recover, or continue a BCT Work. Roots fence filesystem effects; actions describe intended scope but are not a second capability allowlist. A trusted successor automatically takes over only after prior operations are terminal.", structured_output=True)
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
            updated = False
        else:
            if current.owner_principal_id != principal.principal_id:
                # Work ownership coordinates the current executor; it is not a
                # permanent permission boundary. Once every prior operation is
                # terminal, hand the Work to the current trusted principal and
                # advance the epoch so a late former executor cannot write.
                current = await asyncio.to_thread(
                    bct.store.handoff_work,
                    work_id=work_id,
                    old_principal_id=current.owner_principal_id,
                    new_principal_id=principal.principal_id,
                    expected_epoch=current.assignment_epoch,
                )
            current, updated = await asyncio.to_thread(
                bct.store.update_work_scope,
                work_id=work_id,
                principal_id=principal.principal_id,
                expected_epoch=current.assignment_epoch,
                request_summary=request_summary,
                roots=normalized_roots,
                actions=requested_actions,
            )
            duplicate = not updated
        return {"work": _work_dict(current), "duplicate": duplicate, "updated": updated}

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
            "Save a generic project-plan ledger. This is separate from a target's Chain "
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

    @server.tool(
        description=("List every RCC command exposed through bct_browser, grouped by its "
                     "read, effect, reconciliation, or recovery purpose. This discovery call "
                     "does not access RCC or perform a browser effect."),
        structured_output=True,
    )
    async def bct_rcc_command_catalog() -> dict[str, Any]:
        from bct.features.rcc import command_catalog
        return {
            "tool": "bct_browser",
            "invocation": {
                "required": ["work_id", "operation_id", "arguments.command"],
                "note": ("Each command validates its own exact identifiers, target and receipt "
                         "contract. An UNKNOWN effect is never automatically replayed."),
            },
            "commands": command_catalog(),
        }

    @server.tool(
        description=("List RCC Recipe blocks. Each block is an ordered list of public "
                     "bct_browser command names; listing a recipe neither performs nor "
                     "authorizes its steps."),
        structured_output=True,
    )
    async def bct_rcc_recipe_catalog() -> dict[str, Any]:
        from bct.features.rcc import recipe_catalog
        return {
            "tool": "bct_browser",
            "invocation": {"required": ["work_id", "operation_id", "arguments.command"]},
            "recipes": recipe_catalog(),
        }

    def make_executor(capability: str) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        async def execute(
            work_id: str,
            operation_id: str,
            arguments: dict[str, Any],
            approval_ref: str | None = None,
        ) -> dict[str, Any]:
            selected = capability
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
