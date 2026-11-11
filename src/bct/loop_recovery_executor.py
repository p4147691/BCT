"""Automatic local recovery for a verified existing Loop owner.

Only BCT receipt reconciliation and SQLite state transitions occur here.
The caller must supply fresh, exact RCC liveness for the same conversation UUID.
No new chat, no message transmission, and no replay of unknown effects.
"""
from __future__ import annotations
import time

from bct.loop_recovery import LoopRecoveryScanner
from bct.loop_store import LoopStore, LoopStateError


class LoopRecoveryExecutor:
    def __init__(self, store, *, principal_id: str, owner_ready):
        self.store=store
        self.principal_id=principal_id
        self.owner_ready=owner_ready

    @staticmethod
    def resolve_single_work(store, *, principal_id: str) -> str:
        """Resolve no-ID manual recovery only when exactly one owned Loop exists."""
        with store._readonly() as db:
            exists=db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='loop_recipe_runs'"
            ).fetchone()
            if not exists:
                raise LoopStateError("LOOP_WORK_NOT_FOUND")
            matches=db.execute(
                """SELECT l.work_id FROM loop_recipe_runs l
                JOIN works w ON w.work_id=l.work_id
                WHERE l.state='LOOP_STARTED'
                AND w.owner_principal_id=? AND w.state='ACTIVE'
                ORDER BY l.updated_at DESC, l.work_id LIMIT 2""",
                (principal_id,),
            ).fetchall()
        if not matches:
            raise LoopStateError("LOOP_WORK_NOT_FOUND")
        if len(matches)!=1:
            raise LoopStateError("LOOP_WORK_AMBIGUOUS")
        return str(matches[0][0])

    def run_once(self, *, now=None, limit=8, work_id_filter=None):
        now=time.time() if now is None else now
        scanner=LoopRecoveryScanner(self.store)
        ledger=LoopStore(self.store)
        if work_id_filter is not None:
            current=ledger.get(work_id_filter)
            candidates=(
                [current] if current and current["state"]=="LOOP_STARTED"
                and current["lease_until"]<=now else []
            )
        else:
            candidates=scanner.scan(now=now,limit=limit)
        results=[]
        for current in candidates:
            work_id=current["work_id"]
            owner=current["owner"]
            if not self.owner_ready(owner):
                if current["operation_state"] in {"PREPARED", "UNKNOWN", "APPLIED"}:
                    try:
                        settled = ledger.recover_expired_operation(
                            work_id=work_id, owner=owner, epoch=current["epoch"],
                            operation_id=current["operation_id"],
                            principal_id=self.principal_id, now=now,
                        )
                    except (LoopStateError, KeyError) as exc:
                        results.append({"work_id": work_id, "status": "RECEIPT_CHECK_REQUIRED",
                                        "reason": str(exc)})
                        continue
                    status = ("STEP_CONFIRMED" if settled["operation_state"] is None
                              else "UNKNOWN_HOLD" if settled["operation_state"] == "UNKNOWN"
                              else "OWNER_UNAVAILABLE")
                    results.append({"work_id": work_id, "epoch": settled["epoch"],
                                    "status": status, "next_step": settled["next_step"]})
                    continue
                results.append({"work_id":work_id,"status":"OWNER_UNAVAILABLE"})
                continue
            try:
                resumed=ledger.claim(work_id=work_id,owner=owner,
                                     epoch=current["epoch"],now=now)
            except LoopStateError as exc:
                results.append({"work_id":work_id,"status":"CLAIM_BLOCKED",
                                "reason":str(exc)})
                continue
            epoch=resumed["epoch"]
            state=resumed["operation_state"]
            operation_id=resumed["operation_id"]
            if state in {"PREPARED","UNKNOWN"}:
                try:
                    resumed=ledger.reconcile_from_bct(
                        work_id=work_id,owner=owner,epoch=epoch,
                        operation_id=operation_id,principal_id=self.principal_id,
                        now=now,
                    )
                except (LoopStateError,KeyError) as exc:
                    results.append({"work_id":work_id,"epoch":epoch,
                                    "status":"RECEIPT_CHECK_REQUIRED",
                                    "reason":str(exc)})
                    continue
                state=resumed["operation_state"]
            if state=="APPLIED":
                try:
                    advanced=ledger.advance(
                        work_id=work_id,owner=owner,epoch=epoch,
                        next_step=resumed["next_step"]+1,now=now,
                    )
                except LoopStateError as exc:
                    results.append({"work_id":work_id,"epoch":epoch,
                                    "status":"ADVANCE_BLOCKED","reason":str(exc)})
                    continue
                results.append({"work_id":work_id,"epoch":epoch,
                                "status":"STEP_CONFIRMED","next_step":advanced["next_step"]})
            elif state in {"PREPARED","UNKNOWN"}:
                results.append({"work_id":work_id,"epoch":epoch,
                                "status":"UNKNOWN_HOLD","operation_id":operation_id})
            else:
                results.append({"work_id":work_id,"epoch":epoch,
                                "status":"READY_FOR_EXACT_SELF_ROUTE",
                                "next_step":resumed["next_step"]})
        return {"checked":len(candidates),"results":results,
                "external_effect":"NONE"}
