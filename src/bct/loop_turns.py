"""Durable Manager turns for the public LOOP, driven by the existing Watch service."""
from __future__ import annotations

import hashlib
import json
import re
import time

from bct.core.models import OperationState, Outcome, Principal
from bct.loop_recipe_contracts import LoopContractError
from bct.loop_recipe_ledger import LoopRecipeLedger
from bct.node_recovery import NodeRecoveryLedger, observe_node
from bct.send_delayed_message import (
    _rcc_submitted_text_sha256, loop_observed_send_binding, loop_observed_send_matches,
)
from bct.status_views import status_view


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_UNCONFIRMED_SEND = "RCC_HOST_OUTCOME_UNVERIFIED:UNKNOWN:RELAY_EXACT_USER_TURN_NOT_CONFIRMED"

_PLAN_FIELDS = ("remaining", "steps", "verification", "reason")
_EXECUTION_PLAN_FIELDS = ("target", "inputs", "deliverables", "dependencies", "blockers")
_REVIEW_FIELDS = ("delivered", "verification", "unfinished")
_PLAN_GUIDANCE = (
    "Review the original request, overall completion conditions, previous result and receipts. "
    "Keep one plan_id for the same multi-turn deliverable and revise it using the latest revision. "
    "Alongside remaining, steps, verification and reason, save target, inputs (paths, tools or receipts), "
    "deliverables, dependencies and blockers (write 'none' when absent). "
    "Choose ordered work that can advance the deliverable now. "
    "In decide.turn_review record delivered, verification and unfinished, including why and what to do next. "
    "If waiting on an external result, use wait with a meaningful delay; use blocked when no work can advance. "
    "Judge completion against the requested output and quality evidence, independently of turn or test counts."
)



def _text(value, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LoopContractError("LOOP_TEXT_REQUIRED_OR_TOO_LONG")
    return value.strip()


class LoopTurns:
    def __init__(self, store, *, initialize=False):
        self.store = store
        if initialize:
            LoopRecipeLedger(store)

    def start(self, *, work, loop_id, task_id, context, overall_plan, conditions,
              replace_observed_first_watch=False):
        if not _ID.fullmatch(loop_id) or not _ID.fullmatch(task_id):
            raise LoopContractError("LOOP_RUN_IDENTITY_REQUIRED")
        overall_plan, conditions_json = self.validate_plan(overall_plan, conditions)
        now = time.time()
        with self.store.transaction() as db:
            self._check_owner(db, {"work_id": work.work_id,
                                   "owner_principal_id": work.owner_principal_id,
                                   "assignment_epoch": work.assignment_epoch})
            run = db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone()
            if run:
                saved = self._objective(db, loop_id)
                actual = (saved["task_id"], saved["overall_plan"], saved["conditions_json"],
                          saved["assignment_epoch"], saved["owner_principal_id"])
                if (run["work_id"] != work.work_id or tuple(saved[key] for key in (
                        "instruction_text", "direction_text", "manager_conversation_key",
                        "supervisor_conversation_key", "network_project_id",
                )) != context or actual != (
                        task_id, overall_plan, conditions_json, work.assignment_epoch,
                        work.owner_principal_id)):
                    raise LoopContractError("LOOP_RUN_ID_CONFLICT")
            else:
                if replace_observed_first_watch:
                    self._supersede_observed_first_watch(db, work, context[2], now)
                if db.execute("""SELECT 1 FROM loop_recipe_objectives o
                        JOIN loop_recipe_v2_contexts c USING(loop_id)
                        JOIN loop_recipe_v2_runs r USING(loop_id)
                        WHERE (c.manager_conversation_key=? AND r.state NOT IN ('COMPLETED','SUPERSEDED'))
                           OR c.network_project_id=? OR o.task_id=?""",
                              (context[2], context[4], task_id)).fetchone():
                    raise LoopContractError("LOOP_MANAGER_PROJECT_OR_TASK_ALREADY_BOUND")
                db.execute("INSERT INTO loop_recipe_v2_runs VALUES(?,?,?,0,'ACTIVE',?,?)",
                           (loop_id, work.work_id, "topology", now, now))
                db.execute("INSERT INTO loop_recipe_v2_contexts VALUES(?,?,?,?,?,?,?)",
                           (loop_id, *context, now))
                db.execute("""INSERT INTO loop_recipe_objectives
                        (loop_id,task_id,owner_principal_id,assignment_epoch,overall_plan,conditions_json)
                        VALUES(?,?,?,?,?,?)""", (loop_id, task_id, work.owner_principal_id,
                                                work.assignment_epoch, overall_plan, conditions_json))
        return self.status(loop_id)

    @staticmethod
    def _supersede_observed_first_watch(db, work, manager, now):
        # A first turn with no plan, decision, or outgoing send can relinquish
        # the Manager after observation or a confirmed late registration.
        db.execute("""UPDATE loop_recipe_v2_runs
            SET state='SUPERSEDED', revision=revision+1, updated_at=?
            WHERE state='BLOCKED' AND work_id=? AND loop_id IN (
                SELECT c.loop_id FROM loop_recipe_v2_contexts c
                JOIN loop_recipe_objectives o USING(loop_id)
                JOIN loop_recipe_turns t USING(loop_id)
                LEFT JOIN delayed_send_watches w ON w.task_id=t.watch_id AND w.generation=1
                    AND w.source_send_receipt=t.watch_operation_id
                JOIN operations op ON op.operation_id=t.watch_operation_id
                    AND op.work_id=? AND op.principal_id=o.owner_principal_id
                    AND op.assignment_epoch=o.assignment_epoch
                WHERE c.manager_conversation_key=? AND o.owner_principal_id=?
                  AND o.assignment_epoch=? AND o.completion_json IS NULL
                  AND t.turn=1 AND t.actor='MANAGER' AND t.conversation_key=?
                  AND t.state='BLOCKED' AND t.due_at IS NULL AND t.decision_json IS NULL
                  AND t.send_operation_id IS NULL AND op.state='FINISHED'
                  AND ((w.state='LOOP_OBSERVED' AND op.outcome='APPLIED'
                        AND t.response_turn_key<>'' AND t.response_sha256<>'')
                       OR (w.task_id IS NULL AND op.outcome='NOT_APPLIED'
                           AND op.error='DELAYED_PREARM_RESPONSE_ALREADY_TERMINAL'))
                  AND NOT EXISTS (SELECT 1 FROM loop_recipe_turns n WHERE n.loop_id=c.loop_id AND n.turn>1)
                  AND NOT EXISTS (SELECT 1 FROM loop_recipe_detail_plans p WHERE p.loop_id=c.loop_id)
                  AND NOT EXISTS (SELECT 1 FROM loop_recipe_v2_continuations n WHERE n.loop_id=c.loop_id)
            )""", (now, work.work_id, work.work_id, manager, work.owner_principal_id,
                   work.assignment_epoch, manager))

    def previous_manager_scope(self, work, manager):
        with self.store._readonly() as db:
            row = db.execute("""SELECT m.project_id FROM conversation_network_memberships m
                JOIN loop_recipe_v2_contexts c ON c.network_project_id=m.project_id
                    AND c.manager_conversation_key=m.conversation_key
                JOIN loop_recipe_v2_runs r USING(loop_id)
                JOIN loop_recipe_objectives o USING(loop_id)
                WHERE m.activity='ACTIVE' AND m.conversation_key=? AND r.work_id=?
                  AND r.state IN ('COMPLETED','SUPERSEDED')
                  AND o.owner_principal_id=? AND o.assignment_epoch=?""",
                             (manager, work.work_id, work.owner_principal_id,
                              work.assignment_epoch)).fetchone()
            return row["project_id"] if row else ""

    @staticmethod
    def validate_plan(overall_plan, conditions):
        overall_plan = _text(overall_plan)
        if (not conditions or len(conditions) > 64
                or any(not _ID.fullmatch(key) for key in conditions)):
            raise LoopContractError("LOOP_COMPLETION_CONDITIONS_REQUIRED")
        conditions_json = json.dumps({key: _text(value, 2000)
                                      for key, value in conditions.items()}, sort_keys=True)
        return overall_plan, conditions_json

    @staticmethod
    def _objective(db, loop_id):
        row = db.execute("""SELECT o.*, c.instruction_text, c.direction_text,
                c.manager_conversation_key, c.supervisor_conversation_key, c.network_project_id,
                r.work_id, r.state AS run_state, r.current_block_id
                FROM loop_recipe_objectives o JOIN loop_recipe_v2_contexts c USING(loop_id)
                JOIN loop_recipe_v2_runs r USING(loop_id) WHERE o.loop_id=?""", (loop_id,)).fetchone()
        if row is None:
            raise LoopContractError("LOOP_PERSISTENT_OBJECTIVE_REQUIRED")
        return dict(row)

    @staticmethod
    def _current(db, loop_id):
        return db.execute("SELECT * FROM loop_recipe_turns WHERE loop_id=? ORDER BY turn DESC LIMIT 1",
                          (loop_id,)).fetchone()

    @staticmethod
    def _check_owner(db, objective):
        work = db.execute("SELECT owner_principal_id,assignment_epoch,state FROM works WHERE work_id=?",
                          (objective["work_id"],)).fetchone()
        if work is None or tuple(work) != (objective["owner_principal_id"],
                                            objective["assignment_epoch"], "ACTIVE"):
            raise LoopContractError("LOOP_WORK_OWNER_OR_EPOCH_CHANGED")

    def status(self, loop_id):
        with self.store._readonly() as db:
            objective = self._objective(db, loop_id)
            turn = self._current(db, loop_id)
            prior = (db.execute("SELECT * FROM loop_recipe_turns WHERE loop_id=? AND turn=?",
                                (loop_id, turn["source_turn"])).fetchone()
                     if turn and turn["source_turn"] is not None else None)
            plan = (db.execute("""SELECT * FROM loop_recipe_detail_plans
                                WHERE loop_id=? AND actor=? AND turn<=?
                                ORDER BY turn DESC, revision DESC LIMIT 1""",
                               (loop_id, turn["actor"], turn["turn"])).fetchone() if turn else None)
            progress = (db.execute("""SELECT * FROM loop_recipe_progress
                        WHERE loop_id=? AND turn=? AND plan_id=? AND plan_revision=?""",
                        (loop_id, plan["turn"], plan["plan_id"], plan["revision"])).fetchone()
                        if plan else None)
            previous_progress = (db.execute("""SELECT * FROM loop_recipe_progress
                        WHERE loop_id=? AND plan_id=? AND plan_revision<?
                        ORDER BY plan_revision DESC LIMIT 1""",
                        (loop_id, plan["plan_id"], plan["revision"])).fetchone()
                        if plan and progress is None else None)
            receipts = {}
            supervisor_return_evidence = None
            for item in (turn, prior):
                if item is None:
                    continue
                watched = db.execute("""SELECT context_json FROM delayed_send_watches
                    WHERE task_id=? AND generation=1 AND source_send_receipt=?""",
                    (item["watch_id"], item["watch_operation_id"])).fetchone()
                item_context = json.loads(watched["context_json"]) if watched else {}
                if item["actor"] == "SUPERVISOR":
                    supervisor_return_evidence = (supervisor_return_evidence
                        or item_context.get("loop_supervisor_return_evidence"))
                for operation_id in (item["watch_operation_id"], item["send_operation_id"]):
                    if operation_id:
                        receipt = db.execute("""SELECT operation_id,state,outcome,error
                            FROM operations WHERE operation_id=? AND work_id=? AND principal_id=?""",
                            (operation_id, objective["work_id"], objective["owner_principal_id"])).fetchone()
                        if receipt:
                            receipts[operation_id] = dict(receipt)
                            if operation_id == item["send_operation_id"] and item_context.get("loop_observed_send"):
                                receipts[operation_id]["reconciliation"] = item_context["loop_observed_send"]
            recovery = None
            if turn:
                watched = db.execute("""SELECT context_json FROM delayed_send_watches
                    WHERE task_id=? AND generation=1""", (turn["watch_id"],)).fetchone()
                context = json.loads(watched["context_json"] or "{}") if watched else {}
                if context.get("recovery_needed"):
                    recovery = {"case_id": self.recovery_case_id(loop_id, turn["turn"]),
                                "signal": context["recovery_needed"],
                                "watch_operation_id": turn["watch_operation_id"],
                                "send_operation_id": turn["send_operation_id"],
                                "next_action": "RECHECK"}
                    latest = db.execute("""SELECT kind,result,evidence_json,created_at
                        FROM node_recovery_checks WHERE case_id=?
                        ORDER BY sequence DESC LIMIT 1""", (recovery["case_id"],)).fetchone()
                    if latest:
                        recovery["latest_check"] = {
                            "kind": latest["kind"], "result": latest["result"],
                            "created_at": latest["created_at"],
                            "evidence": json.loads(latest["evidence_json"]),
                        }
                        if latest["kind"] == "RECHECK":
                            recovery["next_action"] = (
                                "MANAGER_REVIEW" if latest["result"] == "CHECK"
                                else "WAIT_FOR_EXACT_RESPONSE"
                            )
        objective["completion_conditions"] = json.loads(objective.pop("conditions_json"))
        objective["completion"] = json.loads(objective.pop("completion_json") or "null")
        result = {"status": "OK", "objective": objective, "turn": self._turn_view(turn),
                  "planning_guidance": _PLAN_GUIDANCE,
                  "previous_turn": self._turn_view(prior), "plan": dict(plan) if plan else None,
                  "progress": dict(progress) if progress else None,
                  "previous_plan_progress": dict(previous_progress) if previous_progress else None,
                  "receipts": receipts,
                  "node_recovery": recovery, "supervisor_return_evidence": supervisor_return_evidence}
        if plan:
            result["plan"]["plan"] = json.loads(result["plan"].pop("plan_json"))
        return result

    @staticmethod
    def recovery_case_id(loop_id, turn):
        suffix = hashlib.sha256(f"{loop_id}:{turn}".encode()).hexdigest()[:24]
        return f"loop-node-{suffix}"

    @staticmethod
    def _turn_view(row):
        if row is None:
            return None
        value = dict(row)
        value["decision"] = json.loads(value.pop("decision_json") or "null")
        return value

    @staticmethod
    def _insert_turn(db, objective, *, turn, actor, instruction="", source_turn=None, delay=0, deliver=False):
        key = objective["manager_conversation_key" if actor == "MANAGER"
                        else "supervisor_conversation_key"]
        suffix = hashlib.sha256(f"{objective['loop_id']}:{turn}".encode()).hexdigest()[:32]
        watch_id = f"loop-watch-{suffix}"
        db.execute("""INSERT INTO loop_recipe_turns
            (loop_id,turn,actor,conversation_key,watch_id,watch_operation_id,send_operation_id,
             instruction,source_turn,state,due_at)
             VALUES(?,?,?,?,?,?,?,?,?,'PREPARING',?)""", (
            objective["loop_id"], turn, actor, key, watch_id, f"{watch_id}-op",
            f"loop-send-{suffix}" if deliver else None, instruction,
            source_turn, time.time() + delay,
        ))

    @staticmethod
    def _check_topology(db, objective):
        manager = objective["manager_conversation_key"]
        supervisor = objective["supervisor_conversation_key"]
        project = objective["network_project_id"]
        memberships = db.execute("""SELECT project_id,conversation_key
            FROM conversation_network_memberships WHERE activity='ACTIVE'
                AND (project_id=? OR conversation_key IN (?,?))""",
                                 (project, manager, supervisor)).fetchall()
        if [tuple(row) for row in memberships] != [(project, manager)]:
            raise LoopContractError("LOOP_MANAGER_ONLY_NETWORK_REQUIRED")

    def arm(self, loop_id, conversation_key, *, recovery_delay=0):
        with self.store.transaction() as db:
            objective = self._objective(db, loop_id)
            self._check_owner(db, objective)
            if objective["run_state"] == "SUPERSEDED":
                raise LoopContractError("LOOP_RUN_SUPERSEDED")
            if objective["manager_conversation_key"] != conversation_key:
                raise LoopContractError("LOOP_MANAGER_IDENTITY_MISMATCH")
            if self._current(db, loop_id) is None:
                self._check_topology(db, objective)
                if db.execute("SELECT 1 FROM loop_recipe_turns WHERE conversation_key=? AND due_at IS NOT NULL",
                              (conversation_key,)).fetchone():
                    raise LoopContractError("LOOP_CONVERSATION_ALREADY_WATCHED")
                self._insert_turn(db, objective, turn=1, actor="MANAGER", delay=recovery_delay)
        return self.status(loop_id)

    def resume(self, loop_id, turn, conversation_key, instruction):
        instruction = _text(instruction, 2000)
        with self.store.transaction() as db:
            objective = self._objective(db, loop_id)
            self._check_owner(db, objective)
            if objective["run_state"] == "SUPERSEDED":
                raise LoopContractError("LOOP_RUN_SUPERSEDED")
            current = self._current(db, loop_id)
            if (not current or current["turn"] != turn or current["state"] != "BLOCKED"
                    or conversation_key != objective["manager_conversation_key"]):
                raise LoopContractError("LOOP_BLOCKED_MANAGER_RESUME_REQUIRED")
            self._check_topology(db, objective)
            if db.execute("SELECT 1 FROM loop_recipe_turns WHERE conversation_key=? AND due_at IS NOT NULL",
                          (conversation_key,)).fetchone():
                raise LoopContractError("LOOP_CONVERSATION_ALREADY_WATCHED")
            self._insert_turn(db, objective, turn=turn + 1, actor="MANAGER",
                              source_turn=turn, instruction=instruction, deliver=True)
            db.execute("""UPDATE loop_recipe_v2_runs SET state='WAITING',
                current_block_id='resume',revision=revision+1,updated_at=? WHERE loop_id=?""",
                (time.time(), loop_id))
        return self.status(loop_id)

    def _working_turn(self, db, loop_id, turn, conversation_key):
        objective = self._objective(db, loop_id)
        self._check_owner(db, objective)
        current = self._current(db, loop_id)
        if (current is None or current["turn"] != turn or current["conversation_key"] != conversation_key
                or current["state"] != "WATCHING" or current["decision_json"]):
            raise LoopContractError("LOOP_TURN_NOT_CURRENT_OR_READY")
        return objective, current

    def save_plan(self, loop_id, turn, conversation_key, *, plan_id, expected_revision, plan):
        if not _ID.fullmatch(plan_id) or not isinstance(plan, dict):
            raise LoopContractError("LOOP_DETAIL_PLAN_REQUIRED")
        fields = _PLAN_FIELDS
        if any(key in plan for key in _EXECUTION_PLAN_FIELDS):
            fields += _EXECUTION_PLAN_FIELDS
        plan = {key: _text(plan.get(key), 12000 if key in _PLAN_FIELDS else 4000) for key in fields}
        with self.store.transaction() as db:
            _, current = self._working_turn(db, loop_id, turn, conversation_key)
            previous = db.execute("""SELECT actor,revision FROM loop_recipe_detail_plans
                WHERE loop_id=? AND plan_id=? ORDER BY revision DESC LIMIT 1""",
                (loop_id, plan_id)).fetchone()
            if ((previous["revision"] if previous else 0) != expected_revision
                    or previous and previous["actor"] != current["actor"]):
                raise LoopContractError("LOOP_PLAN_REVISION_STALE")
            db.execute("INSERT INTO loop_recipe_detail_plans VALUES(?,?,?,?,?,?)",
                       (loop_id, plan_id, expected_revision + 1, turn, current["actor"], json.dumps(plan)))
        return self.status(loop_id)

    def record_progress(self, loop_id, turn, conversation_key, *, plan_id, revision, progress):
        completed, total = progress.get("completed"), progress.get("total")
        if type(completed) is not int or type(total) is not int or not 0 <= completed <= total or total < 1:
            raise LoopContractError("LOOP_PROGRESS_INVALID")
        evidence = _text(progress.get("evidence"), 4000)
        with self.store.transaction() as db:
            self._working_turn(db, loop_id, turn, conversation_key)
            plan = db.execute("""SELECT plan_id,revision FROM loop_recipe_detail_plans
                    WHERE loop_id=? AND turn=? ORDER BY rowid DESC LIMIT 1""",
                              (loop_id, turn)).fetchone()
            if not plan or tuple(plan) != (plan_id, revision):
                raise LoopContractError("LOOP_PLAN_REVISION_STALE")
            db.execute("""INSERT INTO loop_recipe_progress VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(loop_id,turn,plan_id,plan_revision)
                       DO UPDATE SET completed=excluded.completed,total=excluded.total,evidence=excluded.evidence""",
                       (loop_id, turn, plan_id, revision, completed, total, evidence))
        return self.status(loop_id)

    def decide(self, loop_id, turn, conversation_key, *, decision):
        route = decision.get("route")
        if route not in {"continue", "wait", "handoff", "return", "blocked", "complete"}:
            raise LoopContractError("LOOP_DECISION_INVALID")
        summary = _text(decision.get("result"), 4000)
        next_instruction = _text(decision.get("next_instruction"), 2000) if route != "complete" else ""
        condition_evidence = decision.get("condition_evidence") or {}
        operation_refs = decision.get("operation_refs") or []
        required_capabilities = decision.get("required_capabilities") or []
        if (not isinstance(required_capabilities, list) or len(required_capabilities) > 16
                or any(not isinstance(capability, str) or not _ID.fullmatch(capability)
                       for capability in required_capabilities)
                or required_capabilities and route != "handoff"):
            raise LoopContractError("LOOP_SUPERVISOR_REQUIREMENTS_INVALID")
        delay = decision.get("delay_seconds", 0)
        if type(delay) is not int or not 0 <= delay <= 3600 or (route == "wait" and delay < 2):
            raise LoopContractError("LOOP_WAIT_DELAY_INVALID")
        if not isinstance(condition_evidence, dict) or not isinstance(operation_refs, list):
            raise LoopContractError("LOOP_EVIDENCE_INVALID")
        if len(operation_refs) > 32 or len(condition_evidence) > 64:
            raise LoopContractError("LOOP_EVIDENCE_LIMIT")
        condition_evidence = {k: _text(v, 2000) for k, v in condition_evidence.items()}
        for ref in operation_refs:
            _text(ref, 80)
        with self.store.transaction() as db:
            objective, current = self._working_turn(db, loop_id, turn, conversation_key)
            manager = current["actor"] == "MANAGER"
            if (route in {"handoff", "complete"} and not manager) or (route == "return" and manager):
                raise LoopContractError("LOOP_DECISION_ACTOR_MISMATCH")
            plan = db.execute("""SELECT plan_id,revision,plan_json FROM loop_recipe_detail_plans
                    WHERE loop_id=? AND turn=? AND actor=?
                    ORDER BY rowid DESC LIMIT 1""", (loop_id, turn, current["actor"])).fetchone()
            if plan is None and route not in {"blocked", "wait"}:
                raise LoopContractError("LOOP_DETAIL_PLAN_REQUIRED")
            turn_review = decision.get("turn_review")
            if turn_review is not None or (plan and "target" in json.loads(plan["plan_json"])):
                if not isinstance(turn_review, dict):
                    raise LoopContractError("LOOP_TURN_REVIEW_REQUIRED")
                turn_review = {key: _text(turn_review.get(key), 4000) for key in _REVIEW_FIELDS}
            capabilities = set()
            for ref in operation_refs:
                operation = db.execute("""SELECT capability,created_at FROM operations
                        WHERE operation_id=? AND work_id=? AND principal_id=? AND assignment_epoch=?
                          AND state='FINISHED' AND outcome='APPLIED'""",
                                       (ref, objective["work_id"], objective["owner_principal_id"],
                                        objective["assignment_epoch"])).fetchone()
                if not operation:
                    raise LoopContractError("LOOP_APPLIED_OPERATION_REQUIRED")
                capabilities.add((operation["capability"], operation["created_at"]))
            if route == "return":
                handoff = db.execute("""SELECT turn,decision_json FROM loop_recipe_turns
                    WHERE loop_id=? AND turn<? AND actor='MANAGER'
                    ORDER BY turn DESC LIMIT 1""", (loop_id, turn)).fetchone()
                expected = json.loads(handoff["decision_json"]) if handoff else {}
                if expected.get("route") != "handoff":
                    raise LoopContractError("LOOP_SUPERVISOR_HANDOFF_REQUIRED")
                sent = db.execute("""SELECT o.created_at FROM loop_recipe_turns t
                    JOIN operations o ON o.operation_id=t.send_operation_id
                    JOIN delayed_send_watches w ON w.task_id=t.watch_id AND w.generation=1
                        AND w.source_send_receipt=t.watch_operation_id
                    WHERE t.loop_id=? AND t.turn=? AND o.state='FINISHED'
                    AND (o.outcome='APPLIED' OR (o.outcome='UNKNOWN' AND o.error=?
                        AND json_extract(w.context_json,'$.loop_observed_send.operation_id')=o.operation_id))""",
                                  (loop_id, handoff["turn"] + 1, _UNCONFIRMED_SEND)).fetchone()
                if sent is None:
                    raise LoopContractError("LOOP_SUPERVISOR_HANDOFF_RECEIPT_REQUIRED")
                verified = {capability for capability, created_at in capabilities if created_at >= sent[0]}
                if not set(expected.get("required_capabilities", ())).issubset(verified):
                    raise LoopContractError("LOOP_SUPERVISOR_OPERATION_EVIDENCE_INCOMPLETE")
            if route == "complete":
                source = db.execute("SELECT * FROM loop_recipe_turns WHERE loop_id=? AND turn=?",
                                    (loop_id, current["source_turn"])).fetchone()
                if (source is None or source["actor"] != "SUPERVISOR"
                        or not source["response_turn_key"] or not source["response_sha256"]
                        or json.loads(source["decision_json"])["route"] != "return"):
                    raise LoopContractError("LOOP_SUPERVISOR_RETURN_REQUIRED")
                if condition_evidence.keys() != json.loads(objective["conditions_json"]).keys():
                    raise LoopContractError("LOOP_COMPLETION_EVIDENCE_INCOMPLETE")
            value = {"route": route, "result": summary, "next_instruction": next_instruction,
                     "condition_evidence": condition_evidence, "operation_refs": operation_refs,
                     "plan": {key: plan[key] for key in ("plan_id", "revision")} if plan else None,
                     "delay_seconds": delay, "required_capabilities": required_capabilities}
            if turn_review is not None:
                value["turn_review"] = turn_review
            db.execute("UPDATE loop_recipe_turns SET decision_json=? WHERE loop_id=? AND turn=?",
                       (json.dumps(value), loop_id, turn))
        return self.status(loop_id)

    def due(self, limit=4):
        with self.store._readonly() as db:
            return [dict(row) for row in db.execute("""SELECT * FROM loop_recipe_turns
                WHERE due_at<=? ORDER BY due_at,watch_id LIMIT ?""", (time.time(), limit))]

    def update(self, row, state, delay=None):
        now = time.time()
        with self.store.transaction() as db:
            changed = db.execute("""UPDATE loop_recipe_turns SET state=?,due_at=?
                          WHERE watch_id=? AND state=? AND due_at=?""",
                       (state, now + delay if delay is not None else None,
                        row["watch_id"], row["state"], row["due_at"])).rowcount
            if changed and state == "BLOCKED":
                db.execute("""UPDATE delayed_send_watches SET state='LOOP_BLOCKED'
                    WHERE task_id=? AND generation=1 AND state='WATCHING' AND source_send_receipt=?""",
                           (row["watch_id"], row["watch_operation_id"]))
            if changed and state != row["state"]:
                run_state = {"WATCHING": "ACTIVE", "UNKNOWN": "RECONCILING"}.get(state, state)
                block = "plan" if state == "WATCHING" else "resume"
                db.execute("""UPDATE loop_recipe_v2_runs SET state=?,current_block_id=?,
                    revision=revision+1,updated_at=? WHERE loop_id=?""",
                    (run_state, block, now, row["loop_id"]))

    def observe(self, row, *, turn_key, digest, supervisor_return_evidence=None):
        with self.store.transaction() as db:
            objective = self._objective(db, row["loop_id"])
            self._check_owner(db, objective)
            current = self._current(db, row["loop_id"])
            if current["watch_id"] != row["watch_id"] or current["state"] != "WATCHING":
                return
            decision = json.loads(current["decision_json"] or "null")
            route = decision["route"] if decision else "blocked"
            if supervisor_return_evidence is not None:
                if current["actor"] != "SUPERVISOR" or route != "return":
                    raise LoopContractError("LOOP_SUPERVISOR_RETURN_REQUIRED")
                if not db.execute("""UPDATE delayed_send_watches SET
                    context_json=json_set(context_json,'$.loop_supervisor_return_evidence',json(?))
                    WHERE task_id=? AND generation=1 AND state='WATCHING'
                      AND source_send_receipt=?""",
                    (json.dumps(supervisor_return_evidence), row["watch_id"],
                     row["watch_operation_id"])).rowcount:
                    raise LoopContractError("LOOP_WATCH_RECEIPT_MISMATCH")
            state = "BLOCKED" if route == "blocked" else "OBSERVED"
            db.execute("""UPDATE loop_recipe_turns SET state=?,due_at=NULL,response_turn_key=?,
                           response_sha256=? WHERE watch_id=?""", (state, turn_key, digest, row["watch_id"]))
            db.execute("""UPDATE delayed_send_watches SET state='LOOP_OBSERVED'
                          WHERE task_id=? AND generation=1 AND state='WATCHING'
                            AND source_send_receipt=?""", (row["watch_id"], row["watch_operation_id"]))
            if route == "complete":
                decision["receipt"] = {"watch_id": row["watch_id"], "response_turn_key": turn_key,
                                       "response_sha256": digest, "turn": row["turn"]}
                db.execute("UPDATE loop_recipe_objectives SET completion_json=? WHERE loop_id=?",
                           (json.dumps(decision), row["loop_id"]))
                db.execute("""UPDATE loop_recipe_v2_runs SET state='COMPLETED',
                          current_block_id='complete',revision=revision+1,updated_at=? WHERE loop_id=?""",
                           (time.time(), row["loop_id"]))
            elif route == "blocked":
                db.execute("""UPDATE loop_recipe_v2_runs SET state='BLOCKED',
                    current_block_id='resume',revision=revision+1,updated_at=? WHERE loop_id=?""",
                    (time.time(), row["loop_id"]))
            else:
                actor = {"handoff": "SUPERVISOR", "return": "MANAGER"}.get(route, row["actor"])
                busy = db.execute("SELECT 1 FROM loop_recipe_turns WHERE conversation_key=? AND due_at IS NOT NULL",
                                  (objective["manager_conversation_key" if actor == "MANAGER"
                                             else "supervisor_conversation_key"],)).fetchone()
                if busy:
                    # Keep the source receipt and retry the atomic transition on the existing cadence.
                    raise LoopContractError("LOOP_TARGET_BUSY")
                instruction = decision["next_instruction"]
                if supervisor_return_evidence is not None:
                    instruction += "\nAfter recording your decision, write a final reply in this chat."
                self._insert_turn(db, objective, turn=row["turn"] + 1, actor=actor,
                                  instruction=instruction, source_turn=row["turn"],
                                  delay=decision["delay_seconds"], deliver=True)
                db.execute("""UPDATE loop_recipe_v2_runs SET state='WAITING',
                    current_block_id='resume',revision=revision+1,updated_at=? WHERE loop_id=?""",
                    (time.time(), row["loop_id"]))

    def reconcile_observed_send(self, row, watch, observed):
        context = watch["context"]
        operation_id = row["send_operation_id"]
        resource = f"rcc-instance:{context['instance_id']}:direct-tab:{context['watched_tab_id']}"
        evidence = {
            "kind": "LOOP_EXACT_USER_TURN_OBSERVED", "operation_id": operation_id,
            "watch_operation_id": row["watch_operation_id"], "turn": row["turn"],
            "conversation_key": row["conversation_key"], "instance_id": context["instance_id"],
            "session_id": context["watched_session_id"], "tab_id": context["watched_tab_id"],
            "window_id": context["watched_window_id"], "source_user_turn_key": observed["latestUserTurnKey"],
            "source_user_sha256": observed["latestUserSha256"], "observed_at_ms": observed["observedAt"],
        }
        with self.store.transaction() as db:
            objective = self._objective(db, row["loop_id"])
            self._check_owner(db, objective)
            current = self._current(db, row["loop_id"])
            if (current["watch_id"] != row["watch_id"] or current["state"] != "PREPARING"
                    or current["send_operation_id"] != operation_id):
                return False
            persisted = db.execute("""SELECT context_json FROM delayed_send_watches
                WHERE task_id=? AND generation=1 AND source_send_receipt=? AND state='WATCHING'""",
                (row["watch_id"], row["watch_operation_id"])).fetchone()
            if not persisted or json.loads(persisted["context_json"]) != context:
                return False
            original = db.execute("""SELECT 1 FROM operations WHERE operation_id=? AND work_id=?
                AND principal_id=? AND assignment_epoch=? AND capability='browser' AND target=?
                AND state='FINISHED' AND outcome='UNKNOWN' AND error=?""",
                (operation_id, objective["work_id"], objective["owner_principal_id"],
                 objective["assignment_epoch"], context["instance_id"], _UNCONFIRMED_SEND)).fetchone()
            dispatch = db.execute("""SELECT created_at FROM operation_effect_stages
                WHERE operation_id=? AND stage='DISPATCH_INTENT'""", (operation_id,)).fetchall()
            claims = db.execute("""SELECT resource_key FROM resource_claims
                WHERE operation_id=? AND work_id=? AND assignment_epoch=? AND unresolved=1""",
                (operation_id, objective["work_id"], objective["assignment_epoch"])).fetchall()
            if (not original or len(dispatch) != 1 or len(claims) != 1
                    or claims[0]["resource_key"] != resource
                    or evidence["observed_at_ms"] < dispatch[0]["created_at"] * 1000):
                return False
            db.execute("""UPDATE delayed_send_watches SET
                context_json=json_set(context_json,'$.loop_observed_send',json(?))
                WHERE task_id=? AND generation=1""", (json.dumps(evidence), row["watch_id"]))
            db.execute("""UPDATE resource_claims SET unresolved=0
                WHERE operation_id=? AND resource_key=?""", (operation_id, resource))
            self.store._event(db, "LOOP_SEND_RECONCILED", operation_id, evidence)
        return True

class LoopTurnRunner:
    def __init__(self, service, turns, snapshot):
        self.service = service
        self.turns = turns
        self.snapshot = snapshot
        self.node_recovery = NodeRecoveryLedger(turns.store)

    def _original(self, work, operation_id):
        try:
            return self.turns.store.get_operation_for(
                operation_id=operation_id, work_id=work.work_id,
                principal_id=work.owner_principal_id,
            )
        except KeyError:
            return None

    def _execute(self, work, operation_id, arguments, *, epoch):
        principal = Principal(work.owner_principal_id, "loop-turn", frozenset({"browser"}))
        return self.service.operations.run(principal=principal, work_id=work.work_id,
                                           operation_id=operation_id, capability="browser",
                                           arguments=arguments, expected_assignment_epoch=epoch)

    def run_once(self, *, limit=4):
        events = []
        for row in self.turns.due(limit):
            try:
                result = self.run_turn(row)
            except (KeyError, ValueError) as exc:
                if str(exc) == "LOOP_WORK_OWNER_OR_EPOCH_CHANGED":
                    self.turns.update(row, "BLOCKED")
                else:
                    self.turns.update(row, row["state"], 15)
                result = type(exc).__name__
            except Exception as exc:
                self.turns.update(row, row["state"], 15)
                result = type(exc).__name__
            events.append({"watch_id": row["watch_id"], "state": result})
        return events

    def run_turn(self, row):
        with self.turns.store._readonly() as db:
            objective = self.turns._objective(db, row["loop_id"])
            self.turns._check_owner(db, objective)
            current = self.turns._current(db, row["loop_id"])
            if current is None or current["watch_id"] != row["watch_id"]:
                return "STALE"
        if row["state"] == "PREPARING":
            return self._prepare(row, objective)
        watch = self._watch_binding(row, objective)
        if watch["state"] != "WATCHING":
            self.turns.update(row, "UNKNOWN" if watch["state"] == "UNKNOWN" else "BLOCKED")
            return watch["state"]
        # Reuse the delayed Watch's exact RCC stop observation, then persist
        # CHECK/RECHECK on the existing node-recovery ledger. Neither step sends
        # a message, reloads a tab, or replaces the Manager.
        recovery = self.service._recover_if_stopped(watch)
        if recovery.get("status") in {"RECOVERY_NEEDED", "RECOVERY_ALREADY_REPORTED"} \
                or watch["context"].get("recovery_needed"):
            self._check_recovery(row, objective)
        observed = self.service._response_for(watch)
        if observed and observed["response_complete"] and observed["input_ready"]:
            self.turns.observe(row, turn_key=observed["response_turn_key"],
                               digest=observed["response_sha256"])
            return "OBSERVED"
        evidence = self._supervisor_return_evidence(current, watch, objective)
        if evidence:
            digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
            self.turns.observe(row, turn_key=evidence["turn_key"], digest=digest,
                               supervisor_return_evidence=evidence)
            return "OBSERVED"
        self.turns.update(row, "WATCHING", 4)
        return "WATCHING"

    def _supervisor_return_evidence(self, turn, watch, objective):
        decision = json.loads(turn["decision_json"] or "{}")
        if turn["actor"] != "SUPERVISOR" or decision.get("route") != "return":
            return None
        context = watch["context"]
        send_id = turn["send_operation_id"]
        source_sha = context.get("source_user_sha256") or ""
        conversation = turn["conversation_key"]
        instance = context["instance_id"]
        if (not send_id or context.get("source_proof_kind") != "BCT_PLANNED_SOURCE_SEND"
                or not re.fullmatch(r"[a-f0-9]{64}", source_sha)
                or context.get("source_send_sha256") != source_sha):
            return None
        work = self.turns.store.get_work(objective["work_id"])
        receipt = self._original(work, send_id)
        if not receipt or receipt.state != OperationState.FINISHED:
            return None
        direct = (receipt.outcome == Outcome.APPLIED
                  and all(receipt.evidence.get(key) == value for key, value in {
                    "command": "send-to-tab", "host_request_id": send_id,
                    "instance_id": instance, "conversation_key": conversation,
                    "source_message_sha256": source_sha,
                }.items()))
        attachment = loop_observed_send_binding(context) if receipt.outcome == Outcome.UNKNOWN else None
        if not direct and not attachment:
            return None
        observed = (self.service.latest(instance_id=instance, conversation_key=conversation,
                                        expected_attachment=attachment)
                    if attachment else self.service.latest(instance_id=instance, conversation_key=conversation))
        if attachment and not loop_observed_send_matches(context, observed):
            return None
        turn_key = observed.get("completedLatestUserTurnKey")
        user_turn_key = observed.get("latestUserTurnKey")
        if (observed.get("ok") is not True or observed.get("conversationKey") != conversation
                or observed.get("generating") is not False
                or not isinstance(turn_key, str) or not turn_key.strip()
                or not isinstance(user_turn_key, str) or not user_turn_key.strip()
                or observed.get("latestUserSha256") != source_sha
                or observed.get("latestUserTextOccurrenceCount") != 1):
            return None
        return {"kind": "RCC_COMPLETED_TURN_WITH_SAVED_SUPERVISOR_RETURN",
                "conversation_key": conversation, "turn_key": turn_key,
                "source_user_turn_key": user_turn_key, "source_user_sha256": source_sha,
                "send_operation_id": send_id, "watch_operation_id": turn["watch_operation_id"],
                "decision_sha256": hashlib.sha256(turn["decision_json"].encode()).hexdigest()}

    def _check_recovery(self, row, objective):
        work = self.turns.store.get_work(objective["work_id"])
        case_id = self.turns.recovery_case_id(row["loop_id"], row["turn"])
        previous = self.node_recovery.get(work=work, case_id=case_id)
        latest = previous.get("latest_check") if previous else None
        # One automatic CHECK and one RECHECK are enough to identify a stable
        # failure. Further recovery remains an explicit Manager/operator choice.
        if latest and (latest["kind"] == "RECHECK"
                       or time.time() - latest["created_at"] < 4):
            return
        snapshot = self.snapshot()
        view = status_view(snapshot if "monitor" in snapshot else {"monitor": snapshot}, "node")
        evidence = observe_node(view, row["conversation_key"])
        self.node_recovery.check(
            work=work, case_id=case_id, task_id=objective["task_id"],
            conversation_key=row["conversation_key"], evidence=evidence,
            kind="RECHECK" if latest else "CHECK",
        )

    def _watch_binding(self, row, objective):
        watch = self.service.ledger.get(row["watch_id"], 1)
        if not watch or watch["source_send_receipt"] != row["watch_operation_id"]:
            raise LoopContractError("LOOP_WATCH_RECEIPT_MISMATCH")
        watch["context"] = json.loads(watch.pop("context_json"))
        context = watch["context"]
        if (watch["conversation_key"] != row["conversation_key"]
                or context["work_id"] != objective["work_id"]
                or context["assignment_epoch"] != objective["assignment_epoch"]
                or context["principal_id"] != objective["owner_principal_id"]
                or context.get("execution_path") != "LOOP"
                or context.get("source_send_operation_id") != (row["send_operation_id"] or None)):
            raise LoopContractError("LOOP_WATCH_BINDING_MISMATCH")
        return watch

    def register_initial_watch(self, loop_id, target):
        with self.turns.store._readonly() as db:
            objective = self.turns._objective(db, loop_id)
            self.turns._check_owner(db, objective)
            row = self.turns._current(db, loop_id)
        if (row and row["turn"] == 1 and row["state"] == "PREPARING"
                and row["actor"] == "MANAGER" and not row["send_operation_id"]
                and row["conversation_key"] == target["conversation_key"]):
            return self._prepare(row, objective, initial_target=target)
        return "LOOP_FIRST_WATCH_NOT_PREPARING"

    def _prepare(self, row, objective, *, initial_target=None):
        from bct.loop_self_dispatch import LoopSelfDispatcher

        work = self.turns.store.get_work(objective["work_id"])
        conversation = row["conversation_key"]
        watch = self._original(work, row["watch_operation_id"])
        if watch and self._check_receipt(row, watch) != "APPLIED":
            return "WATCH_RECEIPT_PENDING_OR_HELD"
        send_id = row["send_operation_id"]
        sent = self._original(work, send_id) if send_id else None
        if sent or (watch and not send_id):
            if not watch:
                raise LoopContractError("LOOP_WATCH_RECEIPT_MISMATCH")
            binding = self._watch_binding(row, objective)
            if sent and sent.outcome == Outcome.UNKNOWN and sent.error == _UNCONFIRMED_SEND:
                if not self._reconcile_unknown_send(row, binding):
                    self.turns.update(row, "PREPARING", 15)
                    return "SEND_RECEIPT_PENDING_OR_HELD"
            elif sent and self._check_receipt(row, sent) != "APPLIED":
                return "SEND_RECEIPT_PENDING_OR_HELD"
            if not self._verify_initial_source(row, objective, binding):
                return "LOOP_INITIAL_USER_INSTRUCTION_MISMATCH"
            self.turns.update(row, "WATCHING", 0)
            return "WATCHING"
        with self.turns.store._readonly() as db:
            self.turns._check_topology(db, objective)
        NodeRecoveryLedger(self.turns.store).assert_send_allowed(
            work_id=work.work_id, conversation_key=conversation,
        )
        # The route comes from fresh RCC state, independently of advisory Node Info.
        target = initial_target or LoopSelfDispatcher.exact_route(
            self.snapshot(), conversation, require_idle=bool(send_id),
        )
        message = ""
        if row["send_operation_id"]:
            message = (
                f"LOOP {row['loop_id']} | Work {work.work_id} | Task {objective['task_id']} "
                f"| Turn {row['turn']} | Role {row['actor']}\n"
                f"Read bct_loop_recipe(action='status', loop_id='{row['loop_id']}') first. "
                "Compare this turn's instruction, the original request, overall plan and "
                "completion conditions with the previous turn's result and receipts. "
                "Follow planning_guidance from status. Keep the same plan_id across turns for "
                "the same deliverable. Execute an actionable step, compare the actual output to "
                "the plan, and save turn_review in action='decide' before ending your response. "
                "For save_plan and decide, supply the current turn and your conversation key "
                "from status. If the turn is still PREPARING, reread status once it is WATCHING.\n\n"
                + row["instruction"]
            )
        arguments = {
            "command": "send-delayed-message", "task_id": row["watch_id"],
            "instance_id": target["instance_id"], "conversation_key": conversation,
            "manager_conversation_key": conversation, "manager_instance_id": target["instance_id"],
            "execution_path": "LOOP", "exclusive_conversation_watch": True,
            "watched_session_id": target["session_id"], "watched_tab_id": target["tab_id"],
            "watched_window_id": target["window_id"],
        }
        if message:
            arguments.update(planned_send_operation_id=row["send_operation_id"], planned_send_text=message)
        if watch is None:
            watch = self._execute(work, row["watch_operation_id"], arguments,
                                  epoch=objective["assignment_epoch"])
            if self._check_receipt(row, watch) != "APPLIED":
                return "WATCH_RECEIPT_PENDING_OR_HELD"
        stored_watch = self._watch_binding(row, objective)
        if stored_watch["state"] != "WATCHING":
            raise LoopContractError("LOOP_WATCH_RECEIPT_MISMATCH")
        if not self._verify_initial_source(row, objective, stored_watch):
            return "LOOP_INITIAL_USER_INSTRUCTION_MISMATCH"
        if message:
            context = stored_watch["context"]
            if context.get("source_send_sha256") != _rcc_submitted_text_sha256(message):
                raise LoopContractError("LOOP_WATCH_PAYLOAD_MISMATCH")
            if any(context.get("watched_" + field) != target[field]
                   for field in ("session_id", "tab_id", "window_id")):
                raise LoopContractError("LOOP_WATCH_ATTACHMENT_CHANGED")
            sent = self._execute(work, send_id, {
                "command": "send-message", **target, "text": message,
            }, epoch=objective["assignment_epoch"])
            if self._check_receipt(row, sent) != "APPLIED":
                return "SEND_RECEIPT_PENDING_OR_HELD"
        self.turns.update(row, "WATCHING", 0)
        return "WATCHING"

    def _reconcile_unknown_send(self, row, watch):
        if watch["state"] != "WATCHING":
            return False
        ctx = watch["context"]
        if loop_observed_send_binding(ctx):
            return True
        attachment = (ctx.get("watched_session_id"), ctx.get("watched_tab_id"),
                      ctx.get("watched_window_id"))
        source = ctx.get("source_send_sha256") or ""
        if (not all(attachment) or ctx.get("source_proof_kind") != "BCT_PLANNED_SOURCE_SEND"
                or not re.fullmatch(r"[a-f0-9]{64}", source)
                or source != ctx.get("source_user_sha256") or source == ctx.get("baseline_user_sha")):
            return False
        observed = self.service.latest(instance_id=ctx["instance_id"],
                                       conversation_key=row["conversation_key"],
                                       expected_attachment=attachment)
        user_key = observed.get("latestUserTurnKey")
        if (observed.get("ok") is not True or observed.get("conversationKey") != row["conversation_key"]
                or (observed.get("tabId"), observed.get("windowId")) != attachment[1:]
                or observed.get("latestUserSha256") != source
                or type(observed.get("latestUserTextOccurrenceCount")) is not int
                or observed["latestUserTextOccurrenceCount"] != 1
                or not isinstance(user_key, str) or not user_key.strip()
                or type(observed.get("observedAt")) is not int):
            return False
        return self.turns.reconcile_observed_send(row, watch, observed)

    def _verify_initial_source(self, row, objective, watch):
        if row["turn"] != 1:
            if row["source_turn"] != 1 or row["send_operation_id"]:
                return True
            with self.turns.store._readonly() as db:
                previous = db.execute("""SELECT response_turn_key FROM loop_recipe_turns
                                       WHERE loop_id=? AND turn=1""", (row["loop_id"],)).fetchone()
            if previous and previous["response_turn_key"]:
                return True
        context = watch["context"]
        if (context.get("source_proof_kind") == "RCC_PREARM_USER_TURN"
                and context.get("source_user_turn_key")
                and context.get("source_user_sha256")
                    == _rcc_submitted_text_sha256(objective["instruction_text"])):
            return True
        self.turns.update(row, "BLOCKED")
        return False

    def _check_receipt(self, row, receipt):
        if receipt.outcome == Outcome.APPLIED:
            return "APPLIED"
        if receipt.outcome in {Outcome.FAILED, Outcome.NOT_APPLIED}:
            self.turns.update(row, "BLOCKED")
        else:
            self.turns.update(row, row["state"], 15)
        return "HELD"
