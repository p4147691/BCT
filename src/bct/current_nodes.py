"""Pure current ChatGPT node classification; no I/O or registry writes."""
from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse
import re

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_NODE = re.compile(r"^N?[1-9][0-9]*$", re.I)


def classify_current_nodes(instances: list[dict[str, Any]], *, observed_at: float | None = None) -> dict[str, Any]:
    """Count only fresh RCC observations. Cached rows are never confirmed."""
    candidates: list[dict[str, Any]] = []
    unavailable = 0
    for instance in instances:
        fresh = instance.get("state") == "OPEN" and instance.get("cached") is not True
        if not fresh:
            unavailable += 1
        for tab in instance.get("tabs") or []:
            if not isinstance(tab, dict):
                continue
            url = urlparse(str(tab.get("url") or ""))
            if url.hostname not in {"chatgpt.com", "www.chatgpt.com"}:
                continue
            path = url.path.rstrip("/")
            if path not in {"", "/c"} and not path.startswith("/c/"):
                continue
            if path == "/c":
                continue
            if tab.get("presence") == "CLOSED":
                continue
            key = str(tab.get("conversation_key") or "").lower()
            node = str(tab.get("node_label") or "")
            valid_uuid = bool(_UUID.fullmatch(key)) and path == "/c/" + key
            valid_node = bool(_NODE.fullmatch(node))
            if not fresh:
                status = "UNAVAILABLE"
            elif tab.get("presence") != "OPEN":
                status = "UNRESOLVED"
            elif valid_uuid and valid_node:
                status = "CONFIRMED"
            elif path == "" and not key and not node and tab.get("new_chat_confirmed") is True:
                status = "TEMPORARY"
            else:
                status = "UNRESOLVED"
            candidates.append({
                "status": status, "node_number": node if valid_node else None,
                "conversation_uuid": key if valid_uuid else None,
                "window_id": tab.get("window_id"), "tab_id": tab.get("tab_id"),
                "tab_index": tab.get("tab_index"), "generating": tab.get("generating") if fresh else None,
                "hwnd": None, "monitor_number": None, "virtual_desktop": None,
                "minimized": None, "observed_at": observed_at if fresh else instance.get("last_seen_at"),
                "source": "RCC_FRESH" if fresh else "RCC_CACHED",
            })
    uuids = Counter(x["conversation_uuid"] for x in candidates if x["status"] == "CONFIRMED")
    numbers = Counter(x["node_number"] for x in candidates if x["status"] == "CONFIRMED")
    for item in candidates:
        if item["status"] == "CONFIRMED" and (uuids[item["conversation_uuid"]] > 1 or numbers[item["node_number"]] > 1):
            item["status"] = "UNRESOLVED"
            item["identity_conflict"] = True
    counts = {name.lower(): sum(x["status"] == name for x in candidates)
              for name in ("CONFIRMED", "TEMPORARY", "UNRESOLVED", "UNAVAILABLE")}
    return {"schema": 1, "observed_at": observed_at, "counts": counts,
            "unavailable_instances": unavailable, "items": candidates}
