"""Canonical names for capabilities that are stored in durable BCT records."""
from __future__ import annotations


# ``relay_browser`` was the old technical name.  It remains readable only so
# existing Work and Operation rows can be reconciled; new requests always use
# the clearer, wider name ``browser``.
_LEGACY_TO_CURRENT = {"relay_browser": "browser"}


def canonical_capability(value: object) -> str:
    """Return the current name without changing a stored historical value."""
    text = str(value or "")
    return _LEGACY_TO_CURRENT.get(text, text)


def capability_matches(value: object, expected: str) -> bool:
    """Compare current and historical durable capability names safely."""
    return canonical_capability(value) == expected


def public_tool_name(capability: str) -> str:
    """Map durable capability names to their public MCP tools."""
    return "bct_" + {"read": "scoped_read", "desktop_read": "read"}.get(capability, capability)
