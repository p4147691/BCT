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


from .trace_timing import TRACE_ID as _MCP_TRACE_ID, trace_stage as _trace_stage

MCP_PRINCIPAL_ID = "bct-mcp-local"

_GENERAL_TOOLS = (
    "bct_capabilities", "bct_status", "bct_conversation_network_get",
    "bct_work_create", "bct_operation_get",
)
_CAPABILITY_USAGE = {
    "test": "Run existing py_compile/unittest checks. Cached catalogues can submit a bounded verification recipe using arguments.operation=verify plus steps; this requires verify and every child capability in work scope.",
    "verify": "Run up to 8 read metadata, test, or github_pr_status steps, or a fixed versioned recipe. Each step is durably journaled. Requires each child action in work scope. Background operation; retrieve receipt and step_journal with bct_operation_get(wait_seconds=25). No file bodies or test output are persisted.",
    "github_pr_status": "Exact expected_head and required_checks required. Optional wait_seconds (0..300) waits server-side; positive waits run in background. Retrieve receipt with bct_operation_get.",
    "github_run_watch": "Register one exact Actions run for a detached, advisory-only Inbox completion. It never merges, pushes, deploys, or changes Work state; retrieve terminal results with bct_inbox_get.",
    "read": "For one file use arguments={\"path\": \"absolute file path\"}; for a bounded folder listing use operation=directory_tree; combine related reads with operation=batch and items containing unique id, path, and optional directory_tree bounds.",
    "system_inspect": "Use arguments.operation as process_list, process, or port. process_list accepts optional query and limit; process requires pid; port requires port.",
    "monitor": "Use arguments.operation as status or validate.",
    "conversation_network_update": "Patch advisory role tags in the existing conversation-network store. Use arguments={\"operation\":\"role-patch\",\"project\":\"scope name or id\",\"node_label\":\"N14\",\"add\":[\"CI\"],\"remove\":[],\"expected_role_tags_sha256\":\"digest from bct_conversation_network_get\"}. This changes no tool permission, browser route, or current Delivery and applies to newly composed messages only.",
    "cdp_inspect": "Read-only existing Chrome tab listing via a single approved Chrome DevTools MCP connection. Use arguments={\\\"operation\\\":\\\"list_pages\\\"}. Requires a work with cdp_inspect permission and locally enabled CDP policy; does not send messages, create tabs, or bypass Chrome consent.",
    "browser_extension_manage": "Read-only Chrome extension inventory via CDP. arguments={\\\"operation\\\":\\\"inventory\\\"} (or pages). Work-scoped; create/update/delete not enabled in this initial common MCP adapter. CDP only. Do not infer Tampermonkey CRUD support from this tool yet.",
    "relay_browser": "RCC 상태 확인은 command=state, instance_id를 쓴다. 단일 원자 명령: create-chat-window(새 Chrome 창+빈 ChatGPT 탭), create-chat-tab(선택 window_id에 빈 탭), send-to-created-tab(생성 영수증의 session_id/tab_id/window_id/create_operation_id와 text로 첫 메시지), move-tab(현재 window_id와 target_window_id, tab_id, index, 기존 conversation_key 또는 생성 create_operation_id), send-to-tab(기존 대화의 정확한 instance_id/session_id/tab_id/window_id, 선택 conversation_key, text)이다. send-to-created-tab과 send-to-tab만 전송 효과가 있다. generic send는 to,text만 쓰는 레거시 논리 수신자 명령이며 탭 ID를 넣지 않는다. create-and-send는 위 동작을 묶은 레거시 조합 명령이다. 모든 명령은 같은 operation_id의 동일 요청에만 멱등이며 UNKNOWN은 새 ID로 재전송하지 않는다.",
    "relay_control": "Execute one enabled hot-read relay purpose using arguments={\"purpose\":\"selected purpose\",\"scope_id\":\"project scope\",\"context\":{...},\"expected_settings_sha256\":\"preview revision\"}. The fixed registry permits one existing BCT operation step per invocation. Settings never grant authority: the Work must contain the delegated capability such as relay_browser or cdp_inspect. Reuse operation_id only for the exact same frozen request and never retry UNKNOWN with a new ID.",
    "orchestrate": "Durable read-evidence manager/worker sessions. Use project-run-plan to select one advisory Manager conversation from an existing conversation scope, then start and sync a session, select a manager epoch, and project-run-bind the exact active RCC attachment. A later attachment generation for the same conversation may be rebound; stale generations are rejected only at the effect boundary. Use dispatch or chain-run for work. Browser mutations run in background; recover with bct_operation_get. Recovery never resends an UNKNOWN effect.",
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
    async def bct_status(compact: bool = True) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        if status_provider is None:
            return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
        snapshot = await asyncio.to_thread(status_provider)
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

    @server.tool(description="Read only a node's durable GitHub completion Inbox. acknowledge is idempotent and only marks returned rows read.", structured_output=True)
    async def bct_inbox_get(initiator_node_id: str, work_id: str,
                            acknowledge: bool = False, limit: int = 80) -> dict[str, Any]:
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
                        "dispatch", "worker-replace", "chain-run", "chain-resume",
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
            result = await asyncio.to_thread(
                bct.operations.run,
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
