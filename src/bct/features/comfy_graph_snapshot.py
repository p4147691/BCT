"""Strict read-only ComfyUI graph snapshot validation and isolated prompt-copy test."""
from __future__ import annotations
import copy
import json

class SnapshotError(ValueError):
    pass

def validate_snapshot(graph: dict) -> dict:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("links"), list):
        raise SnapshotError("COMFY_GRAPH_INVALID")
    nodes = graph["nodes"]
    ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(ids) != len(nodes) or len(set(ids)) != len(ids):
        raise SnapshotError("COMFY_NODE_IDS_INVALID")
    for node in nodes:
        if not isinstance(node.get("type"), str) or not isinstance(node.get("widgets_values", []), list):
            raise SnapshotError("COMFY_NODE_SETTINGS_INVALID")
    for link in graph["links"]:
        if not isinstance(link, list) or len(link) < 5 or link[1] not in ids or link[3] not in ids:
            raise SnapshotError("COMFY_LINK_INVALID")
    return copy.deepcopy(graph)

def isolated_prompt_copy(graph: dict, node_id: int, index: int, prompt: str) -> dict:
    snapshot = validate_snapshot(graph)
    target = next((n for n in snapshot["nodes"] if n["id"] == node_id), None)
    if target is None or not isinstance(prompt, str) or not 0 <= index < len(target.get("widgets_values", [])):
        raise SnapshotError("COMFY_PROMPT_TARGET_INVALID")
    if not isinstance(target["widgets_values"][index], str):
        raise SnapshotError("COMFY_PROMPT_NOT_TEXT")
    target["widgets_values"][index] = prompt
    return snapshot

def unchanged_except_prompt(before: dict, after: dict, node_id: int, index: int) -> bool:
    original = validate_snapshot(before)
    candidate = validate_snapshot(after)
    a = next((n for n in original["nodes"] if n["id"] == node_id), None)
    b = next((n for n in candidate["nodes"] if n["id"] == node_id), None)
    if a is None or b is None:
        return False
    b["widgets_values"][index] = a["widgets_values"][index]
    return json.dumps(original, sort_keys=True) == json.dumps(candidate, sort_keys=True)
