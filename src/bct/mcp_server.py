from __future__ import annotations

import asyncio
import hmac
from pathlib import Path
from typing import Any, Callable, Coroutine

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from .background_operations import BACKGROUND_CAPABILITIES, launch_background_operation
from .core.models import Principal, Work


MCP_PRINCIPAL_ID = "bct-mcp-local"


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


def build_mcp(bct: Any) -> FastMCP:
    """Build the public MCP catalogue from the registered BCT capabilities."""
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
        return {
            "capabilities": list(capabilities),
            "tools": [f"bct_{name}" for name in capabilities],
        }

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
    async def bct_operation_get(work_id: str, operation_id: str) -> dict[str, Any]:
        return bct.store.get_operation_for(
            operation_id=operation_id,
            work_id=work_id,
            principal_id=principal.principal_id,
        ).as_dict()

    def make_executor(capability: str) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        async def execute(
            work_id: str,
            operation_id: str,
            arguments: dict[str, Any],
            approval_ref: str | None = None,
        ) -> dict[str, Any]:
            if capability in BACKGROUND_CAPABILITIES:
                result = await asyncio.to_thread(
                    launch_background_operation,
                    bct,
                    principal=principal,
                    work_id=work_id,
                    operation_id=operation_id,
                    capability=capability,
                    arguments=arguments,
                    approval_ref=approval_ref,
                )
                return result.as_dict()
            result = await asyncio.to_thread(
                bct.operations.run,
                principal=principal,
                work_id=work_id,
                operation_id=operation_id,
                capability=capability,
                arguments=arguments,
                approval_ref=approval_ref,
            )
            return result.as_dict()

        execute.__name__ = "bct_" + capability
        execute.__doc__ = f"Execute the registered BCT {capability!r} capability."
        return execute

    for capability in capabilities:
        server.tool(
            name="bct_" + capability,
            description=f"Run BCT capability {capability} with an exact work and operation ID.",
            structured_output=True,
        )(make_executor(capability))
    return server


class LocalBearerMiddleware:
    """Require the runtime bearer token only for the MCP protocol endpoint."""

    def __init__(self, app: Any, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and str(scope.get("path") or "").rstrip("/") == "/mcp":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            if not hmac.compare_digest(supplied, "Bearer " + self.token):
                response = JSONResponse(
                    {"error": "MCP_BEARER_TOKEN_INVALID"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
