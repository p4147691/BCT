"""Source-only read model for a future Monitor history tab.

Accepts an immutable, non-operational SQLite snapshot. Does not serve HTTP,
observe RCC, read browser DOM, modify identity or provide execution authority.
"""
from pathlib import Path
from .history_readonly import current_nodes, historical_nodes, work_evidence, work_history, project_memberships

SCHEMA = "BCT_MONITOR_HISTORY_VIEW_V1"
MAX_SELECTIONS = 12

def _ids(values, name):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_SELECTIONS:
        raise ValueError(name + "_SELECTION_INVALID")
    if any(not isinstance(x, str) or not x or len(x) > 160 for x in values):
        raise ValueError(name + "_ID_INVALID")
    if len(set(values)) != len(values):
        raise ValueError(name + "_DUPLICATE")
    return values

def _snapshot(path):
    p = Path(path).resolve()
    normalized = str(path).replace("\\\\", "/").replace("\\", "/").casefold()
    if normalized.endswith("/runtime/state/state.sqlite") or p.name.casefold() == "state.sqlite":
        raise ValueError("LIVE_DATABASE_FORBIDDEN")
    if not p.is_file():
        raise FileNotFoundError("SNAPSHOT_NOT_FOUND")
    return p

def history_view(snapshot, *, work_ids=(), project_ids=()):
    """Bounded explicit invocation. Projection never includes message bodies."""
    p = _snapshot(snapshot)
    works = []
    projects = []
    for work_id in _ids(work_ids, "WORK"):
        record = work_history(p, work_id)
        evidence = work_evidence(p, work_id)
        works.append({
            "work_id": work_id,
            "session_count": len(record["sessions"]),
            "session_ids": [x["session"]["session_id"] for x in record["sessions"]],
            "operation_count": len(evidence["operations"]),
            "event_count": len(evidence["events"]),
            "conversation_coverage": "NOT_VERIFIED",
        })
    for project_id in _ids(project_ids, "PROJECT"):
        record = project_memberships(p, project_id)
        projects.append({
            "project_id": project_id,
            "conversation_keys": [x["conversation_key"] for x in record["conversations"]],
            "work_linkage": "NOT_PROVEN",
            "conversation_coverage": "NOT_VERIFIED",
        })
    active = current_nodes(p)
    history = historical_nodes(p)
    return {
        "schema": SCHEMA,
        "source": "IMMUTABLE_SQLITE_SNAPSHOT",
        "snapshot_only": True,
        "current": {"nodes": [{
            "node_id": n["node_id"], "name": n["name"], "role": n["role"],
            "registered": True,
            "connection_record_count": n["registered_connections"],
            "live_presence": "UNVERIFIED",
            "assignable": "UNVERIFIED",
        } for n in active]},
        "history": {
            "nodes": [{
                "node_id": n["node_id"],
                "current_name": n["name"],
                "historical_name": None,
                "historical_role": None,
                "historical_identity_coverage": "UNKNOWN",
                "session_count": n["session_count"],
                "session_ids": [x["session_id"] for x in n["sessions"]],
            } for n in history if n["session_count"] > 0],
            "works": works,
            "projects": projects,
        },
        "conversation_coverage": "NOT_VERIFIED",
        "full_history_verified": False,
    }
