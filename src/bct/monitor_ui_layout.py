"""Bounded BWM-only presentation settings, never executable commands.

The data file is the only runtime layout authority. Ordinary BCT work-scoped
file writes can change it without shipping a new extension or restarting Core.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KEY = "bwm.monitor.ui.layout.v1"
FILENAME = "bwm-ui-layout.json"
BUTTONS = (
    "monitorExtensionReload",
    "monitorRccReload",
    "monitorBctRecover",
    "monitorMcpTunnelRecover",
    "monitorBctControlRefresh",
)

DEFAULT = {
    "version": 1,
    "toolbar": {
        "placement": "inline",
        "order": list(BUTTONS),
        "hidden": [],
        "density": "compact",
        "gap": 2,
    },
    # Presentation only. Never source node identity, status, columns, capture or actions.
    "captureFallback": {
        "mode": "last_good",
        "staleAfterSeconds": 20,
        "maxAgeSeconds": 180,
    },
    "presentation": {
        "nodeTitleFontPx": 12,
        "nodeCardMinHeightPx": 36,
        "nodeGapPx": 6,
        "panelPaddingPx": 10,
        "thumbnailStatusIconPx": 20,
    },
}
PRESENTATION_LIMITS = {
    "nodeTitleFontPx": (10, 16),
    "nodeCardMinHeightPx": (30, 56),
    "nodeGapPx": (2, 14),
    "panelPaddingPx": (5, 16),
    "thumbnailStatusIconPx": (16, 32),
}
MAX_BYTES = 4096


def normalize_layout(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not {"version", "toolbar"}.issubset(payload) or set(payload) - {"version", "toolbar", "presentation", "captureFallback"}:
        raise ValueError("BWM_UI_LAYOUT_SCHEMA_INVALID")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("BWM_UI_LAYOUT_VERSION_INVALID")
    toolbar = payload["toolbar"]
    if not isinstance(toolbar, dict) or not set(toolbar).issubset(
        {"placement", "order", "hidden", "density", "gap"}
    ):
        raise ValueError("BWM_UI_LAYOUT_TOOLBAR_INVALID")
    config = {**DEFAULT["toolbar"], **toolbar}
    order = config["order"]
    hidden = config["hidden"]
    gap = config["gap"]
    if (
        config["placement"] not in ("inline", "below")
        or config["density"] not in ("compact", "normal")
        or type(gap) is not int or not 0 <= gap <= 16
        or not isinstance(order, list) or len(order) != len(BUTTONS)
        or set(order) != set(BUTTONS) or len(set(order)) != len(order)
        or not isinstance(hidden, list) or len(hidden) != len(set(hidden))
        or not set(hidden).issubset(BUTTONS)
    ):
        raise ValueError("BWM_UI_LAYOUT_VALUE_INVALID")
    extra = payload.get("presentation", {})
    if not isinstance(extra, dict) or set(extra) - set(PRESENTATION_LIMITS):
        raise ValueError("BWM_PRESENTATION_FIELDS_INVALID")
    presentation = {**DEFAULT["presentation"], **extra}
    if any(
        type(presentation[key]) is not int or not low <= presentation[key] <= high
        for key, (low, high) in PRESENTATION_LIMITS.items()
    ):
        raise ValueError("BWM_PRESENTATION_VALUE_INVALID")
    fallback_extra = payload.get("captureFallback", {})
    if not isinstance(fallback_extra, dict) or set(fallback_extra) - {
        "mode", "staleAfterSeconds", "maxAgeSeconds"
    }:
        raise ValueError("BWM_CAPTURE_FALLBACK_FIELDS_INVALID")
    fallback = {**DEFAULT["captureFallback"], **fallback_extra}
    if (fallback["mode"] not in ("last_good", "compact", "legacy")
            or type(fallback["staleAfterSeconds"]) is not int
            or type(fallback["maxAgeSeconds"]) is not int
            or not 5 <= fallback["staleAfterSeconds"] <= 120
            or not 30 <= fallback["maxAgeSeconds"] <= 600
            or fallback["staleAfterSeconds"] >= fallback["maxAgeSeconds"]):
        raise ValueError("BWM_CAPTURE_FALLBACK_VALUE_INVALID")
    return {
        "version": 1,
        "toolbar": {
            "placement": config["placement"],
            "order": list(order),
            "hidden": list(hidden),
            "density": config["density"],
            "gap": gap,
        },
        "presentation": presentation,
        "captureFallback": fallback,
    }


def decode_unicode_document(raw: bytes) -> str:
    """Accept UTF-8 (with/without BOM) and BOM-tagged UTF-16, no guesses."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def read_layout(data_root: Path) -> dict[str, Any]:
    path = data_root / FILENAME
    if path.is_symlink():
        raise ValueError("BWM_UI_LAYOUT_SYMLINK_FORBIDDEN")
    if not path.exists():
        return normalize_layout(DEFAULT)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("BWM_UI_LAYOUT_FILE_INVALID")
    raw = path.read_bytes()
    text = decode_unicode_document(raw)
    return normalize_layout(json.loads(text))


def load_layout(data_root: Path) -> tuple[dict[str, Any], str]:
    """Fail closed to a safe layout on malformed config, never propagate code."""
    try:
        return read_layout(data_root), "READY"
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return normalize_layout(DEFAULT), "INVALID_FALLBACK"
