from __future__ import annotations

import argparse
import hmac
import os
import time
from pathlib import Path
from typing import Any

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse

from bct import BCT
from bct.mcp_server import LocalBearerMiddleware, build_mcp
from bct.service_runtime import current_process_identity


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
    release_root = runtime_root / "releases" / arguments.release_sha
    policy_path = release_root / "bct.toml"
    if not policy_path.is_file():
        raise RuntimeError("RUNTIME_POLICY_MISSING")
    bct = BCT(state_path=runtime_root / "state" / "state.sqlite", policy_path=policy_path)
    identity = current_process_identity()
    control_token = os.environ.get("BCT_CONTROL_TOKEN", "")
    mcp_token = os.environ.get("BCT_MCP_TOKEN", "")
    if len(control_token) != 64:
        raise RuntimeError("BCT_CONTROL_TOKEN_MISSING")
    if len(mcp_token) != 64:
        raise RuntimeError("BCT_MCP_TOKEN_MISSING")
    mcp = build_mcp(bct)
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
        "mcp_tool_count": len(bct.operations.capabilities) + 3,
        "started_at": time.time(),
    }
    holder: dict[str, uvicorn.Server] = {}

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(state)

    @mcp.custom_route("/shutdown", methods=["POST"], include_in_schema=False)
    async def shutdown(request: Request) -> JSONResponse:
        supplied = request.headers.get("X-BCT-Control-Token", "")
        if not hmac.compare_digest(supplied, control_token):
            return JSONResponse({"error": "CONTROL_TOKEN_INVALID"}, status_code=403)
        holder["server"].should_exit = True
        return JSONResponse({"accepted": True})

    app = LocalBearerMiddleware(mcp.streamable_http_app(), mcp_token)
    config = uvicorn.Config(app, host="127.0.0.1", port=arguments.port, log_level="warning")
    server = uvicorn.Server(config)
    holder["server"] = server
    server.run()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
