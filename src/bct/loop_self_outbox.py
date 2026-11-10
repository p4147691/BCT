"""Durable, fail-closed SELF wake outbox for BCT Loop Recipe.

The outbox owns an intent, not a browser route. Dispatch can occur only through
an exact RCC identity and the existing BCT Operation ledger. A crash after
reservation leaves UNCERTAIN; no automatic second send is permitted.
"""
from __future__ import annotations

import hashlib
import re
import time

from bct.loop_store import LoopStateError

_UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


class LoopSelfOutbox:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS loop_recipe_self_outbox(
                work_id TEXT NOT NULL, epoch INTEGER NOT NULL, step INTEGER NOT NULL,
                conversation_key TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
                message_text TEXT NOT NULL, message_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(work_id,epoch,step))""")

    @staticmethod
    def _get(db, work_id, epoch, step):
        row = db.execute(
            "SELECT * FROM loop_recipe_self_outbox WHERE work_id=? AND epoch=? AND step=?",
            (work_id,epoch,step)
        ).fetchone()
        return dict(row) if row else None

    def get(self, *, work_id, epoch, step):
        with self.store._readonly() as db:
            return self._get(db,work_id,epoch,step)

    def queue(self, *, work_id, epoch, step, owner, message, now=None):
        """Idempotently declare one SELF wake for a verified current loop step."""
        if not _UUID.fullmatch(str(owner)):
            raise LoopStateError("LOOP_OWNER_UUID_REQUIRED")
        if not isinstance(message,str) or not message.strip() or len(message)>12000:
            raise LoopStateError("LOOP_SELF_MESSAGE_INVALID")
        now=time.time() if now is None else now
        digest=hashlib.sha256(message.encode("utf-8")).hexdigest()
        operation_id="loop-self-"+hashlib.sha256(
            f"{work_id}:{epoch}:{step}".encode("utf-8")
        ).hexdigest()[:24]
        with self.store.transaction() as db:
            loop=db.execute(
                "SELECT * FROM loop_recipe_runs WHERE work_id=?",(work_id,)
            ).fetchone()
            if (not loop or loop["state"]!="LOOP_STARTED"
                    or loop["owner"]!=owner or loop["epoch"]!=epoch
                    or loop["lease_until"]<=now or loop["next_step"]!=step
                    or loop["operation_state"] in ("PREPARED","UNKNOWN","APPLIED")):
                raise LoopStateError("LOOP_SELF_UNSAFE_STATE")
            prior=self._get(db,work_id,epoch,step)
            # A previous epoch's send can still have taken effect even after
            # node replacement. Never create a second wake until reconciled.
            previous=db.execute(
                """SELECT operation_id FROM loop_recipe_self_outbox
                WHERE work_id=? AND (epoch!=? OR step!=?)
                AND state IN ('PENDING','UNCERTAIN','UNKNOWN','DELIVERED')
                LIMIT 1""",(work_id,epoch,step)
            ).fetchone()
            if previous:
                raise LoopStateError("LOOP_SELF_PRIOR_EFFECT_UNRESOLVED")
            if prior:
                if prior["message_sha256"]!=digest or prior["conversation_key"]!=owner:
                    raise LoopStateError("LOOP_SELF_CONFLICT")
                return prior
            db.execute("""INSERT INTO loop_recipe_self_outbox VALUES
                (?,?,?,?,?,?,?,'PENDING',?,?)""",
                (work_id,epoch,step,owner,operation_id,message,digest,now,now))
            return self._get(db,work_id,epoch,step)

    def reserve(self, *, work_id, epoch, step, owner, now=None):
        """Persist an intent before external delivery; claim only once."""
        now=time.time() if now is None else now
        with self.store.transaction() as db:
            loop=db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?",(work_id,)).fetchone()
            if (not loop or loop["owner"]!=owner or loop["epoch"]!=epoch
                    or loop["lease_until"]<=now or loop["state"]!="LOOP_STARTED"
                    or loop["operation_state"] in ("PREPARED","UNKNOWN","APPLIED")):
                raise LoopStateError("LOOP_FENCED")
            row=self._get(db,work_id,epoch,step)
            if not row or row["conversation_key"]!=owner:
                raise LoopStateError("LOOP_SELF_NOT_FOUND")
            if row["state"]!="PENDING":
                raise LoopStateError("LOOP_SELF_ALREADY_DISPATCHED")
            db.execute("""UPDATE loop_recipe_self_outbox SET
                state='UNCERTAIN',updated_at=? WHERE work_id=? AND epoch=? AND step=?""",
                (now,work_id,epoch,step))
            return self._get(db,work_id,epoch,step)

    def reconcile(self, *, work_id, epoch, step, principal_id, now=None):
        """Only the original BCT Operation receipt can settle a wake."""
        now=time.time() if now is None else now
        with self.store._readonly() as db:
            row=self._get(db,work_id,epoch,step)
        if not row or row["state"] not in {"UNCERTAIN","UNKNOWN","DELIVERED","NOT_APPLIED"}:
            raise LoopStateError("LOOP_SELF_RECONCILE_NOT_READY")
        try:
            receipt=self.store.get_operation_for(
                operation_id=row["operation_id"],work_id=work_id,
                principal_id=principal_id,
            )
        except KeyError:
            outcome="UNKNOWN"
        else:
            state=receipt.state.value
            result=receipt.outcome.value if receipt.outcome is not None else "UNKNOWN"
            outcome=result if state=="FINISHED" and result in {"APPLIED","NOT_APPLIED"} else "UNKNOWN"
        new_state={"APPLIED":"DELIVERED","NOT_APPLIED":"NOT_APPLIED",
                   "UNKNOWN":"UNKNOWN"}[outcome]
        with self.store.transaction() as db:
            current=self._get(db,work_id,epoch,step)
            if current["state"] in {"DELIVERED","NOT_APPLIED"} and current["state"]!=new_state:
                raise LoopStateError("LOOP_SELF_RECEIPT_CONFLICT")
            db.execute("""UPDATE loop_recipe_self_outbox SET state=?,updated_at=?
                WHERE work_id=? AND epoch=? AND step=?""",
                (new_state,now,work_id,epoch,step))
            return self._get(db,work_id,epoch,step)

    def list_delivered(self, *, limit=8):
        if not isinstance(limit,int) or not 1 <= limit <= 32:
            raise LoopStateError("LOOP_SELF_LIMIT_INVALID")
        with self.store._readonly() as db:
            return [dict(x) for x in db.execute(
                """SELECT o.* FROM loop_recipe_self_outbox o
                JOIN loop_recipe_runs l ON l.work_id=o.work_id
                WHERE o.state='DELIVERED' AND l.state='LOOP_STARTED'
                ORDER BY o.updated_at,o.work_id LIMIT ?""",
                (limit,),
            ).fetchall()]

    def record_terminal_response(self, *, work_id, epoch, step, owner,
                                 response_turn_key, response_sha256,
                                 next_message=None, now=None):
        """Atomically ACK a proven terminal reply and queue the NEXT SELF step.

        The caller must verify the exact RCC message-source digest before
        passing it here. The previous send cannot be replayed.
        """
        now=time.time() if now is None else now
        if (not response_turn_key or not re.fullmatch(r"[a-f0-9]{64}", response_sha256)
                or (next_message is not None and
                    (not isinstance(next_message,str) or not next_message.strip()
                     or len(next_message)>12000))):
            raise LoopStateError("LOOP_RESPONSE_PROOF_INVALID")
        with self.store.transaction() as db:
            prior=self._get(db,work_id,epoch,step)
            if not prior or prior["conversation_key"]!=owner or prior["state"]!="DELIVERED":
                raise LoopStateError("LOOP_RESPONSE_RECEIPT_REQUIRED")
            loop=db.execute(
                "SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)
            ).fetchone()
            if (not loop or loop["owner"]!=owner or loop["epoch"]<epoch
                    or loop["lease_until"]<=now):
                raise LoopStateError("LOOP_FENCED")
            if next_message is not None and (
                    loop["state"]!="LOOP_STARTED" or loop["next_step"]<=step
                    or loop["operation_state"] is not None):
                raise LoopStateError("LOOP_NEXT_STEP_NOT_CONFIRMED")
            db.execute("""CREATE TABLE IF NOT EXISTS loop_recipe_self_responses(
                work_id TEXT NOT NULL, epoch INTEGER NOT NULL, step INTEGER NOT NULL,
                response_turn_key TEXT NOT NULL, response_sha256 TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(work_id,epoch,step),
                UNIQUE(work_id,response_turn_key))""")
            db.execute("""INSERT INTO loop_recipe_self_responses VALUES(?,?,?,?,?,?)""",
                       (work_id,epoch,step,response_turn_key,response_sha256,now))
            db.execute("""UPDATE loop_recipe_self_outbox SET state='ACKED',
                updated_at=? WHERE work_id=? AND epoch=? AND step=?""",
                (now,work_id,epoch,step))
            queued=None
            if next_message is not None:
                next_step=loop["next_step"]
                active_epoch=loop["epoch"]
                op="loop-self-"+hashlib.sha256(
                    f"{work_id}:{active_epoch}:{next_step}".encode("utf-8")
                ).hexdigest()[:24]
                digest=hashlib.sha256(next_message.encode("utf-8")).hexdigest()
                # The prior ACK + next wake must commit as one unit.
                db.execute("""INSERT INTO loop_recipe_self_outbox VALUES
                    (?,?,?,?,?,?,?,'PENDING',?,?)""",
                    (work_id,active_epoch,next_step,owner,op,next_message,digest,now,now))
                queued=self._get(db,work_id,active_epoch,next_step)
            return {"acknowledged":True,"queued":queued}

    def list_pending(self, *, limit=8):
        """Exact unsent intents only; Core still rechecks all fences."""
        if not isinstance(limit,int) or not 1 <= limit <= 32:
            raise LoopStateError("LOOP_SELF_LIMIT_INVALID")
        with self.store._readonly() as db:
            return [dict(x) for x in db.execute(
                """SELECT * FROM loop_recipe_self_outbox
                WHERE state='PENDING' ORDER BY created_at,work_id LIMIT ?""",
                (limit,),
            ).fetchall()]

    def list_uncertain(self, *, limit=32):
        if not isinstance(limit,int) or not 1<=limit<=128:
            raise LoopStateError("LOOP_SELF_LIMIT_INVALID")
        with self.store._readonly() as db:
            return [dict(x) for x in db.execute(
                """SELECT * FROM loop_recipe_self_outbox
                WHERE state IN ('UNCERTAIN','UNKNOWN')
                ORDER BY updated_at,work_id LIMIT ?""",(limit,)
            ).fetchall()]
