"""Strict tab/session-bound ComfyUI read-only bridge request contract."""
from __future__ import annotations
from bct.features.comfy_graph_snapshot import SnapshotError
from bct.features.comfy_live_read import parse_live_graph_response

def validate_read_request(*, tab_id: int, url: str, session_id: str, observed: dict) -> dict:
    if not isinstance(tab_id, int) or isinstance(tab_id, bool) or tab_id <= 0:
        raise SnapshotError("COMFY_TAB_ID_INVALID")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
        raise SnapshotError("COMFY_SESSION_INVALID")
    if url != "http://127.0.0.1:8188/":
        raise SnapshotError("COMFY_EXACT_URL_REQUIRED")
    if not isinstance(observed, dict) or observed.get("tab_id") != tab_id or observed.get("url") != url or observed.get("session_id") != session_id:
        raise SnapshotError("COMFY_TAB_SESSION_MISMATCH")
    return {"operation": "comfy_canvas_read", "tab_id": tab_id, "url": url, "session_id": session_id}

def verify_read_response(response: dict, *, request: dict) -> dict:
    if not isinstance(response, dict) or any(response.get(k) != request.get(k) for k in ("tab_id", "url", "session_id")):
        raise SnapshotError("COMFY_RESPONSE_IDENTITY_MISMATCH")
    return parse_live_graph_response(response, request["url"])
