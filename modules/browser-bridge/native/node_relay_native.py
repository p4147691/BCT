"""Opt-in Native Messaging frame adapter for the *independent* node mailbox.

No RCC, CDP, BCT MCP session, browser DOM action, implicit retries or
production store paths. Chrome origin is verified by the parent host.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from node_relay_store import NodeRelayStore
from native_host import read_frame, write_frame

_ID = re.compile(r"[a-f0-9]{32}\Z")
_TYPES = {
    "node_relay_enqueue", "node_relay_claim", "node_relay_ack",
    "node_relay_reply", "node_relay_inspect",
}


def node_request(message):
    return isinstance(message, dict) and str(message.get("type") or "").startswith("node_relay_")


def validate(message):
    if not isinstance(message, dict) or set(message)!={"schema_version","type","request_id","arguments"}:
        raise ValueError("BRIDGE_NODE_FRAME_SCHEMA_DENIED")
    if message.get("schema_version")!=1 or message.get("type") not in _TYPES:
        raise ValueError("BRIDGE_NODE_FRAME_TYPE_DENIED")
    rid=message.get("request_id")
    if not isinstance(rid,str) or not _ID.fullmatch(rid):
        raise ValueError("BRIDGE_NODE_REQUEST_ID_INVALID")
    args=message.get("arguments")
    if not isinstance(args,dict):raise ValueError("BRIDGE_NODE_ARGUMENTS_INVALID")
    fields={
        "node_relay_enqueue":{"delivery_id","sender_node","sender_key","receiver_node","receiver_key","original_sha","text"},
        "node_relay_claim":{"delivery_id","receiver_node","receiver_key"},
        "node_relay_ack":{"delivery_id","receiver_node","receiver_key","ack_id"},
        "node_relay_reply":{"delivery_id","receiver_node","receiver_key","ack_id","text","response_sha"},
        "node_relay_inspect":{"delivery_id","sender_node","sender_key"},
    }
    if set(args)!=fields[message["type"]]:raise ValueError("BRIDGE_NODE_FIELDS_DENIED")
    return rid,message["type"],args


def respond(store, message):
    rid = message.get("request_id") if isinstance(message,dict) else None
    try:
        rid,typ,args=validate(message)
        if typ=="node_relay_enqueue":receipt=store.enqueue(args)
        elif typ=="node_relay_claim":receipt=store.claim(**args)
        elif typ=="node_relay_ack":receipt=store.acknowledge(**args)
        elif typ=="node_relay_reply":receipt=store.reply(**args)
        elif typ=="node_relay_inspect":receipt=store.inspect(**args)
        else:raise ValueError("BRIDGE_NODE_TYPE_DENIED")
        return {"request_id":rid,"ok":True,"outcome":"APPLIED","receipt":receipt,
                "effect":"MAILBOX_ONLY","chatgpt_submitted":False}
    except ValueError as exc:
        return {"request_id":rid,"ok":False,"outcome":"NOT_APPLIED",
                "error":str(exc)[:100]}
    except Exception:
        # Lost durable-write result is ambiguous. Never auto replay.
        return {"request_id":rid,"ok":False,"outcome":"UNKNOWN",
                "error":"BRIDGE_NODE_STORE_UNKNOWN_NO_RETRY"}


def serve_node_session(first, inp, out, store):
    """Single persistent native-message session using an injected store."""
    message=first
    while message is not None:
        # Even if Chrome tries to switch protocol over the same port,
        # do not borrow the original BCT-read authority.
        write_frame(out, respond(store,message))
        message=read_frame(inp)
    return 0


def approved_store():
    """No default or plaintext fallback. Production remains disabled until staging."""
    if os.environ.get("BCT_BRIDGE_NODE_RELAY_ENABLED")!="1":
        raise ValueError("BRIDGE_NODE_RELAY_DISABLED")
    if os.name!="nt":
        raise ValueError("BRIDGE_NODE_RELAY_WINDOWS_ONLY")
    raw=os.environ.get("BCT_BRIDGE_NODE_MAILBOX_DB","")
    path=Path(raw)
    if not raw or not path.is_absolute() or path.suffix.lower()!=".sqlite3":
        raise ValueError("BRIDGE_NODE_MAILBOX_PATH_DENIED")
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError("BRIDGE_NODE_MAILBOX_PATH_DENIED")
    # This call is not an ACL attestation. Before enabling a production
    # mailbox, an independent staging process must verify the folder DACL.
    from node_relay_dpapi import DpapiMessageCodec
    return NodeRelayStore(path,DpapiMessageCodec())
