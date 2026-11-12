"""Read-only discovery views assembled without MCP registration or execution."""
from __future__ import annotations

from typing import Any

from .chain_entry_policy import public_entry_policy
from .component_library import discover


def capability_view(
    *, tool_metadata: list[dict[str, Any]], capabilities: tuple[str, ...],
    usage: dict[str, str], catalogue_warning: Any = None,
    query: str = "", tool_name: str = "", component_id: str = "",
    include_manual: bool = False, limit: int = 8, offset: int = 0,
) -> dict[str, Any]:
    from bct.features.rcc import command_catalog
    value = {
        "capabilities": list(capabilities),
        "tools": [tool["name"] for tool in tool_metadata],
        # The live runtime contract takes precedence over client-cached tool descriptions.
        "browser_usage": usage["browser"],
        "browser_contract_version": "rcc-browser-command-v2",
        "browser_public_commands": [item["command"] for item in command_catalog()],
        "message_entry_policy": public_entry_policy(),
        **discover(tools=tool_metadata, capabilities=capabilities, usage=usage,
                   query=query, tool_name=tool_name, component_id=component_id,
                   include_manual=include_manual, limit=limit, offset=offset),
    }
    if catalogue_warning:
        value["catalogue_warning"] = catalogue_warning
    return value


def rcc_command_view() -> dict[str, Any]:
    from bct.features.rcc import command_catalog
    return {
        "tool": "bct_browser",
        "invocation": {
            "required": ["work_id", "operation_id", "arguments.command"],
            "note": ("Each command validates its own exact identifiers, target and receipt "
                     "contract. An UNKNOWN effect is never automatically replayed."),
        },
        "commands": command_catalog(),
    }


def rcc_recipe_view() -> dict[str, Any]:
    from bct.features.rcc import recipe_catalog
    return {
        "tool": "bct_browser",
        "invocation": {"required": ["work_id", "operation_id", "arguments.command"]},
        "recipes": recipe_catalog(),
    }
