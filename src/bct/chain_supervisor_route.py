"""Exact A-to-C Supervisor routes layered on the 1:1 Chain primitive.

This module deliberately does not select an AI role, create a Supervisor, or
send a message.  A Manager first records a Direction anchored to an exact BA
return.  The public recipe may then bind that Direction to *one* currently
confirmed, globally-tagged Supervisor and its exact RCC attachment.  The
ordinary Chain Message transport consumes that binding.

The separation matters: a Worker can report that review is needed, but it
cannot silently choose C; and an old tab/window observation cannot be used
after the route has drifted.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z", re.I)
_INSTANCE = re.compile(r"[a-f0-9]{32}\Z", re.I)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _route_value(value: object, code: str) -> str:
    text = str(value or "").strip().lower()
    if not _UUID.fullmatch(text):
        raise ValueError(code)
    return text


def resolve_confirmed_supervisor(*, node_view: dict[str, Any], rcc_view: dict[str, Any]) -> dict[str, Any]:
    """Resolve exactly one ready Supervisor from one fresh BCT observation.

    The display label is evidence for a person, never the target identity.
    A route is usable only if the role-tagged current node and an RCC tab agree
    on the same immutable conversation UUID.
    """
    current = node_view.get("current_nodes") if isinstance(node_view, dict) else None
    observation = current.get("observation") if isinstance(current, dict) else None
    if not isinstance(observation, dict) or observation.get("state") != "FRESH":
        return {"status": "BLOCKED", "reason": "SUPERVISOR_ROUTE_NODES_NOT_FRESH"}
    items = current.get("items") if isinstance(current, dict) else []
    candidates = [
        row for row in items if isinstance(row, dict)
        and row.get("status") == "CONFIRMED"
        and any(str(tag).strip().casefold() == "supervisor"
                for tag in (row.get("roles") if isinstance(row.get("roles"), list) else []))
    ]
    if not candidates:
        return {"status": "BLOCKED", "reason": "SUPERVISOR_ROUTE_MISSING"}
    if len(candidates) != 1:
        return {"status": "BLOCKED", "reason": "SUPERVISOR_ROUTE_AMBIGUOUS",
                "candidate_count": len(candidates)}
    candidate = candidates[0]
    if candidate.get("generating") is True:
        return {"status": "BLOCKED", "reason": "SUPERVISOR_ROUTE_BUSY",
                "node_number": str(candidate.get("node_number") or "")}
    try:
        conversation_key = _route_value(candidate.get("conversation_uuid"), "SUPERVISOR_ROUTE_CONVERSATION_INVALID")
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc)}

    matches: list[dict[str, Any]] = []
    instances = rcc_view.get("instances") if isinstance(rcc_view, dict) else []
    for instance in instances if isinstance(instances, list) else []:
        if not isinstance(instance, dict) or instance.get("state") != "OPEN":
            continue
        instance_id = str(instance.get("instance_id") or "").strip().lower()
        session_id = str(instance.get("session_id") or "").strip().lower()
        if not _INSTANCE.fullmatch(instance_id) or not _INSTANCE.fullmatch(session_id):
            continue
        for tab in instance.get("tabs") if isinstance(instance.get("tabs"), list) else []:
            if not isinstance(tab, dict):
                continue
            if str(tab.get("conversation_key") or "").strip().lower() != conversation_key:
                continue
            if tab.get("presence") != "OPEN":
                continue
            tab_id, window_id = tab.get("tab_id"), tab.get("window_id")
            if isinstance(tab_id, int) and tab_id > 0 and isinstance(window_id, int) and window_id > 0:
                matches.append({
                    "instance_id": instance_id, "session_id": session_id,
                    "tab_id": tab_id, "window_id": window_id,
                })
    if not matches:
        return {"status": "BLOCKED", "reason": "SUPERVISOR_ROUTE_NOT_OPEN",
                "conversation_key": conversation_key,
                "node_number": str(candidate.get("node_number") or "")}
    if len(matches) != 1:
        return {"status": "BLOCKED", "reason": "SUPERVISOR_ROUTE_ATTACHMENT_AMBIGUOUS",
                "conversation_key": conversation_key, "attachment_count": len(matches)}
    return {
        "status": "READY", "target_role": "supervisor",
        "conversation_key": conversation_key,
        "node_number": str(candidate.get("node_number") or ""),
        "node_name": str(candidate.get("name") or ""),
        **matches[0],
    }


class ChainSupervisorRouteLedger:
    """One immutable-or-refreshable C binding for one unsent A Direction."""

    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_supervisor_routes (
                    direction_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    conversation_key TEXT NOT NULL, node_number TEXT NOT NULL,
                    instance_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    tab_id INTEGER NOT NULL, window_id INTEGER NOT NULL,
                    route_sha256 TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                )
            """)

    def get(self, *, direction_id: str, work_id: str) -> dict[str, Any] | None:
        if not _ID.fullmatch(str(direction_id or "")) or not _ID.fullmatch(str(work_id or "")):
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_ID_INVALID")
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_supervisor_routes WHERE direction_id=? AND work_id=?",
                (direction_id, work_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def bind(self, *, direction_id: str, work_id: str, target: dict[str, Any]) -> dict[str, Any]:
        if not _ID.fullmatch(str(direction_id or "")) or not _ID.fullmatch(str(work_id or "")):
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_ID_INVALID")
        if target.get("status") != "READY" or target.get("target_role") != "supervisor":
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_TARGET_NOT_READY")
        conversation_key = _route_value(target.get("conversation_key"), "CHAIN_SUPERVISOR_ROUTE_CONVERSATION_INVALID")
        instance_id = str(target.get("instance_id") or "").strip().lower()
        session_id = str(target.get("session_id") or "").strip().lower()
        if not _INSTANCE.fullmatch(instance_id) or not _INSTANCE.fullmatch(session_id):
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_ATTACHMENT_INVALID")
        tab_id, window_id = target.get("tab_id"), target.get("window_id")
        if not isinstance(tab_id, int) or tab_id <= 0 or not isinstance(window_id, int) or window_id <= 0:
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_ATTACHMENT_INVALID")
        node_number = str(target.get("node_number") or "").strip()
        if not node_number:
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_NODE_INVALID")
        route = {
            "conversation_key": conversation_key, "node_number": node_number,
            "instance_id": instance_id, "session_id": session_id,
            "tab_id": tab_id, "window_id": window_id,
        }
        digest = _digest(route)
        when = time.time()
        with self.store.transaction() as db:
            direction = db.execute(
                "SELECT work_id,source_kind,decision,chain_state FROM chain_directions WHERE direction_id=?",
                (direction_id,),
            ).fetchone()
            if direction is None or direction["work_id"] != work_id:
                raise ValueError("CHAIN_SUPERVISOR_ROUTE_DIRECTION_NOT_FOUND")
            if direction["decision"] != "NEW_TASK":
                raise ValueError("CHAIN_SUPERVISOR_ROUTE_DIRECTION_NOT_A_NEW_TASK")
            if direction["source_kind"] != "MANAGER_RETURN":
                raise ValueError("CHAIN_SUPERVISOR_ROUTE_REQUIRES_MANAGER_RETURN")
            if direction["chain_state"] != "NOT_PLANNED":
                raise ValueError("CHAIN_SUPERVISOR_ROUTE_DIRECTION_ALREADY_PLANNED")
            existing = db.execute(
                "SELECT * FROM chain_supervisor_routes WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if existing is None:
                db.execute("""
                    INSERT INTO chain_supervisor_routes(
                        direction_id,work_id,conversation_key,node_number,instance_id,session_id,
                        tab_id,window_id,route_sha256,revision,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """, (direction_id, work_id, conversation_key, node_number, instance_id, session_id,
                      tab_id, window_id, digest, 1, when, when))
                duplicate, rebound = False, False
            elif existing["route_sha256"] == digest:
                duplicate, rebound = True, False
            elif existing["conversation_key"] == conversation_key:
                db.execute("""
                    UPDATE chain_supervisor_routes SET node_number=?,instance_id=?,session_id=?,
                    tab_id=?,window_id=?,route_sha256=?,revision=revision+1,updated_at=?
                    WHERE direction_id=?
                """, (node_number, instance_id, session_id, tab_id, window_id, digest, when, direction_id))
                duplicate, rebound = False, True
            else:
                raise ValueError("CHAIN_SUPERVISOR_ROUTE_TARGET_CONFLICT")
        value = self.get(direction_id=direction_id, work_id=work_id) or {}
        return {**value, "duplicate": duplicate, "rebound": rebound}

    def assert_target(self, *, direction_id: str, work_id: str,
                      conversation_key: str, instance_id: str, session_id: str,
                      tab_id: int, window_id: int) -> dict[str, Any]:
        route = self.get(direction_id=direction_id, work_id=work_id)
        if route is None:
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_NOT_PREPARED")
        actual = (str(conversation_key).lower(), str(instance_id).lower(), str(session_id).lower(), tab_id, window_id)
        expected = (route["conversation_key"], route["instance_id"], route["session_id"],
                    int(route["tab_id"]), int(route["window_id"]))
        if actual != expected:
            raise ValueError("CHAIN_SUPERVISOR_ROUTE_TARGET_MISMATCH")
        return route
