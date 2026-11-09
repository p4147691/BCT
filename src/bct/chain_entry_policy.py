"""One small, explicit entry-selection policy for BCT message work.

This module does not infer a user's natural-language request or send anything.
It records the public routing rule used by callers and catalogue descriptions:
ordinary assigned work enters through Chain Recipe; Task Message and Send
Message are opt-in paths requested by name.
"""

from __future__ import annotations


DEFAULT_ENTRY = "CHAIN_RECIPE"
_ENTRIES = {
    "CHAIN_RECIPE": {
        "tool": "bct_chain_recipe",
        "reason": "ORDINARY_REQUEST_DEFAULT",
        "requires_explicit_request": False,
    },
    "TASK_MESSAGE": {
        "tool": "bct_task_message",
        "reason": "EXPLICIT_TASK_MESSAGE_REQUEST",
        "requires_explicit_request": True,
    },
    "SEND_MESSAGE": {
        "tool": "bct_send_message",
        "reason": "EXPLICIT_SEND_MESSAGE_REQUEST",
        "requires_explicit_request": True,
    },
}


def select_message_entry(requested_entry: str = "") -> dict[str, object]:
    """Return the one public message entry selected by an explicit request.

    An empty request is deliberately the ordinary-work default, Chain Recipe.
    Callers that interpret human language must only pass TASK_MESSAGE or
    SEND_MESSAGE when the user actually named that route; this function never
    guesses intent from message contents.
    """
    normalized = requested_entry.strip().upper().replace("-", "_")
    if not normalized:
        normalized = DEFAULT_ENTRY
    if normalized not in _ENTRIES:
        raise ValueError("MESSAGE_ENTRY_INVALID")
    selection = dict(_ENTRIES[normalized])
    selection["entry"] = normalized
    selection["default_entry"] = DEFAULT_ENTRY
    return selection


def public_entry_policy() -> dict[str, object]:
    """Return the small catalogue-safe form of the routing policy."""
    return {
        "default_entry": DEFAULT_ENTRY,
        "ordinary_request_tool": _ENTRIES[DEFAULT_ENTRY]["tool"],
        "explicit_only_tools": [
            _ENTRIES["TASK_MESSAGE"]["tool"],
            _ENTRIES["SEND_MESSAGE"]["tool"],
        ],
        "rule": (
            "Ordinary assigned work uses Chain Recipe. Task Message and "
            "Send Message require an explicit user request by name."
        ),
    }
