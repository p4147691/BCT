"""Project conversation-network directory and read-only Monitor snapshots.

This module does not call Monitor, RCC, Chrome, or an AI model. A caller may
provide an observed Monitor snapshot; this module validates and durably records
only that observation. The literal Monitor node label (for example ``D1-3``)
is display data, never a route identity or a BCT-generated number.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import time

from bct.core.store import Store


SNAPSHOT_SCHEMA = "BCT_MONITOR_NODE_SNAPSHOT_V1"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_UUID = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z", re.I
)
_COMPLETENESS = frozenset({"COMPLETE", "PARTIAL", "UNAVAILABLE"})
_PRESENCE = frozenset({"OPEN", "CLOSED", "UNKNOWN"})
_ACTIVITY = frozenset({"ACTIVE", "HOLD", "EXCLUDED"})


class ConversationNetworkError(ValueError):
    """The supplied directory record or Monitor observation is invalid."""


def _identifier(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ConversationNetworkError(code)
    return text


def _text(value: object, code: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text or len(text) > maximum:
        raise ConversationNetworkError(code)
    return text


def _conversation_key(value: object) -> str:
    key = str(value or "").strip().lower()
    if not _UUID.fullmatch(key):
        raise ConversationNetworkError("CONVERSATION_NETWORK_CONVERSATION_KEY_INVALID")
    return key


def _observed_at(value: object) -> str:
    raw = _text(value, "CONVERSATION_NETWORK_SNAPSHOT_TIME_INVALID", 64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_TIME_INVALID") from exc
    if parsed.tzinfo is None:
        raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_TIME_INVALID")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def upsert_project(store: Store, *, project_id: str, display_name: str,
                   active: bool = True, now: float | None = None) -> dict[str, object]:
    """Create or update a project directory entry; it has no routing effect."""
    project = _identifier(project_id, "CONVERSATION_NETWORK_PROJECT_ID_INVALID")
    name = _text(display_name, "CONVERSATION_NETWORK_PROJECT_NAME_INVALID", 120)
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        existing = db.execute(
            "SELECT project_id FROM conversation_network_projects WHERE project_id=?", (project,)
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO conversation_network_projects(project_id,display_name,active,created_at,updated_at) "
                "VALUES(?,?,?,?,?)", (project, name, int(bool(active)), when, when),
            )
        else:
            db.execute(
                "UPDATE conversation_network_projects SET display_name=?,active=?,updated_at=? WHERE project_id=?",
                (name, int(bool(active)), when, project),
            )
    return {"project_id": project, "display_name": name, "active": bool(active)}


def upsert_conversation(store: Store, *, conversation_key: str, display_name: str,
                        now: float | None = None) -> dict[str, str]:
    """Register a known ChatGPT conversation without attaching it to a project."""
    key = _conversation_key(conversation_key)
    name = _text(display_name, "CONVERSATION_NETWORK_NODE_NAME_INVALID", 120)
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        existing = db.execute(
            "SELECT conversation_key FROM conversation_network_conversations WHERE conversation_key=?", (key,)
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO conversation_network_conversations(conversation_key,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?)", (key, name, when, when),
            )
        else:
            db.execute(
                "UPDATE conversation_network_conversations SET display_name=?,updated_at=? WHERE conversation_key=?",
                (name, when, key),
            )
    return {"conversation_key": key, "display_name": name}


def resolve_project_id(store: Store, *, project_reference: str) -> str:
    """Resolve an exact project ID or one unambiguous user-facing display name."""
    reference = _text(project_reference, "CONVERSATION_NETWORK_PROJECT_REFERENCE_INVALID", 120)
    with store.transaction() as db:
        by_id = db.execute(
            "SELECT project_id FROM conversation_network_projects WHERE project_id=?", (reference,)
        ).fetchone()
        if by_id is not None:
            return str(by_id["project_id"])
        matches = list(db.execute(
            "SELECT project_id FROM conversation_network_projects WHERE display_name=?", (reference,)
        ))
    if not matches:
        raise ConversationNetworkError("CONVERSATION_NETWORK_PROJECT_NOT_FOUND")
    if len(matches) != 1:
        raise ConversationNetworkError("CONVERSATION_NETWORK_PROJECT_AMBIGUOUS")
    return str(matches[0]["project_id"])


def set_membership(store: Store, *, project_id: str, conversation_key: str,
                   activity: str = "ACTIVE", tags: list[str] | tuple[str, ...] = (),
                   now: float | None = None) -> dict[str, object]:
    """Attach a known conversation to a project with advisory-only tags."""
    project = _identifier(project_id, "CONVERSATION_NETWORK_PROJECT_ID_INVALID")
    key = _conversation_key(conversation_key)
    state = str(activity or "").strip().upper()
    if state not in _ACTIVITY:
        raise ConversationNetworkError("CONVERSATION_NETWORK_ACTIVITY_INVALID")
    if not isinstance(tags, (list, tuple)):
        raise ConversationNetworkError("CONVERSATION_NETWORK_TAGS_INVALID")
    checked_tags: list[str] = []
    for value in tags:
        tag = _text(value, "CONVERSATION_NETWORK_TAG_INVALID", 48)
        if tag not in checked_tags:
            checked_tags.append(tag)
    if len(checked_tags) > 24:
        raise ConversationNetworkError("CONVERSATION_NETWORK_TAGS_TOO_MANY")
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        if db.execute("SELECT 1 FROM conversation_network_projects WHERE project_id=?", (project,)).fetchone() is None:
            raise ConversationNetworkError("CONVERSATION_NETWORK_PROJECT_NOT_FOUND")
        if db.execute("SELECT 1 FROM conversation_network_conversations WHERE conversation_key=?", (key,)).fetchone() is None:
            raise ConversationNetworkError("CONVERSATION_NETWORK_CONVERSATION_NOT_FOUND")
        db.execute(
            "INSERT INTO conversation_network_memberships(project_id,conversation_key,activity,created_at,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(project_id,conversation_key) DO UPDATE SET "
            "activity=excluded.activity,updated_at=excluded.updated_at",
            (project, key, state, when, when),
        )
        db.execute(
            "DELETE FROM conversation_network_membership_tags WHERE project_id=? AND conversation_key=?",
            (project, key),
        )
        db.executemany(
            "INSERT INTO conversation_network_membership_tags(project_id,conversation_key,tag,created_at) VALUES(?,?,?,?)",
            [(project, key, tag, when) for tag in checked_tags],
        )
    return {"project_id": project, "conversation_key": key, "activity": state, "tags": checked_tags}


def _validated_snapshot(value: object) -> tuple[dict[str, object], str]:
    if not isinstance(value, dict) or set(value) != {
        "schema", "source", "snapshot_id", "observed_at", "completeness", "nodes"
    }:
        raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_FIELDS_INVALID")
    if value["schema"] != SNAPSHOT_SCHEMA or value["source"] != "MONITOR":
        raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_SCHEMA_INVALID")
    snapshot_id = _identifier(value["snapshot_id"], "CONVERSATION_NETWORK_SNAPSHOT_ID_INVALID")
    completeness = str(value["completeness"] or "").strip().upper()
    if completeness not in _COMPLETENESS:
        raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_COMPLETENESS_INVALID")
    if not isinstance(value["nodes"], list) or len(value["nodes"]) > 512:
        raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_NODES_INVALID")
    if completeness == "UNAVAILABLE" and value["nodes"]:
        raise ConversationNetworkError("CONVERSATION_NETWORK_UNAVAILABLE_HAS_NODES")
    nodes: list[dict[str, str]] = []
    labels: set[str] = set()
    keys: set[str] = set()
    for raw in value["nodes"]:
        if not isinstance(raw, dict) or set(raw) != {"node_label", "conversation_key", "title", "presence"}:
            raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_NODE_FIELDS_INVALID")
        # The Monitor label is opaque presentation data. Deliberately do not
        # parse D1-3 or coerce it to any other notation.
        label = _text(raw["node_label"], "CONVERSATION_NETWORK_MONITOR_LABEL_INVALID", 64)
        key = _conversation_key(raw["conversation_key"])
        title = str(raw["title"] or "").strip()
        if "\x00" in title or len(title) > 256:
            raise ConversationNetworkError("CONVERSATION_NETWORK_MONITOR_TITLE_INVALID")
        presence = str(raw["presence"] or "").strip().upper()
        if presence not in _PRESENCE:
            raise ConversationNetworkError("CONVERSATION_NETWORK_MONITOR_PRESENCE_INVALID")
        if label in labels:
            raise ConversationNetworkError("CONVERSATION_NETWORK_LABEL_CONFLICT")
        if key in keys:
            raise ConversationNetworkError("CONVERSATION_NETWORK_UUID_CONFLICT")
        labels.add(label)
        keys.add(key)
        nodes.append({"node_label": label, "conversation_key": key, "title": title, "presence": presence})
    normalized: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "source": "MONITOR",
        "snapshot_id": snapshot_id,
        "observed_at": _observed_at(value["observed_at"]),
        "completeness": completeness,
        "nodes": nodes,
    }
    return normalized, hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest()


def record_monitor_snapshot(store: Store, snapshot: object, *, now: float | None = None) -> dict[str, object]:
    """Validate and append a Monitor observation without calling Monitor or RCC."""
    checked, digest = _validated_snapshot(snapshot)
    received_at = float(time.time() if now is None else now)
    with store.transaction() as db:
        existing = db.execute(
            "SELECT payload_digest FROM conversation_network_monitor_snapshots WHERE snapshot_id=?",
            (checked["snapshot_id"],),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_digest"]) != digest:
                raise ConversationNetworkError("CONVERSATION_NETWORK_SNAPSHOT_ID_CONFLICT")
            return {"snapshot_id": checked["snapshot_id"], "duplicate": True, "recorded": False}
        db.execute(
            "INSERT INTO conversation_network_monitor_snapshots(snapshot_id,observed_at,completeness,payload_digest,received_at) "
            "VALUES(?,?,?,?,?)",
            (checked["snapshot_id"], checked["observed_at"], checked["completeness"], digest, received_at),
        )
        db.executemany(
            "INSERT INTO conversation_network_monitor_rows(snapshot_id,node_label,conversation_key,title,presence) "
            "VALUES(?,?,?,?,?)",
            [(checked["snapshot_id"], node["node_label"], node["conversation_key"], node["title"], node["presence"])
             for node in checked["nodes"]],
        )
    return {"snapshot_id": checked["snapshot_id"], "duplicate": False, "recorded": True,
            "completeness": checked["completeness"], "node_count": len(checked["nodes"])}


def project_view(store: Store, *, project_id: str) -> dict[str, object]:
    """Return a read-only project directory with its latest Monitor observation."""
    project = _identifier(project_id, "CONVERSATION_NETWORK_PROJECT_ID_INVALID")
    with store.transaction() as db:
        project_row = db.execute(
            "SELECT project_id,display_name,active FROM conversation_network_projects WHERE project_id=?", (project,)
        ).fetchone()
        if project_row is None:
            raise ConversationNetworkError("CONVERSATION_NETWORK_PROJECT_NOT_FOUND")
        snapshots = db.execute(
            "SELECT snapshot_id,observed_at,completeness FROM conversation_network_monitor_snapshots "
            "ORDER BY received_at DESC LIMIT 1"
        ).fetchone()
        latest_available = db.execute(
            "SELECT snapshot_id,observed_at,completeness FROM conversation_network_monitor_snapshots "
            "WHERE completeness IN ('COMPLETE','PARTIAL') ORDER BY received_at DESC LIMIT 1"
        ).fetchone()
        latest_rows = [] if latest_available is None else [dict(row) for row in db.execute(
            "SELECT node_label,conversation_key,title,presence FROM conversation_network_monitor_rows WHERE snapshot_id=?",
            (latest_available["snapshot_id"],),
        )]
        by_key = {str(row["conversation_key"]): row for row in latest_rows}
        members = [dict(row) for row in db.execute(
            "SELECT m.conversation_key,c.display_name,m.activity FROM conversation_network_memberships m "
            "JOIN conversation_network_conversations c ON c.conversation_key=m.conversation_key "
            "WHERE m.project_id=? ORDER BY c.display_name COLLATE NOCASE", (project,)
        )]
        tags = [dict(row) for row in db.execute(
            "SELECT conversation_key,tag FROM conversation_network_membership_tags WHERE project_id=? "
            "ORDER BY tag COLLATE NOCASE", (project,)
        )]
    tags_by_key: dict[str, list[str]] = {}
    for tag in tags:
        tags_by_key.setdefault(str(tag["conversation_key"]), []).append(str(tag["tag"]))
    latest_completeness = None if latest_available is None else str(latest_available["completeness"])
    unavailable = snapshots is not None and str(snapshots["completeness"]) == "UNAVAILABLE"
    result_members = []
    known_keys = {str(member["conversation_key"]) for member in members}
    for member in members:
        key = str(member["conversation_key"])
        monitor = by_key.get(key)
        if unavailable:
            match = "MONITOR_UNAVAILABLE"
        elif monitor is not None:
            match = "MATCHED"
        elif latest_completeness == "PARTIAL":
            match = "PARTIAL_UNOBSERVED"
        else:
            match = "NETWORK_UNOBSERVED"
        result_members.append({
            "display_name": str(member["display_name"]), "activity": str(member["activity"]),
            "role_tags": tags_by_key.get(key, []), "monitor_match": match,
            "monitor": None if monitor is None else {
                "node_label": str(monitor["node_label"]), "title": str(monitor["title"]),
                "presence": str(monitor["presence"]),
                "observed_at": str(latest_available["observed_at"]),
            },
        })
    return {
        "project": {"display_name": str(project_row["display_name"]), "active": bool(project_row["active"])},
        "monitor_snapshot": None if snapshots is None else {
            "observed_at": str(snapshots["observed_at"]),
            "completeness": str(snapshots["completeness"]),
        },
        "members": result_members,
        "monitor_only": [
            {"node_label": str(row["node_label"]), "title": str(row["title"]), "presence": str(row["presence"])}
            for row in latest_rows if str(row["conversation_key"]) not in known_keys
        ],
    }
