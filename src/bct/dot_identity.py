"""Dot metadata boundary. Dot references never enter conversation UUID ledgers."""
from __future__ import annotations
import json
import re

_KEY = re.compile(r"[A-Za-z0-9_-]{1,160}~[A-Za-z0-9_-]{1,160}\Z")

def dot_key(value):
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ValueError("DOT_REFERENCE_INVALID")
    return value

def dot_directory(store):
    if not callable(getattr(store, "transaction", None)):
        return {}
    with store.transaction() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dot_node_info'").fetchone()
        if not exists:
            return {}
        return {row["dot_key"]: {**json.loads(row["metadata"]), "revision": row["revision"]}
                for row in db.execute("SELECT dot_key,metadata,revision FROM dot_node_info")}

def save_dot_info(store, payload):
    allowed = {"dot_key", "display_name", "scope_name", "node_memo", "assigned_task", "role_tags", "expected_revision"}
    if set(payload) - allowed:
        raise ValueError("DOT_FIELD_NOT_ALLOWED")
    key = dot_key(payload.get("dot_key"))
    data = {"dot_key": key, "node_label": "O", "identity_kind": "DOT", "conversation_key": ""}
    for field, limit in (("display_name",120),("scope_name",120),("node_memo",2000),("assigned_task",240)):
        value = payload.get(field, "")
        if not isinstance(value,str) or len(value)>limit or "\x00" in value:
            raise ValueError("DOT_METADATA_INVALID")
        data[field] = value.strip()
    tags = payload.get("role_tags", [])
    if not isinstance(tags,list) or len(tags)>24 or any(not isinstance(t,str) or not t.strip() or len(t)>48 for t in tags):
        raise ValueError("DOT_ROLES_INVALID")
    # This surface is a commander; it cannot impersonate UUID-bound execution roles.
    if any(t.casefold() in {"manager","worker","supervisor"} for t in tags):
        raise ValueError("DOT_EXECUTION_ROLE_UNSUPPORTED")
    data["role_tags"] = list(dict.fromkeys(["Orchestrator", *tags]))
    with store.transaction() as db:
        db.execute("CREATE TABLE IF NOT EXISTS dot_node_info(dot_key TEXT PRIMARY KEY,metadata TEXT NOT NULL,revision INTEGER NOT NULL)")
        row = db.execute("SELECT revision FROM dot_node_info WHERE dot_key=?", (key,)).fetchone()
        revision = int(row["revision"]) if row else 0
        if type(payload.get("expected_revision")) is not int or payload["expected_revision"] != revision:
            raise ValueError("DOT_METADATA_CONFLICT")
        if data["scope_name"]:
            raise ValueError("DOT_ORCHESTRATOR_GLOBAL_ONLY")
        other = db.execute("SELECT 1 FROM dot_node_info WHERE dot_key<>?", (key,)).fetchone()
        if other:
            raise ValueError("DOT_ORCHESTRATOR_ALREADY_REGISTERED")
        data["scope_id"] = ""
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
        db.execute("INSERT INTO dot_node_info VALUES(?,?,?) ON CONFLICT(dot_key) DO UPDATE SET metadata=excluded.metadata,revision=excluded.revision",
                   (key,encoded,revision+1))
    return {**data,"revision":revision+1}
