"""Fail-closed Loop successor preparation using original BCT receipts.

This ledger does not create chats or send messages. It records exact bounded
external-operation intents and accepts only verified RCC identity/effect proofs.
It must never infer a new UUID or replay an uncertain creation/send.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
from bct.loop_store import LoopStore, LoopStateError
from bct.chain_worker_provision import _attachment
from bct.status_views import status_view

_UUID=re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")


class LoopSuccessorLedger:
    def __init__(self,store):
        self.store=store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS loop_successor_cases(
                work_id TEXT PRIMARY KEY, predecessor TEXT NOT NULL,
                predecessor_epoch INTEGER NOT NULL,
                create_op TEXT NOT NULL UNIQUE, send_op TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL, instance_id TEXT NOT NULL,
                window_id INTEGER NOT NULL, created_tab_id INTEGER,
                successor TEXT, response_turn_key TEXT,
                response_sha TEXT, updated_at REAL NOT NULL,
                handoff_text_sha TEXT)""")

            db.execute("""CREATE TABLE IF NOT EXISTS loop_successor_history(
                work_id TEXT NOT NULL, predecessor_epoch INTEGER NOT NULL,
                case_json TEXT NOT NULL, archived_at REAL NOT NULL,
                PRIMARY KEY(work_id, predecessor_epoch))""")

    def get(self,work_id):
        with self.store._readonly() as db:
            row=db.execute("SELECT * FROM loop_successor_cases WHERE work_id=?",
                           (work_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _unavailable(snapshot,predecessor):
        nodes=status_view(snapshot,"node").get("current_nodes",{})
        if nodes.get("observation",{}).get("state")!="FRESH":
            return False
        matched=[n for n in nodes.get("items",[])
                 if n.get("conversation_uuid")==predecessor]
        # Unknown/absent is NOT evidence of an irrecoverable owner.
        return (len(matched)==1 and matched[0].get("status")=="CONFIRMED"
                and matched[0].get("source")=="RCC_FRESH"
                and matched[0].get("connection",{}).get("disconnected") is True)

    def prepare(self,*,work_id,snapshot_a,snapshot_b,instance_id,window_id,now=None):
        """Require repeated disconnected evidence, expired lease, and no UNKNOWN."""
        now=time.time() if now is None else now
        if not re.fullmatch(r"[a-f0-9]{32}",str(instance_id)) or (
            type(window_id) is not int or window_id <= 0):
            raise LoopStateError("LOOP_SUCCESSOR_TARGET_INVALID")
        loop=LoopStore(self.store).get(work_id)
        if loop is None or loop["state"]!="LOOP_STARTED":
            raise LoopStateError("LOOP_SUCCESSOR_WORK_NOT_RUNNING")
        if loop.get("allow_new_nodes") == 0:
            raise LoopStateError("LOOP_NEW_NODES_DISALLOWED")
        if loop["lease_until"]>now:
            raise LoopStateError("LOOP_SUCCESSOR_LEASE_ACTIVE")
        if loop["operation_state"] in {"UNKNOWN","PREPARED"}:
            raise LoopStateError("LOOP_SUCCESSOR_EFFECT_UNCERTAIN")
        observations=[
            (v.get("monitor") or {}).get("current_nodes",{}).get("observed_at")
            for v in (snapshot_a,snapshot_b)
        ]
        if (not all(type(t) in {float,int} for t in observations)
                or observations[1] <= observations[0]
                or observations[1]-observations[0] < 2.0
                or not all(self._unavailable(v,loop["owner"])
                           for v in (snapshot_a,snapshot_b))):
            raise LoopStateError("LOOP_SUCCESSOR_NOT_PROVEN_UNAVAILABLE")
        with self.store.transaction() as db:
            old=db.execute("SELECT * FROM loop_successor_cases WHERE work_id=?",
                           (work_id,)).fetchone()
            current = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if (not current or current["owner"] != loop["owner"]
                    or current["epoch"] != loop["epoch"] or current["lease_until"] > now
                    or current["state"] != "LOOP_STARTED"
                    or current["operation_state"] in {"UNKNOWN", "PREPARED"}
                    or current["allow_new_nodes"] == 0):
                raise LoopStateError("LOOP_SUCCESSOR_EPOCH_UNSAFE")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='loop_recipe_self_outbox'").fetchone():
                if db.execute("SELECT 1 FROM loop_recipe_self_outbox WHERE work_id=? AND state IN ('UNCERTAIN','UNKNOWN') LIMIT 1",
                              (work_id,)).fetchone():
                    raise LoopStateError("LOOP_SELF_PRIOR_EFFECT_UNRESOLVED")
            if old and old["state"] == "TAKEN_OVER":
                if old["successor"] != loop["owner"] or old["predecessor_epoch"] >= loop["epoch"]:
                    raise LoopStateError("LOOP_SUCCESSOR_CASE_CONFLICT")
                db.execute("INSERT INTO loop_successor_history VALUES(?,?,?,?)",
                           (work_id, old["predecessor_epoch"], json.dumps(dict(old), sort_keys=True), now))
                db.execute("DELETE FROM loop_successor_cases WHERE work_id=?", (work_id,))
                old = None
            if old:
                if (old["predecessor"]!=loop["owner"] or
                    old["predecessor_epoch"]!=loop["epoch"] or
                    old["instance_id"]!=instance_id or old["window_id"]!=window_id):
                    raise LoopStateError("LOOP_SUCCESSOR_CASE_CONFLICT")
                return dict(old)
            base=hashlib.sha256(f"{work_id}:{loop['epoch']}".encode()).hexdigest()[:20]
            db.execute("""INSERT INTO loop_successor_cases(
                work_id,predecessor,predecessor_epoch,create_op,send_op,
                state,instance_id,window_id,updated_at)
                VALUES(?,?,?,?,?,'CREATE_INTENT',?,?,?)""",
                (work_id,loop["owner"],loop["epoch"],"loop-create-"+base,
                 "loop-handoff-"+base,instance_id,window_id,now))
        return self.get(work_id)

    def reserve_effect(self,*,work_id,kind,handoff_text_sha=None,now=None):
        """One-shot durable reservation before create/send. Never repeat UNKNOWN."""
        now=time.time() if now is None else now
        states={"create":("CREATE_INTENT","CREATE_DISPATCHING"),
                "send":("CREATED","SEND_DISPATCHING")}
        if kind not in states:
            raise LoopStateError("LOOP_SUCCESSOR_EFFECT_INVALID")
        expected,selected=states[kind]
        with self.store.transaction() as db:
            loop = db.execute("SELECT allow_new_nodes FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if not loop or loop["allow_new_nodes"] == 0:
                raise LoopStateError("LOOP_NEW_NODES_DISALLOWED")
            row=db.execute("SELECT * FROM loop_successor_cases WHERE work_id=?",
                           (work_id,)).fetchone()
            if not row or row["state"]!=expected:
                raise LoopStateError("LOOP_SUCCESSOR_ALREADY_DISPATCHED")
            if kind=="send":
                if not isinstance(handoff_text_sha,str) or not re.fullmatch(
                        r"[a-f0-9]{64}",handoff_text_sha):
                    raise LoopStateError("LOOP_SUCCESSOR_TEXT_SHA_REQUIRED")
                db.execute("""UPDATE loop_successor_cases
                    SET state=?,handoff_text_sha=?,updated_at=?
                    WHERE work_id=? AND state=?""",
                    (selected,handoff_text_sha,now,work_id,expected))
            else:
                db.execute("""UPDATE loop_successor_cases SET state=?,updated_at=?
                    WHERE work_id=? AND state=?""",(selected,now,work_id,expected))
        return self.get(work_id)

    def confirm_create(self,*,work_id,principal_id,snapshot,now=None):
        now=time.time() if now is None else now
        row=self.get(work_id)
        if not row or row["state"] not in {"CREATE_INTENT","CREATE_DISPATCHING","CREATED"}:
            raise LoopStateError("LOOP_SUCCESSOR_CREATE_NOT_READY")
        try:
            receipt=self.store.get_operation_for(
                operation_id=row["create_op"],work_id=work_id,principal_id=principal_id
            )
        except KeyError:
            raise LoopStateError("LOOP_SUCCESSOR_CREATE_RECEIPT_UNKNOWN")
        evidence=receipt.evidence or {}
        if receipt.state.value!="FINISHED" or not receipt.outcome or (
            receipt.outcome.value!="APPLIED"):
            raise LoopStateError("LOOP_SUCCESSOR_CREATE_NOT_PROVEN")
        tab=evidence.get("created_tab_id")
        if evidence.get("command") not in {"create-chat-tab","create-chat-window"} or (
            evidence.get("instance_id")!=row["instance_id"] or
            evidence.get("created_request_id")!=row["create_op"] or
            type(tab) is not int or tab<=0 or
            evidence.get("created_window_id")!=row["window_id"]):
            raise LoopStateError("LOOP_SUCCESSOR_CREATE_EVIDENCE_MISMATCH")
        attached=_attachment(snapshot,instance_id=row["instance_id"],tab_id=tab)
        if not attached or attached["window_id"]!=row["window_id"]:
            raise LoopStateError("LOOP_SUCCESSOR_ATTACHMENT_UNKNOWN")
        # UUID cannot be guessed from a blank tab, title, or node number.
        with self.store.transaction() as db:
            db.execute("""UPDATE loop_successor_cases SET state='CREATED',
                created_tab_id=?,updated_at=? WHERE work_id=? AND
                state IN ('CREATE_INTENT','CREATE_DISPATCHING','CREATED')""",(tab,now,work_id))
        return self.get(work_id)

    def bind_successor(self,*,work_id,principal_id,snapshot,now=None):
        """Identify UUID only from the original sent-to-created-tab receipt.

        A newly created blank ChatGPT tab has no trusted conversation UUID.
        Its first handoff send must use the exact create Operation ID; if
        that send is UNKNOWN, this function only waits for the original proof.
        """
        now=time.time() if now is None else now
        row=self.get(work_id)
        if not row or row["state"] not in {"CREATED","SEND_DISPATCHING","IDENTIFIED"}:
            raise LoopStateError("LOOP_SUCCESSOR_CREATION_NOT_PROVEN")
        try:
            send=self.store.get_operation_for(
                operation_id=row["send_op"],work_id=work_id,principal_id=principal_id
            )
        except KeyError as exc:
            raise LoopStateError("LOOP_SUCCESSOR_SEND_RECEIPT_UNKNOWN") from exc
        proof=send.evidence or {}
        key=str(proof.get("conversation_key") or "").lower()
        if (send.state.value!="FINISHED" or not send.outcome or
            send.outcome.value!="APPLIED" or
            proof.get("command")!="send-to-created-tab" or
            proof.get("host_request_id")!=row["send_op"] or
            proof.get("source_message_sha256")!=row["handoff_text_sha"] or
            proof.get("instance_id")!=row["instance_id"] or
            not _UUID.fullmatch(key) or key==row["predecessor"]):
            raise LoopStateError("LOOP_SUCCESSOR_SEND_NOT_PROVEN")
        attached=_attachment(snapshot,instance_id=row["instance_id"],
                             tab_id=row["created_tab_id"])
        if (not attached or attached["conversation_key"]!=key or
            attached["window_id"]!=row["window_id"]):
            raise LoopStateError("LOOP_SUCCESSOR_UUID_UNVERIFIED")
        if row["successor"] and row["successor"]!=key:
            raise LoopStateError("LOOP_SUCCESSOR_UUID_CONFLICT")
        with self.store.transaction() as db:
            db.execute("""UPDATE loop_successor_cases SET successor=?,
                state='IDENTIFIED',updated_at=? WHERE work_id=?""",
                (key,now,work_id))
        return self.get(work_id)

    def verify_handoff(self,*,work_id,principal_id,successor_response,
                       expected_response_sha,now=None):
        """Require original send receipt and exact observed inheritance reply."""
        now=time.time() if now is None else now
        row=self.get(work_id)
        if not row or row["state"] not in {"IDENTIFIED","HANDOFF_ACK"}:
            raise LoopStateError("LOOP_SUCCESSOR_NOT_IDENTIFIED")
        try:
            receipt=self.store.get_operation_for(
                operation_id=row["send_op"],work_id=work_id,principal_id=principal_id)
        except KeyError:
            raise LoopStateError("LOOP_SUCCESSOR_HANDOFF_RECEIPT_UNKNOWN")
        evidence=receipt.evidence or {}
        if not (receipt.state.value=="FINISHED" and receipt.outcome and
                receipt.outcome.value=="APPLIED" and
                evidence.get("conversation_key")==row["successor"] and
                evidence.get("host_request_id")==row["send_op"]):
            raise LoopStateError("LOOP_SUCCESSOR_HANDOFF_NOT_PROVEN")
        response_text=(successor_response or {}).get("responseText")
        if not isinstance(successor_response,dict) or (
            successor_response.get("conversationKey")!=row["successor"] or
            successor_response.get("terminal") is not True or
            successor_response.get("generating") is not False or
            successor_response.get("observationState")!="TERMINAL" or
            not isinstance(response_text,str) or
            hashlib.sha256(response_text.encode("utf-8")).hexdigest()!=expected_response_sha or
            successor_response.get("responseSha256")!=expected_response_sha or
            "LOOP_SUCCESSOR_READY" not in response_text.splitlines() or
            successor_response.get("responseSourceUserSha256")!=row["handoff_text_sha"] or
            successor_response.get("latestUserSha256")!=row["handoff_text_sha"] or
            not successor_response.get("responseSourceUserTurnKey") or
            successor_response.get("latestUserTurnKey")!=
                successor_response.get("responseSourceUserTurnKey") or
            not successor_response.get("responseTurnKey")):
            raise LoopStateError("LOOP_SUCCESSOR_RESPONSE_UNVERIFIED")
        if row["response_turn_key"] and row["response_turn_key"]!=successor_response["responseTurnKey"]:
            raise LoopStateError("LOOP_SUCCESSOR_RESPONSE_CONFLICT")
        with self.store.transaction() as db:
            db.execute("""UPDATE loop_successor_cases SET state='HANDOFF_ACK',
                response_turn_key=?,response_sha=?,updated_at=?
                WHERE work_id=?""",
                (successor_response["responseTurnKey"],expected_response_sha,now,work_id))
        return self.get(work_id)

    def finish(self,*,work_id,now=None):
        """Atomic Loop Epoch transfer after all proven predecessor handoff gates."""
        now=time.time() if now is None else now
        from bct.loop_self_outbox import LoopSelfOutbox
        LoopSelfOutbox(self.store)
        with self.store.transaction() as db:
            case=db.execute("SELECT * FROM loop_successor_cases WHERE work_id=?",
                            (work_id,)).fetchone()
            if not case or case["state"]!="HANDOFF_ACK":
                raise LoopStateError("LOOP_SUCCESSOR_HANDOFF_NOT_ACKED")
            loop=db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?",
                            (work_id,)).fetchone()
            if (not loop or loop["owner"]!=case["predecessor"] or
                loop["state"]!="LOOP_STARTED" or
                loop["epoch"]!=case["predecessor_epoch"] or
                loop["lease_until"]>now or
                loop["operation_state"] in {"PREPARED","UNKNOWN","APPLIED"}):
                raise LoopStateError("LOOP_SUCCESSOR_EPOCH_UNSAFE")
            has_recovery_ledger=db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='node_recovery_cases'"
            ).fetchone()
            if not has_recovery_ledger:
                raise LoopStateError("LOOP_SUCCESSOR_PREDECESSOR_NOT_FENCED")
            exact_fence_id="loop-fence-"+hashlib.sha256(
                f"{work_id}:{case['predecessor_epoch']}".encode()
            ).hexdigest()[:24]
            predecessor_fence=db.execute(
                """SELECT 1 FROM node_recovery_cases
                WHERE case_id=? AND work_id=? AND conversation_key=? AND state IN
                ('PAUSED','REPLACEMENT_PREPARED') LIMIT 1""",
                (exact_fence_id,work_id,case["predecessor"]),
            ).fetchone()
            if not predecessor_fence:
                raise LoopStateError("LOOP_SUCCESSOR_PREDECESSOR_NOT_FENCED")
            if db.execute("""SELECT 1 FROM loop_recipe_self_outbox
                    WHERE work_id=? AND state IN ('UNCERTAIN','UNKNOWN') LIMIT 1""", (work_id,)).fetchone():
                raise LoopStateError("LOOP_SELF_PRIOR_EFFECT_UNRESOLVED")
            new_epoch=loop["epoch"]+1
            from bct.loop_supervisor_handoff import LoopReviewLedger
            LoopReviewLedger.transfer_configured(db, work_id=work_id,
                predecessor=case["predecessor"], successor=case["successor"],
                epoch=new_epoch, handoff_operation_id=case["send_op"], now=now)
            # Protect unsent intents; old external effects are never transferred.
            db.execute("""UPDATE loop_recipe_runs SET owner=?,epoch=?,
                lease_until=?,updated_at=? WHERE work_id=?""",
                (case["successor"],new_epoch,now+60,now,work_id))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='loop_recipe_self_outbox'").fetchone():
                db.execute("""UPDATE loop_recipe_self_outbox SET epoch=?,
                    conversation_key=?,updated_at=? WHERE work_id=?
                    AND epoch=? AND state='PENDING'""",
                    (new_epoch,case["successor"],now,work_id,loop["epoch"]))
            # Persist a new resume instruction with the Epoch transfer. This
            # never replays the predecessor's send or task operation.
            if not db.execute("SELECT 1 FROM loop_recipe_self_outbox WHERE work_id=? AND epoch=? AND state='PENDING'",
                              (work_id, new_epoch)).fetchone():
                message = (
                    "[BCT LOOP RESUME AFTER VERIFIED SUCCESSION]\n"
                    f"Work ID: {work_id}\nDirection ID: {loop['direction_id']}\n"
                    f"Task ID: {loop['task_id']}\nOwner UUID: {case['successor']}\n"
                    f"Epoch: {new_epoch}\nNext incomplete step: {loop['next_step']}\n"
                    f"Plan SHA256: {loop['plan_sha256']}\n"
                    "Read the saved plan, original operation receipts and current Epoch first. "
                    "Continue only the next uncompleted step under this Epoch. Never replay "
                    "APPLIED or UNKNOWN operations. You are the single Loop Manager/worker. "
                    "Do not return to yourself or create child nodes. Reconcile the original receipts "
                    "with bct_loop_recipe; if still uncertain, preserve the hold and report the blocker "
                    "to the original requester through its configured reporting path."
                )
                op = "loop-self-" + hashlib.sha256(f"{work_id}:{new_epoch}:{loop['next_step']}".encode()).hexdigest()[:24]
                db.execute("INSERT INTO loop_recipe_self_outbox VALUES(?,?,?,?,?,?,?,'PENDING',?,?)",
                           (work_id,new_epoch,loop["next_step"],case["successor"],op,message,
                            hashlib.sha256(message.encode()).hexdigest(),now,now))
            db.execute("""UPDATE loop_successor_cases SET state='TAKEN_OVER',
                updated_at=? WHERE work_id=?""",(now,work_id))
            seq=db.execute("SELECT COALESCE(MAX(event_seq),0)+1 FROM loop_recipe_events WHERE work_id=?",
                           (work_id,)).fetchone()[0]
            db.execute("INSERT INTO loop_recipe_events VALUES(?,?,?,?,?,?)",
                       (work_id,seq,"SUCCESSOR_PROVEN",new_epoch,case["send_op"],now))
        return LoopStore(self.store).get(work_id)
