"""Read-only identity projection bridging RCC tabs to Windows window fingerprints.

Not a control path: ambiguous, stale, or missing evidence fails closed.
The bct_status current_nodes owner remains responsible for its own projection.
"""
from __future__ import annotations
from typing import Any

def resolve_chrome_window(tab: dict[str, Any], rcc_windows: list[dict[str, Any]],
                          desktop_windows: list[dict[str, Any]]) -> dict[str, Any]:
    tab_id, chrome_window_id = tab.get("tab_id"), tab.get("window_id")
    if type(tab_id) is not int or type(chrome_window_id) is not int or tab_id <= 0 or chrome_window_id <= 0:
        raise ValueError("invalid RCC tab identity")
    if not tab.get("conversation_key"):
        raise ValueError("unbound conversation")
    chrome_matches = [w for w in rcc_windows if w.get("window_id") == chrome_window_id]
    if len(chrome_matches) != 1:
        raise ValueError("ambiguous RCC window")
    chrome = chrome_matches[0]
    if not any(t.get("tab_id") == tab_id and t.get("conversation_key") == tab["conversation_key"]
               for t in chrome.get("tabs", [])):
        raise ValueError("tab no longer belongs to RCC window")
    # HWND is never inferred from ordinal order, title, or screen position.
    fingerprint = chrome.get("desktop_fingerprint")
    if not isinstance(fingerprint, dict):
        raise ValueError("missing trusted Chrome/Windows bridge")
    keys = ("hwnd", "pid", "process_start_time_utc")
    if any(not fingerprint.get(k) for k in keys):
        raise ValueError("incomplete Windows fingerprint")
    matches = [w for w in desktop_windows if all(w.get(k) == fingerprint[k] for k in keys)]
    if len(matches) != 1:
        raise ValueError("ambiguous or stale HWND/PID")
    return {"tab_id": tab_id, "window_id": chrome_window_id,
            "conversation_key": tab["conversation_key"],
            "hwnd": fingerprint["hwnd"], "pid": fingerprint["pid"],
            "process_start_time_utc": fingerprint["process_start_time_utc"]}
