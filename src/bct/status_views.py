"""Read-only user-facing BCT status views; never changes node identity or state."""
from __future__ import annotations

from typing import Any

STATUS_SCOPES = ("bct", "node", "rcc", "monitor")


def status_view(snapshot: dict[str, Any], scope: str) -> dict[str, Any]:
    if scope not in STATUS_SCOPES:
        raise ValueError("BCT_STATUS_SCOPE_INVALID")
    if scope == "bct":
        return snapshot
    monitor = snapshot.get("monitor")
    if not isinstance(monitor, dict):
        return {"status": "UNAVAILABLE", "scope": scope, "reason": "MONITOR_SNAPSHOT_UNAVAILABLE"}
    if scope == "node":
        current = monitor.get("current_nodes")
        if not isinstance(current, dict):
            return {"status": "UNAVAILABLE", "scope": scope, "reason": "CURRENT_NODES_UNAVAILABLE"}
        # Never turn historical/closed nodes into current members.
        return {"status": "OK", "scope": scope, "current_nodes": current}
    if scope == "rcc":
        return {"status": "OK", "scope": scope, "rcc": monitor.get("rcc")}
    return {"status": "OK", "scope": scope, "monitor": {
        key: monitor.get(key) for key in ("current_nodes", "service", "observability", "schema", "generated_at")
    }}
