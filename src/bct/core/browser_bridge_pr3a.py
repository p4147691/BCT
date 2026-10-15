"""PR3-a isolated Browser Bridge boundary over PR1/PR2 durable contracts.

No Chrome / native host registration / live DB / transport calls.
"""
from __future__ import annotations
import hashlib
import json
from .models import ConflictError
from .durable_pr2 import reserve_delivery, record_attempt, acknowledge_delivery, recovery_snapshot

def _id(value):
    if not isinstance(value,str) or not value or len(value)>256:
        raise ValueError("INVALID_BRIDGE_ID")
    return value

def install_bridge_schema(store):
    """Additive tables; invoke only on explicitly provisioned isolated/test Store."""
    with store.transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS browser_bridge_completion (
            event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
            generation INTEGER NOT NULL, source_node_id TEXT NOT NULL, result_message_id TEXT NOT NULL,
            result_digest TEXT NOT NULL, event_digest TEXT NOT NULL)""")

def completion_report(store, *, event_id, session_id, assignment_id, generation,
                      source_node_id, result_message_id, result_digest):
    for v in (event_id,session_id,assignment_id,source_node_id,result_message_id,result_digest): _id(v)
    if type(generation) is not int or generation<1: raise ValueError("INVALID_GENERATION")
    payload=(session_id,assignment_id,generation,source_node_id,result_message_id,result_digest)
    digest=hashlib.sha256(json.dumps(payload,separators=(",",":")).encode()).hexdigest()
    with store.transaction() as db:
        result=db.execute("SELECT * FROM orchestration_mailbox WHERE message_id=?",(result_message_id,)).fetchone()
        attempt=db.execute("""SELECT worker_node_id FROM orchestration_assignment_attempts
            WHERE assignment_id=? AND generation=? AND worker_node_id=?""",
            (assignment_id,generation,source_node_id)).fetchone()
        if (result is None or attempt is None or result["kind"]!="RESULT"
            or result["session_id"]!=session_id or result["assignment_id"]!=assignment_id
            or result["assignment_generation"]!=generation or result["sender_node_id"]!=source_node_id
            or result["message_digest"]!=result_digest):
            raise ConflictError("COMPLETION_PROVENANCE_MISMATCH")
        old=db.execute("SELECT event_digest FROM browser_bridge_completion WHERE event_id=?",(event_id,)).fetchone()
        if old is not None:
            if old["event_digest"]!=digest: raise ConflictError("COMPLETION_EVENT_CONFLICT")
            return {"event_id":event_id,"duplicate":True,"result_message_id":result_message_id}
        db.execute("INSERT INTO browser_bridge_completion VALUES(?,?,?,?,?,?,?,?)",(event_id,*payload,digest))
        return {"event_id":event_id,"duplicate":False,"result_message_id":result_message_id}

def result_get(store, *, event_id):
    _id(event_id)
    db=store._connect()
    try:
        row=db.execute("""SELECT c.*,m.payload_json,m.message_digest FROM browser_bridge_completion c
          JOIN orchestration_mailbox m ON m.message_id=c.result_message_id WHERE c.event_id=?""",(event_id,)).fetchone()
        if row is None or row["message_digest"]!=row["result_digest"]:
            raise KeyError("RESULT_NOT_FOUND")
        return {"event_id":event_id,"result_message_id":row["result_message_id"],
                "source_node_id":row["source_node_id"],"session_id":row["session_id"],
                "assignment_id":row["assignment_id"],"generation":row["generation"],
                "result_digest":row["result_digest"],"body":json.loads(row["payload_json"])}
    finally: db.close()

def delivery_receipt_get(store, *, delivery_id, session_id):
    _id(delivery_id);_id(session_id)
    return next((x for x in recovery_snapshot(store,session_id=session_id)["deliveries"]
                 if x["delivery_id"]==delivery_id),None)

def delivery_request(store, *, delivery_id, session_id, target_node_id, attachment_id,
                     attachment_generation, assignment_id, assignment_generation):
    """Read-only authorization gate; immutable outbox created by PR2, never duplicated."""
    for v in (delivery_id,session_id,target_node_id,attachment_id,assignment_id): _id(v)
    db=store._connect()
    try:
        row=db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=? AND session_id=?",
                       (delivery_id,session_id)).fetchone()
        if row is None or tuple(row[k] for k in ("target_node_id","attachment_id","attachment_generation",
                       "assignment_id","assignment_generation")) != (
                       target_node_id,attachment_id,attachment_generation,assignment_id,assignment_generation):
            raise ConflictError("DELIVERY_IDENTITY_MISMATCH")
        att=db.execute("SELECT active,node_id FROM orchestration_attachments WHERE attachment_id=? AND generation=?",
                       (attachment_id,attachment_generation)).fetchone()
        if att is None or not att["active"] or att["node_id"]!=target_node_id:
            raise ConflictError("TARGET_FENCED")
        return {"delivery_id":delivery_id,"state":row["state"],"payload":json.loads(row["payload_json"])}
    finally:db.close()

def recipient_ack(store, *, delivery_id, command_id, target_node_id, attachment_id,
                  attachment_generation, payload_digest, ack_digest, epoch, token, now=None):
    """Command dedupe and PR2 ACK must commit together, including on duplicate."""
    for v in (delivery_id,command_id,target_node_id,attachment_id,payload_digest,ack_digest):_id(v)
    db=store._connect()
    try:
        row=db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=?",(delivery_id,)).fetchone()
        if row is None or (row["target_node_id"],row["attachment_id"],row["attachment_generation"]) != (
                target_node_id,attachment_id,attachment_generation):
            raise ConflictError("RECIPIENT_FENCED")
        actual=hashlib.sha256(row["payload_json"].encode()).hexdigest()
        if actual!=payload_digest:raise ConflictError("COMMAND_PAYLOAD_MISMATCH")
        expected_command=hashlib.sha256((delivery_id+":"+payload_digest).encode()).hexdigest()
        if command_id!=expected_command:raise ConflictError("COMMAND_ID_CONFLICT")
    finally:db.close()
    changed=acknowledge_delivery(store,delivery_id=delivery_id,target_node_id=target_node_id,
                 attachment_id=attachment_id,attachment_generation=attachment_generation,
                 ack_digest=ack_digest,epoch=epoch,token=token,now=now)
    return {"command_id":command_id,"duplicate":not changed,"ack_digest":ack_digest}


def fake_send(store, *, delivery_id, epoch, token, transport, now):
    """Delivery is not ACK. UNKNOWN is never auto-retried."""
    reservation=reserve_delivery(store,delivery_id=delivery_id,epoch=epoch,token=token,now=now)
    rid=reservation["reservation_token"]
    if not transport.ready:
        record_attempt(store,delivery_id=delivery_id,epoch=epoch,token=token,reservation_token=rid,
                       phase="PRE_SEND_ABORT",now=now)
        return "PRE_SEND_ABORT"
    record_attempt(store,delivery_id=delivery_id,epoch=epoch,token=token,reservation_token=rid,
                   phase="SEND_STARTED",now=now)
    try: delivered=transport.send(delivery_id,reservation["target_node_id"])
    except Exception:delivered=False
    record_attempt(store,delivery_id=delivery_id,epoch=epoch,token=token,reservation_token=rid,
                   phase="DELIVERED" if delivered else "UNKNOWN",now=now)
    return "SENT" if delivered else "UNKNOWN"
