"""Read-only BCT -> MemoryGuard renderer/process node evidence projection.

The caller MUST supply authenticated BCT status and server-verified, complete
Chrome processes observations. This module never obtains browser permissions,
accepts a user-provided PID as authority, or changes BCT/Chrome state.
"""
from __future__ import annotations

import re
import time
from collections import Counter

_UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_NODE = re.compile(r"^N[1-9][0-9]*$")
_MAX_AGE = 120.0
_SOURCE = "RCC_CHROME_PROCESSES_READONLY"


def _fresh(value: object, now: float) -> bool:
    return type(value) in (int, float) and 0 <= now - value <= _MAX_AGE


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def project_node_processes(
    authenticated_bct_status: dict,
    *,
    renderer_observations: list[dict] | None = None,
    os_process_observations: dict[int, dict] | None = None,
    now_unix: float | None = None,
) -> dict:
    """Return ONLY exact single-tab renderer/OS PID bindings as verified.

    renderer_observations must be collected by a trusted RCC implementation
    using chrome.processes.getProcessIdForTab and getProcessInfo, not supplied
    by a remote client. os_process_observations are server-side Windows process
    identity reads (PID + creation time). Missing either source => no proof.
    """
    now = time.time() if now_unix is None else float(now_unix)
    result = {
        "schema": "BCT_MEMORYGUARD_NODE_PROCESS_V1",
        "read_only": True,
        "authorize_unload": False,
        "status": "UNVERIFIED",
        "verified_bindings": [],
        "unverified_targets": [],
    }
    if not isinstance(authenticated_bct_status, dict):
        result["reason"] = "BCT_STATUS_UNAVAILABLE"
        return result
    core = authenticated_bct_status.get("core")
    monitor = authenticated_bct_status.get("monitor")
    if not isinstance(core, dict) or not core.get("ready") or not isinstance(monitor, dict):
        result["reason"] = "BCT_STATUS_UNVERIFIED"
        return result
    if not _fresh(monitor.get("generated_at"), now):
        result["reason"] = "BCT_STATUS_STALE"
        return result
    rcc = monitor.get("rcc")
    instances = rcc.get("instances") if isinstance(rcc, dict) else None
    if not isinstance(instances, list):
        result["reason"] = "RCC_STATE_UNAVAILABLE"
        return result
    targets = []
    for inst in instances:
        if not isinstance(inst, dict) or inst.get("state") != "OPEN":
            continue
        instance_id = inst.get("instance_id")
        session_id = inst.get("session_id")
        if not isinstance(instance_id, str) or not instance_id or not isinstance(session_id, str) or not session_id:
            continue
        tabs = inst.get("tabs")
        if not isinstance(tabs, list):
            continue
        for tab in tabs:
            if not isinstance(tab, dict) or tab.get("presence") != "OPEN":
                continue
            key = tab.get("conversation_key")
            node = tab.get("node_label")
            tab_id, window_id = tab.get("tab_id"), tab.get("window_id")
            if not (isinstance(key, str) and _UUID.fullmatch(key)
                    and isinstance(node, str) and _NODE.fullmatch(node)
                    and _positive(tab_id) and _positive(window_id)):
                continue
            targets.append({
                "instance_id": instance_id, "session_id": session_id,
                "tab_id": tab_id, "window_id": window_id,
                "conversation_uuid": key, "node": node,
                "tab_title": str(tab.get("title") or "")[:200],
            })
    # Exact duplicate IDs or conflicting RCC identities fail closed.
    target_counts = Counter((t["instance_id"], t["session_id"], t["tab_id"]) for t in targets)
    targets = [t for t in targets if target_counts[t["instance_id"], t["session_id"], t["tab_id"]] == 1]
    result["unverified_targets"] = [
        {**t, "status": "미확인"} for t in targets
    ]
    if not renderer_observations or not os_process_observations:
        result["reason"] = "RENDERER_PROCESS_EVIDENCE_UNAVAILABLE"
        return result
    if not isinstance(renderer_observations, list) or not isinstance(os_process_observations, dict):
        result["reason"] = "PROCESS_EVIDENCE_INVALID"
        return result
    matched = []
    for t in targets:
        rows = [
            r for r in renderer_observations
            if isinstance(r, dict)
            and r.get("source") == _SOURCE
            and r.get("instance_id") == t["instance_id"]
            and r.get("session_id") == t["session_id"]
            and r.get("tab_id") == t["tab_id"]
            and r.get("window_id") == t["window_id"]
            and r.get("conversation_uuid") == t["conversation_uuid"]
        ]
        if len(rows) != 1:
            continue
        row = rows[0]
        pid = row.get("os_process_id")
        renderer_id = row.get("renderer_process_id")
        # Chrome's process ID and Windows OS PID are distinct identities.
        # A complete renderer task list containing just this one tab is required.
        if not (_positive(pid) and _positive(renderer_id)
                and row.get("process_type") == "renderer"
                and row.get("exclusive_task_list_proven") is True
                and row.get("task_tab_ids") == [t["tab_id"]]
                and row.get("tab_renderer_process_id") == renderer_id
                and _fresh(row.get("observed_at_unix"), now)):
            continue
        live = os_process_observations.get(pid)
        if not isinstance(live, dict) or not (
            live.get("pid") == pid and str(live.get("name") or "").lower() == "chrome.exe"
            and _fresh(live.get("observed_at_unix"), now)
            and type(live.get("create_time")) in (int, float)
            and live["create_time"] > 0
        ):
            continue
        matched.append((t, row, live))
    # Same renderer serving multiple ChatGPT tabs is never attributed to one.
    process_counts = Counter(row["os_process_id"] for _t, row, _live in matched)
    renderer_counts = Counter((t["instance_id"], row["renderer_process_id"]) for t, row, _live in matched)
    bindings = []
    for t, row, live in matched:
        if process_counts[row["os_process_id"]] != 1 or renderer_counts[t["instance_id"], row["renderer_process_id"]] != 1:
            continue
        bindings.append({
            "source": "VERIFIED_BCT_TARGET_PROCESS_NODE",
            "verified": True, "pid": row["os_process_id"],
            "create_time": live["create_time"],
            "node": t["node"],
            "conversation_uuid": t["conversation_uuid"],
            "target_id": str(t["tab_id"]),
            "tab_id": t["tab_id"], "window_id": t["window_id"],
            "instance_id": t["instance_id"], "session_id": t["session_id"],
            "tab_title": t["tab_title"], "title_source": "RCC_TAB",
            "window_attribution": "TARGET_PROCESS_EXCLUSIVE",
            "target_process_exclusive": True,
            "observed_at_unix": min(
                monitor["generated_at"], row["observed_at_unix"], live["observed_at_unix"]
            ),
            "authorize_unload": False,
        })
    result["verified_bindings"] = bindings
    verified_keys = {(b["instance_id"], b["session_id"], b["tab_id"]) for b in bindings}
    result["unverified_targets"] = [
        {**t, "status": "미확인"} for t in targets
        if (t["instance_id"], t["session_id"], t["tab_id"]) not in verified_keys
    ]
    result["status"] = "VERIFIED" if bindings else "UNVERIFIED"
    result["reason"] = "VERIFIED_EXCLUSIVE_RENDERERS" if bindings else "NO_EXACT_EXCLUSIVE_PROCESS_BINDING"
    return result
