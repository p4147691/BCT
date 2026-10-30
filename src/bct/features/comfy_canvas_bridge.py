"""BCT-owned fixed ComfyUI frontend bridge contract, no browser mutation."""
from __future__ import annotations
from pathlib import Path
from bct.features.comfy_live_read import parse_live_graph_response, validate_comfy_target

BRIDGE_SCRIPT = Path(__file__).with_name("comfy_canvas_bridge.js")

def parse_bridge_snapshot(payload: dict, *, url: str) -> dict:
    validate_comfy_target(url)
    return parse_live_graph_response(payload, url)
