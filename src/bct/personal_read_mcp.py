"""Personal MCP reads with a credential independent of the shared BCT tunnel."""
from __future__ import annotations

import asyncio
from base64 import b64encode
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote_plus, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

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
_BEARER = re.compile(r"[A-Za-z0-9_.~+/-]+={0,2}")
_METADATA_PATH = "/.well-known/oauth-protected-resource" + _PERSONAL_MCP_PATH
_READ_SCOPE = "files:read"


class _NoIntrospectionRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class PersonalOAuth:
    issuer: str
    resource: str
    introspection_url: str
    chatgpt_client: str
    owner_subject: str
    introspection_client: str
    introspection_secret: str = field(repr=False)

    @classmethod
    def from_config(cls, raw: str, secret: str) -> PersonalOAuth:
        values = json.loads(raw)
        names = {"issuer", "resource", "introspection_url", "chatgpt_client", "owner_subject", "introspection_client"}
        if (not isinstance(values, dict) or values.keys() != names or not secret
                or any(not isinstance(value, str) or not value.strip() for value in values.values())):
            raise ValueError("PERSONAL_OAUTH_CONFIG_INVALID")
        for name in ("issuer", "resource", "introspection_url"):
            url = urlsplit(values[name])
            if (url.scheme != "https" or not url.hostname or url.username is not None
                    or url.query or url.fragment or any(char.isspace() or char in '\\"' for char in values[name])):
                raise ValueError("PERSONAL_OAUTH_CONFIG_INVALID")
        if values["chatgpt_client"] == values["introspection_client"]:
            raise ValueError("PERSONAL_OAUTH_CONFIG_INVALID")
        return cls(**values, introspection_secret=secret)

    @property
    def challenge(self) -> str:
        resource = urlsplit(self.resource)
        metadata = f"{resource.scheme}://{resource.netloc}/.well-known/oauth-protected-resource{resource.path}"
        return f'Bearer resource_metadata="{metadata}", scope="{_READ_SCOPE}"'

    @property
    def metadata(self) -> dict[str, Any]:
        return {"resource": self.resource, "authorization_servers": [self.issuer], "scopes_supported": [_READ_SCOPE],
                "bearer_methods_supported": ["header"]}

    def permits(self, token: str) -> bool:
        password = f"{quote_plus(self.introspection_client)}:{quote_plus(self.introspection_secret)}"
        auth = b64encode(password.encode("ascii")).decode("ascii")
        payload = urlencode({"token": token, "token_type_hint": "access_token"}).encode("ascii")
        request = Request(self.introspection_url, data=payload, headers={"Authorization": f"Basic {auth}",
                          "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
        opener = build_opener(ProxyHandler({}), _NoIntrospectionRedirect())
        try:
            with opener.open(request, timeout=5) as response:
                body = response.read(32769)
            if len(body) > 32768:
                return False
            claims = json.loads(body)
        except (OSError, ValueError):
            return False
        if not isinstance(claims, dict):
            return False
        audience = claims.get("aud")
        granted_scope = claims.get("scope")
        expires = claims.get("exp")
        return (claims.get("active") is True and claims.get("iss") == self.issuer
                and claims.get("sub") == self.owner_subject and claims.get("client_id") == self.chatgpt_client
                and audience in (self.resource, [self.resource])
                and isinstance(granted_scope, str) and _READ_SCOPE in granted_scope.split()
                and type(expires) is int and expires > time.time())


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

    def __init__(self, shared_app, personal_app, *, shared_token, auth_digest, oauth):
        self.shared_app = shared_app
        self.personal_app = personal_app
        self.shared_token = shared_token.encode()
        self.auth_digest = auth_digest
        self.oauth = oauth

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self._lifespan(scope, receive, send)
        path = scope.get("path")
        if self.oauth and path == _METADATA_PATH and scope.get("method") == "GET":
            return await JSONResponse(self.oauth.metadata)(scope, receive, send)
        if path != _PERSONAL_MCP_PATH or scope["type"] != "http":
            return await self.shared_app(scope, receive, send)
        values = [value for name, value in scope.get("headers", ()) if name.lower() == b"authorization"]
        if len(values) == 1 and values[0][:7].lower() == b"bearer ":
            raw = values[0][7:]
            if not hmac.compare_digest(raw, self.shared_token) and await self._permits(raw.decode("latin-1")):
                return await self.personal_app(scope, receive, send)
        challenge = self.oauth.challenge if self.oauth else "Bearer"
        return await JSONResponse({"error": "PERSONAL_MCP_TOKEN_INVALID"}, status_code=401,
                                  headers={"WWW-Authenticate": challenge})(scope, receive, send)

    async def _permits(self, token: str) -> bool:
        if self.oauth:
            return (len(token) <= 8192 and bool(_BEARER.fullmatch(token))
                    and await asyncio.to_thread(self.oauth.permits, token))
        return bool(_TOKEN.fullmatch(token)) and hmac.compare_digest(
            hashlib.sha256(token.encode("ascii")).hexdigest(), self.auth_digest,
        )

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


def attach_personal_read(shared_app, runtime_root, *, shared_token, auth_digest, roots_json,
                         oauth_json="", introspection_secret=""):
    """Keep the production route unchanged until an independent connector is configured."""
    if not any((auth_digest, roots_json, oauth_json, introspection_secret)):
        return shared_app
    oauth = None
    if oauth_json or introspection_secret:
        if auth_digest:
            raise ValueError("PERSONAL_OAUTH_REQUIRES_EXCLUSIVE_AUTH_MODE")
        oauth = PersonalOAuth.from_config(oauth_json, introspection_secret)
    elif (not _TOKEN.fullmatch(auth_digest)
            or hmac.compare_digest(hashlib.sha256(shared_token.encode()).hexdigest(), auth_digest)):
        raise ValueError("PERSONAL_MCP_CREDENTIAL_MUST_BE_SEPARATE")
    personal_app = build_personal_mcp(runtime_root, roots=_personal_roots(roots_json))
    return PersonalMCPRouter(shared_app, personal_app, shared_token=shared_token, auth_digest=auth_digest, oauth=oauth)
