"""PR3a internal-only capability adapters; Core remains the authority."""
import hashlib
import json
from .models import ConflictError
from .orchestration import _digest, _canonical
from .durable_pr2 import (reserve_delivery, record_attempt, acknowledge_delivery, recovery_snapshot)

def install_schema(store):
    with store.transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_completion_v1 (
            event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
            generation INTEGER NOT NULL, source_node_id TEXT NOT NULL, result_id TEXT NOT NULL,
            result_digest TEXT NOT NULL, event_digest TEXT NOT NULL)""")

def _source(db, session_id, assignment_id, generation, source_node_id, result_id, result_digest):
    row=db.execute("SELECT * FROM orchestration_mailbox WHERE message_id=?",(result_id,)).fetchone()
    att=db.execute("""SELECT worker_node_id FROM orchestration_assignment_attempts
       WHERE assignment_id=? AND generation=? AND worker_node_id=?""",
       (assignment_id,generation,source_node_id)).fetchone()
    assignment=db.execute("SELECT session_id,current_generation FROM orchestration_assignments WHERE assignment_id=?",
                          (assignment_id,)).fetchone()
    if not row or not att or not assignment or assignment["session_id"]!=session_id or assignment["current_generation"]!=generation:
        raise ConflictError("SOURCE_FENCED")
    if (row["session_id"],row["assignment_id"],row["assignment_generation"],row["sender_node_id"],row["kind"]) != (
           session_id,assignment_id,generation,source_node_id,"RESULT"):
        raise ConflictError("SOURCE_PROVENANCE_MISMATCH")
    try: recomputed=_digest(json.loads(row["payload_json"]))
    except (ValueError,TypeError): raise ConflictError("SOURCE_PAYLOAD_INVALID")
    if recomputed!=row["message_digest"] or recomputed!=result_digest:
        raise ConflictError("SOURCE_DIGEST_MISMATCH")
    return row

def completion_report(store, *, event_id, session_id, assignment_id, generation,
                      source_node_id, result_id, result_digest):
    for v in (event_id,session_id,assignment_id,source_node_id,result_id,result_digest):
        if not isinstance(v,str) or not v or len(v)>256: raise ValueError("INVALID_ID")
    if type(generation) is not int or generation<1: raise ValueError("INVALID_GENERATION")
    identity=[session_id,assignment_id,generation,source_node_id,result_id,result_digest]
    event_digest=_digest(identity)
    with store.transaction() as db:
        _source(db,*identity)
        old=db.execute("SELECT event_digest FROM bridge_completion_v1 WHERE event_id=?",(event_id,)).fetchone()
        if old:
            if old["event_digest"]!=event_digest:raise ConflictError("EVENT_ID_CONFLICT")
            return {"event_id":event_id,"duplicate":True}
        db.execute("INSERT INTO bridge_completion_v1 VALUES(?,?,?,?,?,?,?,?)",
                   (event_id,*identity,event_digest))
        return {"event_id":event_id,"duplicate":False}

def result_get(store, *, event_id):
    db=store._connect()
    try:
        row=db.execute("SELECT * FROM bridge_completion_v1 WHERE event_id=?",(event_id,)).fetchone()
        if row is None:raise KeyError("COMPLETION_NOT_FOUND")
        identity=[row[k] for k in ("session_id","assignment_id","generation","source_node_id","result_id","result_digest")]
        if row["event_digest"]!=_digest(identity): raise ConflictError("EVENT_DIGEST_MISMATCH")
        result=_source(db,*identity)
        return {"event_id":event_id,"source_node_id":row["source_node_id"],
                "result_id":row["result_id"],"digest":row["result_digest"],
                "payload":json.loads(result["payload_json"])}
    finally:db.close()

def delivery_request(store, *, delivery_id, session_id, target_node_id, attachment_id,
                     attachment_generation, assignment_id, assignment_generation):
    db=store._connect()
    try:
        row=db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=? AND session_id=?",
                       (delivery_id,session_id)).fetchone()
        if row is None or tuple(row[k] for k in ("target_node_id","attachment_id","attachment_generation",
                                                 "assignment_id","assignment_generation")) != (
                         target_node_id,attachment_id,attachment_generation,assignment_id,assignment_generation):
            raise ConflictError("DELIVERY_IDENTITY_MISMATCH")
        attachment=db.execute("SELECT active,node_id FROM orchestration_attachments WHERE attachment_id=? AND generation=?",
                              (attachment_id,attachment_generation)).fetchone()
        assignment=db.execute("SELECT session_id,current_generation FROM orchestration_assignments WHERE assignment_id=?",
                              (assignment_id,)).fetchone()
        if (not attachment or not attachment["active"] or attachment["node_id"]!=target_node_id
            or not assignment or assignment["session_id"]!=session_id
            or assignment["current_generation"]!=assignment_generation):
            raise ConflictError("TARGET_FENCED")
        return {"delivery_id":delivery_id,"state":row["state"],"payload":json.loads(row["payload_json"])}
    finally:db.close()

def delivery_receipt_get(store, *, session_id, delivery_id):
    return next((r for r in recovery_snapshot(store,session_id=session_id)["deliveries"]
                 if r["delivery_id"]==delivery_id),None)

def fake_send(store, *, delivery_id, epoch, token, transport, now):
    reservation=reserve_delivery(store,delivery_id=delivery_id,epoch=epoch,token=token,now=now)
    key=reservation["reservation_token"]
    if not transport.ready:
        record_attempt(store,delivery_id=delivery_id,epoch=epoch,token=token,reservation_token=key,phase="PRE_SEND_ABORT",now=now)
        return "PRE_SEND_ABORT"
    record_attempt(store,delivery_id=delivery_id,epoch=epoch,token=token,reservation_token=key,phase="SEND_STARTED",now=now)
    try: sent=transport.send(delivery_id,reservation["target_node_id"])
    except Exception: sent=False
    record_attempt(store,delivery_id=delivery_id,epoch=epoch,token=token,reservation_token=key,
                   phase="DELIVERED" if sent else "UNKNOWN",now=now)
    return "SENT" if sent else "UNKNOWN"

def recipient_ack(store, *, delivery_id, command_id, target_node_id, attachment_id,
                  attachment_generation, assignment_id, assignment_generation,
                  payload_digest, ack_digest, recipient_proof, epoch, token, now):
    """Internal fake recipient only. Proof is an explicit validated test-scoped grant, NOT browser authentication."""
    with store.transaction() as db:
        row=db.execute("SELECT * FROM orchestration_dispatch_outbox WHERE delivery_id=?",(delivery_id,)).fetchone()
        if not row or tuple(row[k] for k in ("target_node_id","attachment_id","attachment_generation",
                                             "assignment_id","assignment_generation")) != (
                 target_node_id,attachment_id,attachment_generation,assignment_id,assignment_generation):
            raise ConflictError("ACK_IDENTITY_MISMATCH")
        attachment=db.execute("SELECT active,node_id FROM orchestration_attachments WHERE attachment_id=? AND generation=?",
                              (attachment_id,attachment_generation)).fetchone()
        assignment=db.execute("SELECT session_id,current_generation FROM orchestration_assignments WHERE assignment_id=?",
                              (assignment_id,)).fetchone()
        if not attachment or not attachment["active"] or attachment["node_id"]!=target_node_id or not assignment or assignment["session_id"]!=row["session_id"] or assignment["current_generation"]!=assignment_generation:
            raise ConflictError("ACK_TARGET_FENCED")
        if (not isinstance(recipient_proof,dict) or recipient_proof.get("recipient_node_id")!=target_node_id
            or recipient_proof.get("attachment_id")!=attachment_id or recipient_proof.get("generation")!=attachment_generation
            or recipient_proof.get("processed_command_id")!=command_id
            or recipient_proof.get("ack_digest")!=ack_digest
            or recipient_proof.get("verified_by")!="isolated_fake_transport"):
            raise ConflictError("RECIPIENT_PROOF_DENIED")
        digest=hashlib.sha256(row["payload_json"].encode()).hexdigest()
        if digest!=payload_digest or hashlib.sha256((delivery_id+":"+digest).encode()).hexdigest()!=command_id:
            raise ConflictError("COMMAND_MISMATCH")
        changed=acknowledge_delivery(store,delivery_id=delivery_id,target_node_id=target_node_id,
          attachment_id=attachment_id,attachment_generation=attachment_generation,
          ack_digest=ack_digest,epoch=epoch,token=token,now=now,_db=db)
    return {"command_id":command_id,"duplicate":not changed}
