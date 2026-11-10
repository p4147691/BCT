"""Loop Recipe's isolated durable state machine.

This module intentionally performs no RCC sends, chat creation, or external effect.
The BCT Store supplies BEGIN IMMEDIATE transactional fencing and receipts.
"""
from __future__ import annotations
import hashlib
import re
import time

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class LoopStateError(ValueError):
    pass


class LoopStore:
    """State transitions for SINGLE_PERSISTENT, using the canonical BCT Store."""

    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS loop_recipe_runs(
                work_id TEXT PRIMARY KEY, direction_id TEXT NOT NULL,
                task_id TEXT NOT NULL, owner TEXT NOT NULL,
                epoch INTEGER NOT NULL, lease_until REAL NOT NULL,
                state TEXT NOT NULL, plan_text TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL, next_step INTEGER NOT NULL DEFAULT 0,
                operation_id TEXT, operation_state TEXT,
                last_error TEXT, updated_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS loop_recipe_events(
                work_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
                kind TEXT NOT NULL, epoch INTEGER NOT NULL,
                operation_id TEXT, created_at REAL NOT NULL,
                PRIMARY KEY(work_id,event_seq))""")

    @staticmethod
    def _ident(value):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise LoopStateError("LOOP_ID_INVALID")

    @staticmethod
    def _get(db, work_id):
        row = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
        return dict(row) if row else None

    def get(self, work_id):
        self._ident(work_id)
        with self.store._readonly() as db:
            return self._get(db, work_id)

    @staticmethod
    def _event(db, work_id, kind, epoch, operation_id=None, now=None):
        seq = db.execute(
            "SELECT COALESCE(MAX(event_seq),0)+1 FROM loop_recipe_events WHERE work_id=?",
            (work_id,),
        ).fetchone()[0]
        db.execute("INSERT INTO loop_recipe_events VALUES(?,?,?,?,?,?)",
                   (work_id, seq, kind, epoch, operation_id, time.time() if now is None else now))

    def start(self, *, work_id, direction_id, task_id, owner, plan_text, now=None):
        for item in (work_id, direction_id, task_id, owner):
            self._ident(item)
        if not isinstance(plan_text, str) or not plan_text.strip():
            raise LoopStateError("LOOP_PLAN_REQUIRED")
        now = time.time() if now is None else now
        digest = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
        # Canonical Work must exist. Never create a substitute Work here.
        self.store.get_work(work_id)
        with self.store.transaction() as db:
            prior = self._get(db, work_id)
            if prior:
                if (prior["direction_id"], prior["task_id"], prior["plan_sha256"]) != (
                    direction_id, task_id, digest
                ):
                    raise LoopStateError("LOOP_START_CONFLICT")
                return prior
            db.execute("""INSERT INTO loop_recipe_runs(
                work_id,direction_id,task_id,owner,epoch,lease_until,
                state,plan_text,plan_sha256,next_step,updated_at
            ) VALUES(?,?,?,?,1,?,'LOOP_STARTED',?,?,0,?)""",
                       (work_id,direction_id,task_id,owner,now+60,plan_text,digest,now))
            self._event(db,work_id,"STARTED",1,now=now)
            return self._get(db,work_id)

    def claim(self, *, work_id, owner, epoch, now=None):
        self._ident(owner)
        now = time.time() if now is None else now
        with self.store.transaction() as db:
            row = self._get(db,work_id)
            if not row:
                raise LoopStateError("LOOP_NOT_FOUND")
            if row["state"] == "COMPLETED":
                raise LoopStateError("LOOP_COMPLETED")
            if row["epoch"] != epoch:
                raise LoopStateError("LOOP_FENCED")
            # A successor may take over an expired lease even when an effect
            # is uncertain, but must reconcile that SAME Operation ID before
            # any new effect. Blocking the claim would deadlock recovery.
            if row["lease_until"] > now and row["owner"] != owner:
                raise LoopStateError("LOOP_LEASE_HELD")
            new_epoch = epoch + (row["owner"] != owner or row["lease_until"] <= now)
            db.execute("""UPDATE loop_recipe_runs SET owner=?,epoch=?,lease_until=?,
                updated_at=? WHERE work_id=? AND epoch=?""",
                (owner,new_epoch,now+60,now,work_id,epoch))
            if owner != row["owner"]:
                self._event(db,work_id,"SUCCESSOR_CLAIMED",new_epoch,now=now)
            return self._get(db,work_id)

    def prepare_operation(self, *, work_id, owner, epoch, operation_id, now=None):
        self._ident(operation_id)
        now = time.time() if now is None else now
        with self.store.transaction() as db:
            row=self._owned(db,work_id,owner,epoch,now)
            if row["operation_state"] in {"UNKNOWN","PREPARED"}:
                raise LoopStateError("LOOP_RECONCILE_REQUIRED")
            if row["operation_state"] == "APPLIED":
                raise LoopStateError("LOOP_STEP_PENDING_ADVANCE")
            if db.execute(
                "SELECT 1 FROM loop_recipe_events WHERE work_id=? AND operation_id=?",
                (work_id, operation_id),
            ).fetchone():
                raise LoopStateError("LOOP_OPERATION_ALREADY_USED")
            if row["state"] == "COMPLETED":
                raise LoopStateError("LOOP_COMPLETED")
            db.execute("""UPDATE loop_recipe_runs SET operation_id=?,
                operation_state='PREPARED',updated_at=? WHERE work_id=?""",
                (operation_id,now,work_id))
            self._event(db,work_id,"OPERATION_PREPARED",epoch,operation_id,now)
            return self._get(db,work_id)

    @staticmethod
    def _owned(db,work_id,owner,epoch,now):
        row=LoopStore._get(db,work_id)
        if not row or row["owner"] != owner or row["epoch"] != epoch:
            raise LoopStateError("LOOP_FENCED")
        if row["state"] == "COMPLETED":
            raise LoopStateError("LOOP_COMPLETED")
        if row["lease_until"] <= now:
            raise LoopStateError("LOOP_LEASE_EXPIRED")
        return row

    def reconcile(self, *, work_id, owner, epoch, operation_id, result, now=None):
        """Caller must supply the original externally verified operation receipt."""
        if result not in {"APPLIED","NOT_APPLIED","UNKNOWN"}:
            raise LoopStateError("LOOP_RECEIPT_INVALID")
        now=time.time() if now is None else now
        with self.store.transaction() as db:
            row=self._owned(db,work_id,owner,epoch,now)
            if row["operation_id"] != operation_id or row["operation_state"] not in {
                "PREPARED","UNKNOWN","APPLIED","NOT_APPLIED"
            }:
                raise LoopStateError("LOOP_RECEIPT_MISMATCH")
            if row["operation_state"] in {"APPLIED","NOT_APPLIED"}:
                if row["operation_state"] != result:
                    raise LoopStateError("LOOP_RECEIPT_CONFLICT")
                return row
            db.execute("UPDATE loop_recipe_runs SET operation_state=?,updated_at=? WHERE work_id=?",
                       (result,now,work_id))
            self._event(db,work_id,"OPERATION_RECONCILED",epoch,operation_id,now)
            return self._get(db,work_id)

    def reconcile_from_bct(self, *, work_id, owner, epoch, operation_id, principal_id, now=None):
        """Only canonical BCT operation receipts can settle an external effect."""
        try:
            receipt = self.store.get_operation_for(
                operation_id=operation_id, work_id=work_id, principal_id=principal_id
            )
        except KeyError as exc:
            raise LoopStateError("LOOP_RECEIPT_NOT_FOUND") from exc
        outcome = receipt.outcome.value if receipt.outcome is not None else "UNKNOWN"
        # A failed or incomplete operation can still have external effects.
        # Preserve uncertainty unless exact BCT evidence proves otherwise.
        if receipt.state.value != "FINISHED" or outcome not in {"APPLIED","NOT_APPLIED"}:
            outcome = "UNKNOWN"
        return self.reconcile(
            work_id=work_id, owner=owner, epoch=epoch,
            operation_id=operation_id, result=outcome, now=now,
        )

    def advance(self, *, work_id, owner, epoch, next_step, now=None):
        now=time.time() if now is None else now
        with self.store.transaction() as db:
            row=self._owned(db,work_id,owner,epoch,now)
            if row["operation_state"] != "APPLIED" or next_step != row["next_step"]+1:
                raise LoopStateError("LOOP_STEP_NOT_VERIFIED")
            db.execute("""UPDATE loop_recipe_runs SET next_step=?,operation_state=NULL,
                updated_at=? WHERE work_id=?""",(next_step,now,work_id))
            self._event(db,work_id,"STEP_ADVANCED",epoch,row["operation_id"],now)
            return self._get(db,work_id)

    def complete(self, *, work_id, owner, epoch, verified, now=None):
        now=time.time() if now is None else now
        with self.store.transaction() as db:
            row=self._owned(db,work_id,owner,epoch,now)
            if not verified or row["next_step"] < 1 or row["operation_state"] is not None:
                raise LoopStateError("LOOP_COMPLETION_UNVERIFIED")
            db.execute("UPDATE loop_recipe_runs SET state='COMPLETED',updated_at=? WHERE work_id=?",
                       (now,work_id))
            self._event(db,work_id,"COMPLETED",epoch,now=now)
            return self._get(db,work_id)
