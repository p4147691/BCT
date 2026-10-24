"""Worker Result Inbox independent of GitHub completion Inbox.

Read-only queries never ACK or dispatch. Explicit atomic decisions fence result
hashes. Caller must provide a verified Worker response captured by existing RCC.
"""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
import sqlite3
import time
from pathlib import Path

DECISIONS = {"DISPATCH", "DEFER", "COMPLETE", "NEED_INFO"}
def _json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

class WorkerResultInbox:
    def __init__(self, path: str | Path):
        self.path = str(path)

    @staticmethod
    def install(db):
        db.executescript("""
        CREATE TABLE IF NOT EXISTS worker_result_inbox (
            delivery_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, manager_uuid TEXT NOT NULL,
            worker_uuid TEXT NOT NULL, result_text TEXT NOT NULL, result_sha256 TEXT NOT NULL,
            result_utf16 INTEGER NOT NULL, capture_state TEXT NOT NULL,
            decision TEXT, decision_receipt_json TEXT, created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS worker_result_inbox_pending
          ON worker_result_inbox(manager_uuid,decision,delivery_id);
        """)
    def _open(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c
    def ingest(self, *, delivery_id, work_id, manager_uuid, worker_uuid, result_text,
               result_sha256, capture_state="VERIFIED"):
        if not all(isinstance(x,str) and x for x in (delivery_id,work_id,manager_uuid,worker_uuid,result_text)):
            raise ValueError("RESULT_INPUT_REQUIRED")
        if capture_state not in ("VERIFIED","UNKNOWN"):
            raise ValueError("RESULT_STATE_INVALID")
        digest=hashlib.sha256(result_text.encode("utf-8")).hexdigest()
        if digest!=result_sha256: raise ValueError("RESULT_HASH_MISMATCH")
        utf16=len(result_text.encode("utf-16-le"))//2
        with closing(self._open()) as db, db:
            self.install(db)
            db.execute("BEGIN IMMEDIATE")
            prior=db.execute("SELECT work_id,manager_uuid,worker_uuid,result_sha256 FROM worker_result_inbox WHERE delivery_id=?",(delivery_id,)).fetchone()
            if prior:
                if tuple(prior)!= (work_id,manager_uuid,worker_uuid,digest):raise ValueError("DELIVERY_REUSE_CONFLICT")
                return "DUPLICATE"
            db.execute("INSERT INTO worker_result_inbox VALUES(?,?,?,?,?,?,?,?,NULL,NULL,?)",
                       (delivery_id,work_id,manager_uuid,worker_uuid,result_text,digest,utf16,capture_state,time.time()))
            return "STORED"
    def pending(self, *, manager_uuid: str, after: str = "", limit: int = 100):
        if not 1<=limit<=500:raise ValueError("PAGE_LIMIT_INVALID")
        with closing(self._open()) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute("""SELECT * FROM worker_result_inbox WHERE manager_uuid=?
                AND decision IS NULL AND delivery_id>? ORDER BY delivery_id LIMIT ?""",
                (manager_uuid,after,limit)).fetchall()
            return [dict(x) for x in rows]
    def pending_all(self, *, manager_uuid: str, limit: int = 100):
        result=[];after=""
        while True:
            rows=self.pending(manager_uuid=manager_uuid,after=after,limit=limit)
            if not rows:break
            result.extend(rows);after=rows[-1]["delivery_id"]
        return result
    def decide(self, *, delivery_id, manager_uuid, decision, receipt_id, reason, observed_sha):
        if decision not in DECISIONS or not receipt_id or not reason:
            raise ValueError("DECISION_REQUIRED")
        with closing(self._open()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM worker_result_inbox WHERE delivery_id=? AND manager_uuid=?",(delivery_id,manager_uuid)).fetchone()
            if not row:raise ValueError("RESULT_NOT_FOUND")
            if row["result_sha256"] != observed_sha:raise ValueError("RESULT_CHANGED")
            receipt={"receipt_id":receipt_id,"decision":decision,"reason":reason,
                     "delivery_id":delivery_id,"result_sha256":observed_sha}
            raw=_json(receipt)
            if row["decision_receipt_json"]:
                if row["decision_receipt_json"] !=raw:raise ValueError("DECISION_CONFLICT")
                return "DUPLICATE"
            db.execute("UPDATE worker_result_inbox SET decision=?,decision_receipt_json=? WHERE delivery_id=?",
                       (decision,raw,delivery_id))
            return "DECIDED"
    def coalesced_wake(self, manager_uuid):
        items=self.pending_all(manager_uuid=manager_uuid)
        return {"wake_needed":bool(items),"pending_count":len(items),
                "delivery_ids":[x["delivery_id"] for x in items],"effect":"NONE"}
