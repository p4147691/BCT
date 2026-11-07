from __future__ import annotations

import hashlib
import time
from threading import Lock
from pathlib import Path
from typing import Any

from bct.current_nodes import classify_current_nodes
from bct.conversation_network import (
    conversation_display_order_directory,
    conversation_scope_directory,
    ensure_observed_node_labels,
    node_labels_for_conversations,
)
from bct.integrations.rcc import NamedPipeRelayClient, RelayEffectUnknown, RelayUnavailable, discover_instance_ids
from bct.integrations.native_process import process_matches
from bct.service_runtime import read_json
from bct.trace_timing import recent_stages


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


# In-process monitor-only health hints. Never used for relay routing or ACK.
_RCC_HEALTH_LOCK = Lock()
_RCC_HEALTH: dict[str, dict[str, Any]] = {}
# Reuse the existing open PR #251 classification. A bounded monitor-only
# timeout is not evidence that the RCC Native Host was disconnected.
_RCC_RETRY_SECONDS = 30.0
_RCC_TIMEOUT_RETRY_SECONDS = 5.0
_RCC_CACHE_LIMIT = 32
_RCC_INFLIGHT: set[str] = set()
_RCC_FIRST_PROBES_PER_PASS = 2
_RCC_RETRIES_PER_PASS = 1
_RCC_FRESH_TIMEOUT_S = 1.0
_RCC_RETRY_TIMEOUT_S = 0.6
_RCC_TIMEOUT_RETRY_TIMEOUT_S = 1.2


def _rcc_probe_status(exc: Exception) -> str:
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, RelayEffectUnknown)
        and str(exc) == "RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH"
    ):
        return "PROBE_TIMEOUT"
    if isinstance(exc, RelayUnavailable) or (
        isinstance(exc, RelayEffectUnknown)
        and str(exc) == "RCC_PIPE_CLOSED_AFTER_DISPATCH"
    ):
        return "UNAVAILABLE"
    return "PROBE_ERROR"

def _rcc_cached_row(instance_id: str, hint: dict[str, Any], now: float) -> dict[str, Any]:
    if not hint:
        return {
            "instance_id": instance_id, "state": "UNKNOWN",
            "error": "PROBE_DEFERRED", "tabs": [], "cached": True,
        }
    last_known_row = hint.get("last_known_row")
    if not isinstance(last_known_row, dict):
        last_known_row = {}
    result: dict[str, Any] = {
        **last_known_row,
        "instance_id": instance_id,
        "state": hint.get("probe_state", "UNAVAILABLE" if hint.get("unavailable") else "UNKNOWN"),
        "error": hint.get("error", "PROBE_IN_PROGRESS"),
        # A short RCC probe timeout is not evidence that every observed tab
        # disappeared. Preserve the last verified display snapshot while
        # marking it stale; Monitor must not erase node cards and thumbnail
        # numbers merely because a bounded read missed its deadline.
        "tabs": list(last_known_row.get("tabs") or []), "cached": True,
    }
    if hint.get("last_known_state"):
        result["last_known_state"] = hint["last_known_state"]
        result["last_seen_at"] = hint.get("last_seen_at")
    if hint.get("unavailable"):
        result["retry_in_ms"] = max(0, round((hint.get("retry_at", now) - now) * 1000))
    return result


def _rcc_states(instance_ids: list[str]) -> list[dict[str, Any]]:
    client = NamedPipeRelayClient()
    with _RCC_HEALTH_LOCK:
        for stale in list(_RCC_HEALTH):
            if stale not in instance_ids:
                del _RCC_HEALTH[stale]
        hints = {key: dict(value) for key, value in _RCC_HEALTH.items()}
    # Healthy instances first. Preserve the returned instance order below.
    ordered = sorted(instance_ids, key=lambda ident: bool(hints.get(ident, {}).get("unavailable")))
    results: dict[str, dict[str, Any]] = {}
    first_probes = 0
    retry_probes = 0
    for instance_id in ordered:
        hint = hints.get(instance_id, {})
        now = time.monotonic()
        unavailable = bool(hint.get("unavailable"))
        deferred = (
            unavailable and (
                now < hint.get("retry_at", 0)
                or retry_probes >= _RCC_RETRIES_PER_PASS
            )
        ) or (not hint and first_probes >= _RCC_FIRST_PROBES_PER_PASS)
        if deferred:
            results[instance_id] = _rcc_cached_row(instance_id, hint, now)
            continue
        with _RCC_HEALTH_LOCK:
            if instance_id in _RCC_INFLIGHT:
                results[instance_id] = _rcc_cached_row(instance_id, hint, now)
                continue
            _RCC_INFLIGHT.add(instance_id)
        if unavailable:
            retry_probes += 1
        elif not hint:
            first_probes += 1
        try:
            result = client.request(
                instance_id=instance_id,
                request_id=f"monitor-{time.time_ns():x}",
                command="state",
                timeout_s=(
                    _RCC_TIMEOUT_RETRY_TIMEOUT_S if unavailable and hint.get("probe_state") == "PROBE_TIMEOUT"
                    else _RCC_RETRY_TIMEOUT_S if unavailable
                    else _RCC_FRESH_TIMEOUT_S
                ),
            )
            if not isinstance(result.get("state"), dict):
                raise ValueError("RCC_MONITOR_STATE_INVALID")
            state = result["state"]
            endpoints = {
                int(item["tabId"]): item
                for item in state.get("endpoints", [])
                if isinstance(item, dict) and isinstance(item.get("tabId"), int)
            }
            tabs = []
            for item in state.get("tabs", []):
                if not isinstance(item, dict) or not isinstance(item.get("tabId"), int):
                    continue
                endpoint = endpoints.get(int(item["tabId"]), {})
                tab_index = item.get("index")
                if not isinstance(tab_index, int) or isinstance(tab_index, bool) or tab_index < 0:
                    tab_index = endpoint.get("tabIndex")
                if not isinstance(tab_index, int) or isinstance(tab_index, bool) or tab_index < 0:
                    tab_index = None
                reasoning = endpoint.get("reasoning")
                if not isinstance(reasoning, dict):
                    reasoning = {}
                reasoning_status = str(reasoning.get("status") or "").strip().upper()
                reasoning_level = str(reasoning.get("level") or "").strip()
                reasoning_source = str(reasoning.get("source") or "").strip()
                if (reasoning_status != "OBSERVED" or not reasoning_level \
                        or len(reasoning_level) > 32 or len(reasoning_source) > 64):
                    reasoning_status = "UNAVAILABLE"
                    reasoning_level = ""
                    reasoning_source = ""
                surface = endpoint.get("surface")
                if not isinstance(surface, dict):
                    surface = {}
                surface_kind = str(surface.get("kind") or "UNKNOWN").strip().upper()
                surface_source = str(surface.get("source") or "").strip()
                if surface_kind not in {"CHAT", "WORK", "CODEX", "UNKNOWN"} or len(surface_source) > 64:
                    surface_kind = "UNKNOWN"
                    surface_source = ""
                telemetry = endpoint.get("telemetry")
                if not isinstance(telemetry, dict):
                    telemetry = {}
                connection = endpoint.get("connection")
                if not isinstance(connection, dict):
                    connection = {}
                user_attention = telemetry.get("user_attention")
                if not isinstance(user_attention, dict):
                    user_attention = None
                tabs.append({
                    "tab_id": item["tabId"],
                    "window_id": item.get("windowId"),
                    "tab_index": tab_index,
                    "conversation_key": str(endpoint.get("conversationKey") or "").lower(),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "presence": str(endpoint.get("presence") or "UNKNOWN"),
                    "active": bool(endpoint.get("tabActive")),
                    "generating": bool(endpoint.get("generating")),
                    "reasoning": {
                        "status": reasoning_status,
                        "level": reasoning_level,
                        "source": reasoning_source,
                        "observed_at": reasoning.get("observedAt"),
                    },
                    "surface": {"kind": surface_kind, "source": surface_source},
                    "connection": {
                        "disconnected": connection.get("disconnected")
                        if type(connection.get("disconnected")) is bool else None,
                        "reason": str(connection.get("reason") or "")[:160],
                    },
                    "telemetry": {
                        "generation_state": str(telemetry.get("generationState") or "")[:32],
                        "readiness": str(telemetry.get("readiness") or "")[:32],
                        "last_activity_at": telemetry.get("lastActivityAt"),
                        "generation_started_at": telemetry.get("generationStartedAt"),
                        "generation_finished_at": telemetry.get("generationFinishedAt"),
                        "js_heap_used_mb": telemetry.get("js_heap_used_mb"),
                        "js_heap_limit_mb": telemetry.get("js_heap_limit_mb"),
                        "rendered_chars": telemetry.get("rendered_chars"),
                        "turns": telemetry.get("turns"),
                        "performance_state": telemetry.get("performanceState"),
                        "rolling_avg_response_ms": telemetry.get("rollingAvgResponseMs"),
                        "signal_source": str(telemetry.get("signal_source") or "")[:32],
                        "user_attention": {
                            "kind": str(user_attention.get("kind") or "")[:64],
                            "label": str(user_attention.get("label") or "")[:120],
                        } if user_attention else None,
                    },
                })
            live_row = {
                "instance_id": instance_id,
                "session_id": str(state.get("sessionId") or ""),
                "state": "OPEN",
                "background_build_id": str(state.get("backgroundBuildId") or ""),
                "tabs": tabs,
            }
            results[instance_id] = live_row
            with _RCC_HEALTH_LOCK:
                _RCC_HEALTH[instance_id] = {
                    "unavailable": False, "last_known_state": "OPEN",
                    "last_seen_at": time.time(),
                    "last_known_row": live_row,
                }
        except Exception as exc:
            error = type(exc).__name__
            probe_state = _rcc_probe_status(exc)
            results[instance_id] = {
                "instance_id": instance_id, "state": probe_state,
                "error": error, "tabs": [],
            }
            with _RCC_HEALTH_LOCK:
                _RCC_HEALTH[instance_id] = {
                    "unavailable": True, "error": error,
                    "probe_state": probe_state,
                    "retry_at": time.monotonic() + (
                        _RCC_TIMEOUT_RETRY_SECONDS if probe_state == "PROBE_TIMEOUT"
                        else _RCC_RETRY_SECONDS
                    ),
                    "last_known_state": hint.get("last_known_state"),
                    "last_seen_at": hint.get("last_seen_at"),
                    "last_known_row": hint.get("last_known_row"),
                }
        finally:
            with _RCC_HEALTH_LOCK:
                _RCC_INFLIGHT.discard(instance_id)
    with _RCC_HEALTH_LOCK:
        if len(_RCC_HEALTH) > _RCC_CACHE_LIMIT:
            for key in list(_RCC_HEALTH)[:len(_RCC_HEALTH) - _RCC_CACHE_LIMIT]:
                del _RCC_HEALTH[key]
    return [results[instance_id] for instance_id in instance_ids]


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rcc_payload_status(
    *, source_path: Path | None, live_path: Path | None,
    instances: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare exact bytes without exposing local paths or extension contents."""
    source_sha256 = _file_sha256(source_path)
    live_sha256 = _file_sha256(live_path)
    if source_sha256 is None:
        state = "SOURCE_MISSING"
    elif live_sha256 is None:
        state = "LIVE_MISSING"
    elif source_sha256 == live_sha256:
        state = "MATCH"
    else:
        state = "MISMATCH"
    return {
        "state": state,
        "source_sha256": source_sha256,
        "live_sha256": live_sha256,
        "files_match": state == "MATCH",
        "advertised_build_ids": sorted({
            str(row.get("background_build_id") or "")
            for row in instances
            if str(row.get("background_build_id") or "")
        }),
    }


def _conversation_network_manager_statuses(
    store: Any, *, observed_conversation_keys: list[str],
) -> list[dict[str, Any]]:
    """Project durable Manager state without assigning or replacing a role."""
    # Narrow contract fixtures used by current-node integration tests expose
    # only monitor_snapshot(). Production Store always owns transaction().
    if not callable(getattr(store, "transaction", None)):
        return []
    observed = {
        str(value or "").strip().lower()
        for value in observed_conversation_keys
        if str(value or "").strip()
    }
    with store.transaction() as db:
        projects = [dict(row) for row in db.execute(
            "SELECT project_id,display_name FROM conversation_network_projects "
            "WHERE active=1 ORDER BY display_name COLLATE NOCASE,project_id"
        )]
        managers = [dict(row) for row in db.execute(
            "SELECT m.project_id,m.conversation_key,c.display_name,n.node_number "
            "FROM conversation_network_memberships m "
            "JOIN conversation_network_membership_tags t "
            "ON t.project_id=m.project_id AND t.conversation_key=m.conversation_key "
            "JOIN conversation_network_conversations c ON c.conversation_key=m.conversation_key "
            "JOIN conversation_network_node_labels n ON n.conversation_key=m.conversation_key "
            "WHERE m.activity='ACTIVE' AND lower(t.tag)='manager' "
            "ORDER BY m.project_id,n.node_number,m.conversation_key"
        )]
    managers_by_project: dict[str, list[dict[str, Any]]] = {}
    for manager in managers:
        managers_by_project.setdefault(str(manager["project_id"]), []).append(manager)
    result: list[dict[str, Any]] = []
    for project in projects:
        project_id = str(project["project_id"])
        candidates = managers_by_project.get(project_id, [])
        manager = candidates[0] if len(candidates) == 1 else None
        conversation_key = "" if manager is None else str(manager["conversation_key"]).lower()
        if not candidates:
            status = "MISSING"
        elif len(candidates) > 1:
            status = "CONFLICT"
        else:
            status = "OPEN" if conversation_key in observed else "NOT_OPEN"
        node_number = 0 if manager is None else int(manager["node_number"])
        result.append({
            "scope_id": project_id,
            "scope_name": str(project["display_name"]),
            "status": status,
            "manager_conversation_key": conversation_key,
            "manager_node_label": "" if node_number <= 0 else f"N{((node_number - 1) % 99) + 1}",
            "manager_title": "" if manager is None else str(manager["display_name"]),
            "manager_count": len(candidates),
        })
    return result


def build_monitor_state(
    *, store: Any, service_state: dict[str, Any], data_root: Path,
    rcc_source_path: Path | None = None, rcc_live_path: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    snapshot = store.monitor_snapshot()
    after_snapshot = time.perf_counter()
    sessions = _session_states(data_root / "process-sessions")
    after_sessions = time.perf_counter()
    instance_ids = discover_instance_ids()
    after_discovery = time.perf_counter()
    rcc = _rcc_states(instance_ids)
    after_rcc = time.perf_counter()
    observed_conversations = [
        (str(tab.get("conversation_key") or ""), str(tab.get("title") or ""))
        for instance in rcc for tab in instance.get("tabs", [])
        if isinstance(tab, dict)
    ]
    manager_statuses = _conversation_network_manager_statuses(
        store,
        observed_conversation_keys=[key for key, _title in observed_conversations],
    )
    labels = ensure_observed_node_labels(store, conversations=observed_conversations)
    # Existing Monitor GET is a legitimate observation wake, not a new poller.
    # Requeue only never-dispatched PENDING committed label events.
    store.wake_node_label_notifications(
        labels.keys(),
        topology=[
            (str(instance.get("instance_id") or ""), str(instance.get("session_id") or ""),
             int(tab.get("tab_id") or 0), int(tab.get("window_id") or 0),
             str(tab.get("conversation_key") or ""))
            for instance in rcc for tab in instance.get("tabs", [])
            if isinstance(tab, dict)
        ],
    )
    scopes = conversation_scope_directory(
        store,
        conversation_keys=[key for key, _title in observed_conversations],
    )
    display_orders = conversation_display_order_directory(
        store,
        conversation_keys=[key for key, _title in observed_conversations],
    )
    for instance in rcc:
        for tab in instance.get("tabs", []):
            if not isinstance(tab, dict):
                continue
            label = labels.get(str(tab.get("conversation_key") or "").lower())
            if label:
                tab["node_label"] = label
            key = str(tab.get("conversation_key") or "").lower()
            scope = dict(scopes.get(key) or {})
            if key in display_orders:
                scope["display_order"] = display_orders[key]
            if scope:
                tab["conversation_scope"] = scope
    # Passive timing of the existing read-only monitor stages. Do not persist,
    # probe additional endpoints, or expose operation payloads and credentials.
    timings = {
        "store_snapshot_ms": round((after_snapshot - started) * 1000, 3),
        "process_sessions_ms": round((after_sessions - after_snapshot) * 1000, 3),
        "rcc_discovery_ms": round((after_discovery - after_sessions) * 1000, 3),
        "rcc_state_ms": round((after_rcc - after_discovery) * 1000, 3),
        "total_ms": round((after_rcc - started) * 1000, 3),
    }
    claim_diagnostics = store.claim_diagnostics()
    shared_claims = sum(
        1 for item in claim_diagnostics if item["scope"] == "SHARED_RESOURCE"
    )
    return {
        "observability": {"schema": 1, "read_only": False, "registry_sync": "DISPLAY_LABELS_ONLY", "timings": timings, "mcp_recent": recent_stages()},
        "schema": 1,
        "generated_at": time.time(),
        "service": dict(service_state),
        "counts": {
            "works": len(snapshot["works"]),
            "operations": len(snapshot["operations"]),
            "unresolved_claims": len(snapshot["unresolved_claims"]),
            "unresolved_claims_shared": shared_claims,
            "unresolved_claims_exact": len(claim_diagnostics) - shared_claims,
            "nodes": len(snapshot["nodes"]),
            "connections": len(snapshot["connections"]),
            "rcc_instances": len(instance_ids),
            "process_sessions": len(sessions),
            "orchestration_sessions": len(snapshot["orchestration_sessions"]),
            "orchestration_assignments": len(snapshot["orchestration_assignments"]),
            "github_inbox": len(snapshot.get("github_run_inbox", [])),
        },
        "current_nodes": classify_current_nodes(rcc, observed_at=time.time()),
        "conversation_network_managers": manager_statuses,
        "rcc": {
            "instances": rcc,
            "payload": _rcc_payload_status(
                source_path=rcc_source_path, live_path=rcc_live_path,
                instances=rcc,
            ),
        },
        "process_sessions": sessions,
        "claim_diagnostics": claim_diagnostics,
        **snapshot,
    }


def build_monitor_ui_state(
    *, store: Any, service_state: dict[str, Any], data_root: Path,
) -> dict[str, Any]:
    """Return the bounded, read-only snapshot needed to paint the Monitor roster.

    This deliberately does not allocate labels, wake notifications, inspect
    process sessions, hash payload files, or enumerate historical Work/Claim
    data.  Those are operator/maintenance concerns, not prerequisites for
    showing the current RCC roster.
    """
    started = time.perf_counter()
    instance_ids = discover_instance_ids()
    after_discovery = time.perf_counter()
    rcc = _rcc_states(instance_ids)
    after_rcc = time.perf_counter()
    observed_conversations = [
        (str(tab.get("conversation_key") or ""), str(tab.get("title") or ""))
        for instance in rcc for tab in instance.get("tabs", [])
        if isinstance(tab, dict)
    ]
    conversation_keys = [key for key, _title in observed_conversations]
    manager_statuses = _conversation_network_manager_statuses(
        store, observed_conversation_keys=conversation_keys,
    )
    labels = node_labels_for_conversations(store, conversation_keys=conversation_keys)
    scopes = conversation_scope_directory(store, conversation_keys=conversation_keys)
    display_orders = conversation_display_order_directory(store, conversation_keys=conversation_keys)
    for instance in rcc:
        for tab in instance.get("tabs", []):
            if not isinstance(tab, dict):
                continue
            key = str(tab.get("conversation_key") or "").lower()
            label = labels.get(key)
            if label:
                tab["node_label"] = label
            scope = dict(scopes.get(key) or {})
            if key in display_orders:
                scope["display_order"] = display_orders[key]
            if scope:
                tab["conversation_scope"] = scope
    after_projection = time.perf_counter()
    return {
        "observability": {
            "schema": 1,
            "read_only": True,
            "timings": {
                "rcc_discovery_ms": round((after_discovery - started) * 1000, 3),
                "rcc_state_ms": round((after_rcc - after_discovery) * 1000, 3),
                "projection_ms": round((after_projection - after_rcc) * 1000, 3),
                "total_ms": round((after_projection - started) * 1000, 3),
            },
        },
        "schema": 1,
        "generated_at": time.time(),
        "service": dict(service_state),
        "current_nodes": classify_current_nodes(rcc, observed_at=time.time()),
        "conversation_network_managers": manager_statuses,
        "rcc": {"instances": rcc},
        "github_run_inbox": store.get_github_run_inbox(limit=12),
    }
