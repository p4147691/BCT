from __future__ import annotations
from urllib.parse import urlsplit
from bct.features.comfy_graph_snapshot import validate_snapshot, SnapshotError

COMFY_ORIGIN = "http://127.0.0.1:8188"

def validate_comfy_target(url: str) -> None:
    try:
        parsed = urlsplit(url)
    except (ValueError, TypeError) as exc:
        raise SnapshotError("COMFY_TARGET_INVALID") from exc
    if parsed.scheme != "http" or parsed.netloc != "127.0.0.1:8188" or parsed.username or parsed.password:
        raise SnapshotError("COMFY_TARGET_FORBIDDEN")

def parse_live_graph_response(payload: dict, expected_url: str) -> dict:
    validate_comfy_target(expected_url)
    if not isinstance(payload, dict) or payload.get("url") != expected_url:
        raise SnapshotError("COMFY_TARGET_MISMATCH")
    if payload.get("source") != "live_canvas_memory":
        raise SnapshotError("COMFY_LIVE_SOURCE_UNVERIFIED")
    return validate_snapshot(payload.get("graph"))

def request_live_graph(manager, *, tab_id: str, url: str) -> dict:
    validate_comfy_target(url)
    if not isinstance(tab_id, str) or not tab_id.isdecimal():
        raise SnapshotError("COMFY_TAB_ID_INVALID")
    # No generic script execution is exposed. The adapter must explicitly
    # implement this fixed command; unsupported tools fail closed.
    response = manager.request("tools/call", {
        "name": "comfy_read_live_graph",
        "arguments": {"tab_id": tab_id, "url": url},
    })
    return parse_live_graph_response(response, url)
