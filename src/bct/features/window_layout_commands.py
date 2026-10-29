"""Validated, effect-free command preparation for existing BCT and RCC tools.

Only a BCT Work/Operation can execute returned commands. These helpers never
send, click, acquire leases, or modify an UNKNOWN receipt.
"""
from __future__ import annotations
import re
from typing import Any

_HEX = re.compile(r"^[a-f0-9]{32}$")
_UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")

def plan_window_state_action(lease_id: str, action: str) -> tuple[str, dict[str, str]]:
    if not isinstance(lease_id, str) or not _HEX.fullmatch(lease_id):
        raise ValueError("exact window lease required")
    if action not in {"minimize", "restore", "maximize"}:
        raise ValueError("unsupported window action")
    return "desktop_window_manage", {"lease_id": lease_id, "operation": action}

def plan_tab_move(*, instance_id: str, session_id: str, tab_id: int,
                  window_id: int, target_window_id: int, index: int,
                  conversation_key: str, observed: dict[str, Any],
                  allow_generating: bool = False) -> tuple[str, dict[str, Any]]:
    if not all(isinstance(x, str) and _HEX.fullmatch(x) for x in (instance_id, session_id)):
        raise ValueError("invalid RCC instance or session")
    if any(type(v) is not int or v <= 0 for v in (tab_id, window_id, target_window_id)):
        raise ValueError("invalid tab/window ID")
    if type(index) is not int or index < -1:
        raise ValueError("invalid tab index")
    if not isinstance(conversation_key, str) or not _UUID.fullmatch(conversation_key):
        raise ValueError("exact conversation identity required")
    if (observed.get("tab_id") != tab_id
            or observed.get("window_id") != window_id
            or observed.get("conversation_key") != conversation_key):
        raise ValueError("observed tab identity changed")
    if observed.get("generating") and not allow_generating:
        raise ValueError("generating conversation protected")
    return "relay_browser", {
        "command": "move-tab", "instance_id": instance_id, "session_id": session_id,
        "tab_id": tab_id, "window_id": window_id,
        "target_window_id": target_window_id, "index": index,
        "conversation_key": conversation_key,
    }
