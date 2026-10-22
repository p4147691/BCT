"""BCT-scoped CDP MCP connection holder.

The browser session is lazy: registering this object does not launch Chrome,
open a tab, or ask for debugging consent.
"""
from __future__ import annotations

from bct.features.cdp_persistent import PersistentCDP


class CDPConnectionManager:
    def __init__(self):
        self._client: PersistentCDP | None = None
        self._argv: tuple[str, ...] | None = None

    def configure(self, argv: tuple[str, ...], *, timeout: float = 30.0) -> None:
        argv = tuple(argv)
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("CDP_MCP_ARGV_INVALID")
        if self._client is not None:
            if argv != self._argv:
                raise RuntimeError("CDP_MCP_CONNECTION_ALREADY_CONFIGURED")
            return
        self._argv = argv
        self._client = PersistentCDP(argv, timeout=timeout)

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.connected)

    async def request(self, method: str, params: dict | None = None):
        # No generic browser mutations before BCT operation policy/claim
        # integration. Allow only MCP discovery and a bounded tab listing.
        params = params or {}
        discovery = method in {"tools/list", "ping"}
        tabs_only = method == "tools/call" and params == {
            "name": "list_pages", "arguments": {}
        }
        if not (discovery or tabs_only):
            raise PermissionError("CDP_MCP_OPERATION_NOT_AUTHORIZED")
        if self._client is None:
            raise RuntimeError("CDP_MCP_NOT_CONFIGURED")
        return await self._client.request(method, params)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._argv = None
