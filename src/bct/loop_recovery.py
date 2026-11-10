"""Bounded Loop Recipe recovery scan, fail-closed without RCC guessing."""
from __future__ import annotations
import time


class LoopRecoveryScanner:
    def __init__(self, store):
        self.store=store

    def scan(self, *, now=None, limit=32):
        now=time.time() if now is None else now
        if not isinstance(limit,int) or not (1 <= limit <= 128):
            raise ValueError("LOOP_SCAN_LIMIT_INVALID")
        with self.store._readonly() as db:
            # Existence-check keeps scan compatible with old DBs.
            exists=db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='loop_recipe_runs'"
            ).fetchone()
            if not exists:
                return []
            rows=db.execute("""SELECT work_id,direction_id,task_id,owner,epoch,
                lease_until,operation_id,operation_state,next_step FROM loop_recipe_runs
                WHERE state='LOOP_STARTED' AND lease_until <= ?
                ORDER BY lease_until,work_id LIMIT ?""",(now,limit)).fetchall()
        notices=[]
        for row in rows:
            item=dict(row)
            state=item["operation_state"]
            if state in {"PREPARED","UNKNOWN"}:
                action="RECONCILE_ORIGINAL_RECEIPT"
            elif state=="APPLIED":
                action="ADVANCE_CONFIRMED_STEP"
            else:
                action="RECHECK_NODE_THEN_RECOVER"
            notices.append({**item,"advisory_action":action,
                            "external_effect":"NONE_READ_ONLY"})
        return notices
