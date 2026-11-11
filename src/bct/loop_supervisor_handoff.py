"""Loop completion adapter over Chain's exact-send and response-watch blocks.

A single Manager owns the Loop; an independent global Supervisor receives one
immutable evidence packet. This does not create nodes, grant permissions,
merge, deploy, or interpret a review as LIVE acceptance. Existing Chain
SELF/MANAGER transport returns the review to the original Manager. Unknown
sends are reconciled against their original Operation, never replayed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from bct.chain_direction import resolve_direction_target
from bct.core.capabilities import capability_matches
from bct.core.models import Principal
from bct.loop_self_dispatch import LoopSelfDispatcher
from bct.loop_store import LoopStateError
from bct.node_recovery import NodeRecoveryLedger
from bct.send_delayed_message import DurableWatchLedger, SendDelayedMessageService


def validate_loop_review_topology(snapshot, *, owner, supervisor):
    """Reuse exact Chain identities, without inventing a third Worker node."""
    if owner == supervisor:
        raise LoopStateError("LOOP_REVIEW_NOT_INDEPENDENT")
    manager = resolve_direction_target(snapshot=snapshot, conversation_key=owner)
    reviewer = resolve_direction_target(snapshot=snapshot, conversation_key=supervisor)
    m, s = manager["node_info"], reviewer["node_info"]
    roles = lambda node: {str(x).casefold() for x in node.get("roles", [])}
    if "manager" not in roles(m) or roles(m) & {"worker", "supervisor"}:
        raise LoopStateError("LOOP_REVIEW_MANAGER_ROLE_REQUIRED")
    if "supervisor" not in roles(s) or roles(s) & {"manager", "worker"}:
        raise LoopStateError("LOOP_REVIEW_SUPERVISOR_ROLE_REQUIRED")
    if not (m.get("network_id") or m.get("network")):
        raise LoopStateError("LOOP_REVIEW_MANAGER_SCOPE_REQUIRED")
    if s.get("network_id") or s.get("network"):
        raise LoopStateError("LOOP_REVIEW_SUPERVISOR_MUST_BE_GLOBAL")
    return manager, reviewer


class LoopReviewLedger:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS loop_review_handoffs(
                work_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                supervisor TEXT NOT NULL, instruction TEXT NOT NULL,
                state TEXT NOT NULL, epoch INTEGER, candidate_sha TEXT,
                evidence_text TEXT, message_text TEXT, message_sha256 TEXT,
                task_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                response_json TEXT, updated_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS loop_review_history(
                work_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
                event_kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                created_at REAL NOT NULL, PRIMARY KEY(work_id,event_seq))""")

    @staticmethod
    def archive(db, row, *, kind, proof, now):
        sequence = db.execute("SELECT COALESCE(MAX(event_seq),0)+1 FROM loop_review_history WHERE work_id=?", (row["work_id"],)).fetchone()[0]
        db.execute("INSERT INTO loop_review_history VALUES(?,?,?,?,?)",
            (row["work_id"], sequence, kind,
             json.dumps({"review":dict(row),"proof":proof},sort_keys=True), now))

    @staticmethod
    def transfer_configured(db, *, work_id, predecessor, successor, epoch, handoff_operation_id, now):
        """Called only inside the proven successor Epoch-transfer transaction.

        No already-dispatched review changes recipient/return destination. This
        transfers durable ownership only, not role tags or permissions. Fresh
        Manager/global-Supervisor topology is still mandatory before dispatch.
        """
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='loop_review_handoffs'").fetchone():
            return
        row = db.execute("SELECT * FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
        if not row:
            return
        if row["state"] != "CONFIGURED" or row["owner"] != predecessor:
            raise LoopStateError("LOOP_REVIEW_SUCCESSION_UNSAFE")
        LoopReviewLedger.archive(db, row, kind="SUCCESSOR_CONFIGURED_BINDING",
            proof={"successor":successor,"epoch":epoch,"handoff_operation_id":handoff_operation_id}, now=now)
        db.execute("UPDATE loop_review_handoffs SET owner=?,updated_at=? WHERE work_id=?",
                   (successor,now,work_id))

    def history(self, work_id):
        with self.store._readonly() as db:
            return [dict(row) for row in db.execute("SELECT * FROM loop_review_history WHERE work_id=? ORDER BY event_seq", (work_id,))]

    def get(self, work_id):
        with self.store._readonly() as db:
            row = db.execute("SELECT * FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
        return dict(row) if row else None

    def configure(self, *, work_id, owner, supervisor, instruction, snapshot):
        validate_loop_review_topology(snapshot, owner=owner, supervisor=supervisor)
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 4000:
            raise LoopStateError("LOOP_REVIEW_INSTRUCTION_REQUIRED")
        key = hashlib.sha256(work_id.encode()).hexdigest()[:24]
        with self.store.transaction() as db:
            loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if not loop or loop["owner"] != owner or loop["state"] != "LOOP_STARTED":
                raise LoopStateError("LOOP_REVIEW_OWNER_CHANGED")
            prior = db.execute("SELECT * FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
            if prior:
                if (prior["owner"], prior["supervisor"], prior["instruction"]) != (owner, supervisor, instruction):
                    raise LoopStateError("LOOP_REVIEW_BINDING_CONFLICT")
            else:
                db.execute("""INSERT INTO loop_review_handoffs
                    (work_id,owner,supervisor,instruction,state,task_id,operation_id,updated_at)
                    VALUES(?,?,?,?,'CONFIGURED',?,?,?)""",
                    (work_id, owner, supervisor, instruction, "loop-review-"+key,
                     "loop-review-send-"+key, time.time()))
        return self.get(work_id)

    def request(self, *, work_id, owner, epoch, candidate_sha, evidence_text, now=None):
        now = time.time() if now is None else now
        if not re.fullmatch(r"[a-f0-9]{40}", candidate_sha):
            raise LoopStateError("LOOP_REVIEW_EXACT_SHA_REQUIRED")
        if not isinstance(evidence_text, str) or not evidence_text.strip() or len(evidence_text) > 5000:
            raise LoopStateError("LOOP_REVIEW_EVIDENCE_REQUIRED")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
            loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if not row or not loop or row["owner"] != owner or loop["owner"] != owner or loop["epoch"] != epoch:
                raise LoopStateError("LOOP_REVIEW_OWNER_CHANGED")
            if row["state"] != "CONFIGURED":
                if (row["epoch"], row["candidate_sha"], row["evidence_text"]) != (epoch, candidate_sha, evidence_text):
                    raise LoopStateError("LOOP_REVIEW_REQUEST_CONFLICT")
                return dict(row)
            if (loop["state"] != "LOOP_STARTED" or loop["lease_until"] <= now
                    or loop["next_step"] < 1 or loop["operation_state"] is not None):
                raise LoopStateError("LOOP_COMPLETION_UNVERIFIED")
            # An unresolved/unsent SELF could race the review handoff. A delivered
            # final turn is permitted: review-pending removes it from polling.
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='loop_recipe_self_outbox'").fetchone()
            if exists and db.execute("SELECT 1 FROM loop_recipe_self_outbox WHERE work_id=? AND state IN ('PENDING','UNCERTAIN','UNKNOWN')", (work_id,)).fetchone():
                raise LoopStateError("LOOP_REVIEW_SELF_EFFECT_UNRESOLVED")
            message = (
                "[LOOP INDEPENDENT SUPERVISOR REVIEW]\n"
                f"Work: {work_id}\nLoop Task: {loop['task_id']}\nDirection: {loop['direction_id']}\n"
                f"Review Task: {row['task_id']}\nManager UUID: {owner}\n"
                f"Candidate SHA: {candidate_sha}\nPlan SHA256: {loop['plan_sha256']}\n"
                f"Completed step cursor: {loop['next_step']}\nPlan:\n{loop['plan_text']}\n\n"
                "Review the exact candidate and original evidence independently. Do not treat this packet "
                "as proof of acceptance or as new authorization. Reuse existing test/CI/integration blocks "
                "only within the Work and the user's actual permission. Do not merge, deploy, create nodes, "
                "or change roles merely because this handoff exists. Preserve UNKNOWN operations.\n"
                f"Save your own review plan with bct_set_execute_plan(work_id={work_id}, "
                f"direction_id={loop['direction_id']}, task_id={row['task_id']}). "
                "Report PLAN REVISION and PROGRESS in every reply. "
                "Use the existing delayed-send SELF/MANAGER contract. If more review remains, use SELF; "
                "otherwise return MANAGER with evidence, blockers, and an explicit verdict. "
                "Only when ALL requested acceptance criteria, including any authorized integration/LIVE scope, "
                "are independently verified, include exactly `LOOP ACCEPTANCE: PASS` and "
                f"`LOOP CANDIDATE SHA: {candidate_sha}` in the MANAGER payload. Otherwise use "
                "`LOOP ACCEPTANCE: HOLD`. Code review or CI alone is not full acceptance. "
                "For HOLD, tell the Manager to read bct_loop_recipe(status), acknowledge the exact "
                "returned response SHA with resume_review, fix within the original scope, and "
                "request review again with the new exact candidate SHA.\n\n"
                f"Review scope:\n{row['instruction']}\n\nEvidence:\n{evidence_text}"
            )
            if len(message) > 12000:
                raise LoopStateError("LOOP_REVIEW_PACKET_TOO_LARGE")
            digest = hashlib.sha256(message.encode()).hexdigest()
            db.execute("""UPDATE loop_review_handoffs SET state='PENDING',epoch=?,candidate_sha=?,
                evidence_text=?,message_text=?,message_sha256=?,updated_at=? WHERE work_id=?""",
                (epoch, candidate_sha, evidence_text, message, digest, now, work_id))
            if exists:
                # Retire, do not pretend to ACK, the already-delivered final
                # SELF turn. Its immutable Operation remains the proof. It must
                # not wake again when a later HOLD is explicitly resumed.
                db.execute("UPDATE loop_recipe_self_outbox SET state='RETIRED_FOR_REVIEW',updated_at=? WHERE work_id=? AND state='DELIVERED'", (now,work_id))
            db.execute("UPDATE loop_recipe_runs SET state='REVIEW_PENDING',updated_at=? WHERE work_id=?", (now, work_id))
        return self.get(work_id)

    def resume(self, *, work_id, owner, epoch, response_sha256, snapshot, now=None):
        """Explicitly acknowledge a delivered HOLD and begin a new review round.

        Old packets, decisions, task IDs and Operations are archived unchanged.
        UNKNOWN, DISPATCHING and even an unreturned review cannot authorize a new
        round. The new intent is unsent CONFIGURED, never a retry of the old send.
        """
        now = time.time() if now is None else now
        row = self.get(work_id)
        if not row or row["state"] != "REVIEW_HOLD":
            raise LoopStateError("LOOP_REVIEW_HOLD_REQUIRED")
        validate_loop_review_topology(snapshot, owner=owner, supervisor=row["supervisor"])
        context = json.loads(row["response_json"] or "null")
        if not context or context["decision"]["response_sha256"] != response_sha256:
            raise LoopStateError("LOOP_REVIEW_RETURN_PROOF_REQUIRED")
        actual = DurableWatchLedger(self.store).read_execution_context(task_id=row["task_id"], generation=context["generation"])
        if actual != context or not self._return_applied(row, context):
            raise LoopStateError("LOOP_REVIEW_RETURN_PROOF_REQUIRED")
        next_key = hashlib.sha256((row["operation_id"]+":"+response_sha256).encode()).hexdigest()[:24]
        with self.store.transaction() as db:
            current = db.execute("SELECT * FROM loop_review_handoffs WHERE work_id=?", (work_id,)).fetchone()
            loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if (not current or dict(current) != row or not loop or loop["state"] != "REVIEW_PENDING"
                    or row["owner"] != owner or loop["owner"] != owner
                    or row["epoch"] != epoch or loop["epoch"] != epoch
                    or loop["operation_state"] is not None):
                raise LoopStateError("LOOP_REVIEW_RESUME_FENCED")
            self.archive(db, current, kind="HOLD_RESUMED",
                proof={"response_sha256":response_sha256,"new_epoch":epoch+1}, now=now)
            db.execute("""UPDATE loop_review_handoffs SET state='CONFIGURED',epoch=NULL,
                candidate_sha=NULL,evidence_text=NULL,message_text=NULL,message_sha256=NULL,
                task_id=?,operation_id=?,response_json=NULL,updated_at=? WHERE work_id=?""",
                ("loop-review-"+next_key,"loop-review-send-"+next_key,now,work_id))
            db.execute("UPDATE loop_recipe_runs SET state='LOOP_STARTED',epoch=?,lease_until=?,updated_at=? WHERE work_id=?", (epoch+1,now+60,now,work_id))
            from bct.loop_store import LoopStore
            LoopStore._event(db,work_id,"REVIEW_HOLD_RESUMED",epoch+1,row["operation_id"],now)
        return self.get(work_id)

    def _return_applied(self, row, context):
        binding = context["binding"]
        if (context["watch_state"] != "RETURNED_TO_MANAGER"
                or context["worker_conversation_key"] != row["supervisor"]
                or binding.get("work_id") != row["work_id"]
                or binding.get("manager_conversation_key") != row["owner"]
                or context["decision"]["route"] != "MANAGER"):
            raise LoopStateError("LOOP_REVIEW_RETURN_BINDING_CHANGED")
        key = hashlib.sha256(f"{row['task_id']}|{context['generation']}|{context['response_turn_id']}".encode()).hexdigest()[:24]
        work = self.store.get_work(row["work_id"])
        receipt = self.store.get_operation_for(operation_id="delayed-manager-"+key,
            work_id=row["work_id"], principal_id=work.owner_principal_id)
        return receipt.state.value == "FINISHED" and receipt.outcome is not None and receipt.outcome.value == "APPLIED"

    def pending(self, limit=8):
        with self.store._readonly() as db:
            return [dict(r) for r in db.execute("SELECT * FROM loop_review_handoffs WHERE state IN ('PENDING','DISPATCHING','DELIVERED') ORDER BY updated_at LIMIT ?", (limit,))]

    def reserve(self, work_id):
        with self.store.transaction() as db:
            changed = db.execute("UPDATE loop_review_handoffs SET state='DISPATCHING',updated_at=? WHERE work_id=? AND state='PENDING'", (time.time(), work_id))
            if changed.rowcount != 1:
                raise LoopStateError("LOOP_REVIEW_ALREADY_DISPATCHED")
        return self.get(work_id)

    def reconcile(self, work_id):
        row = self.get(work_id)
        work = self.store.get_work(work_id)
        receipt = self.store.get_operation_for(operation_id=row["operation_id"], work_id=work_id, principal_id=work.owner_principal_id)
        if receipt.state.value != "FINISHED" or receipt.outcome is None:
            return row
        outcome = receipt.outcome.value
        if outcome not in {"APPLIED", "NOT_APPLIED"}:
            return row
        state = "DELIVERED" if outcome == "APPLIED" else "NOT_APPLIED"
        with self.store.transaction() as db:
            db.execute("UPDATE loop_review_handoffs SET state=?,updated_at=? WHERE work_id=? AND state='DISPATCHING'", (state, time.time(), work_id))
        return self.get(work_id)

    def observe_return(self, work_id):
        row = self.get(work_id)
        context = DurableWatchLedger(self.store).read_execution_context(task_id=row["task_id"])
        if not context or context["watch_state"] != "RETURNED_TO_MANAGER":
            return row
        if not self._return_applied(row, context):
            return row
        key = hashlib.sha256(f"{row['task_id']}|{context['generation']}|{context['response_turn_id']}".encode()).hexdigest()[:24]
        payload = context["decision"]["payload"]
        verdicts = re.findall(r"(?m)^LOOP ACCEPTANCE: (PASS|HOLD)$", payload)
        shas = re.findall(r"(?m)^LOOP CANDIDATE SHA: ([a-f0-9]{40})$", payload)
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        with self.store._readonly() as db:
            current = db.execute("SELECT direction_id FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
        check = ChainExecutionPlanLedger.read_latest_execute_plan_check(store=self.store,
            work_id=work_id, direction_id=current["direction_id"], task_id=row["task_id"])
        plan = ChainExecutionPlanLedger.get_for_chain(store=self.store,
            work_id=work_id, direction_id=current["direction_id"], task_id=row["task_id"])
        plan_complete = bool(plan and check and check["reported_revision"] == plan["revision"]
            and check["plan_id"] == plan["plan_id"] and check["generation"] == context["generation"]
            and check["response_sha256"] == context["decision"]["response_sha256"]
            and not check["issues"] and check["total_steps"] is not None
            and check["completed_steps"] == check["total_steps"])
        accepted = verdicts == ["PASS"] and shas == [row["candidate_sha"]] and plan_complete
        with self.store.transaction() as db:
            loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id=?", (work_id,)).fetchone()
            if (not loop or loop["owner"] != row["owner"] or loop["epoch"] != row["epoch"]
                    or loop["state"] != "REVIEW_PENDING"):
                raise LoopStateError("LOOP_REVIEW_OWNER_CHANGED")
            state = "ACCEPTED" if accepted else "REVIEW_HOLD"
            changed = db.execute("UPDATE loop_review_handoffs SET state=?,response_json=?,updated_at=? WHERE work_id=? AND state='DELIVERED'",
                (state, json.dumps(context, sort_keys=True), time.time(), work_id))
            if changed.rowcount and accepted:
                from bct.loop_store import LoopStore
                db.execute("UPDATE loop_recipe_runs SET state='COMPLETED',updated_at=? WHERE work_id=?", (time.time(), work_id))
                LoopStore._event(db, work_id, "INDEPENDENT_ACCEPTANCE_RETURNED", row["epoch"], "delayed-manager-"+key)
        return self.get(work_id)


class LoopSupervisorHandoff:
    """Compose the existing Chain Watch service and BCT browser Operation."""
    def __init__(self, store, operations, browser_feature):
        self.store, self.operations = store, operations
        self.ledger = LoopReviewLedger(store)
        self.service = SendDelayedMessageService(store=store, operations=operations, browser_feature=browser_feature)

    def _direction_id(self, work_id):
        from bct.loop_store import LoopStore
        return LoopStore(self.store).get(work_id)["direction_id"]

    def run_once(self, *, snapshot, limit=4):
        outcomes = []
        for row in self.ledger.pending(limit):
            work_id = row["work_id"]
            try:
                if row["state"] == "DISPATCHING":
                    result = self.ledger.reconcile(work_id)
                elif row["state"] == "DELIVERED":
                    result = self.ledger.observe_return(work_id)
                else:
                    manager, _ = validate_loop_review_topology(snapshot, owner=row["owner"], supervisor=row["supervisor"])
                    route = LoopSelfDispatcher.exact_route(snapshot, row["supervisor"])
                    work = self.store.get_work(work_id)
                    if work.state != "ACTIVE" or not any(capability_matches(a, "browser") for a in work.actions):
                        raise LoopStateError("LOOP_REVIEW_WORK_NOT_AUTHORIZED")
                    NodeRecoveryLedger(self.store).assert_send_allowed(work_id=work_id, conversation_key=row["supervisor"])
                    with self.store._readonly() as db:
                        occupied = db.execute("SELECT 1 FROM delayed_send_watches WHERE conversation_key=? AND task_id!=? AND state IN ('WATCHING','RESERVED','DISPATCHING','UNKNOWN') LIMIT 1", (row["supervisor"], row["task_id"])).fetchone()
                    if occupied:
                        raise LoopStateError("LOOP_REVIEW_SUPERVISOR_BUSY")
                    # Prearm before reservation/send: repeated read-only preparation
                    # is safe; only one process may reserve the external effect.
                    self.service.prearm(task_id=row["task_id"], work=work,
                        instance_id=route["instance_id"], conversation_key=row["supervisor"],
                        manager_conversation_key=row["owner"], manager_instance_id=manager["instance_id"],
                        operation_id="prearm-"+row["operation_id"],
                        planned_send_operation_id=row["operation_id"], planned_send_text=row["message_text"],
                        execution_path="DIRECTION_DECLARED",
                        chain_direction_id=self._direction_id(work_id), exclusive_conversation_watch=True,
                        watched_session_id=route["session_id"], watched_tab_id=route["tab_id"], watched_window_id=route["window_id"])
                    self.ledger.reserve(work_id)
                    self.operations.run(principal=Principal(work.owner_principal_id,"loop-review-existing-work",frozenset({"browser"})),
                        work_id=work_id, operation_id=row["operation_id"], capability="browser",
                        arguments={"command":"send-message", **route, "text":row["message_text"]})
                    result = self.ledger.reconcile(work_id)
                outcomes.append({"work_id":work_id,"state":result["state"],"operation_id":row["operation_id"]})
            except Exception as exc:
                outcomes.append({"work_id":work_id,"state":"HELD","reason":str(exc)[:180],"operation_id":row["operation_id"]})
        return outcomes
