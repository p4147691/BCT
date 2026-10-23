"""Settings-only MCP catalogue presentation with refresh on tools/list.

Settings never create capabilities or extend BCT Work/Operation authority.
Changes to on/off/description apply on the next tools/list request without a
source edit or runtime restart. Unregistered tool names fail closed.
"""
from __future__ import annotations

import hashlib
import threading
import tomllib
from pathlib import Path
from typing import Any

_MANDATORY = frozenset({
    "bct_capabilities", "bct_status", "bct_work_create",
    "bct_operation_get", "bct_dispatch",
})
_MAX_BYTES = 65536
_MAX_DESCRIPTION = 1800


class CatalogueSettings:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._revision: str | None = None
        self._lock = threading.RLock()
        self._tools: dict[str, Any] = {}
        self.last_error: str | None = None

    @property
    def revision(self) -> str | None:
        return self._revision

    def attach(self, server: Any) -> None:
        """Attach to FastMCP's registered catalogue after tool creation.

        Exact pinned MCP package API is covered by contract tests. We preserve
        compiled Tool metadata, including argument schemas, rather than
        rebuilding functions dynamically.
        """
        with self._lock:
            self._tools = dict(server._tool_manager._tools)
        server.catalogue_settings = self
        original_list = server.list_tools
        original_call = server.call_tool

        async def configured_list_tools():
            self.refresh(server)
            return await original_list()

        async def configured_call_tool(name, arguments, **kwargs):
            self.refresh(server)
            return await original_call(name, arguments, **kwargs)

        server.list_tools = configured_list_tools
        server.call_tool = configured_call_tool
        # FastMCP binds its protocol handlers during __init__; replacing only
        # the public methods is insufficient for actual MCP tools/list calls.
        server._mcp_server.list_tools()(configured_list_tools)
        server._mcp_server.call_tool(validate_input=False)(configured_call_tool)

    def _parse(self, raw: bytes) -> dict[str, dict[str, Any]]:
        if len(raw) > _MAX_BYTES:
            raise ValueError("MCP_CATALOGUE_SETTINGS_TOO_LARGE")
        data = tomllib.loads(raw.decode("utf-8"))
        if set(data) - {"tools"}:
            raise ValueError("MCP_CATALOGUE_UNKNOWN_ROOT")
        tables = data.get("tools", {})
        if not isinstance(tables, dict):
            raise ValueError("MCP_CATALOGUE_TOOLS_INVALID")
        if len(tables) > 100:
            raise ValueError("MCP_CATALOGUE_TOO_MANY_OVERRIDES")
        for name, entry in tables.items():
            if name not in self._tools:
                raise ValueError("MCP_CATALOGUE_UNREGISTERED_TOOL:" + str(name))
            if not isinstance(entry, dict) or set(entry) - {"enabled", "description"}:
                raise ValueError("MCP_CATALOGUE_INVALID_TOOL_OVERRIDE:" + name)
            enabled = entry.get("enabled", True)
            description = entry.get("description")
            if not isinstance(enabled, bool):
                raise ValueError("MCP_CATALOGUE_ENABLED_NOT_BOOLEAN:" + name)
            if name in _MANDATORY and not enabled:
                raise ValueError("MCP_CATALOGUE_MANDATORY_TOOL_CANNOT_HIDE:" + name)
            if description is not None and (
                not isinstance(description, str)
                or not 1 <= len(description) <= _MAX_DESCRIPTION
            ):
                raise ValueError("MCP_CATALOGUE_DESCRIPTION_INVALID:" + name)
        return tables

    def refresh(self, server: Any) -> bool:
        """Reload atomically; invalid config preserves the last good catalogue."""
        with self._lock:
            try:
                raw = self.path.read_bytes() if self.path.is_file() else b""
                digest = hashlib.sha256(raw).hexdigest()
                if digest == self._revision:
                    return False
                overrides = self._parse(raw) if raw else {}
                wanted: dict[str, Any] = {}
                for name, tool in self._tools.items():
                    opts = overrides.get(name, {})
                    if not opts.get("enabled", True):
                        continue
                    desc = opts.get("description")
                    wanted[name] = (
                        tool.model_copy(update={"description": desc})
                        if desc is not None else tool
                    )
                # Single lock and no await: readers never see a partial update.
                server._tool_manager._tools.clear()
                server._tool_manager._tools.update(wanted)
                self._revision = digest
                self.last_error = None
                return True
            except (OSError, UnicodeError, ValueError) as exc:
                # Invalid settings never remove the last accepted tools.
                self.last_error = "MCP_CATALOGUE_RELOAD_REJECTED:" + str(exc)
                return False
