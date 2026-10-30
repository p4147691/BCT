"""Injected bounded ComfyUI bridge transport; no CDP, Chrome startup, or eval."""
from __future__ import annotations
from bct.features.comfy_graph_snapshot import SnapshotError

class ComfyCanvasAdapter:
    def __init__(self, transport=None):
        self._transport = transport

    def read_canvas(self, arguments: dict) -> dict:
        if self._transport is None:
            raise SnapshotError("COMFY_BRIDGE_TRANSPORT_NOT_BOUND")
        # The adapter accepts only an explicitly injected, trusted transport.
        return self._transport.read_canvas(dict(arguments))
