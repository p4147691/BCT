from __future__ import annotations

import argparse
import asyncio
import hmac
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from bct import BCT
from bct.core.capabilities import canonical_capability
from bct.core.models import BCTError, Principal, Work
from bct.mcp_server import LocalBearerMiddleware, build_mcp
from bct.monitor_runtime import build_monitor_state, build_monitor_ui_state, monitor_roster_revision
from bct.codex_surface import register_codex_surfaces
from bct.dot_identity import dot_directory, dot_key, save_dot_info
from bct.status_views import status_view
from bct.core.chat_stream_rcc_watch import ChatStreamRccWatch
from bct.integrations.rcc import NamedPipeRelayClient
from bct.node_label_notifications import NodeLabelNotifier, ensure_notification_work
from bct.conversation_network import (
    arrange_conversations,
    ConversationNetworkError,
    configure_conversation_scope,
    transfer_conversation_manager_role,
    retire_conversation_node_label,
    upsert_conversation,
)
from bct.bottleneck_ack import BottleneckAckController, load_bottleneck_ack_policy
from bct.service_runtime import acquire_runtime_writer_lock, current_process_identity


MONITOR_EXTENSION_ORIGIN = "chrome-extension://kaigandfpieiogfbfaemoimenmipedck"
MONITOR_PRINCIPAL_ID = "bct-monitor-extension"
MONITOR_WORK_ID = "bct-monitor-extension-control"
_OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5
RCC_BACKGROUND_SOURCE_PATH = Path(r"D:\BCT\source\modules\rcc\extension\background.js")
RCC_BACKGROUND_LIVE_PATH = Path(r"D:\ChromeExtensions\RCC\extension\background.js")


def build_server_config(app: Any, *, port: int) -> uvicorn.Config:
    """Bound shutdown even while a Streamable HTTP client keeps a session open."""
    return uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    )


def request_server_shutdown(server: uvicorn.Server) -> None:
    """Drain active requests, then skip an unbounded application lifespan shutdown."""
    server.should_exit = True
    server.force_exit = True


def monitor_extension_origin_allowed(value: str) -> bool:
    return str(value or "").rstrip("/") == MONITOR_EXTENSION_ORIGIN


def ensure_monitor_work(bct: BCT, *, runtime_root: Path) -> Principal:
    """Create the one durable BCT work used by the installed Monitor extension."""
    principal = Principal(
        MONITOR_PRINCIPAL_ID,
        "monitor-extension-origin",
        frozenset({"browser"}),
    )
    expected = Work(
        MONITOR_WORK_ID,
        "BCT Monitor exact conversation controls",
        (str(runtime_root.resolve()),),
        frozenset({"browser"}),
        principal.principal_id,
    )
    try:
        current = bct.store.get_work(MONITOR_WORK_ID)
    except KeyError:
        bct.store.create_work(expected)
    else:
        # Existing runtime state can still carry the old capability spelling
        # ``relay_browser``.  It grants the same bounded browser authority,
        # but must remain intact as historical Work evidence.
        legacy_browser_equivalent = (
            current.work_id == expected.work_id
            and current.request_summary == expected.request_summary
            and current.roots == expected.roots
            and frozenset(canonical_capability(action) for action in current.actions)
            == expected.actions
            and current.owner_principal_id == expected.owner_principal_id
            and current.assignment_epoch == expected.assignment_epoch
            and current.state == expected.state
        )
        if current != expected and not legacy_browser_equivalent:
            raise RuntimeError("MONITOR_WORK_CONTRACT_MISMATCH")
    return principal


def run_monitor_conversation_rename(
    bct: BCT,
    *,
    principal: Principal,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run one exact RCC title mutation through the normal BCT receipt path."""
    allowed = {
        "instance_id", "session_id", "tab_id", "conversation_key",
        "title", "operation_id", "timeout_s",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("MONITOR_RENAME_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    operation_id = str(payload.get("operation_id") or "").strip()
    if not _OPERATION_ID_PATTERN.fullmatch(operation_id):
        raise ValueError("MONITOR_RENAME_OPERATION_ID_INVALID")
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 100:
        raise ValueError("MONITOR_RENAME_TITLE_INVALID")
    arguments = {
        "command": "rename-conversation",
        "instance_id": str(payload.get("instance_id") or "").strip(),
        "session_id": str(payload.get("session_id") or "").strip(),
        "tab_id": payload.get("tab_id"),
        "conversation_key": str(payload.get("conversation_key") or "").strip(),
        "title": title,
        "timeout_s": payload.get("timeout_s", 30.0),
    }
    receipt = bct.operations.run(
        principal=principal,
        work_id=MONITOR_WORK_ID,
        operation_id=operation_id,
        capability="browser",
        arguments=arguments,
    ).as_dict()
    if str(receipt.get("outcome") or "").upper() == "APPLIED":
        upsert_conversation(
            bct.store,
            conversation_key=arguments["conversation_key"],
            display_name=title,
        )
    return receipt


def run_monitor_dot_rename(
    bct: BCT,
    *,
    principal: Principal,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Rename one exact Dot surface without treating its reference as a chat UUID."""
    allowed = {
        "instance_id", "session_id", "tab_id", "dot_key",
        "title", "operation_id", "timeout_s",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("MONITOR_DOT_RENAME_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    operation_id = str(payload.get("operation_id") or "").strip()
    if not _OPERATION_ID_PATTERN.fullmatch(operation_id):
        raise ValueError("MONITOR_DOT_RENAME_OPERATION_ID_INVALID")
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 100:
        raise ValueError("MONITOR_DOT_RENAME_TITLE_INVALID")
    arguments = {
        "command": "rename-dot",
        "instance_id": str(payload.get("instance_id") or "").strip(),
        "session_id": str(payload.get("session_id") or "").strip(),
        "tab_id": payload.get("tab_id"),
        "dot_key": dot_key(payload.get("dot_key")),
        "title": title,
        "timeout_s": payload.get("timeout_s", 30.0),
    }
    return bct.operations.run(
        principal=principal,
        work_id=MONITOR_WORK_ID,
        operation_id=operation_id,
        capability="browser",
        arguments=arguments,
    ).as_dict()


def run_monitor_conversation_scope_update(
    bct: BCT, *, payload: dict[str, Any]
) -> dict[str, object]:
    """Persist one chat's display scope and advisory roles.

    This is metadata only. It does not create a Work, acquire a Claim, elect a
    privileged Manager, or perform any browser action.
    """
    operation = str(payload.get("operation") or "set-node-info").strip().casefold()
    if operation == "manager-transfer":
        allowed = {
            "operation", "project_id", "predecessor_conversation_key",
            "successor_conversation_key", "expected_successor_role_tags_sha256",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError("MONITOR_CONVERSATION_SCOPE_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
        return transfer_conversation_manager_role(
            bct.store,
            project_id=str(payload.get("project_id") or ""),
            predecessor_conversation_key=str(payload.get("predecessor_conversation_key") or ""),
            successor_conversation_key=str(payload.get("successor_conversation_key") or ""),
            expected_successor_role_tags_sha256=str(payload.get("expected_successor_role_tags_sha256") or ""),
        )
    allowed = {
        "operation",
        "conversation_key", "display_name", "scope_name", "role_tags",
        "expected_role_tags_sha256", "node_memo", "assigned_task",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("MONITOR_CONVERSATION_SCOPE_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    return configure_conversation_scope(
        bct.store,
        conversation_key=str(payload.get("conversation_key") or ""),
        display_name=str(payload.get("display_name") or ""),
        scope_name=str(payload.get("scope_name") or ""),
        role_tags=payload.get("role_tags") or [],
        expected_role_tags_sha256=payload.get("expected_role_tags_sha256"),
        node_memo=payload.get("node_memo"),
        assigned_task=payload.get("assigned_task"),
    )


async def codex_surface_register_response(bct: BCT, request: Request) -> JSONResponse:
    if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
        return JSONResponse({"error":"MONITOR_EXTENSION_ORIGIN_INVALID"},status_code=403)
    try:
        payload = await request.json()
        if not isinstance(payload,dict) or set(payload) != {"urls"}:
            raise ValueError("CODEX_SURFACE_FIELDS_INVALID")
        directory = await asyncio.to_thread(register_codex_surfaces,bct.store,payload["urls"])
        return JSONResponse({"status":"OK","directory":directory})
    except ValueError as exc:
        return JSONResponse({"error":str(exc)},status_code=400)


async def dot_node_info_response(bct: BCT, request: Request) -> JSONResponse:
    if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
        return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
    try:
        if request.method == "GET":
            records = await asyncio.to_thread(dot_directory, bct.store)
            return JSONResponse({"status": "OK", "dots": records})
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("DOT_OBJECT_REQUIRED")
        result = await asyncio.to_thread(save_dot_info, bct.store, payload)
        return JSONResponse({"status": "OK", "conversation": result})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def run_monitor_conversation_order_update(
    bct: BCT, *, payload: dict[str, Any]
) -> dict[str, object]:
    """Persist display order and an optional cross-scope move atomically."""
    allowed = {"conversation_keys", "scope_id", "moved_conversation_key"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("MONITOR_CONVERSATION_ORDER_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    return arrange_conversations(
        bct.store,
        conversation_keys=payload.get("conversation_keys") or [],
        scope_id=str(payload.get("scope_id") or ""),
        moved_conversation_key=str(payload.get("moved_conversation_key") or ""),
    )


def run_monitor_conversation_node_retire(
    bct: BCT, *, payload: dict[str, Any]
) -> dict[str, object]:
    allowed = {"conversation_key", "expected_node_label"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("MONITOR_CONVERSATION_NODE_RETIRE_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    return retire_conversation_node_label(
        bct.store,
        conversation_key=str(payload.get("conversation_key") or ""),
        expected_node_label=str(payload.get("expected_node_label") or ""),
    )


def run_monitor_rcc_reload(
    bct: BCT,
    *,
    principal: Principal,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Reload one exact observed RCC instance through the durable receipt path."""
    allowed = {"instance_id", "operation_id", "timeout_s"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("MONITOR_RCC_RELOAD_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    operation_id = str(payload.get("operation_id") or "").strip()
    if not _OPERATION_ID_PATTERN.fullmatch(operation_id):
        raise ValueError("MONITOR_RCC_RELOAD_OPERATION_ID_INVALID")
    instance_id = str(payload.get("instance_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{6,128}", instance_id):
        raise ValueError("MONITOR_RCC_RELOAD_INSTANCE_ID_INVALID")
    arguments = {
        "command": "reload-extension",
        "instance_id": instance_id,
        "timeout_s": payload.get("timeout_s", 10.0),
    }
    return bct.operations.run(
        principal=principal,
        work_id=MONITOR_WORK_ID,
        operation_id=operation_id,
        capability="browser",
        arguments=arguments,
    ).as_dict()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--port", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    runtime_root = Path(arguments.runtime_root).resolve()
    writer_lock = acquire_runtime_writer_lock(runtime_root)
    release_root = runtime_root / "releases" / arguments.release_sha
    policy_path = release_root / "bct.toml"
    if not policy_path.is_file():
        raise RuntimeError("RUNTIME_POLICY_MISSING")
    from .features.deploy import DeploymentProfiles, _validate_profile_start_allowed
    runtime_profiles = DeploymentProfiles(policy_path)
    _validate_profile_start_allowed(
        runtime_profiles, runtime_profiles.for_runtime_root(runtime_root)
    )
    bct = BCT(
        state_path=runtime_root / "state" / "state.sqlite",
        policy_path=policy_path,
        data_root=runtime_root.parent / "data",
    )
    from .send_delayed_message import SendDelayedMessageService
    from .background_operations import recover_orphaned_orchestration_operations
    orphan_recoveries = recover_orphaned_orchestration_operations(bct)
    monitor_principal = ensure_monitor_work(bct, runtime_root=runtime_root)
    label_principal = ensure_notification_work(bct, runtime_root)
    node_label_notifier = NodeLabelNotifier(bct, label_principal)
    bottleneck_ack = BottleneckAckController(
        load_bottleneck_ack_policy(policy_path), bct=bct, principal=monitor_principal,
    )
    identity = current_process_identity()
    control_token = os.environ.get("BCT_CONTROL_TOKEN", "")
    mcp_token = os.environ.get("BCT_MCP_TOKEN", "")
    if len(control_token) != 64:
        raise RuntimeError("BCT_CONTROL_TOKEN_MISSING")
    if len(mcp_token) != 64:
        raise RuntimeError("BCT_MCP_TOKEN_MISSING")
    catalogue_mode = os.environ.get("BCT_MCP_CATALOGUE", "full")
    if catalogue_mode not in ("full", "compact", "hybrid"):
        raise RuntimeError("BCT_MCP_CATALOGUE_INVALID")
    compact_catalogue = catalogue_mode == "compact"
    hybrid_catalogue = catalogue_mode == "hybrid"
    state = {
        "status": "OK",
        "ready": True,
        "service": arguments.service_name,
        **identity.as_dict(),
        "release_sha": arguments.release_sha,
        "manifest_sha256": arguments.manifest_sha256,
        "generation": arguments.generation,
        "instance_id": arguments.instance_id,
        "health_contract": 2,
        "capabilities": list(bct.operations.capabilities),
        "mcp_ready": True,
        "mcp_endpoint": f"http://127.0.0.1:{arguments.port}/mcp",
        "mcp_tool_count": 10 if hybrid_catalogue else 8 if compact_catalogue else len(bct.operations.capabilities) + 5,
        "started_at": time.time(),
        "orphan_recoveries": orphan_recoveries,
        "orchestration_policy": {
            "manager_failover_seconds": bct.orchestration.manager_failover_seconds,
            "worker_reroute_wait_seconds": bct.orchestration.worker_reroute_wait_seconds,
            "required_node_hold_seconds": bct.orchestration.required_node_hold_seconds,
        },
        "manager_decision_recovery": {
            "enabled": bct.manager_decision_recovery is not None,
            "runs": 0,
        },
        "worker_dispatch_recovery": {
            "enabled": bct.worker_dispatch_recovery is not None,
            "runs": 0,
        },
        "manager_succession_recovery": {
            "enabled": bct.manager_succession_recovery is not None,
            "runs": 0,
        },
        "delivery_continuation_recovery": {
            "enabled": True, "runs": 0,
        },
        "bottleneck_ack": bottleneck_ack.status(),
        "chat_stream_rcc_watch": {"state": "IDLE", "polls": 0, "last_events": 0},
        "delayed_send_watch": {"state": "IDLE", "polls": 0, "last_events": 0},
        "automatic_chain_recovery": {
            "enabled": True, "runs": 0,
            "scope": "EXACT_A_B_C_S_CHECK_RECHECK",
        },
    }

    recovery_stop = threading.Event()
    node_label_notifier.start()

    def manager_decision_recovery_loop() -> None:
        recovery = bct.manager_decision_recovery
        if recovery is None:
            return
        while not recovery_stop.is_set():
            try:
                outcome = recovery.run_once(limit=8)
                state["manager_decision_recovery"] = {
                    "enabled": True,
                    "runs": int(state["manager_decision_recovery"].get("runs", 0)) + 1,
                    "last_outcome": outcome,
                    "last_error": None,
                    "last_run_at": time.time(),
                }
            except Exception as exc:  # fail closed; the durable rows remain authoritative
                state["manager_decision_recovery"] = {
                    "enabled": True,
                    "runs": int(state["manager_decision_recovery"].get("runs", 0)) + 1,
                    "last_error": type(exc).__name__ + ":" + str(exc),
                    "last_run_at": time.time(),
                }
            recovery_stop.wait(2.0)

    def worker_dispatch_recovery_loop() -> None:
        recovery = bct.worker_dispatch_recovery
        if recovery is None:
            return
        while not recovery_stop.is_set():
            try:
                outcome = recovery.run_once(limit=8)
                state["worker_dispatch_recovery"] = {
                    "enabled": True,
                    "runs": int(state["worker_dispatch_recovery"].get("runs", 0)) + 1,
                    "last_outcome": outcome,
                    "last_error": None,
                    "last_run_at": time.time(),
                }
            except Exception as exc:  # durable rows remain authoritative
                state["worker_dispatch_recovery"] = {
                    "enabled": True,
                    "runs": int(state["worker_dispatch_recovery"].get("runs", 0)) + 1,
                    "last_error": type(exc).__name__ + ":" + str(exc),
                    "last_run_at": time.time(),
                }
            # Event-first latency with bounded polling as the recovery safety net.
            recovery.wait(2.0)

    def manager_succession_recovery_loop() -> None:
        recovery = bct.manager_succession_recovery
        if recovery is None:
            return
        while not recovery_stop.is_set():
            try:
                outcome = recovery.run_once(limit=8)
                state["manager_succession_recovery"] = {
                    "enabled": True,
                    "runs": int(state["manager_succession_recovery"].get("runs", 0)) + 1,
                    "last_outcome": outcome,
                    "last_error": None,
                    "last_run_at": time.time(),
                }
            except Exception as exc:  # no state change is assumed after a failed observation
                state["manager_succession_recovery"] = {
                    "enabled": True,
                    "runs": int(state["manager_succession_recovery"].get("runs", 0)) + 1,
                    "last_error": type(exc).__name__ + ":" + str(exc),
                    "last_run_at": time.time(),
                }
            recovery_stop.wait(2.0)

    def bottleneck_ack_loop() -> None:
        """Observe RCC telemetry only; the controller owns any one-shot effect."""
        while not recovery_stop.is_set():
            try:
                monitor = build_monitor_state(
                    store=bct.store, service_state=state,
                    data_root=runtime_root.parent / "data",
                )
                state["bottleneck_ack"] = bottleneck_ack.observe(
                    monitor["rcc"]["instances"],
                )
            except Exception as exc:  # Never turn an observation fault into a relay retry.
                state["bottleneck_ack"] = {"state": "UNKNOWN", "error": type(exc).__name__}
            recovery_stop.wait(2.0)

    def delivery_continuation_recovery_loop() -> None:
        recovery = bct.delivery_continuation_recovery
        # Shared recovery cycle hook; no manager identity provider or relay is
        # wired in production yet, so this never submits a live message.
        from .github_manager_wake import GithubWakeRecoveryAdapter
        github_wake = GithubWakeRecoveryAdapter(bct.store, manager_candidates=lambda: [])
        while not recovery_stop.is_set():
            try:
                outcome = recovery.run_once(limit=8)
                outcome["github_manager_wake"] = github_wake.run_once()
                state["delivery_continuation_recovery"] = {
                    "enabled": True,
                    "runs": int(state["delivery_continuation_recovery"].get("runs", 0)) + 1,
                    "last_outcome": outcome,
                    "last_error": None,
                    "last_run_at": time.time(),
                }
            except Exception as exc:
                state["delivery_continuation_recovery"] = {
                    "enabled": True,
                    "runs": int(state["delivery_continuation_recovery"].get("runs", 0)) + 1,
                    "last_error": type(exc).__name__ + ":" + str(exc),
                    "last_run_at": time.time(),
                }
            recovery_stop.wait(2.0)

    def chat_stream_rcc_watch_loop() -> None:
        # No watches => no RCC request. No message submits or claims.
        observer = ChatStreamRccWatch(bct.store, NamedPipeRelayClient())
        while not recovery_stop.wait(15.0):
            try:
                events = observer.poll_once()
                state["chat_stream_rcc_watch"] = {
                    "state": "OBSERVED", "polls": int(
                        state["chat_stream_rcc_watch"].get("polls", 0)) + 1,
                    "last_events": len(events), "last_polled_at": time.time(),
                }
            except Exception as exc:
                # Never turn a telemetry outage into a guessed reconnect.
                state["chat_stream_rcc_watch"] = {
                    "state": "UNAVAILABLE", "error": type(exc).__name__,
                    "polls": int(state["chat_stream_rcc_watch"].get("polls", 0)) + 1,
                    "last_events": 0,
                }

    def delayed_send_watch_loop() -> None:
        service = SendDelayedMessageService(
            store=bct.store,
            browser_feature=bct.operations._features["browser"],
            operations=bct.operations,
        )
        while not recovery_stop.wait(2.0):
            try:
                outcome = service.poll_once(limit=8)
                state["delayed_send_watch"] = {
                    "state":"OBSERVED",
                    "polls":int(state["delayed_send_watch"].get("polls",0))+1,
                    "last_events":len(outcome["events"]),
                    "last_result":outcome,
                }
            except Exception as exc:
                state["delayed_send_watch"] = {
                    "state":"UNAVAILABLE",
                    "error":type(exc).__name__,
                    "polls":int(state["delayed_send_watch"].get("polls",0))+1,
                }

    def status_snapshot() -> dict[str, Any]:
        """Expose one no-argument, read-only operator view for MCP clients."""
        monitor = build_monitor_state(
            store=bct.store,
            service_state=state,
            data_root=runtime_root.parent / "data",
            rcc_source_path=RCC_BACKGROUND_SOURCE_PATH,
            rcc_live_path=RCC_BACKGROUND_LIVE_PATH,
        )
        return {
            "schema": 1,
            "core": dict(state),
            "runtime": {
                "release_sha": arguments.release_sha,
                "manifest_sha256": arguments.manifest_sha256,
                "generation": arguments.generation,
            },
            "monitor": monitor,
        }

    def automatic_chain_recovery_loop() -> None:
        """Automatic-first node Check/Recheck, independent of user prompts."""
        from .automatic_chain_recovery import AutomaticChainNodeRecovery
        from .automatic_manager_rebinding import AutomaticManagerRebinding
        from .automatic_prepared_replacement import AutomaticPreparedReplacement
        recovery = AutomaticChainNodeRecovery(
            store=bct.store, status_provider=status_snapshot,
        )
        manager_binding = AutomaticManagerRebinding(
            store=bct.store, status_provider=status_snapshot,
        )
        prepared_replacement = AutomaticPreparedReplacement(
            store=bct.store, status_provider=status_snapshot,
        )
        while not recovery_stop.is_set():
            try:
                outcome = recovery.run_once(limit=16)
                # Manager transfer must already be formally recorded, and
                # the actual successor UUID/role/connection must be verified.
                # This never creates a new Chat or replays a Worker task.
                outcome["manager_rebinding"] = manager_binding.run_once(limit=8)
                outcome["prepared_replacement"] = prepared_replacement.run_once(limit=8)
                state["automatic_chain_recovery"] = {
                    "enabled": True,
                    "runs": int(state["automatic_chain_recovery"].get("runs", 0)) + 1,
                    "last_outcome": outcome,
                    "last_error": None,
                    "last_run_at": time.time(),
                    "scope": "EXACT_A_B_C_S_CHECK_RECHECK",
                }
            except Exception as exc:
                state["automatic_chain_recovery"] = {
                    "enabled": True,
                    "runs": int(state["automatic_chain_recovery"].get("runs", 0)) + 1,
                    "last_error": type(exc).__name__,
                    "last_run_at": time.time(),
                    "scope": "EXACT_A_B_C_S_CHECK_RECHECK",
                }
            # A healthy Chat can generate for an unbounded period. Never
            # treat elapsed time alone as a replacement trigger.
            recovery_stop.wait(8.0)

    mcp = build_mcp(bct, status_provider=status_snapshot, compact_catalogue=compact_catalogue, hybrid_catalogue=hybrid_catalogue)
    holder: dict[str, uvicorn.Server] = {}

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(state)

    @mcp.custom_route("/monitor/ui-layout", methods=["GET"], include_in_schema=False)
    async def monitor_ui_layout(request: Request) -> JSONResponse:
        # Local presentation settings only; no action API and no credential data.
        from bct.monitor_ui_layout import load_layout, project_for_client
        config, status = await asyncio.to_thread(load_layout, runtime_root.parent / "data")
        config = project_for_client(config,
                                    capture_fallback_capable=request.query_params.get("capture_fallback") == "1")
        return JSONResponse({"schema": 1, "status": status, "config": config},
                            headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/monitor/state", methods=["GET"], include_in_schema=False)
    async def monitor_state(request: Request) -> JSONResponse:
        """Serve the display roster without running Monitor maintenance work."""
        snapshot = await asyncio.to_thread(
            build_monitor_ui_state,
            store=bct.store,
            service_state=state,
            data_root=runtime_root.parent / "data",
        )
        return JSONResponse(snapshot)

    @mcp.custom_route("/monitor/roster-revision", methods=["GET"], include_in_schema=False)
    async def monitor_roster_revision_state(request: Request) -> JSONResponse:
        """Return only the durable display marker used by an open Monitor."""
        snapshot = await asyncio.to_thread(monitor_roster_revision, bct.store)
        return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/monitor/current-nodes", methods=["GET"], include_in_schema=False)
    async def monitor_current_nodes(request: Request) -> JSONResponse:
        """Return the small, read-only current-node view from one Monitor snapshot.

        This route exists for callers that need an exact open conversation/node
        identity before acting.  It deliberately does not expose the historical
        work/event lists from ``/monitor/state`` and does not create a watcher,
        lease, delivery, or permission decision.
        """
        monitor = await asyncio.to_thread(
            build_monitor_ui_state,
            store=bct.store,
            service_state=state,
            data_root=runtime_root.parent / "data",
        )
        return JSONResponse({
            "schema": 1,
            "source": "READ_ONLY_MONITOR_UI_SNAPSHOT",
            "generated_at": monitor.get("generated_at"),
            "current_nodes": monitor.get("current_nodes"),
            "conversation_network_managers": monitor.get("conversation_network_managers", []),
        }, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/monitor/rcc-command-catalog", methods=["GET"], include_in_schema=False)
    async def monitor_rcc_command_catalog(request: Request) -> JSONResponse:
        """Expose the MCP public-command catalogue for Monitor's read-only viewer.

        This route neither invokes a command nor derives availability from role,
        ownership, or remembered browser state.  Keeping the rows sourced from
        ``command_catalog`` prevents a separately maintained Monitor list.
        """
        from bct.features.rcc import command_catalog
        return JSONResponse({
            "schema": 1,
            "source": "bct.features.rcc.command_catalog",
            "commands": command_catalog(),
        }, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/monitor", methods=["GET"], include_in_schema=False)
    async def monitor(request: Request) -> FileResponse:
        asset = release_root / "modules" / "status-ui" / "index.html"
        if not asset.is_file():
            return JSONResponse({"error": "BCT_MONITOR_ASSET_MISSING"}, status_code=503)
        return FileResponse(asset, media_type="text/html; charset=utf-8")

    @mcp.custom_route(
        "/monitor/conversation-title/rename",
        methods=["POST"],
        include_in_schema=False,
    )
    async def monitor_conversation_title_rename(request: Request) -> JSONResponse:
        if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
            return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("MONITOR_RENAME_OBJECT_REQUIRED")
            result = await asyncio.to_thread(
                run_monitor_conversation_rename,
                bct,
                principal=monitor_principal,
                payload=payload,
            )
        except (ValueError, BCTError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    @mcp.custom_route(
        "/monitor/dot-title/rename",
        methods=["POST"],
        include_in_schema=False,
    )
    async def monitor_dot_title_rename(request: Request) -> JSONResponse:
        if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
            return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("MONITOR_DOT_RENAME_OBJECT_REQUIRED")
            result = await asyncio.to_thread(
                run_monitor_dot_rename,
                bct,
                principal=monitor_principal,
                payload=payload,
            )
        except (ValueError, BCTError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    @mcp.custom_route(
        "/monitor/rcc/reload",
        methods=["POST"],
        include_in_schema=False,
    )
    async def monitor_rcc_reload(request: Request) -> JSONResponse:
        if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
            return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("MONITOR_RCC_RELOAD_OBJECT_REQUIRED")
            result = await asyncio.to_thread(
                run_monitor_rcc_reload,
                bct,
                principal=monitor_principal,
                payload=payload,
            )
        except (ValueError, BCTError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    @mcp.custom_route("/monitor/codex-surface/register", methods=["POST"], include_in_schema=False)
    async def monitor_codex_surface_register(request: Request) -> JSONResponse:
        return await codex_surface_register_response(bct, request)

    @mcp.custom_route("/monitor/dot-node-info", methods=["GET", "POST"], include_in_schema=False)
    async def monitor_dot_node_info(request: Request) -> JSONResponse:
        return await dot_node_info_response(bct, request)

    @mcp.custom_route(
        "/monitor/conversation-network/update",
        methods=["POST"],
        include_in_schema=False,
    )
    async def monitor_conversation_network_update(request: Request) -> JSONResponse:
        if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
            return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("MONITOR_CONVERSATION_SCOPE_OBJECT_REQUIRED")
            result = await asyncio.to_thread(
                run_monitor_conversation_scope_update,
                bct,
                payload=payload,
            )
        except (ValueError, ConversationNetworkError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "OK", "conversation": result})

    @mcp.custom_route(
        "/monitor/conversation-network/reorder",
        methods=["POST"],
        include_in_schema=False,
    )
    async def monitor_conversation_network_reorder(request: Request) -> JSONResponse:
        if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
            return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("MONITOR_CONVERSATION_ORDER_OBJECT_REQUIRED")
            result = await asyncio.to_thread(
                run_monitor_conversation_order_update,
                bct,
                payload=payload,
            )
        except (ValueError, ConversationNetworkError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "OK", "order": result})

    @mcp.custom_route(
        "/monitor/conversation-node/retire",
        methods=["POST"],
        include_in_schema=False,
    )
    async def monitor_conversation_node_retire(request: Request) -> JSONResponse:
        if not monitor_extension_origin_allowed(request.headers.get("origin", "")):
            return JSONResponse({"error": "MONITOR_EXTENSION_ORIGIN_INVALID"}, status_code=403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("MONITOR_CONVERSATION_NODE_RETIRE_OBJECT_REQUIRED")
            result = await asyncio.to_thread(
                run_monitor_conversation_node_retire,
                bct,
                payload=payload,
            )
        except (ValueError, ConversationNetworkError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "OK", "retirement": result})

    @mcp.custom_route("/shutdown", methods=["POST"], include_in_schema=False)
    async def shutdown(request: Request) -> JSONResponse:
        supplied = request.headers.get("X-BCT-Control-Token", "")
        if not hmac.compare_digest(supplied, control_token):
            return JSONResponse({"error": "CONTROL_TOKEN_INVALID"}, status_code=403)
        request_server_shutdown(holder["server"])
        return JSONResponse({"accepted": True})

    app = LocalBearerMiddleware(mcp.streamable_http_app(), mcp_token)
    config = build_server_config(app, port=arguments.port)
    server = uvicorn.Server(config)
    holder["server"] = server
    recovery_thread = None
    dispatch_thread = None
    succession_thread = None
    bottleneck_thread = None
    delivery_continuation_thread = threading.Thread(
        target=delivery_continuation_recovery_loop,
        name="bct-delivery-continuation-recovery", daemon=True,
    )
    delivery_continuation_thread.start()
    chat_stream_watch_thread = threading.Thread(
        target=chat_stream_rcc_watch_loop,
        name="bct-chat-stream-rcc-watch", daemon=True,
    )
    chat_stream_watch_thread.start()
    delayed_send_watch_thread = threading.Thread(
        target=delayed_send_watch_loop, name="bct-delayed-send-watch", daemon=True,
    )
    delayed_send_watch_thread.start()
    automatic_chain_recovery_thread = threading.Thread(
        target=automatic_chain_recovery_loop,
        name="bct-automatic-chain-recovery", daemon=True,
    )
    automatic_chain_recovery_thread.start()
    if bct.manager_decision_recovery is not None:
        recovery_thread = threading.Thread(
            target=manager_decision_recovery_loop,
            name="bct-manager-decision-recovery", daemon=True,
        )
        recovery_thread.start()
    if bct.worker_dispatch_recovery is not None:
        dispatch_thread = threading.Thread(
            target=worker_dispatch_recovery_loop,
            name="bct-worker-dispatch-recovery", daemon=True,
        )
        dispatch_thread.start()
    if bct.manager_succession_recovery is not None:
        succession_thread = threading.Thread(
            target=manager_succession_recovery_loop,
            name="bct-manager-succession-recovery", daemon=True,
        )
        succession_thread.start()
    if bottleneck_ack.policy.enabled:
        bottleneck_thread = threading.Thread(
            target=bottleneck_ack_loop, name="bct-bottleneck-ack", daemon=True,
        )
        bottleneck_thread.start()
    try:
        server.run()
    finally:
        recovery_stop.set()
        node_label_notifier.stop()
        automatic_chain_recovery_thread.join(timeout=3.0)
        if recovery_thread is not None:
            recovery_thread.join(timeout=3.0)
        if dispatch_thread is not None:
            dispatch_thread.join(timeout=3.0)
        if succession_thread is not None:
            succession_thread.join(timeout=3.0)
        if bottleneck_thread is not None:
            bottleneck_thread.join(timeout=3.0)
        delivery_continuation_thread.join(timeout=3.0)
        chat_stream_watch_thread.join(timeout=3.0)
        try:
            bct.cdp_connections.close()
        finally:
            writer_lock.close()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
