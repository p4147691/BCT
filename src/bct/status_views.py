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
        # Join only exact fresh RCC tabs already present in the same Monitor snapshot.
        # The Monitor right-click editor writes scope/name/roles into BCT; no new
        # registry or second authority is created here.
        lookup: dict[tuple[object, object, object], dict[str, Any]] = {}
        rcc = monitor.get("rcc")
        for instance in (rcc.get("instances") or []) if isinstance(rcc, dict) else []:
            if not isinstance(instance, dict) or instance.get("state") != "OPEN" or instance.get("cached") is True:
                continue
            for tab in instance.get("tabs") or []:
                if not isinstance(tab, dict) or tab.get("presence") != "OPEN":
                    continue
                key = (tab.get("tab_id"), tab.get("window_id"), str(tab.get("conversation_key") or "").lower())
                lookup[key] = tab
        projected = []
        for item in current.get("items") or []:
            if not isinstance(item, dict):
                continue
            # No closed or cached rows appear in the current-node view.
            if item.get("status") == "UNAVAILABLE":
                continue
            row = dict(item)
            if row.get("status") == "CONFIRMED":
                key = (row.get("tab_id"), row.get("window_id"), str(row.get("conversation_uuid") or "").lower())
                tab = lookup.get(key)
                if tab is not None:
                    scope_data = tab.get("conversation_scope") if isinstance(tab.get("conversation_scope"), dict) else {}
                    row.update({
                        "name": str(tab.get("title") or ""),
                        "network": str(scope_data.get("scope_name") or ""),
                        "network_id": str(scope_data.get("scope_id") or ""),
                        "roles": list(scope_data.get("role_tags") or []),
                        "display_order": scope_data.get("display_order"),
                        "active": tab.get("active") is True,
                    })
            projected.append(row)
        visible = dict(current)
        visible["items"] = projected
        visible["counts"] = {name: sum(x.get("status") == name.upper() for x in projected)
                             for name in ("confirmed", "temporary", "unresolved")}
        return {"status": "OK", "scope": scope, "current_nodes": visible}
    if scope == "rcc":
        return {"status": "OK", "scope": scope, "rcc": monitor.get("rcc")}
    return {"status": "OK", "scope": scope, "monitor": {
        key: monitor.get(key) for key in ("current_nodes", "service", "observability", "schema", "generated_at")
    }}
