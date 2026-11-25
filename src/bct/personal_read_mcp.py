"""Personal MCP reads with a credential independent of the shared BCT tunnel."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any

from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.routing import Router

from .core.models import Decision, DecisionKind, PreconditionError, Principal, Work
from .core.operations import OperationCoordinator
from .core.store import Store
from .features.common import is_reparse_point
from .features.desktop_read import DesktopReadFeature
from .mcp_server import BCTMCPServer
from .operation_queries import read_operation

_PERSONAL_WORK = "bct-personal-reads"
_PERSONAL_CAPABILITY = "personal_read"
_PERSONAL_PRINCIPAL = Principal("bct-personal-control", "personal-bearer", frozenset({_PERSONAL_CAPABILITY}))
_PERSONAL_MCP_PATH = "/personal-mcp"
_TOKEN = re.compile(r"[0-9a-f]{64}")


class PersonalReadPolicy:
    """This coordinator owns only one read feature and one private receipt store."""

    def decide(self, *, principal, work, action, approval_ref=None):
        allowed = (principal == _PERSONAL_PRINCIPAL and work.work_id == _PERSONAL_WORK
                   and work.owner_principal_id == principal.principal_id and work.state == "ACTIVE"
                   and action == _PERSONAL_CAPABILITY)
        return Decision(DecisionKind.ALLOW if allowed else DecisionKind.DENY,
                        "PERSONAL_READ_AUTHORIZED" if allowed else "PERSONAL_READ_ACCESS_DENIED",
                        "read-only operation", "personal-read-v1")


class PersonalReadFeature(DesktopReadFeature):
    capability = _PERSONAL_CAPABILITY

    def __init__(self, store, *, roots, protected_roots):
        super().__init__(store, protected_roots=protected_roots)
        self.roots = roots

    def _guard(self, path, fd=None):
        if not any(path.is_relative_to(root) for root in self.roots):
            raise PreconditionError("TARGET_OUTSIDE_PERSONAL_READ_SCOPE")
        super()._guard(path, fd)


def _personal_roots(raw):
    values = json.loads(raw)
    if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
        raise ValueError("PERSONAL_READ_ROOTS_INVALID")
    paths = tuple(Path(value) for value in values)
    if any(not path.is_absolute() or not path.is_dir()
           or any(is_reparse_point(item) for item in (path, *path.parents))
           for path in paths):
        raise ValueError("PERSONAL_READ_ROOTS_INVALID")
    return tuple(path.resolve() for path in paths)


def build_personal_mcp(runtime_root, *, roots):
    store = Store(runtime_root / "state/personal-read.sqlite")
    try:
        work = store.get_work(_PERSONAL_WORK)
    except KeyError:
        work = store.create_work(Work(_PERSONAL_WORK, "Personal PC reads", (),
                                     _PERSONAL_PRINCIPAL.capabilities, _PERSONAL_PRINCIPAL.principal_id))
    if work.owner_principal_id != _PERSONAL_PRINCIPAL.principal_id or work.state != "ACTIVE":
        raise ValueError("PERSONAL_READ_RECEIPTS_UNAVAILABLE")
    operations = OperationCoordinator(store=store, policy=PersonalReadPolicy())
    operations.register(PersonalReadFeature(
        store, roots=roots, protected_roots=(runtime_root, runtime_root.parent / "maintenance",
                                             runtime_root.parent / "data"),
    ))
    server = BCTMCPServer("BCT Personal Control")

    @server.tool(description="Read ordinary local files or folders inside the owner's configured roots. "
                             "Example arguments={\"operation\":\"file\",\"path\":\"D:/Documents/note.txt\"}. "
                             "An operation ID identifies the receipt. No Work ID or per-file grant is required.",
                 annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False), structured_output=True)
    async def bct_read(operation_id: str, arguments: dict) -> dict[str, Any]:
        result = await asyncio.to_thread(
            operations.run, principal=_PERSONAL_PRINCIPAL, work_id=_PERSONAL_WORK,
            operation_id=operation_id, capability=_PERSONAL_CAPABILITY, arguments=arguments,
        )
        return result.as_dict()

    @server.tool(description="Read the receipt for one personal file operation.",
                 annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False), structured_output=True)
    async def bct_operation_get(operation_id: str) -> dict[str, Any]:
        return await read_operation(store, principal_id=_PERSONAL_PRINCIPAL.principal_id,
                                    work_id=_PERSONAL_WORK, operation_id=operation_id)

    return server.streamable_http_app(stateless_http=True, json_response=True, streamable_http_path=_PERSONAL_MCP_PATH)


class PersonalMCPRouter:
    """Dispatch a second MCP surface without sharing credentials or tools."""

    def __init__(self, shared_app, personal_app, *, auth_digest):
        self.shared_app = shared_app
        self.personal_app = personal_app
        self.auth_digest = auth_digest

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self._lifespan(scope, receive, send)
        if scope.get("path") != _PERSONAL_MCP_PATH:
            return await self.shared_app(scope, receive, send)
        values = [value for name, value in scope.get("headers", ()) if name.lower() == b"authorization"]
        if len(values) == 1 and values[0].startswith(b"Bearer "):
            token = values[0][7:].decode("latin-1")
            if _TOKEN.fullmatch(token) and hmac.compare_digest(
                hashlib.sha256(token.encode("ascii")).hexdigest(), self.auth_digest,
            ):
                return await self.personal_app(scope, receive, send)
        return await JSONResponse({"error": "PERSONAL_MCP_TOKEN_INVALID"}, status_code=401,
                                  headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)

    async def _lifespan(self, scope, receive, send):
        # Starlette mounts do not dispatch lifespan to their children.
        @asynccontextmanager
        async def lifespan(_app):
            shared = self.shared_app.app
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(shared.router.lifespan_context(shared))
                await stack.enter_async_context(self.personal_app.router.lifespan_context(self.personal_app))
                yield

        await Router(lifespan=lifespan)(scope, receive, send)


def attach_personal_read(shared_app, runtime_root, *, shared_token, auth_digest, roots_json):
    """Keep the production route unchanged until an independent connector is configured."""
    if not auth_digest and not roots_json:
        return shared_app
    if (not _TOKEN.fullmatch(auth_digest)
            or hmac.compare_digest(hashlib.sha256(shared_token.encode()).hexdigest(), auth_digest)):
        raise ValueError("PERSONAL_MCP_CREDENTIAL_MUST_BE_SEPARATE")
    personal_app = build_personal_mcp(runtime_root, roots=_personal_roots(roots_json))
    return PersonalMCPRouter(shared_app, personal_app, auth_digest=auth_digest)
