"""Read-only BCT succession package with a separate atomic successor claim receipt.

No dispatch, wake, resend, deployment or resource_claim writes.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any
from .recovery_card import serialize_card

def _rows(db: sqlite3.Connection, statement: str, params: tuple = ()) -> list[dict]:
    return [dict(v) for v in db.execute(statement, params)]

def collect_succession(store_path: str | Path, predecessor_work_id: str,
                       cards: list[dict], manifest: dict) -> dict[str, Any]:
    """Live state is read with SQLite mode=ro; receipt state never implies permission."""
    con = sqlite3.connect(Path(store_path).resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        work = _rows(con,"SELECT work_id,state,request_summary FROM works WHERE work_id=?",(predecessor_work_id,))
        if not work: raise ValueError("PREDECESSOR_WORK_NOT_FOUND")
        operations = _rows(con,"SELECT operation_id,work_id,capability,state,outcome FROM operations WHERE work_id=? ORDER BY operation_id",(predecessor_work_id,))
        columns = {r[1] for r in con.execute("PRAGMA table_info(github_run_inbox)")}
        if "github_run_inbox" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            inbox = []; inbox_unknown=["GITHUB_INBOX_TABLE_UNAVAILABLE"]
        else:
            # Use the preinstalled durable Inbox schema without guessing column names.
            recipients = {r[1] for r in con.execute("PRAGMA table_info(github_run_inbox_recipients)")}
            if {"subscription_id","work_id"}.issubset(recipients):
                inbox = _rows(con, "SELECT i.* FROM github_run_inbox i JOIN github_run_inbox_recipients r ON r.subscription_id=i.subscription_id WHERE r.work_id=? ORDER BY i.subscription_id",(predecessor_work_id,))
                inbox_unknown = []
            else: inbox=[];inbox_unknown=["INBOX_RECIPIENT_SCHEMA_UNKNOWN"]
        sessions = _rows(con,"SELECT session_id,state,work_id FROM process_sessions WHERE work_id=?",(predecessor_work_id,)) if "process_sessions" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} else []
    finally: con.close()
    sorted_cards = sorted(cards,key=lambda c: c["card_sha256"])
    tasks=[]
    for card in sorted_cards:
        state=card.get("task_state","UNKNOWN")
        if state=="COMPLETE":
            next_step="PRESERVE_VERIFIED_RESULT"
        elif state in ("UNKNOWN","IN_PROGRESS"):
            next_step="READ_ONLY_STATUS_RECONCILIATION_NO_RESEND"
        else: next_step="SUPERVISOR_REVIEW"
        tasks.append({"card_sha256":card["card_sha256"],"state":state,"next_minimal_step":next_step,
                      "result_sha256":card.get("result_sha256") if state=="COMPLETE" else None})
    body={"schema":"BCT_SUCCESSION_PACKAGE_V1","predecessor_work":work[0],
          "predecessor_chain":[card["predecessor_identity"] for card in sorted_cards],
          "operations":operations,"inbox_receipts":inbox,"process_sessions":sessions,
          "cards":tasks,"capability_manifest":manifest,
          "verified_facts":{"work_receipt":True,"operation_count":len(operations),"inbox_count":len(inbox)},
          "UNKNOWN":inbox_unknown+[t["card_sha256"] for t in tasks if t["state"] in ("UNKNOWN","IN_PROGRESS")],
          "next_minimal_step":"RECONCILE_UNCERTAIN_TASKS" if any(t["state"]!="COMPLETE" for t in tasks) else "REVIEW_COMPLETION",
          "effect":"NONE_READ_ONLY"}
    body["package_sha256"]=hashlib.sha256(serialize_card(body)).hexdigest()
    return body

class SuccessorLedger:
    """Separate persisted SQLite intent/ACK records; never locks Work or Claim."""
    def __init__(self,path: str | Path):
        self.path=str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS successor_assignments
                      (package_sha TEXT PRIMARY KEY, successor_id TEXT NOT NULL,
                       status TEXT NOT NULL, package_json TEXT NOT NULL,
                       ack_json TEXT, created_at REAL NOT NULL)""")
    def assign(self,package:dict, successor_id:str)->dict:
        if not successor_id:raise ValueError("SUCCESSOR_REQUIRED")
        digest=package["package_sha256"]
        payload=serialize_card(package).decode("utf-8")
        with closing(sqlite3.connect(self.path,timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT successor_id,status FROM successor_assignments WHERE package_sha=?",(digest,)).fetchone()
            if row:
                return {"state":"DUPLICATE" if row[0]==successor_id else "CONFLICT_OTHER_SUCCESSOR",
                        "successor_id":row[0],"package_sha256":digest}
            db.execute("INSERT INTO successor_assignments VALUES(?,?,?,?,?,?)",
                       (digest,successor_id,"ASSIGNED_PREPARED",payload,None,time.time()))
        return {"state":"ASSIGNED_PREPARED","successor_id":successor_id,"package_sha256":digest}
    def acknowledge(self,package:dict,successor_id:str)->dict:
        ack={"schema":"BCT_SUCCESSOR_ACK_V1","package_sha256":package["package_sha256"],
             "successor_id":successor_id,"predecessor_chain":package["predecessor_chain"],
             "verified_facts":package["verified_facts"],"UNKNOWN":package["UNKNOWN"],
             "next_minimal_step":package["next_minimal_step"],"effect":"NONE_NO_DISPATCH"}
        raw=serialize_card(ack).decode("utf-8")
        with closing(sqlite3.connect(self.path,timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT successor_id,ack_json FROM successor_assignments WHERE package_sha=?",(package["package_sha256"],)).fetchone()
            if not row or row[0]!=successor_id:raise ValueError("SUCCESSOR_ASSIGNMENT_MISMATCH")
            if row[1] and row[1]!=raw:raise ValueError("ACK_IMMUTABLE")
            db.execute("UPDATE successor_assignments SET status='ACKED',ack_json=? WHERE package_sha=?",(raw,package["package_sha256"]))
        return ack
