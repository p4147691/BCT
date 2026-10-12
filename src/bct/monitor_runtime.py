from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from bct.integrations.rcc import discover_instance_ids
from bct.integrations.native_process import process_matches
from bct.service_runtime import process_identity, read_json


def _decision_state(endpoint_path: Path) -> dict[str, Any]:
    value = read_json(endpoint_path)
    if not isinstance(value, dict):
        return {"state": "UNCONFIGURED"}
    process = value.get("process") if isinstance(value.get("process"), dict) else {}
    try:
        current = process_identity(int(process.get("pid") or 0))
    except (TypeError, ValueError):
        current = None
    owned = bool(
        current is not None
        and current.pid == process.get("pid")
        and current.executable == process.get("executable")
        and current.creation_marker == process.get("creation_marker")
        and current.fingerprint == process.get("fingerprint")
    )
    return {
        "state": "RUNNING" if owned else "STALE",
        "owner": str(value.get("owner") or ""),
        "runtime": str(value.get("runtime") or ""),
        "mode": str(value.get("mode") or ""),
        "model_name": str(value.get("model_name") or ""),
        "generation": value.get("generation"),
        "pid": process.get("pid"),
        "owned": owned,
        "warmed_up": bool(value.get("warmed_up")),
    }


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


def build_monitor_state(
    *, store: Any, service_state: dict[str, Any], data_root: Path
) -> dict[str, Any]:
    snapshot = store.monitor_snapshot()
    sessions = _session_states(data_root / "process-sessions")
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
            "rcc_instances": len(discover_instance_ids()),
            "process_sessions": len(sessions),
        },
        "decision": _decision_state(data_root / "decision-endpoint.json"),
        "rcc": {"instances": discover_instance_ids()},
        "process_sessions": sessions,
        **snapshot,
    }
