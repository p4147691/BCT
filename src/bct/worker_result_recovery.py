"""Optional Core recovery tick: durable, no-send Manager return planning.

Reads the existing WorkerResultInbox SQLite file. Does not call RCC/Chrome.
The caller supplies independently authenticated manager bindings and busy state.
"""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
import sqlite3
from .worker_result_inbox import WorkerResultInbox

def _canonical(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))

class WorkerResultRecovery:
    def __init__(self, inbox: WorkerResultInbox):
        self.inbox=inbox

    @staticmethod
    def install(db):
        db.execute("""CREATE TABLE IF NOT EXISTS worker_result_return_plans (
          manager_uuid TEXT PRIMARY KEY, manager_epoch INTEGER NOT NULL,
          plan_id TEXT NOT NULL UNIQUE, delivery_ids_json TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state='PLANNED_NO_SEND'))""")

    def run_once(self, *, manager_uuid: str, manager_epoch: int, idle: bool,
                 bindings: dict[str,dict], fake_dispatch=None) -> dict:
        if not manager_uuid or type(manager_epoch) is not int or manager_epoch < 1:
            raise ValueError("MANAGER_BINDING_INVALID")
        items=self.inbox.pending_all(manager_uuid=manager_uuid)
        if not items:
            return {"state":"EMPTY","effect":"NONE","count":0}
        if not idle:
            return {"state":"BUSY_QUEUED","effect":"NONE","count":len(items)}
        # Strictly fail-closed before preparing anything: no partial batch.
        for item in items:
            binding=bindings.get(item["delivery_id"])
            if not isinstance(binding,dict) or binding.get("manager_uuid")!=manager_uuid or binding.get("worker_uuid")!=item["worker_uuid"] or binding.get("work_id")!=item["work_id"] or binding.get("manager_epoch")!=manager_epoch or binding.get("delivery_id")!=item["delivery_id"]:
                return {"state":"ESCALATE_BINDING_MISMATCH","effect":"NONE","count":len(items)}
            if item["capture_state"]!="VERIFIED":
                return {"state":"ESCALATE_UNKNOWN","effect":"NONE","count":len(items)}
            if hashlib.sha256(item["result_text"].encode("utf-8")).hexdigest()!=item["result_sha256"]:
                return {"state":"ESCALATE_HASH_MISMATCH","effect":"NONE","count":len(items)}
        ids=[x["delivery_id"] for x in items]
        plan_id=hashlib.sha256(_canonical([manager_uuid,manager_epoch,[(i["delivery_id"],i["result_sha256"]) for i in items]]).encode("utf-8")).hexdigest()
        with closing(self.inbox._open()) as db, db:
            self.install(db)
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT manager_epoch,plan_id FROM worker_result_return_plans WHERE manager_uuid=?",(manager_uuid,)).fetchone()
            if old:
                return {"state":"ALREADY_PLANNED" if old["manager_epoch"]==manager_epoch and old["plan_id"]==plan_id else "ESCALATE_EXISTING_PLAN",
                        "effect":"NONE","count":len(items)}
            db.execute("INSERT INTO worker_result_return_plans VALUES(?,?,?,?,?)",
                       (manager_uuid,manager_epoch,plan_id,_canonical(ids),"PLANNED_NO_SEND"))
        # Dispatch is test-only: it receives metadata, never response text.
        plan={"manager_uuid":manager_uuid,"manager_epoch":manager_epoch,"plan_id":plan_id,
              "delivery_ids":ids,"signal":"RESULTS_PENDING","effect":"NONE_NO_SEND"}
        if fake_dispatch is not None:
            fake_dispatch(plan)
        return {"state":"PLANNED_NO_SEND","effect":"NONE_NO_SEND","count":len(items),"plan":plan}
