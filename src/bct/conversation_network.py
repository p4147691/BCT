"""Conversation scopes and read-only Monitor snapshots.

This module does not call Monitor, RCC, Chrome, or an AI model. A caller may
provide an observed Monitor snapshot; this module validates and durably records
only that observation. Each registered conversation receives one durable BCT
display label (``N1``, ``N2``, ...).  The label is an alias for people, never
a route identity, policy subject, or BCT Node/Connection.

``conversation_network_projects`` is retained as the durable compatibility
table, but its user-facing meaning is one *conversation scope*.  A scope can
describe a Git project, a product, or any other group without introducing a
second network object.  Role tags such as ``Manager`` are advisory metadata;
they never grant authority and there may be zero, one, or many Managers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import time
import uuid

from bct.core.store import Store


SNAPSHOT_SCHEMA = "BCT_MONITOR_NODE_SNAPSHOT_V1"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_UUID = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z", re.I
)
_COMPLETENESS = frozenset({"COMPLETE", "PARTIAL", "UNAVAILABLE"})
_PRESENCE = frozenset({"OPEN", "CLOSED", "UNKNOWN"})
_ACTIVITY = frozenset({"ACTIVE", "HOLD", "EXCLUDED"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NODE_LABEL = re.compile(r"N([1-9][0-9]*)\Z", re.I)


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


def _node_label(number: int) -> str:
    return f"N{number}"


def role_tags_sha256(tags: list[str] | tuple[str, ...]) -> str:
    """Return the UTF-8 digest for one canonical advisory-role list."""
    ordered = sorted((str(tag) for tag in tags), key=lambda value: (value.casefold(), value))
    return hashlib.sha256(_canonical(ordered).encode("utf-8")).hexdigest()


def _active_role_tags(db, conversation_key: str) -> tuple[str, list[str]]:
    membership = db.execute(
        "SELECT project_id FROM conversation_network_memberships "
        "WHERE conversation_key=? AND activity='ACTIVE' ORDER BY updated_at DESC LIMIT 1",
        (conversation_key,),
    ).fetchone()
    if membership is None:
        return "", []
    project_id = str(membership["project_id"])
    tags = [str(row["tag"]) for row in db.execute(
        "SELECT tag FROM conversation_network_membership_tags "
        "WHERE project_id=? AND conversation_key=? ORDER BY tag COLLATE NOCASE,tag",
        (project_id, conversation_key),
    )]
    return project_id, tags


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
    """Register a conversation and allocate its permanent display-only label."""
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
        label_row = db.execute(
            "SELECT node_number FROM conversation_network_node_labels WHERE conversation_key=?", (key,)
        ).fetchone()
        if label_row is None:
            next_number = int(db.execute(
                "SELECT COALESCE(MAX(node_number),0)+1 AS next_number FROM conversation_network_node_labels"
            ).fetchone()["next_number"])
            db.execute(
                "INSERT INTO conversation_network_node_labels(conversation_key,node_number,assigned_at) VALUES(?,?,?)",
                (key, next_number, when),
            )
        else:
            next_number = int(label_row["node_number"])
    return {"conversation_key": key, "display_name": name, "node_label": _node_label(next_number)}


def node_labels_for_conversations(store: Store, *, conversation_keys: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Read existing BCT display labels without allocating or changing state."""
    keys = sorted({str(value or "").strip().lower() for value in conversation_keys if _UUID.fullmatch(str(value or "").strip())})
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with store.transaction() as db:
        rows = list(db.execute(
            "SELECT conversation_key,node_number FROM conversation_network_node_labels "
            f"WHERE conversation_key IN ({placeholders})", keys,
        ))
    return {str(row["conversation_key"]): _node_label(int(row["node_number"])) for row in rows}


def ensure_observed_node_labels(store: Store, *, conversations: list[tuple[str, str]]) -> dict[str, str]:
    """Allocate display labels for RCC-observed conversations, never roles or routes."""
    titles: dict[str, str] = {}
    for raw_key, raw_title in conversations:
        key = str(raw_key or "").strip().lower()
        if not _UUID.fullmatch(key):
            continue
        title = str(raw_title or "").replace("\x00", "").strip()[:120] or "ChatGPT"
        titles.setdefault(key, title)
    if not titles:
        return {}
    with store.transaction() as db:
        next_number = int(db.execute(
            "SELECT COALESCE(MAX(node_number),0)+1 AS next_number FROM conversation_network_node_labels"
        ).fetchone()["next_number"])
        for key in sorted(titles):
            if db.execute(
                "SELECT 1 FROM conversation_network_conversations WHERE conversation_key=?", (key,)
            ).fetchone() is None:
                db.execute(
                    "INSERT INTO conversation_network_conversations(conversation_key,display_name,created_at,updated_at) VALUES(?,?,?,?)",
                    (key, titles[key], time.time(), time.time()),
                )
            if db.execute(
                "SELECT 1 FROM conversation_network_node_labels WHERE conversation_key=?", (key,)
            ).fetchone() is None:
                db.execute(
                    "INSERT INTO conversation_network_node_labels(conversation_key,node_number,assigned_at) VALUES(?,?,?)",
                    (key, next_number, time.time()),
                )
                next_number += 1
    return node_labels_for_conversations(store, conversation_keys=list(titles))


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
        if state == "ACTIVE":
            db.execute(
                "UPDATE conversation_network_memberships SET activity='EXCLUDED',updated_at=? "
                "WHERE conversation_key=? AND activity='ACTIVE' AND project_id<>?",
                (when, key, project),
            )
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


def _role_tags(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ConversationNetworkError("CONVERSATION_NETWORK_TAGS_INVALID")
    result: list[str] = []
    for value in values:
        tag = _text(value, "CONVERSATION_NETWORK_TAG_INVALID", 48)
        if tag not in result:
            result.append(tag)
    if len(result) > 24:
        raise ConversationNetworkError("CONVERSATION_NETWORK_TAGS_TOO_MANY")
    return result


def configure_conversation_scope(
    store: Store,
    *,
    conversation_key: str,
    display_name: str,
    scope_name: str = "",
    role_tags: list[str] | tuple[str, ...] = (),
    expected_role_tags_sha256: str | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Set the one current user-facing scope and advisory tags for a chat.

    This deliberately does not elect a privileged Manager, require a Manager,
    or move a Chrome tab.  Existing memberships are kept as inactive history
    rows so a trash/recovery view can still describe the previous scope.
    """
    key = _conversation_key(conversation_key)
    name = _text(display_name, "CONVERSATION_NETWORK_NODE_NAME_INVALID", 120)
    scope = str(scope_name or "").strip()
    if "\x00" in scope or len(scope) > 120:
        raise ConversationNetworkError("CONVERSATION_NETWORK_SCOPE_NAME_INVALID")
    tags = _role_tags(role_tags)
    if expected_role_tags_sha256 is not None:
        expected_role_tags_sha256 = str(expected_role_tags_sha256).strip().lower()
        if not _SHA256.fullmatch(expected_role_tags_sha256):
            raise ConversationNetworkError("CONVERSATION_NETWORK_ROLE_TAGS_SHA256_INVALID")
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        _current_scope, current_tags = _active_role_tags(db, key)
        if (expected_role_tags_sha256 is not None
                and role_tags_sha256(current_tags) != expected_role_tags_sha256):
            raise ConversationNetworkError("CONVERSATION_NETWORK_ROLE_TAGS_CONFLICT")
        conversation = db.execute(
            "SELECT conversation_key FROM conversation_network_conversations WHERE conversation_key=?",
            (key,),
        ).fetchone()
        if conversation is None:
            db.execute(
                "INSERT INTO conversation_network_conversations(conversation_key,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?)",
                (key, name, when, when),
            )
            next_number = int(db.execute(
                "SELECT COALESCE(MAX(node_number),0)+1 AS next_number FROM conversation_network_node_labels"
            ).fetchone()["next_number"])
            db.execute(
                "INSERT INTO conversation_network_node_labels(conversation_key,node_number,assigned_at) VALUES(?,?,?)",
                (key, next_number, when),
            )
        else:
            db.execute(
                "UPDATE conversation_network_conversations SET display_name=?,updated_at=? WHERE conversation_key=?",
                (name, when, key),
            )

        project_id = ""
        if scope:
            matches = list(db.execute(
                "SELECT project_id FROM conversation_network_projects "
                "WHERE display_name=? COLLATE NOCASE ORDER BY updated_at DESC",
                (scope,),
            ))
            if len(matches) > 1:
                raise ConversationNetworkError("CONVERSATION_NETWORK_SCOPE_AMBIGUOUS")
            if matches:
                project_id = str(matches[0]["project_id"])
                db.execute(
                    "UPDATE conversation_network_projects SET display_name=?,active=1,updated_at=? WHERE project_id=?",
                    (scope, when, project_id),
                )
            else:
                project_id = f"network.{uuid.uuid4().hex}"
                db.execute(
                    "INSERT INTO conversation_network_projects(project_id,display_name,active,created_at,updated_at) "
                    "VALUES(?,?,?,?,?)",
                    (project_id, scope, 1, when, when),
                )

        # A chat has one current scope. Old rows remain queryable history and
        # are not deleted merely because the user moves the chat elsewhere.
        db.execute(
            "UPDATE conversation_network_memberships SET activity='EXCLUDED',updated_at=? "
            "WHERE conversation_key=? AND activity='ACTIVE' AND project_id<>?",
            (when, key, project_id),
        )
        if not project_id:
            db.execute(
                "UPDATE conversation_network_memberships SET activity='EXCLUDED',updated_at=? "
                "WHERE conversation_key=? AND activity='ACTIVE'",
                (when, key),
            )
        else:
            db.execute(
                "INSERT INTO conversation_network_memberships(project_id,conversation_key,activity,created_at,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(project_id,conversation_key) DO UPDATE SET "
                "activity='ACTIVE',updated_at=excluded.updated_at",
                (project_id, key, "ACTIVE", when, when),
            )
            db.execute(
                "DELETE FROM conversation_network_membership_tags WHERE project_id=? AND conversation_key=?",
                (project_id, key),
            )
            db.executemany(
                "INSERT INTO conversation_network_membership_tags(project_id,conversation_key,tag,created_at) "
                "VALUES(?,?,?,?)",
                [(project_id, key, tag, when) for tag in tags],
            )
    label = node_labels_for_conversations(store, conversation_keys=[key]).get(key, "")
    return {
        "conversation_key": key,
        "display_name": name,
        "node_label": label,
        "scope_id": project_id,
        "scope_name": scope,
        "role_tags": tags if project_id else [],
        "role_tags_sha256": role_tags_sha256(tags if project_id else []),
    }


def conversation_scope_directory(
    store: Store, *, conversation_keys: list[str] | tuple[str, ...]
) -> dict[str, dict[str, object]]:
    """Return current scope metadata for exact UUIDs without allocating it."""
    keys = sorted({
        str(value or "").strip().lower()
        for value in conversation_keys
        if _UUID.fullmatch(str(value or "").strip())
    })
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with store.transaction() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT m.conversation_key,m.project_id,p.display_name AS scope_name,m.updated_at "
            "FROM conversation_network_memberships m "
            "JOIN conversation_network_projects p ON p.project_id=m.project_id "
            f"WHERE m.activity='ACTIVE' AND m.conversation_key IN ({placeholders}) "
            "ORDER BY m.conversation_key,m.updated_at DESC",
            keys,
        )]
        tag_rows = [dict(row) for row in db.execute(
            "SELECT t.conversation_key,t.project_id,t.tag "
            "FROM conversation_network_membership_tags t "
            "JOIN conversation_network_memberships m "
            "ON m.project_id=t.project_id AND m.conversation_key=t.conversation_key "
            f"WHERE m.activity='ACTIVE' AND t.conversation_key IN ({placeholders}) "
            "ORDER BY t.tag COLLATE NOCASE",
            keys,
        )]
    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        key = str(row["conversation_key"])
        if key not in selected:
            selected[key] = {
                "scope_id": str(row["project_id"]),
                "scope_name": str(row["scope_name"]),
                "role_tags": [],
            }
    for row in tag_rows:
        key = str(row["conversation_key"])
        current = selected.get(key)
        if current is not None and str(row["project_id"]) == current["scope_id"]:
            current["role_tags"].append(str(row["tag"]))
    for current in selected.values():
        current["role_tags_sha256"] = role_tags_sha256(current["role_tags"])
    return selected


def patch_conversation_role_tags(
    store: Store,
    *,
    project_id: str,
    node_label: str,
    add: list[str] | tuple[str, ...] = (),
    remove: list[str] | tuple[str, ...] = (),
    expected_role_tags_sha256: str,
    now: float | None = None,
) -> dict[str, object]:
    """Patch advisory roles for one exact project member with optimistic CAS.

    Node labels are accepted only as human-facing selectors inside one exact
    project. The stored and routed identity remains the conversation UUID.
    """
    project = _identifier(project_id, "CONVERSATION_NETWORK_PROJECT_ID_INVALID")
    match = _NODE_LABEL.fullmatch(str(node_label or "").strip())
    if match is None:
        raise ConversationNetworkError("CONVERSATION_NETWORK_NODE_LABEL_INVALID")
    node_number = int(match.group(1))
    additions = _role_tags(add)
    removals = _role_tags(remove)
    if not additions and not removals:
        raise ConversationNetworkError("CONVERSATION_NETWORK_ROLE_PATCH_EMPTY")
    if set(additions) & set(removals):
        raise ConversationNetworkError("CONVERSATION_NETWORK_ROLE_PATCH_OVERLAP")
    expected = str(expected_role_tags_sha256 or "").strip().lower()
    if not _SHA256.fullmatch(expected):
        raise ConversationNetworkError("CONVERSATION_NETWORK_ROLE_TAGS_SHA256_INVALID")
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        row = db.execute(
            "SELECT m.conversation_key,c.display_name FROM conversation_network_memberships m "
            "JOIN conversation_network_node_labels n ON n.conversation_key=m.conversation_key "
            "JOIN conversation_network_conversations c ON c.conversation_key=m.conversation_key "
            "WHERE m.project_id=? AND m.activity='ACTIVE' AND n.node_number=?",
            (project, node_number),
        ).fetchone()
        if row is None:
            raise ConversationNetworkError("CONVERSATION_NETWORK_MEMBER_NOT_FOUND")
        conversation_key = str(row["conversation_key"])
        current = [str(item["tag"]) for item in db.execute(
            "SELECT tag FROM conversation_network_membership_tags "
            "WHERE project_id=? AND conversation_key=? ORDER BY tag COLLATE NOCASE,tag",
            (project, conversation_key),
        )]
        current_digest = role_tags_sha256(current)
        if current_digest != expected:
            raise ConversationNetworkError("CONVERSATION_NETWORK_ROLE_TAGS_CONFLICT")
        updated = [tag for tag in current if tag not in removals]
        for tag in additions:
            if tag not in updated:
                updated.append(tag)
        updated.sort(key=lambda value: (value.casefold(), value))
        changed = updated != current
        if changed:
            db.execute(
                "DELETE FROM conversation_network_membership_tags WHERE project_id=? AND conversation_key=?",
                (project, conversation_key),
            )
            db.executemany(
                "INSERT INTO conversation_network_membership_tags(project_id,conversation_key,tag,created_at) "
                "VALUES(?,?,?,?)",
                [(project, conversation_key, tag, when) for tag in updated],
            )
            db.execute(
                "UPDATE conversation_network_memberships SET updated_at=? "
                "WHERE project_id=? AND conversation_key=?",
                (when, project, conversation_key),
            )
    return {
        "project_id": project,
        "node_label": _node_label(node_number),
        "display_name": str(row["display_name"]),
        "role_tags": updated,
        "role_tags_sha256": role_tags_sha256(updated),
        "changed": changed,
    }


def conversation_display_order_directory(
    store: Store, *, conversation_keys: list[str] | tuple[str, ...]
) -> dict[str, int]:
    """Return durable display order for exact known conversations."""
    keys = sorted({
        str(value or "").strip().lower()
        for value in conversation_keys
        if _UUID.fullmatch(str(value or "").strip())
    })
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with store.transaction() as db:
        rows = db.execute(
            "SELECT conversation_key,display_order FROM conversation_network_conversations "
            f"WHERE conversation_key IN ({placeholders})",
            keys,
        ).fetchall()
    return {str(row["conversation_key"]): int(row["display_order"] or 0) for row in rows}


def arrange_conversations(
    store: Store,
    *,
    conversation_keys: list[str] | tuple[str, ...],
    scope_id: str = "",
    moved_conversation_key: str = "",
    now: float | None = None,
) -> dict[str, object]:
    """Atomically reorder visible chats and optionally move one between scopes.

    This is display metadata only.  It preserves a moved chat's advisory role
    tags, never changes its N label, and does not grant policy authority.
    """
    if not isinstance(conversation_keys, (list, tuple)):
        raise ConversationNetworkError("CONVERSATION_NETWORK_ORDER_INVALID")
    keys = [_conversation_key(value) for value in conversation_keys]
    if not keys or len(keys) > 512 or len(set(keys)) != len(keys):
        raise ConversationNetworkError("CONVERSATION_NETWORK_ORDER_INVALID")
    destination = str(scope_id or "").strip()
    if destination and not _ID.fullmatch(destination):
        raise ConversationNetworkError("CONVERSATION_NETWORK_SCOPE_ID_INVALID")
    moved = _conversation_key(moved_conversation_key) if str(moved_conversation_key or "").strip() else ""
    if moved and moved not in keys:
        raise ConversationNetworkError("CONVERSATION_NETWORK_MOVED_NODE_MISSING")
    when = float(time.time() if now is None else now)
    with store.transaction() as db:
        found = {
            str(row["conversation_key"])
            for row in db.execute(
                "SELECT conversation_key FROM conversation_network_conversations "
                f"WHERE conversation_key IN ({','.join('?' for _ in keys)})",
                keys,
            )
        }
        if found != set(keys):
            raise ConversationNetworkError("CONVERSATION_NETWORK_ORDER_NODE_UNKNOWN")
        if destination and db.execute(
            "SELECT 1 FROM conversation_network_projects WHERE project_id=? AND active=1",
            (destination,),
        ).fetchone() is None:
            raise ConversationNetworkError("CONVERSATION_NETWORK_SCOPE_UNKNOWN")

        current_rows = db.execute(
            "SELECT conversation_key,project_id FROM conversation_network_memberships "
            f"WHERE activity='ACTIVE' AND conversation_key IN ({','.join('?' for _ in keys)})",
            keys,
        ).fetchall()
        current = {str(row["conversation_key"]): str(row["project_id"]) for row in current_rows}
        for key in keys:
            if key != moved and current.get(key, "") != destination:
                raise ConversationNetworkError("CONVERSATION_NETWORK_ORDER_SCOPE_MISMATCH")

        if moved and current.get(moved, "") != destination:
            old_scope = current.get(moved, "")
            tags: list[str] = []
            if old_scope:
                tags = [str(row["tag"]) for row in db.execute(
                    "SELECT tag FROM conversation_network_membership_tags "
                    "WHERE project_id=? AND conversation_key=? ORDER BY tag COLLATE NOCASE",
                    (old_scope, moved),
                )]
            db.execute(
                "UPDATE conversation_network_memberships SET activity='EXCLUDED',updated_at=? "
                "WHERE conversation_key=? AND activity='ACTIVE'",
                (when, moved),
            )
            if destination:
                db.execute(
                    "INSERT INTO conversation_network_memberships(project_id,conversation_key,activity,created_at,updated_at) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(project_id,conversation_key) DO UPDATE SET "
                    "activity='ACTIVE',updated_at=excluded.updated_at",
                    (destination, moved, "ACTIVE", when, when),
                )
                db.execute(
                    "DELETE FROM conversation_network_membership_tags WHERE project_id=? AND conversation_key=?",
                    (destination, moved),
                )
                db.executemany(
                    "INSERT INTO conversation_network_membership_tags(project_id,conversation_key,tag,created_at) "
                    "VALUES(?,?,?,?)",
                    [(destination, moved, tag, when) for tag in tags],
                )

        db.executemany(
            "UPDATE conversation_network_conversations SET display_order=?,updated_at=? WHERE conversation_key=?",
            [(index, when, key) for index, key in enumerate(keys, start=1)],
        )
    return {
        "scope_id": destination,
        "conversation_keys": keys,
        "moved_conversation_key": moved,
    }


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
            "SELECT m.conversation_key,c.display_name,m.activity,n.node_number FROM conversation_network_memberships m "
            "JOIN conversation_network_conversations c ON c.conversation_key=m.conversation_key "
            "JOIN conversation_network_node_labels n ON n.conversation_key=m.conversation_key "
            "WHERE m.project_id=? AND m.activity='ACTIVE' ORDER BY c.display_name COLLATE NOCASE", (project,)
        )]
        tags = [dict(row) for row in db.execute(
            "SELECT t.conversation_key,t.tag FROM conversation_network_membership_tags t "
            "JOIN conversation_network_memberships m "
            "ON m.project_id=t.project_id AND m.conversation_key=t.conversation_key "
            "WHERE t.project_id=? AND m.activity='ACTIVE' "
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
            "node_label": _node_label(int(member["node_number"])),
            "display_name": str(member["display_name"]), "activity": str(member["activity"]),
            "role_tags": tags_by_key.get(key, []), "monitor_match": match,
            "role_tags_sha256": role_tags_sha256(tags_by_key.get(key, [])),
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
