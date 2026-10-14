from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from bct.integrations.rcc import NamedPipeRelayClient, discover_instance_ids
from bct.integrations.native_process import process_matches
from bct.service_runtime import read_json


def _session_states(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        value = read_json(directory / "session.json")
        if not isinstance(value, dict):
            continue
        child = value.get("child") if isinstance(value.get("child"), dict) else {}
        worker = value.get("worker") if isinstance(value.get("worker"), dict) else {}
        rows.append({
            "session_id": directory.name,
            "state": str(value.get("state") or "UNKNOWN"),
            "kind": str(value.get("kind") or ""),
            "work_id": str(value.get("work_id") or ""),
            "child_pid": child.get("pid"),
            "child_alive": bool(child) and process_matches(child),
            "worker_pid": worker.get("pid"),
            "worker_alive": bool(worker) and process_matches(worker),
            "updated_at": value.get("updated_at"),
        })
    return rows


def _rcc_states(instance_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    client = NamedPipeRelayClient()
    for instance_id in instance_ids:
        try:
            result = client.request(
                instance_id=instance_id,
                request_id=f"monitor-{time.time_ns():x}",
                command="state",
                timeout_s=1.0,
            )
            state = result.get("state") if isinstance(result.get("state"), dict) else {}
            endpoints = {
                int(item["tabId"]): item
                for item in state.get("endpoints", [])
                if isinstance(item, dict) and isinstance(item.get("tabId"), int)
            }
            tabs = []
            for item in state.get("tabs", []):
                if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                    continue
                endpoint = endpoints.get(int(item["id"]), {})
                tabs.append({
                    "tab_id": item["id"],
                    "window_id": item.get("windowId"),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "presence": str(endpoint.get("presence") or "UNKNOWN"),
                    "active": bool(endpoint.get("tabActive")),
                    "generating": bool(endpoint.get("generating")),
                })
            rows.append({
                "instance_id": instance_id,
                "session_id": str(state.get("sessionId") or ""),
                "state": "OPEN",
                "background_build_id": str(state.get("backgroundBuildId") or ""),
                "tabs": tabs,
            })
        except Exception as exc:
            rows.append({
                "instance_id": instance_id,
                "state": "UNAVAILABLE",
                "error": type(exc).__name__,
                "tabs": [],
            })
    return rows


def build_monitor_state(
    *, store: Any, service_state: dict[str, Any], data_root: Path
) -> dict[str, Any]:
    snapshot = store.monitor_snapshot()
    sessions = _session_states(data_root / "process-sessions")
    instance_ids = discover_instance_ids()
    rcc = _rcc_states(instance_ids)
    return {
        "schema": 1,
        "generated_at": time.time(),
        "service": dict(service_state),
        "counts": {
            "works": len(snapshot["works"]),
            "operations": len(snapshot["operations"]),
            "unresolved_claims": len(snapshot["unresolved_claims"]),
            "nodes": len(snapshot["nodes"]),
            "connections": len(snapshot["connections"]),
            "rcc_instances": len(instance_ids),
            "process_sessions": len(sessions),
            "orchestration_sessions": len(snapshot["orchestration_sessions"]),
            "orchestration_assignments": len(snapshot["orchestration_assignments"]),
        },
        "rcc": {"instances": rcc},
        "process_sessions": sessions,
        **snapshot,
    }
