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
from bct.core.models import BCTError, Principal, Work
from bct.mcp_server import LocalBearerMiddleware, build_mcp
from bct.monitor_runtime import build_monitor_state
from bct.service_runtime import acquire_runtime_writer_lock, current_process_identity


MONITOR_EXTENSION_ORIGIN = "chrome-extension://kaigandfpieiogfbfaemoimenmipedck"
MONITOR_PRINCIPAL_ID = "bct-monitor-extension"
MONITOR_WORK_ID = "bct-monitor-extension-control"
_OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5


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
        frozenset({"relay_browser"}),
    )
    expected = Work(
        MONITOR_WORK_ID,
        "BCT Monitor exact conversation controls",
        (str(runtime_root.resolve()),),
        frozenset({"relay_browser"}),
        principal.principal_id,
    )
    try:
        current = bct.store.get_work(MONITOR_WORK_ID)
    except KeyError:
        bct.store.create_work(expected)
    else:
        if current != expected:
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
    return bct.operations.run(
        principal=principal,
        work_id=MONITOR_WORK_ID,
        operation_id=operation_id,
        capability="relay_browser",
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
    from .background_operations import recover_orphaned_orchestration_operations
    orphan_recoveries = recover_orphaned_orchestration_operations(bct)
    monitor_principal = ensure_monitor_work(bct, runtime_root=runtime_root)
    identity = current_process_identity()
    control_token = os.environ.get("BCT_CONTROL_TOKEN", "")
    mcp_token = os.environ.get("BCT_MCP_TOKEN", "")
    if len(control_token) != 64:
        raise RuntimeError("BCT_CONTROL_TOKEN_MISSING")
    if len(mcp_token) != 64:
        raise RuntimeError("BCT_MCP_TOKEN_MISSING")
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
        "mcp_tool_count": len(bct.operations.capabilities) + 4,
        "started_at": time.time(),
        "orphan_recoveries": orphan_recoveries,
        "manager_decision_recovery": {
            "enabled": bct.manager_decision_recovery is not None,
            "runs": 0,
        },
        "worker_dispatch_recovery": {
            "enabled": bct.worker_dispatch_recovery is not None,
            "runs": 0,
        },
    }

    recovery_stop = threading.Event()

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

    def status_snapshot() -> dict[str, Any]:
        """Expose one no-argument, read-only operator view for MCP clients."""
        monitor = build_monitor_state(
            store=bct.store,
            service_state=state,
            data_root=runtime_root.parent / "data",
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

    mcp = build_mcp(bct, status_provider=status_snapshot)
    holder: dict[str, uvicorn.Server] = {}

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(state)

    @mcp.custom_route("/monitor/state", methods=["GET"], include_in_schema=False)
    async def monitor_state(request: Request) -> JSONResponse:
        return JSONResponse(await asyncio.to_thread(
            build_monitor_state,
            store=bct.store,
            service_state=state,
            data_root=runtime_root.parent / "data",
        ))

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
    try:
        server.run()
    finally:
        recovery_stop.set()
        if recovery_thread is not None:
            recovery_thread.join(timeout=3.0)
        if dispatch_thread is not None:
            dispatch_thread.join(timeout=3.0)
        writer_lock.close()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
