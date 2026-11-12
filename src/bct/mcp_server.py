from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from mcp.server.fastmcp import FastMCP, Image
from starlette.responses import JSONResponse

from .background_operations import BACKGROUND_CAPABILITIES, launch_background_operation
from .chat_input_queue import queue_message_command
from .code_block_commands import organize_code_blocks_command
from .core.models import Principal
from .mcp_catalogue_config import CatalogueSettings
from .status_views import status_view
from .task_message_commands import task_message_command
from .discovery_views import capability_view, rcc_command_view, rcc_recipe_view
from .operation_queries import read_github_inbox, read_operation
from .work_services import create_or_update_work
from .status_queries import read_status, read_conversation_network
from .project_plan import prepare_project_plan
from .recipes.code_blocks import scan_work_code_blocks
from .node_recovery_commands import NodeRecoveryCommands
from .execution_plan_commands import ExecutionPlanCommands
from .execution_context_queries import read_execution_context
from .chain_direction_commands import ChainDirectionCommands


from .trace_timing import TRACE_ID as _MCP_TRACE_ID, trace_stage as _trace_stage

from .recipes.runtime import ChainRecipeRuntime
from .recipes.recovery import _assert_node_send_allowed
from .recipes.chain import chain_recipe
from .recipes.network import set_conversation_network
from .recipes.state import check_conversation_network_recipe

MCP_PRINCIPAL_ID = "bct-mcp-local"

_GENERAL_TOOLS = (
    "bct_capabilities", "bct_status", "queue_message", "bct_get_conversation_network", "bct_check_conversation_network", "scan_code_blocks", "organize_code_blocks",
    "bct_execution_context", "bct_set_direction", "bct_get_direction", "bct_chain_branch",
    "bct_loop_recipe", "bct_set_execute_plan", "bct_get_execute_plan", "bct_set_project_plan",
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
        settings = getattr(server, "catalogue_settings", None)
        value = capability_view(
            tool_metadata=tool_metadata, capabilities=capabilities, usage=_CAPABILITY_USAGE,
            catalogue_warning=settings.last_error if settings is not None else None,
            query=query, tool_name=tool_name, component_id=component_id,
            include_manual=include_manual, limit=limit, offset=offset,
        )
        handler_ms = (time.perf_counter_ns() - started_ns) / 1e6
        _trace_stage(
            "handler_done", tool_kind="capabilities", handler_ms=handler_ms,
            wait_ms=0.0, execution_ms=handler_ms,
        )
        return value


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
        return await chain_recipe(
            recipe_runtime,
            source_text=source_text,
            source_kind=source_kind,
            work_id=work_id,
            source_task_id=source_task_id,
            source_generation=source_generation,
            project=project,
            action=action,
            direction_text=direction_text,
            decision=decision,
            direction_id=direction_id,
            assessment=assessment,
            task_id=task_id,
            operation_id=operation_id,
            target_conversation_key=target_conversation_key,
            max_generations=max_generations,
            report_target_conversation_key=report_target_conversation_key,
            generation=generation,
            entry_context_id=entry_context_id,
            worker_preparation_id=worker_preparation_id,
            parent_direction_id=parent_direction_id,
            parent_step_id=parent_step_id,
            branch_kind=branch_kind,
            branch_reason=branch_reason,
            branch_request_id=branch_request_id,
        )

    @server.tool(
        description=(
            "Return the current read-only BCT summary: Core release/health, Monitor projection, "
            "RCC instances, and active process sessions. Optional compact defaults true; creates no work or mutation."
        ),
        structured_output=True,
    )
    async def bct_status(compact: bool = True, scope: str = "bct", sort_by: str = "number") -> dict[str, Any]:
        return await read_status(
            bct, principal_id=principal.principal_id, status_provider=status_provider,
            browser_usage=_CAPABILITY_USAGE["browser"], compact=compact, scope=scope, sort_by=sort_by,
        )

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
        return await read_conversation_network(bct, project=project)

    @server.tool(description="Check Conversation Network with read-only current node/RCC evidence, durable active and closed scope directory, current supervisor readiness, and optionally authorized project-context summaries. Does not create plans, conversation networks, or messages.", structured_output=True)
    async def bct_check_conversation_network(project: str = "", sort_by: str = "number", work_id: str = "", operation_id: str = "") -> dict[str, Any]:
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        snapshot = await asyncio.to_thread(status_provider)
        return await check_conversation_network_recipe(recipe_runtime,
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
        return await queue_message_command(
            bct.store, work_id=work_id,
            target_conversation_key=target_conversation_key, action=action,
            message_id=message_id, instruction=instruction,
            origin_conversation_key=origin_conversation_key, claim_id=claim_id,
            result_sha256=result_sha256, reason=reason, hold_kind=hold_kind,
            limit=limit,
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
        return await scan_work_code_blocks(
            recipe_runtime, work_id=work_id, root=root, max_files=max_files,
            max_bytes_per_file=max_bytes_per_file, max_blocks=max_blocks,
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
        return await organize_code_blocks_command(
            getattr(bct, "store", None), principal_id=principal.principal_id,
            write_execute=make_executor("write"), work_id=work_id, action=action,
            path=path, block_id=block_id, replacement=replacement, root=root,
            operation_id=operation_id, expected_file_sha256=expected_file_sha256,
            expected_block_sha256=expected_block_sha256,
            expected_after_sha256=expected_after_sha256, plan_sha256=plan_sha256,
        )

    @server.tool(description="Compatibility name for saving an AI-authored project plan as a versioned, Work-authorized project-context ledger. This is not a target's Chain Execute Plan and does not plan or execute work. Prefer bct_set_project_plan.", structured_output=True)
    async def bct_run_plan(
        work_id: str, operation_id: str, plan_id: str, project: str,
        objective: str, acceptance: str, steps: list[dict[str, Any]],
        author: str, expected_revision: int = 0, discretion: str = "normal",
        assumptions: list[str] | None = None,
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        prepared = prepare_project_plan(
            work_id=work_id, plan_id=plan_id, project=project, objective=objective,
            acceptance=acceptance, steps=steps, author=author,
            expected_revision=expected_revision, discretion=discretion, assumptions=assumptions,
        )
        if prepared["status"] != "READY":
            return prepared
        return await make_executor("project_context")(
            work_id, operation_id, prepared["arguments"], approval_ref,
        )

    @server.tool(description="Set existing project membership or role tags through the authorized conversation_network_update capability; supports project-upsert, membership-assign and role-patch.", structured_output=True)
    async def bct_set_conversation_network(
        work_id: str, operation_id: str, arguments: dict[str, Any],
        approval_ref: str | None = None,
    ) -> dict[str, Any]:
        return await set_conversation_network(
            recipe_runtime,
            work_id=work_id,
            operation_id=operation_id,
            arguments=arguments,
            approval_ref=approval_ref,
        )


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
        return await task_message_command(recipe_runtime, **locals())

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
                    _assert_node_send_allowed, recipe_runtime, work_id, guarded_conversation,
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
        return await read_execution_context(
            bct.store, work_id=work_id, task_id=task_id, generation=generation,
        )


    def _node_recovery_commands() -> NodeRecoveryCommands:
        return NodeRecoveryCommands(
            store=bct.store, principal_id=principal.principal_id, runtime=recipe_runtime,
            browser_execute=make_executor("browser"),
        )

    def _execution_plan_commands() -> ExecutionPlanCommands:
        return ExecutionPlanCommands(bct.store)

    def _chain_direction_commands() -> ChainDirectionCommands:
        return ChainDirectionCommands(bct.store, principal_id=principal.principal_id)

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
        return await _node_recovery_commands().check(
            work_id=work_id, conversation_key=conversation_key, task_id=task_id, case_id=case_id,
        )

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
        return await _node_recovery_commands().recheck(work_id=work_id, case_id=case_id)

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
        return await _node_recovery_commands().pause(
            work_id=work_id, case_id=case_id, reason=reason,
        )

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
        return await _node_recovery_commands().replace(
            work_id=work_id, case_id=case_id,
            successor_conversation_key=successor_conversation_key,
            inheritance_task_id=inheritance_task_id, action=action,
            operation_id=operation_id, instance_id=instance_id, session_id=session_id,
            target_tab_id=target_tab_id, target_window_id=target_window_id,
            origin_conversation_key=origin_conversation_key,
            origin_instance_id=origin_instance_id,
        )

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
        return await _node_recovery_commands().reset(
            work_id=work_id, case_id=case_id, action=action, operation_id=operation_id,
            instance_id=instance_id, session_id=session_id, tab_id=tab_id,
            window_id=window_id, conversation_key=conversation_key,
        )

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
        return await _chain_direction_commands().get_direction(
            work_id=work_id, direction_id=direction_id,
        )

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
        return await _chain_direction_commands().branch(
            action=action, work_id=work_id, request_id=request_id,
            parent_work_id=parent_work_id, parent_direction_id=parent_direction_id,
            parent_step_id=parent_step_id, parent_task_id=parent_task_id,
            parent_generation=parent_generation, kind=kind, reason=reason,
            exact_refs=exact_refs, required=required, state=state,
            next_safe_step=next_safe_step, evidence=evidence,
        )

    @server.tool(
        name="bct_loop_recipe",
        description=("New Loop starts are disabled after Chain restoration; existing status/claim/reconcile/advance remain. "
                     "reconcile verifies the original BCT Operation receipt. "
                     "Records SELF wake intent; optional existing global Supervisor binding via "
                     "supervisor/review_instruction, configure_review/request_review and exact "
                     "candidate_sha/evidence_text completion handoff. Status includes plan/progress/review/result_report. "
                     "Requester references are not browser UUIDs: configure_requester defaults to pull-only; "
                     "requester_conversation_key explicitly opts into fresh exact RCC report delivery. "
                     "Acceptance never proves the user was notified. New starts disallow new nodes unless "
                     "allow_new_nodes is explicit; configure_recovery records that policy for existing runs. "
                     "No node creation or permission expansion; Core dispatches the reserved handoff."),
        structured_output=True,
    )
    async def bct_loop_recipe(
        action: str = "status", work_id: str = "", direction_id: str = "",
        task_id: str = "", owner: str = "", plan_text: str = "",
        epoch: int = 1, operation_id: str = "", next_step: int = 0,
        message_text: str = "", verified: bool = False,
        supervisor: str = "", review_instruction: str = "",
        candidate_sha: str = "", evidence_text: str = "", direction_text: str = "",
        review_response_sha: str = "", requester_ref: str = "",
        requester_conversation_key: str = "", allow_new_nodes: bool = False,
    ) -> dict[str, Any]:
        from bct.loop_store import LoopStore
        from bct.chain_direction import ChainDirectionLedger
        from bct.chain_execution_plan import ChainExecutionPlanLedger

        # Chain compatibility has been restored. Stop a new Loop before any
        # Direction, run, plan, requester or review record can be created.
        if action == "start":
            return {"status":"INVALID_REQUEST", "reason":"LOOP_NEW_START_DISABLED_CHAIN_RESTORED",
                    "effects":"NONE", "existing_records":"PRESERVED"}

        if not work_id and action == "recover":
            from bct.loop_recovery_executor import LoopRecoveryExecutor
            try:
                work_id = await asyncio.to_thread(
                    LoopRecoveryExecutor.resolve_single_work,
                    bct.store, principal_id=MCP_PRINCIPAL_ID,
                )
            except ValueError as exc:
                return {"status": "INVALID_REQUEST", "reason": str(exc)}
        if not work_id:
            return {"status": "INVALID_REQUEST", "reason": "LOOP_WORK_REQUIRED"}
        try:
            work = await asyncio.to_thread(bct.store.get_work, work_id)
            if work.owner_principal_id != MCP_PRINCIPAL_ID:
                return {"status": "ACCESS_DENIED"}
            ledger = LoopStore(bct.store)
            if action == "recover":
                if status_provider is None:
                    return {"status": "UNAVAILABLE", "reason": "LOOP_FRESH_STATUS_REQUIRED"}
                from bct.loop_recovery_executor import LoopRecoveryExecutor
                snapshot = await asyncio.to_thread(status_provider)
                nodes = status_view(snapshot, "node").get("current_nodes", {})
                if nodes.get("observation", {}).get("state") != "FRESH":
                    return {"status": "UNAVAILABLE", "reason": "LOOP_NODES_NOT_FRESH"}
                ready = {
                    node.get("conversation_uuid")
                    for node in nodes.get("items", [])
                    if node.get("status") == "CONFIRMED"
                    and node.get("generating") is False
                    and not node.get("connection", {}).get("disconnected", True)
                    and node.get("telemetry", {}).get("readiness") == "IDLE"
                }
                result = await asyncio.to_thread(
                    LoopRecoveryExecutor(
                        bct.store, principal_id=MCP_PRINCIPAL_ID,
                        owner_ready=lambda value: value in ready,
                    ).run_once, work_id_filter=work_id,
                )
                return {"status": "OK", "recovery": result}
            if action == "configure_requester":
                from bct.loop_result import LoopResultLedger
                if requester_conversation_key and status_provider is None:
                    return {"status":"UNAVAILABLE", "reason":"LOOP_FRESH_STATUS_REQUIRED"}
                snapshot = await asyncio.to_thread(status_provider) if requester_conversation_key else None
                result = await asyncio.to_thread(LoopResultLedger(bct.store).configure,
                    work_id=work_id, owner=owner, requester_ref=requester_ref,
                    conversation_key=requester_conversation_key or None, snapshot=snapshot)
                return {"status":"OK", "result_report":{k:v for k,v in result.items() if k not in {"message_text", "route_json"}}}
            if action == "configure_recovery":
                loop = await asyncio.to_thread(ledger.configure_recovery, work_id=work_id,
                    owner=owner, epoch=epoch, allow_new_nodes=allow_new_nodes)
                return {"status":"OK", "loop":loop}
            if action == "status":
                loop = await asyncio.to_thread(ledger.get, work_id)
                from bct.loop_supervisor_handoff import LoopReviewLedger
                review = LoopReviewLedger(bct.store).get(work_id)
                if review:
                    review = {k: v for k, v in review.items() if k not in {"message_text", "evidence_text", "instruction"}}
                plan = (ChainExecutionPlanLedger.get_for_chain(store=bct.store, work_id=work_id,
                    direction_id=loop["direction_id"], task_id=loop["task_id"]) if loop else None)
                progress = (ChainExecutionPlanLedger.read_latest_execute_plan_check(store=bct.store,
                    work_id=work_id, direction_id=loop["direction_id"], task_id=loop["task_id"]) if loop else None)
                from bct.loop_result import LoopResultLedger
                result_report = await asyncio.to_thread(LoopResultLedger(bct.store).recover_acceptance, work_id)
                if result_report:
                    result_report = {k:v for k,v in result_report.items() if k not in {"message_text", "route_json"}}
                return {"status": "OK" if loop else "NOT_FOUND", "loop": loop,
                        "plan": plan, "progress": progress, "review": review,
                        "result_report": result_report,
                        "user_notification": "UNVERIFIED"}
            if action in {"configure_review", "request_review", "resume_review", "reconcile_review"}:
                from bct.loop_supervisor_handoff import LoopReviewLedger
                review_ledger = LoopReviewLedger(bct.store)
                if action == "reconcile_review":
                    result = await asyncio.to_thread(review_ledger.reconcile_return, work_id=work_id,
                        owner=owner, epoch=epoch, response_sha256=review_response_sha)
                elif action == "resume_review":
                    if status_provider is None:
                        return {"status": "UNAVAILABLE", "reason": "LOOP_FRESH_STATUS_REQUIRED"}
                    snapshot = await asyncio.to_thread(status_provider)
                    result = await asyncio.to_thread(review_ledger.resume, work_id=work_id,
                        owner=owner, epoch=epoch, response_sha256=review_response_sha, snapshot=snapshot)
                elif action == "configure_review":
                    if status_provider is None:
                        return {"status": "UNAVAILABLE", "reason": "LOOP_FRESH_STATUS_REQUIRED"}
                    snapshot = await asyncio.to_thread(status_provider)
                    result = await asyncio.to_thread(review_ledger.configure, work_id=work_id,
                        owner=owner, supervisor=supervisor, instruction=review_instruction, snapshot=snapshot)
                else:
                    result = await asyncio.to_thread(review_ledger.request, work_id=work_id,
                        owner=owner, epoch=epoch, candidate_sha=candidate_sha, evidence_text=evidence_text)
                return {"status": "OK", "review": {k:v for k,v in result.items() if k != "message_text"}}
            if action == "start":
                if requester_ref or requester_conversation_key:
                    if not requester_ref.strip() or len(requester_ref) > 240:
                        return {"status":"INVALID_REQUEST", "reason":"LOOP_REQUESTER_REFERENCE_REQUIRED"}
                    if requester_conversation_key:
                        if requester_conversation_key in {owner, supervisor}:
                            return {"status":"INVALID_REQUEST", "reason":"LOOP_RESULT_SELF_RETURN_FORBIDDEN"}
                        if status_provider is None:
                            return {"status":"UNAVAILABLE", "reason":"LOOP_FRESH_STATUS_REQUIRED"}
                        from bct.loop_self_dispatch import LoopSelfDispatcher
                        requester_snapshot = await asyncio.to_thread(status_provider)
                        LoopSelfDispatcher.exact_route(requester_snapshot, requester_conversation_key, require_idle=False)
                direction = await asyncio.to_thread(
                    ChainDirectionLedger(bct.store).get, direction_id=direction_id,
                )
                if direction is None and direction_text:
                    # Explicit single-node Loop entry. Reuse the Direction ledger,
                    # not the three-node Chain delivery topology. Existing records
                    # and ordinary Chain validation are never weakened or changed.
                    if not supervisor or status_provider is None:
                        return {"status": "INVALID_REQUEST", "reason": "LOOP_REVIEW_BINDING_REQUIRED"}
                    from bct.loop_supervisor_handoff import validate_loop_review_topology
                    snapshot = await asyncio.to_thread(status_provider)
                    validate_loop_review_topology(snapshot, owner=owner, supervisor=supervisor)
                    if not review_instruction.strip() or len(review_instruction) > 4000:
                        return {"status": "INVALID_REQUEST", "reason": "LOOP_REVIEW_INSTRUCTION_REQUIRED"}
                    direction = await asyncio.to_thread(ChainDirectionLedger(bct.store).save,
                        direction_id=direction_id, work_id=work_id, source_kind="USER",
                        decision="NEW_TASK", direction_text=direction_text,
                        source_text=direction_text)
                if (not direction or direction["work_id"] != work_id
                        or direction["decision"] != "NEW_TASK"
                        or direction["chain_state"] != "NOT_PLANNED"):
                    return {"status": "INVALID_REQUEST", "reason": "LOOP_DIRECTION_NOT_READY"}
                if supervisor:
                    if status_provider is None:
                        return {"status": "UNAVAILABLE", "reason": "LOOP_FRESH_STATUS_REQUIRED"}
                    from bct.loop_supervisor_handoff import validate_loop_review_topology, LoopReviewLedger
                    snapshot = await asyncio.to_thread(status_provider)
                    validate_loop_review_topology(snapshot, owner=owner, supervisor=supervisor)
                    if not review_instruction.strip() or len(review_instruction) > 4000:
                        return {"status": "INVALID_REQUEST", "reason": "LOOP_REVIEW_INSTRUCTION_REQUIRED"}
                loop = await asyncio.to_thread(
                    ledger.start, work_id=work_id, direction_id=direction_id,
                    task_id=task_id, owner=owner, plan_text=plan_text,
                    allow_new_nodes=allow_new_nodes,
                )
                plan_id = "loop-plan-" + hashlib.sha256(
                    (work_id+":"+direction_id+":"+task_id).encode("utf-8")
                ).hexdigest()[:20]
                plan = await asyncio.to_thread(
                    ChainExecutionPlanLedger(bct.store).save,
                    plan_id=plan_id, work_id=work_id, direction_id=direction_id,
                    task_id=task_id, generation=1, plan_text=plan_text,
                )
                review = None
                if supervisor:
                    review = await asyncio.to_thread(LoopReviewLedger(bct.store).configure,
                        work_id=work_id, owner=owner, supervisor=supervisor,
                        instruction=review_instruction, snapshot=snapshot)
                result_report = None
                if requester_ref:
                    from bct.loop_result import LoopResultLedger
                    result_report = await asyncio.to_thread(LoopResultLedger(bct.store).configure,
                        work_id=work_id, owner=owner, requester_ref=requester_ref,
                        conversation_key=requester_conversation_key or None,
                        snapshot=requester_snapshot if requester_conversation_key else None)
                return {"status": "OK", "loop": loop, "plan": plan, "review": review,
                        "result_report": result_report}
            if action in {"queue_self", "self_status", "reconcile_self"}:
                from bct.loop_self_outbox import LoopSelfOutbox
                outbox = LoopSelfOutbox(bct.store)
                if action == "queue_self":
                    value = await asyncio.to_thread(
                        outbox.queue,work_id=work_id,epoch=epoch,step=next_step,
                        owner=owner,message=message_text,
                    )
                elif action == "self_status":
                    value = await asyncio.to_thread(
                        outbox.get,work_id=work_id,epoch=epoch,step=next_step,
                    )
                else:
                    value = await asyncio.to_thread(
                        outbox.reconcile,work_id=work_id,epoch=epoch,
                        step=next_step,principal_id=MCP_PRINCIPAL_ID,
                    )
                # Do not expose user instruction text in status responses.
                if value is not None:
                    value = {k:v for k,v in value.items() if k != "message_text"}
                return {"status": "OK" if value else "NOT_FOUND",
                        "self_outbox": value}
            # Completion may arrive after a long generating turn exhausted its
            # lease. Renew only this exact owner/epoch and a fully reconciled
            # cursor, through the same fresh-observation fence as public claim.
            current = await asyncio.to_thread(ledger.get, work_id) if action == "complete" else None
            renew_for_completion = bool(
                action == "complete" and verified is True and current is not None
                and current["owner"] == owner and current["epoch"] == epoch
                and current["state"] == "LOOP_STARTED" and current["next_step"] >= 1
                and current["operation_state"] is None and current["lease_until"] <= time.time()
            )
            if action == "claim" or renew_for_completion:
                current = await asyncio.to_thread(ledger.get, work_id)
                if current is not None and current["state"] == "COMPLETED":
                    return {"status": "INVALID_REQUEST", "reason": "LOOP_COMPLETED"}
                if status_provider is None:
                    return {"status": "UNAVAILABLE",
                            "reason": "LOOP_EXACT_SUCCESSOR_STATUS_REQUIRED"}
                from bct.loop_self_dispatch import LoopSelfDispatcher
                from bct.loop_store import LoopStateError
                same_owner = (current is not None and current["owner"] == owner
                              and current["epoch"] == epoch)
                renewing = same_owner and current["state"] == "LOOP_STARTED"
                # Concurrent Monitor probes can return a cached INFLIGHT row;
                # timeout observations have a five-second probe backoff. Retry
                # observation only, never a send, and never accept cached data.
                delays = (0, .25, 1, 2, 3) if renewing else (0,)
                for attempt, delay in enumerate(delays):
                    if delay:
                        await asyncio.sleep(delay)
                    if renewing:
                        latest = await asyncio.to_thread(ledger.get, work_id)
                        if (latest is None or latest["owner"] != owner
                                or latest["epoch"] != epoch
                                or latest["state"] != "LOOP_STARTED"):
                            raise LoopStateError("LOOP_FENCED")
                    observed = await asyncio.to_thread(status_provider)
                    try:
                        LoopSelfDispatcher.exact_route(
                            observed, owner, require_idle=not same_owner,
                        )
                        break
                    except LoopStateError as exc:
                        if (str(exc) != "LOOP_NODE_OBSERVATION_STALE"
                                or attempt == len(delays) - 1):
                            raise
                # The transactional claim still fences takeover after the last
                # observation. Busy-owner renewal does not authorize delivery.
                loop = await asyncio.to_thread(
                    ledger.claim, work_id=work_id, owner=owner, epoch=epoch,
                )
                if action == "claim":
                    return {"status": "OK", "loop": loop}
                epoch = loop["epoch"]
            if action == "prepare_operation":
                loop = await asyncio.to_thread(
                    ledger.prepare_operation, work_id=work_id, owner=owner,
                    epoch=epoch, operation_id=operation_id,
                )
            elif action == "reconcile":
                loop = await asyncio.to_thread(
                    ledger.reconcile_from_bct, work_id=work_id, owner=owner,
                    epoch=epoch, operation_id=operation_id,
                    principal_id=MCP_PRINCIPAL_ID,
                )
            elif action == "advance":
                loop = await asyncio.to_thread(
                    ledger.advance, work_id=work_id, owner=owner,
                    epoch=epoch, next_step=next_step,
                )
            elif action == "complete":
                if verified is not True:
                    return {"status": "INVALID_REQUEST",
                            "reason": "LOOP_COMPLETION_VERIFICATION_REQUIRED"}
                from bct.loop_supervisor_handoff import LoopReviewLedger
                review_ledger = LoopReviewLedger(bct.store)
                if review_ledger.get(work_id):
                    review = await asyncio.to_thread(review_ledger.request, work_id=work_id,
                        owner=owner, epoch=epoch, candidate_sha=candidate_sha, evidence_text=evidence_text)
                    return {"status": "REVIEW_PENDING", "review": {k:v for k,v in review.items() if k != "message_text"}}
                loop = await asyncio.to_thread(
                    ledger.complete, work_id=work_id, owner=owner,
                    epoch=epoch, verified=True,
                )
            else:
                return {"status": "INVALID_REQUEST", "reason": "LOOP_ACTION_INVALID"}
            return {"status": "OK", "loop": loop}
        except (ValueError, KeyError) as exc:
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
        return await _execution_plan_commands().set(
            work_id=work_id, direction_id=direction_id, task_id=task_id,
            plan_text=plan_text, generation=generation, plan_id=plan_id,
        )

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
        return await _execution_plan_commands().update(
            plan_id=plan_id, plan_text=plan_text, update_reason=update_reason,
            work_id=work_id, task_id=task_id, generation=generation,
        )

    @server.tool(
        name="bct_get_execute_plan",
        description="Read one exact B-authored Chain Execution Plan. Does not send, plan, or decide.",
        structured_output=True,
    )
    async def bct_get_execute_plan(plan_id: str, work_id: str = "") -> dict[str, Any]:
        return await _execution_plan_commands().get(plan_id=plan_id, work_id=work_id)

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
        return await create_or_update_work(
            bct.store, principal_id=principal.principal_id,
            capabilities=principal.capabilities, work_id=work_id,
            request_summary=request_summary, roots=roots, actions=actions,
        )

    @server.tool(description="Read one exact operation receipt owned by the current MCP work.", structured_output=True)
    async def bct_operation_get(work_id: str, operation_id: str, wait_seconds: float = 0) -> dict[str, Any]:
        return await read_operation(
            bct.store, principal_id=principal.principal_id, work_id=work_id,
            operation_id=operation_id, wait_seconds=wait_seconds, trace_stage=_trace_stage,
        )

    @server.tool(description="Read GitHub CI/completion notifications for an owned BCT Work. acknowledge marks returned notifications read.", structured_output=True)
    async def bct_github_inbox_get(initiator_node_id: str = "", work_id: str = "",
                                   acknowledge: bool = False, limit: int = 80) -> dict[str, Any]:
        return await read_github_inbox(
            bct.store, principal_id=principal.principal_id,
            initiator_node_id=initiator_node_id, work_id=work_id,
            acknowledge=acknowledge, limit=limit,
        )

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
        return rcc_command_view()

    @server.tool(
        description=("List RCC Recipe blocks. Each block is an ordered list of public "
                     "bct_browser command names; listing a recipe neither performs nor "
                     "authorizes its steps."),
        structured_output=True,
    )
    async def bct_rcc_recipe_catalog() -> dict[str, Any]:
        return rcc_recipe_view()

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

    recipe_runtime = ChainRecipeRuntime(
        bct=bct, principal=principal, status_provider=status_provider,
        make_executor=make_executor,
    )

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
