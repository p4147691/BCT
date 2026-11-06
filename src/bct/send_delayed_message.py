"""One-response Send Delayed Message continuation for BCT Task Run.

This module owns the state transition, not RCC delivery. Callers supply the
existing durable watch registration and send-message implementations.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .continuation_primitives import (
    ActionRequest, Alarm, ContinuationContext, ContinuationDecision,
    ContinuationRoute, branch_for_decision, response_ready_alarm,
    send_message_for_branch,
)


def _rcc_submitted_text_sha256(message: str) -> str:
    """Match RCC RelayCore.normalizeMessageText before comparing DOM source SHA."""
    normalized = message.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    normalized = "\n".join(re.sub(r"[ \t]+$", "", line)
                           for line in normalized.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _self_message_with_execute_plan(message: str, plan: dict | None) -> str:
    """Carry B's exact saved plan into the next turn of the same Chain."""
    if plan is None:
        return message
    return (
        "이전 B 턴에서 이 Chain에 저장한 Execute Plan입니다. "
        "A Direction의 범위와 금지사항 안에서 이 계획을 실행하세요.\n"
        f"plan_id={plan['plan_id']}, plan_sha256={plan['plan_sha256']}\n"
        "[Execute Plan]\n"
        f"{plan['plan_text']}\n"
        "[/Execute Plan]\n\n"
        "이번 SELF 지시:\n"
        + message
    )


def _self_prearm_guidance(*, work_id: str, task_id: str) -> str:
    """Give an ordinary Chat worker one exact public rearm call.

    The next generation is already reserved and carries the exact worker,
    manager and RCC source-send binding.  Asking the worker to rediscover a
    target through the generic execute capability is both unnecessary and
    error-prone, so the continuation names the narrow public command and the
    only two required identifiers.
    """
    return (
        "다음 BB 응답 감시를 먼저 선예약하세요. 아래 공개 명령을 그대로 호출합니다.\n"
        f'`bct_send_delayed_message(work_id="{work_id}", task_id="{task_id}")`\n'
        "이 SELF 회차에는 대상·창·탭을 다시 고르지 않습니다. 이전 정확 전송의 예약 문맥을 "
        "재사용하므로 범용 execute capability를 사용하지 마세요. "
        "선예약 결과가 APPLIED인지 확인한 뒤에만 아래 작업을 시작하세요."
    )


class NextTarget(str, Enum):
    SELF = "SELF"
    MANAGER = "MANAGER"


@dataclass(frozen=True)
class NextInstruction:
    target: NextTarget
    text: str


@dataclass(frozen=True)
class Watch:
    task_id: str
    generation: int
    conversation_key: str
    response_turn_id: str
    source_send_receipt: str


@dataclass(frozen=True)
class Continuation:
    status: str
    next_watch: Watch | None = None
    send_receipt: str | None = None


class InstructionError(ValueError):
    pass


def extract_next_instruction(response: str) -> NextInstruction:
    """Read an explicit final instruction block, never guess from ordinary prose."""
    if not isinstance(response, str):
        raise InstructionError("NEXT_INSTRUCTION_NOT_TEXT")
    lines = response.rstrip().splitlines()
    marker_pattern = re.compile(
        r"^(NEXT TASK — (?:SELF|MANAGER))(?:\s*[:：]\s*(.*))?$"
    )
    markers = []
    for index, line in enumerate(lines):
        match = marker_pattern.fullmatch(line.strip())
        if match is not None:
            markers.append((index, match.group(1), match.group(2) or ""))
    if not markers or markers[0][0] == len(lines)-1:
        # An inline body after ':' is a complete instruction even when the
        # marker is the final rendered line.
        if not markers or not markers[0][2].strip():
            raise InstructionError("NEXT_INSTRUCTION_MISSING_OR_AMBIGUOUS")
    targets = {value for _, value, _ in markers}
    if len(targets) != 1:
        raise InstructionError("NEXT_INSTRUCTION_MISSING_OR_AMBIGUOUS")
    idx, marker, inline_body = markers[0]
    # ChatGPT may render the same semantic marker once as a response heading
    # and once inside a generated report/artifact. Identical routes are not a
    # branch ambiguity. Preserve every following line in order while removing
    # only duplicate copies of that exact marker. Mixed SELF/MANAGER markers
    # remain rejected above.
    body_lines = [inline_body] if inline_body.strip() else []
    for line in lines[idx+1:]:
        duplicate = marker_pattern.fullmatch(line.strip())
        if duplicate is not None:
            if duplicate.group(1) == marker and (duplicate.group(2) or "").strip():
                body_lines.append(duplicate.group(2))
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()
    if not body or len(body) > 10800:
        raise InstructionError("NEXT_INSTRUCTION_INVALID")
    return NextInstruction(
        NextTarget.SELF if marker.endswith("SELF") else NextTarget.MANAGER,
        body,
    )


def next_instruction_action(alarm) -> ActionRequest:
    """Turn the legacy explicit marker into a recipe action request.

    This is intentionally the only place where the Delayed Send compatibility
    recipe interprets `NEXT TASK`.  The primitive alarm itself remains neutral
    about message syntax and destination policy.
    """
    return send_message_for_branch(
        alarm=alarm, branch=branch_for_decision(next_instruction_decision(alarm)),
    )


def next_instruction_decision(alarm) -> ContinuationDecision:
    """Compatibility adapter: make the finishing B turn's decision explicit.

    Legacy responses encode this decision in ``NEXT TASK``.  The continuation
    boundary records the decoded decision before it routes a BB/BA delivery.
    """
    instruction = extract_next_instruction(alarm.evidence.response_text)
    route = (ContinuationRoute.SELF if instruction.target == NextTarget.SELF
             else ContinuationRoute.MANAGER)
    return ContinuationDecision(route=route, payload=instruction.text)



def bind_next_response(watch: Watch, *, send_receipt: str,
                       response_turn_id: str) -> Watch:
    """Bind the pre-reserved next watch to the exact new send and response."""
    if watch.response_turn_id or watch.source_send_receipt:
        raise ValueError("NEXT_WATCH_ALREADY_BOUND")
    if not send_receipt or not response_turn_id:
        raise ValueError("NEXT_WATCH_RECEIPT_REQUIRED")
    return Watch(watch.task_id, watch.generation, watch.conversation_key,
                 response_turn_id, send_receipt)


def dispatch_send_delayed_message(
    *, watch: Watch, alarm: Alarm, decision: ContinuationDecision,
    manager_conversation_key: str, register_next_watch: Callable[[Watch], None],
    send_message: Callable[[str, str, str], str],
) -> Continuation:
    """Perform the message-only action of the Send Delayed Message recipe.

    The caller has already observed the exact response, created an alarm, and
    recorded the prior B turn's decision.  This function deliberately owns
    only the legacy ``SELF/MANAGER -> send message`` branch.  A future Delayed
    Wakeup Message recipe can consume the same alarm and decision without
    changing watch or alarm behavior.
    """
    branch = branch_for_decision(decision)
    action = send_message_for_branch(alarm=alarm, branch=branch)
    key = hashlib.sha256(
        f"{watch.task_id}|{watch.generation}|{watch.response_turn_id}".encode()
    ).hexdigest()[:24]
    if action.recipient_role == "worker":
        next_watch = Watch(watch.task_id, watch.generation+1,
                           watch.conversation_key, "", "")
        register_next_watch(next_watch)
        receipt = send_message(watch.conversation_key, action.payload,
                               "delayed-self-" + key)
        return Continuation("SELF_SENT", next_watch, receipt)
    receipt = send_message(manager_conversation_key, action.payload,
                           "delayed-manager-" + key)
    return Continuation("RETURNED_TO_MANAGER", None, receipt)


def continue_send_delayed_message(
    *, watch: Watch, response_turn_id: str, response_text: str,
    response_complete: bool, input_ready: bool, manager_conversation_key: str,
    register_next_watch: Callable[[Watch], None],
    send_message: Callable[[str, str, str], str],
) -> Continuation:
    """Reserve next watch before SELF send; sender owns durable idempotency.

    One call handles one observed assistant response. The caller persists the
    watch/operation and uses the existing RCC send receipt for the effect.
    """
    if response_turn_id != watch.response_turn_id:
        return Continuation("WAITING_EXPECTED_RESPONSE")
    if not response_complete or not input_ready:
        return Continuation("WAITING_RESPONSE")
    alarm = response_ready_alarm(
        watch_ref=f"{watch.task_id}:{watch.generation}",
        subject_ref=watch.conversation_key,
        expected_response_turn_id=watch.response_turn_id,
        response_turn_id=response_turn_id,
        response_text=response_text,
        response_complete=response_complete,
        input_ready=input_ready,
    )
    if alarm is None:
        return Continuation("WAITING_RESPONSE")
    try:
        decision = next_instruction_decision(alarm)
    except InstructionError:
        return Continuation("INSTRUCTION_UNAVAILABLE")
    return dispatch_send_delayed_message(
        watch=watch, alarm=alarm, decision=decision,
        manager_conversation_key=manager_conversation_key,
        register_next_watch=register_next_watch, send_message=send_message,
    )

def continue_send_delayed_message_from_rcc(
    *, watch: Watch, observation: dict, manager_conversation_key: str,
    register_next_watch: Callable[[Watch], None],
    send_message: Callable[[str, str, str], str],
) -> Continuation:
    """Translate an RCC response observation into one continuation transition.

    The RCC adapter must supply the exact completed response turn and verified
    input readiness. A missing field is a pending observation, never permission
    to submit a message.
    """
    if not isinstance(observation, dict):
        return Continuation("WAITING_RESPONSE")
    if observation.get("conversation_key") != watch.conversation_key:
        return Continuation("WAITING_EXPECTED_RESPONSE")
    turn = str(observation.get("response_turn_id") or "")
    body = observation.get("response_text")
    if not isinstance(body, str):
        return Continuation("WAITING_RESPONSE")
    return continue_send_delayed_message(
        watch=watch, response_turn_id=turn, response_text=body,
        response_complete=observation.get("response_complete") is True,
        input_ready=observation.get("input_ready") is True,
        manager_conversation_key=manager_conversation_key,
        register_next_watch=register_next_watch,
        send_message=send_message,
    )


class DurableWatchLedger:
    """Persist watch generations inside the existing BCT SQLite database."""
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS delayed_send_watches (
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    conversation_key TEXT NOT NULL,
                    response_turn_id TEXT NOT NULL,
                    source_send_receipt TEXT NOT NULL,
                    state TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(task_id,generation)
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(delayed_send_watches)")}
            if "context_json" not in columns:
                db.execute("ALTER TABLE delayed_send_watches ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
            db.execute("""
                CREATE TABLE IF NOT EXISTS continuation_alarms (
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    PRIMARY KEY(task_id, generation, kind)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS continuation_decisions (
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    route TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    response_turn_key TEXT NOT NULL,
                    response_sha256 TEXT NOT NULL,
                    PRIMARY KEY(task_id, generation)
                )
            """)

    def reserve(self, watch: Watch) -> bool:
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT * FROM delayed_send_watches WHERE task_id=? AND generation=?",
                (watch.task_id,watch.generation)).fetchone()
            if current is not None:
                if (current["conversation_key"] != watch.conversation_key
                    or current["response_turn_id"] != watch.response_turn_id
                    or current["source_send_receipt"] != watch.source_send_receipt):
                    raise ValueError("DELAYED_WATCH_CONFLICT")
                return False
            db.execute(
                "INSERT INTO delayed_send_watches(task_id,generation,conversation_key,response_turn_id,source_send_receipt,state) VALUES(?,?,?,?,?,?)",
                (watch.task_id,watch.generation,watch.conversation_key,
                 watch.response_turn_id,watch.source_send_receipt,"RESERVED"))
            return True

    def reserve_next(self, parent: Watch, next_watch: Watch) -> bool:
        """Reserve BB's next turn and carry only recipe invariants forward."""
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT * FROM delayed_send_watches WHERE task_id=? AND generation=?",
                (next_watch.task_id, next_watch.generation),
            ).fetchone()
            if current is not None:
                if (current["conversation_key"] != next_watch.conversation_key
                    or current["response_turn_id"] != next_watch.response_turn_id
                    or current["source_send_receipt"] != next_watch.source_send_receipt):
                    raise ValueError("DELAYED_WATCH_CONFLICT")
                return False
            row = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=?",
                (parent.task_id, parent.generation),
            ).fetchone()
            parent_context = json.loads(row["context_json"] or "{}") if row else {}
            carried = {
                key: parent_context[key] for key in
                ("recipe", "max_generations") if key in parent_context
            }
            # Legacy and Task Message watches predate execution-path
            # provenance. Do not rewrite their receipt shape by carrying empty
            # placeholders, while preserving an actually declared/direct path
            # across BB generations.
            for key in ("execution_path", "chain_direction_id"):
                if parent_context.get(key):
                    carried[key] = parent_context[key]
            db.execute(
                "INSERT INTO delayed_send_watches("
                "task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) VALUES(?,?,?,?,?,?,?)",
                (next_watch.task_id, next_watch.generation,
                 next_watch.conversation_key, next_watch.response_turn_id,
                 next_watch.source_send_receipt, "RESERVED",
                 json.dumps(carried, sort_keys=True)),
            )
        return True

    def prearm(self, watch: Watch) -> bool:
        """Worker registers a one-turn watch before beginning its task."""
        if not watch.response_turn_id or not watch.source_send_receipt:
            raise ValueError("DELAYED_PREARM_SOURCE_REQUIRED")
        created = self.reserve(watch)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='WATCHING' "
                "WHERE task_id=? AND generation=? AND state='RESERVED'",
                (watch.task_id,watch.generation))
        return created

    def prearm_task(self, *, task_id: str, work_id: str, principal_id: str,
                    assignment_epoch: int, instance_id: str,
                    conversation_key: str, manager_conversation_key: str,
                    manager_instance_id: str, baseline: dict,
                    registration_receipt: str, planned_send_operation_id: str = "",
                    planned_send_text: str = "",
                    execution_path: str = "", chain_direction_id: str = "",
                    exclusive_conversation_watch: bool = False,
                    max_generations: int = 0, watched_session_id: str = "",
                    watched_tab_id: int = 0, watched_window_id: int = 0) -> dict:
        """Worker prearms one current response, reusing any reserved next turn."""
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id):
            raise ValueError("DELAYED_TASK_ID_INVALID")
        if type(max_generations) is not int or not 0 <= max_generations <= 12:
            raise ValueError("DELAYED_MAX_GENERATIONS_INVALID")
        if execution_path not in {"", "DIRECTION_DECLARED", "DIRECT_EXACT_TARGET"}:
            raise ValueError("DELAYED_EXECUTION_PATH_INVALID")
        if chain_direction_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", chain_direction_id):
            raise ValueError("DELAYED_CHAIN_DIRECTION_ID_INVALID")
        if (execution_path == "DIRECTION_DECLARED") != bool(chain_direction_id):
            raise ValueError("DELAYED_EXECUTION_PATH_DIRECTION_MISMATCH")
        planned = bool(planned_send_operation_id or planned_send_text)
        if planned:
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", planned_send_operation_id)
                    or not planned_send_text or len(planned_send_text) > 12000):
                raise ValueError("DELAYED_PLANNED_SOURCE_INVALID")
        elif (baseline.get("terminal") is True
              and baseline.get("generating") is False
              and baseline.get("inputReady") is True
              and baseline.get("latestUserSha256")
              and baseline.get("latestUserSha256") == baseline.get("responseSourceUserSha256")
              and baseline.get("latestUserTurnKey")
              and baseline.get("latestUserTurnKey") == baseline.get("responseSourceUserTurnKey")):
            raise ValueError("DELAYED_PREARM_RESPONSE_ALREADY_TERMINAL")
        context = ContinuationContext.delayed_send(
            work_id=work_id, principal_id=principal_id,
            assignment_epoch=assignment_epoch, instance_id=instance_id,
            conversation_key=conversation_key,
            manager_conversation_key=manager_conversation_key,
            manager_instance_id=manager_instance_id,
        ).as_legacy_record() | {
            "baseline_count": baseline.get("responseTurnCount"),
            "baseline_generating": baseline.get("generating") is True,
            "baseline_key": str(baseline.get("responseTurnKey") or ""),
            "baseline_sha": str(baseline.get("responseSha256") or ""),
            "source_user_turn_key": str(baseline.get("latestUserTurnKey") or ""),
            "source_user_sha256": str(baseline.get("latestUserSha256") or ""),
            "max_generations": max_generations,
            "execution_path": execution_path,
            "chain_direction_id": chain_direction_id,
        }
        if watched_session_id and watched_tab_id > 0 and watched_window_id > 0:
            context.update({
                "watched_session_id": watched_session_id,
                "watched_tab_id": watched_tab_id,
                "watched_window_id": watched_window_id,
            })
        if max_generations:
            context["recipe"] = "task-message-v1"
        if not isinstance(context["baseline_count"], int) or context["baseline_count"] < 0:
            raise ValueError("DELAYED_RCC_TURN_COUNT_UNAVAILABLE")
        if planned:
            # No user turn exists yet: reserve against the *previous* Assistant
            # and bind the future source only via an exact BCT send receipt.
            context["source_proof_kind"] = "BCT_PLANNED_SOURCE_SEND"
            context["source_user_turn_key"] = ""
            context["source_user_sha256"] = _rcc_submitted_text_sha256(planned_send_text)
            context["source_send_operation_id"] = planned_send_operation_id
            context["source_send_sha256"] = context["source_user_sha256"]
        else:
            # Manually submitted task: anchor the currently observed user turn.
            if (not context["source_user_turn_key"]
                    or not re.fullmatch(r"[0-9a-f]{64}", context["source_user_sha256"])
                    or (context["source_user_turn_key"].startswith("fallback-turn-")
                        and baseline.get("latestUserTextOccurrenceCount") != 1)):
                raise ValueError("DELAYED_SOURCE_USER_PROOF_REQUIRED")
            context["source_proof_kind"] = "RCC_PREARM_USER_TURN"
        with self.store.transaction() as db:
            if exclusive_conversation_watch:
                overlapping = db.execute(
                    "SELECT task_id,generation FROM delayed_send_watches "
                    "WHERE state='WATCHING' AND conversation_key=? AND task_id!=? "
                    "AND json_extract(context_json,'$.work_id')=? "
                    "AND json_extract(context_json,'$.assignment_epoch')=? "
                    "ORDER BY task_id,generation LIMIT 1",
                    (conversation_key, task_id, work_id, assignment_epoch),
                ).fetchone()
                if overlapping is not None:
                    raise ValueError("DELAYED_CONVERSATION_ALREADY_WATCHING")
            existing = db.execute(
                "SELECT * FROM delayed_send_watches WHERE task_id=? "
                "ORDER BY generation DESC LIMIT 1", (task_id,)
            ).fetchone()
            if existing is None:
                gen = 1
                db.execute(
                    "INSERT INTO delayed_send_watches("
                    "task_id,generation,conversation_key,response_turn_id,"
                    "source_send_receipt,state,context_json) VALUES(?,?,?,?,?,?,?)",
                    (task_id,gen,conversation_key,f"task:{task_id}:{gen}",
                     registration_receipt,"WATCHING",
                     json.dumps(context,sort_keys=True)),
                )
                created = True
            elif existing["state"] == "RESERVED":
                gen = int(existing["generation"])
                if existing["conversation_key"] != conversation_key:
                    raise ValueError("DELAYED_WORKER_CHANGED")
                old = json.loads(existing["context_json"] or "{}")
                if (("work_id" in old and old["work_id"] != work_id)
                        or ("manager_conversation_key" in old
                            and old["manager_conversation_key"] != manager_conversation_key)):
                    raise ValueError("DELAYED_CONTEXT_CHANGED")
                context.update({
                    key: old[key] for key in
                    ("source_send_operation_id", "source_send_sha256",
                     "recipe", "max_generations", "execution_path",
                     "chain_direction_id") if key in old
                })
                db.execute(
                    "UPDATE delayed_send_watches SET response_turn_id=?, "
                    "source_send_receipt=?,state='WATCHING',context_json=? "
                    "WHERE task_id=? AND generation=? AND state='RESERVED'",
                    (f"task:{task_id}:{gen}",registration_receipt,
                     json.dumps(context,sort_keys=True),task_id,gen),
                )
                created = True
            elif existing["state"] == "WATCHING":
                gen = int(existing["generation"])
                old = json.loads(existing["context_json"] or "{}")
                if (existing["conversation_key"] != conversation_key
                        or old.get("work_id") != work_id
                        or old.get("manager_conversation_key") != manager_conversation_key
                    or old.get("max_generations", 0) != max_generations
                    or (planned and (old.get("source_send_operation_id") != planned_send_operation_id
                                     or old.get("source_send_sha256") != context["source_send_sha256"]))):
                    raise ValueError("DELAYED_CONTEXT_CHANGED")
                created = False
            else:
                raise ValueError("DELAYED_TASK_ALREADY_FINISHED")
        return {"task_id":task_id,"generation":gen,"state":"WATCHING","created":created}

    def cancel_task(self, *, task_id: str, generation: int,
                    work_id: str, principal_id: str, assignment_epoch: int) -> dict:
        """Cancel exactly one WATCHING generation, never dispatch or touch others."""
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id):
            raise ValueError("DELAYED_TASK_ID_INVALID")
        if type(generation) is not int or generation < 1:
            raise ValueError("DELAYED_GENERATION_INVALID")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT state,context_json FROM delayed_send_watches "
                "WHERE task_id=? AND generation=?", (task_id, generation)
            ).fetchone()
            if row is None:
                raise ValueError("DELAYED_WATCH_NOT_FOUND")
            context = json.loads(row["context_json"] or "{}")
            if (context.get("work_id") != work_id
                    or context.get("principal_id") != principal_id
                    or context.get("assignment_epoch") != assignment_epoch):
                raise ValueError("DELAYED_CANCEL_OWNER_MISMATCH")
            if row["state"] == "CANCELLED":
                return {"task_id":task_id,"generation":generation,
                        "state":"CANCELLED","already_cancelled":True}
            if row["state"] != "WATCHING":
                raise ValueError("DELAYED_CANCEL_NOT_WATCHING")
            changed = db.execute(
                "UPDATE delayed_send_watches SET state='CANCELLED' "
                "WHERE task_id=? AND generation=? AND state='WATCHING'",
                (task_id,generation)
            )
            if changed.rowcount != 1:
                raise ValueError("DELAYED_CANCEL_RACE")
        return {"task_id":task_id,"generation":generation,
                "state":"CANCELLED","already_cancelled":False}

    def latest_binding(self, task_id: str) -> dict:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id=? AND json_extract(context_json,'$.instance_id') IS NOT NULL "
                "ORDER BY generation DESC LIMIT 1", (task_id,)
            ).fetchone()
        return json.loads(row["context_json"]) if row else {}

    def watching(self, *, limit: int = 12) -> list[dict]:
        with self.store._readonly() as db:
            rows = db.execute(
                "SELECT d.* FROM delayed_send_watches d JOIN works w "
                "ON w.work_id=json_extract(d.context_json,'$.work_id') "
                "WHERE d.state='WATCHING' AND w.state='ACTIVE' "
                "AND w.assignment_epoch=json_extract(d.context_json,'$.assignment_epoch') "
                "ORDER BY d.task_id,d.generation LIMIT ?", (limit,),
            ).fetchall()
        result=[]
        for row in rows:
            value=dict(row)
            value["context"]=json.loads(value.pop("context_json"))
            result.append(value)
        return result

    def bind_self_source_send(self, *, task_id: str, next_generation: int,
                              operation_id: str, message_sha256: str) -> None:
        """Bind one APPLIED BCT SELF send to its pre-reserved next generation."""
        if (not operation_id or not re.fullmatch(r"[0-9a-f]{64}", message_sha256)):
            raise ValueError("DELAYED_SOURCE_SEND_INVALID")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='RESERVED'",
                (task_id, next_generation),
            ).fetchone()
            if row is None:
                raise ValueError("DELAYED_SOURCE_WATCH_NOT_RESERVED")
            context = json.loads(row["context_json"] or "{}")
            if context.get("source_send_operation_id"):
                if (context["source_send_operation_id"] != operation_id
                        or context.get("source_send_sha256") != message_sha256):
                    raise ValueError("DELAYED_SOURCE_SEND_CONFLICT")
                return
            context["source_send_operation_id"] = operation_id
            context["source_send_sha256"] = message_sha256
            updated = db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='RESERVED'",
                (json.dumps(context,sort_keys=True),task_id,next_generation),
            )
            if updated.rowcount != 1:
                raise ValueError("DELAYED_SOURCE_SEND_RACE")

    def record_watch_diagnostic(self, row: dict, reason: str) -> bool:
        """Persist a symbolic rejection code only; no user text or turn content."""
        if reason not in {
            "RCC_READ_UNAVAILABLE", "TURN_COUNT_UNAVAILABLE",
            "SOURCE_KEY_OR_SHA_MISSING", "SOURCE_OCCURRENCE_AMBIGUOUS",
            "SOURCE_PROVENANCE_MISMATCH", "SEND_PROOF_MISMATCH",
            "SEND_RECEIPT_UNAVAILABLE", "SEND_RECEIPT_INVALID",
            "RESPONSE_NOT_NEW", "RESPONSE_NOT_TERMINAL",
            "NEXT_INSTRUCTION_UNAVAILABLE",
        }:
            return False
        with self.store.transaction() as db:
            found = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if found is None:
                return False
            ctx = json.loads(found["context_json"] or "{}")
            if ctx.get("watch_diagnostic_reason") == reason:
                return True
            ctx["watch_diagnostic_reason"] = reason
            return db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(ctx, sort_keys=True), row["task_id"], row["generation"]),
            ).rowcount == 1

    def note_recovery_signal(self, row: dict, *, kind: str, observed_at: float) -> int:
        """Count consecutive explicit RCC stop signals on the existing watch."""
        if kind not in {
                "CONNECTION_DISCONNECTED", "RETRY_REQUIRED",
                "NEW_CHAT_REQUIRED", "RECOVERY_REQUIRED"}:
            return 0
        with self.store.transaction() as db:
            found = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if found is None:
                return 0
            context = json.loads(found["context_json"] or "{}")
            prior = context.get("recovery_signal")
            count = (int(prior.get("count") or 0) + 1
                     if isinstance(prior, dict) and prior.get("kind") == kind else 1)
            context["recovery_signal"] = {
                "kind": kind, "count": count, "observed_at": float(observed_at),
            }
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )
            return count

    def clear_recovery_signal(self, row: dict) -> None:
        with self.store.transaction() as db:
            found = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if found is None:
                return
            context = json.loads(found["context_json"] or "{}")
            if "recovery_signal" not in context:
                return
            context.pop("recovery_signal", None)
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )

    def prepare_recovery_generation(
        self, row: dict, *, conversation_key: str, baseline: dict,
        operation_id: str, message_sha256: str, recovery_kind: str,
        reconcile_operation_id: str = "",
    ) -> int:
        """Move one stalled watch to the next generation before an exact send."""
        next_generation = int(row["generation"]) + 1
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT state,context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=?", (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None or current["state"] != "WATCHING":
                raise ValueError("DELAYED_RECOVERY_WATCH_CHANGED")
            existing = db.execute(
                "SELECT conversation_key,state,context_json FROM delayed_send_watches "
                "WHERE task_id=? AND generation=?",
                (row["task_id"], next_generation),
            ).fetchone()
            if existing is not None:
                context = json.loads(existing["context_json"] or "{}")
                if (existing["conversation_key"] != conversation_key
                        or context.get("source_send_operation_id") != operation_id
                        or context.get("source_send_sha256") != message_sha256
                        or str(context.get("source_send_reconcile_operation_id") or "")
                           != reconcile_operation_id):
                    raise ValueError("DELAYED_RECOVERY_GENERATION_CONFLICT")
                return next_generation
            old_context = json.loads(current["context_json"] or "{}")
            context = dict(old_context)
            for key in (
                    "observed_response_turn_key", "observed_response_sha",
                    "watch_diagnostic_reason", "watch_terminal_reason",
                    "manager_action", "recovery_signal"):
                context.pop(key, None)
            context.update({
                "baseline_count": int(baseline.get("responseTurnCount") or 0),
                "baseline_generating": baseline.get("generating") is True,
                "baseline_key": str(baseline.get("responseTurnKey") or ""),
                "baseline_sha": str(baseline.get("responseSha256") or ""),
                "source_proof_kind": "BCT_PLANNED_SOURCE_SEND",
                "source_user_turn_key": "",
                "source_user_sha256": message_sha256,
                "source_send_operation_id": operation_id,
                "source_send_reconcile_operation_id": reconcile_operation_id,
                "source_send_sha256": message_sha256,
                "recovery_kind": recovery_kind,
                "recovered_from_generation": int(row["generation"]),
            })
            old_context["recovery_kind"] = recovery_kind
            old_context["recovery_next_generation"] = next_generation
            changed = db.execute(
                "UPDATE delayed_send_watches SET state='RECOVERING',context_json=? "
                "WHERE task_id=? AND generation=? AND state='WATCHING'",
                (json.dumps(old_context, sort_keys=True), row["task_id"], row["generation"]),
            )
            if changed.rowcount != 1:
                raise ValueError("DELAYED_RECOVERY_WATCH_CHANGED")
            db.execute(
                "INSERT INTO delayed_send_watches(task_id,generation,conversation_key,"
                "response_turn_id,source_send_receipt,state,context_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (row["task_id"], next_generation, conversation_key,
                 f"task:{row['task_id']}:{next_generation}", operation_id,
                 "WATCHING", json.dumps(context, sort_keys=True)),
            )
        return next_generation

    def finish_recovery(self, row: dict, *, next_generation: int) -> None:
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE delayed_send_watches SET state='RESTARTED' WHERE task_id=? "
                "AND generation=? AND state='RECOVERING'",
                (row["task_id"], row["generation"]),
            )
            next_row = db.execute(
                "SELECT state FROM delayed_send_watches WHERE task_id=? AND generation=?",
                (row["task_id"], next_generation),
            ).fetchone()
            if changed.rowcount != 1 or next_row is None or next_row["state"] != "WATCHING":
                raise ValueError("DELAYED_RECOVERY_FINISH_CONFLICT")

    def rollback_recovery(self, row: dict, *, next_generation: int, reason: str) -> None:
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='RECOVERING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None:
                return
            context = json.loads(current["context_json"] or "{}")
            context["recovery_not_applied"] = reason
            db.execute(
                "UPDATE delayed_send_watches SET state='WATCHING',context_json=? "
                "WHERE task_id=? AND generation=? AND state='RECOVERING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )
            db.execute(
                "UPDATE delayed_send_watches SET state='CANCELLED' WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], next_generation),
            )

    def mark_recovery_unknown(self, row: dict, *, next_generation: int) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='UNKNOWN' WHERE task_id=? "
                "AND generation IN (?,?) AND state IN ('RECOVERING','WATCHING')",
                (row["task_id"], row["generation"], next_generation),
            )

    def mark_current_recovery_unknown(self, row: dict, *, reason: str) -> None:
        """Stop one unresolved recovery without retrying a possibly applied effect."""
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None:
                return
            context = json.loads(current["context_json"] or "{}")
            context["recovery_unknown_reason"] = reason
            db.execute(
                "UPDATE delayed_send_watches SET state='UNKNOWN',context_json=? "
                "WHERE task_id=? AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )

    def next_recovery_attempt(self, row: dict, *, route: str) -> int:
        """Allocate a retry number inside the existing watch context."""
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None:
                raise ValueError("DELAYED_RECOVERY_WATCH_CHANGED")
            context = json.loads(current["context_json"] or "{}")
            attempts = context.get("recovery_attempts")
            if not isinstance(attempts, dict):
                attempts = {}
            attempt = int(attempts.get(route) or 0) + 1
            attempts[route] = attempt
            context["recovery_attempts"] = attempts
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )
            return attempt

    def remember_recovery_chat(self, row: dict, *, create_operation_id: str,
                               session_id: str, tab_id: int, window_id: int) -> None:
        """Keep a confirmed new Chat so a safe send retry does not create more tabs."""
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None:
                raise ValueError("DELAYED_RECOVERY_WATCH_CHANGED")
            context = json.loads(current["context_json"] or "{}")
            context["recovery_created_chat"] = {
                "create_operation_id": create_operation_id,
                "session_id": session_id,
                "tab_id": int(tab_id),
                "window_id": int(window_id),
            }
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )

    def remember_recovery_send_unknown(self, row: dict, *, send_operation_id: str,
                                       create_operation_id: str) -> None:
        """Keep one ambiguous successor send for receipt-only reconciliation.

        The watch deliberately remains WATCHING.  A later poll may query the
        exact original RCC operation, but must never submit the message again.
        """
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None:
                raise ValueError("DELAYED_RECOVERY_WATCH_CHANGED")
            context = json.loads(current["context_json"] or "{}")
            context["recovery_pending_send"] = {
                "send_operation_id": send_operation_id,
                "create_operation_id": create_operation_id,
            }
            context["recovery_unknown_reason"] = "NEW_CHAT_SEND_EFFECT_UNKNOWN"
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )

    def next_recovery_reconcile_attempt(self, row: dict, *, observed_at: float) -> int:
        """Allocate a bounded, backoff-controlled receipt reconciliation attempt."""
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if current is None:
                raise ValueError("DELAYED_RECOVERY_WATCH_CHANGED")
            context = json.loads(current["context_json"] or "{}")
            state = context.get("recovery_reconcile")
            if not isinstance(state, dict):
                state = {}
            attempt = int(state.get("attempt") or 0)
            last_at = float(state.get("last_at") or 0.0)
            wait_seconds = min(30.0, 2.0 ** max(0, attempt - 1)) if attempt else 0.0
            if observed_at - last_at < wait_seconds:
                return 0
            attempt += 1
            context["recovery_reconcile"] = {
                "attempt": attempt, "last_at": observed_at,
            }
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (json.dumps(context, sort_keys=True), row["task_id"], row["generation"]),
            )
            return attempt

    def mark_source_superseded(self, row: dict, observed: dict) -> bool:
        """Retire a watch only after a different exact terminal source is proven.

        RCC intentionally exposes the latest Assistant response.  Once a later
        unique user turn has a terminal response, an older watch can no longer
        recover its own response from that surface.  Keep that boundary honest:
        this is a non-success terminal state and never authorizes a send.
        """
        latest_key = str(observed.get("latestUserTurnKey") or "")
        source_key = str(observed.get("responseSourceUserTurnKey") or "")
        latest_sha = str(observed.get("latestUserSha256") or "")
        source_sha = str(observed.get("responseSourceUserSha256") or "")
        current_count = observed.get("responseTurnCount")
        baseline_count = row.get("context", {}).get("baseline_count")
        response_key = str(observed.get("responseTurnKey") or "")
        response_sha = str(observed.get("responseSha256") or "")
        baseline_key = str(row.get("context", {}).get("baseline_key") or "")
        baseline_sha = str(row.get("context", {}).get("baseline_sha") or "")
        newer_response = (
            isinstance(current_count, int) and isinstance(baseline_count, int)
            and (current_count > baseline_count
                 or (response_key != baseline_key and response_sha != baseline_sha))
        )
        if (observed.get("terminal") is not True
                or observed.get("inputReady") is not True
                or observed.get("generating") is not False
                or not newer_response
                or not latest_key or latest_key != source_key
                or not re.fullmatch(r"[0-9a-f]{64}", latest_sha)
                or latest_sha != source_sha
                or observed.get("latestUserTextOccurrenceCount") != 1
                or observed.get("responseSourceUserTextOccurrenceCount") != 1):
            return False
        with self.store.transaction() as db:
            found = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (row["task_id"], row["generation"]),
            ).fetchone()
            if found is None:
                return False
            ctx = json.loads(found["context_json"] or "{}")
            expected_sha = str(ctx.get("source_user_sha256") or "")
            if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
                    or latest_sha == expected_sha):
                return False
            if ctx.get("source_proof_kind") == "BCT_PLANNED_SOURCE_SEND":
                if (not ctx.get("source_send_operation_id")
                        or ctx.get("source_send_sha256") != expected_sha):
                    return False
            ctx.pop("watch_diagnostic_reason", None)
            ctx["watch_terminal_reason"] = "SOURCE_SUPERSEDED"
            ctx["superseding_source_turn_key"] = latest_key
            ctx["superseding_source_sha256"] = latest_sha
            return db.execute(
                "UPDATE delayed_send_watches SET state='SUPERSEDED',context_json=? "
                "WHERE task_id=? AND generation=? AND state='WATCHING'",
                (json.dumps(ctx, sort_keys=True), row["task_id"], row["generation"]),
            ).rowcount == 1

    def mark_manager_decision_required(self, watch: Watch, *, reason: str) -> bool:
        """Finish an exact response watch when B supplied no safe BB/BA route.

        A terminal Worker response is already durable evidence at this point,
        so leaving the row WATCHING would falsely describe it as unfinished.
        Do not guess a destination and do not send anything.  The Manager can
        review the bound response and author a new Chain Message explicitly.
        """
        if reason != "NEXT_INSTRUCTION_UNAVAILABLE":
            raise ValueError("DELAYED_MANAGER_DECISION_REASON_INVALID")
        with self.store.transaction() as db:
            found = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING' AND response_turn_id=?",
                (watch.task_id, watch.generation, watch.response_turn_id),
            ).fetchone()
            if found is None:
                return False
            ctx = json.loads(found["context_json"] or "{}")
            if (not ctx.get("observed_response_turn_key")
                    or not ctx.get("observed_response_sha")):
                return False
            ctx.pop("watch_diagnostic_reason", None)
            ctx["watch_terminal_reason"] = reason
            ctx["manager_action"] = "REVIEW_RESPONSE_AND_AUTHOR_NEXT_MESSAGE"
            return db.execute(
                "UPDATE delayed_send_watches "
                "SET state='MANAGER_DECISION_REQUIRED',context_json=? "
                "WHERE task_id=? AND generation=? AND state='WATCHING' "
                "AND response_turn_id=?",
                (json.dumps(ctx, sort_keys=True), watch.task_id,
                 watch.generation, watch.response_turn_id),
            ).rowcount == 1

    def bind_observed_turn(self, watch: Watch, turn_key: str, response_sha: str) -> bool:
        """Persist the exact RCC response identity before claiming any send."""
        if not isinstance(turn_key, str) or not turn_key.strip() or not response_sha:
            return False
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING' AND response_turn_id=?",
                (watch.task_id, watch.generation, watch.response_turn_id),
            ).fetchone()
            if row is None:
                return False
            context = json.loads(row["context_json"] or "{}")
            existing = context.get("observed_response_turn_key")
            if existing and (existing != turn_key or context.get("observed_response_sha") != response_sha):
                return False
            context["observed_response_turn_key"] = turn_key
            context["observed_response_sha"] = response_sha
            # A bound terminal response supersedes every WATCHING diagnostic.
            # Keep later instruction-parse failures visible by allowing the
            # caller to record NEXT_INSTRUCTION_UNAVAILABLE after this bind.
            context.pop("watch_diagnostic_reason", None)
            updated = db.execute(
                "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                "AND generation=? AND state='WATCHING' AND response_turn_id=?",
                (json.dumps(context, sort_keys=True), watch.task_id,
                 watch.generation, watch.response_turn_id),
            )
            return updated.rowcount == 1

    def claim_response(self, watch: Watch) -> bool:
        """Only one caller may execute the effect for this response."""
        with self.store.transaction() as db:
            updated = db.execute(
                "UPDATE delayed_send_watches SET state='DISPATCHING' "
                "WHERE task_id=? AND generation=? AND state='WATCHING' "
                "AND response_turn_id=? AND source_send_receipt=?",
                (watch.task_id,watch.generation,watch.response_turn_id,
                 watch.source_send_receipt))
            return updated.rowcount == 1

    def record_alarm(self, watch: Watch, alarm: Alarm) -> bool:
        """Persist an immutable READY alarm before an action can consume it."""
        if (alarm.watch_ref != f"{watch.task_id}:{watch.generation}"
                or alarm.evidence.subject_ref != watch.conversation_key):
            raise ValueError("CONTINUATION_ALARM_CONTEXT_MISMATCH")
        evidence = {
            "subject_ref": alarm.evidence.subject_ref,
            "response_turn_id": alarm.evidence.response_turn_id,
            "response_text": alarm.evidence.response_text,
            "response_complete": alarm.evidence.response_complete,
            "input_ready": alarm.evidence.input_ready,
        }
        encoded = json.dumps(evidence, sort_keys=True)
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT evidence_json,state FROM continuation_alarms "
                "WHERE task_id=? AND generation=? AND kind=?",
                (watch.task_id, watch.generation, alarm.kind.value),
            ).fetchone()
            if existing is not None:
                if existing["evidence_json"] != encoded:
                    raise ValueError("CONTINUATION_ALARM_CONFLICT")
                return False
            db.execute(
                "INSERT INTO continuation_alarms(task_id,generation,kind,evidence_json,state) "
                "VALUES(?,?,?,?,?)",
                (watch.task_id, watch.generation, alarm.kind.value, encoded, "READY"),
            )
            return True

    def consume_alarm(self, watch: Watch, alarm: Alarm) -> bool:
        """Claim one ready alarm exactly once, after its watch was claimed."""
        with self.store.transaction() as db:
            updated = db.execute(
                "UPDATE continuation_alarms SET state='CONSUMING' "
                "WHERE task_id=? AND generation=? AND kind=? AND state='READY'",
                (watch.task_id, watch.generation, alarm.kind.value),
            )
            return updated.rowcount == 1

    def mark_alarm_result(self, watch: Watch, alarm: Alarm, state: str) -> None:
        if state not in {"CONSUMED", "NOT_APPLIED", "UNKNOWN"}:
            raise ValueError("CONTINUATION_ALARM_RESULT_INVALID")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE continuation_alarms SET state=? WHERE task_id=? "
                "AND generation=? AND kind=? AND state='CONSUMING'",
                (state, watch.task_id, watch.generation, alarm.kind.value),
            )

    def mark_send_not_applied(
        self, watch: Watch, alarm: Alarm, *, route: str
    ) -> bool:
        """Preserve a completed response when continuation send had no effect.

        RCC ``NOT_APPLIED`` is confirmed absence of an external send, not an
        ambiguous effect.  End the watch for Manager review without retrying or
        degrading the exact response and decision evidence to ``UNKNOWN``.
        """
        if route not in {"SELF", "MANAGER"}:
            raise ValueError("CONTINUATION_ROUTE_INVALID")
        with self.store.transaction() as db:
            found = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='DISPATCHING' AND response_turn_id=?",
                (watch.task_id, watch.generation, watch.response_turn_id),
            ).fetchone()
            if found is None:
                return False
            context = json.loads(found["context_json"] or "{}")
            context["watch_terminal_reason"] = "CONTINUATION_SEND_NOT_APPLIED"
            context["manager_action"] = "REVIEW_RESPONSE_AND_AUTHOR_NEXT_MESSAGE"
            context["continuation_route"] = route
            updated = db.execute(
                "UPDATE delayed_send_watches SET state='MANAGER_DECISION_REQUIRED',"
                "context_json=? WHERE task_id=? AND generation=? "
                "AND state='DISPATCHING' AND response_turn_id=?",
                (json.dumps(context, sort_keys=True), watch.task_id,
                 watch.generation, watch.response_turn_id),
            )
            if updated.rowcount != 1:
                return False
            alarm_updated = db.execute(
                "UPDATE continuation_alarms SET state='NOT_APPLIED' "
                "WHERE task_id=? AND generation=? AND kind=? "
                "AND state='CONSUMING'",
                (watch.task_id, watch.generation, alarm.kind.value),
            )
            if alarm_updated.rowcount != 1:
                raise ValueError("CONTINUATION_ALARM_NOT_CONSUMING")
            return True

    def get_alarm(self, watch: Watch, kind: str) -> dict | None:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM continuation_alarms WHERE task_id=? "
                "AND generation=? AND kind=?",
                (watch.task_id, watch.generation, kind),
            ).fetchone()
        return dict(row) if row else None

    def record_decision(self, watch: Watch, decision: ContinuationDecision,
                        *, response_turn_key: str, response_sha256: str) -> bool:
        """Persist B's BB/BA decision before any continuation delivery.

        Repeating the same observation is idempotent; a different decision for
        the exact same completed turn is a conflict and must not be routed.
        """
        if (not isinstance(response_turn_key, str) or not response_turn_key.strip()
                or not isinstance(response_sha256, str) or not response_sha256):
            raise ValueError("CONTINUATION_DECISION_EVIDENCE_INVALID")
        values = (watch.task_id, watch.generation, decision.route.value,
                  decision.payload, response_turn_key, response_sha256)
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT route,payload,response_turn_key,response_sha256 "
                "FROM continuation_decisions WHERE task_id=? AND generation=?",
                (watch.task_id, watch.generation),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values[2:]:
                    raise ValueError("CONTINUATION_DECISION_CONFLICT")
                return False
            db.execute(
                "INSERT INTO continuation_decisions("
                "task_id,generation,route,payload,response_turn_key,response_sha256) "
                "VALUES(?,?,?,?,?,?)", values,
            )
            return True

    def enforce_generation_limit(
        self, watch: Watch, decision: ContinuationDecision
    ) -> ContinuationDecision:
        """Return BB to Manager at the durable recipe limit, preserving B's request."""
        current = self.get(watch.task_id, watch.generation)
        context = json.loads(current["context_json"] or "{}") if current else {}
        maximum = context.get("max_generations", 0)
        if (type(maximum) is not int or maximum <= 0
                or decision.route != ContinuationRoute.SELF
                or watch.generation < maximum):
            return decision
        effective = ContinuationDecision(
            route=ContinuationRoute.MANAGER,
            payload=(
                f"BB 반복 한도({maximum}회)에 도달했습니다. Worker가 요청한 다음 "
                f"작업은 실행하지 않고 Manager 판단으로 반환합니다.\n\n"
                f"Worker의 다음 제안:\n{decision.payload}"
            ),
        )
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT context_json FROM delayed_send_watches WHERE task_id=? "
                "AND generation=? AND state='WATCHING'",
                (watch.task_id, watch.generation),
            ).fetchone()
            if row is not None:
                saved = json.loads(row["context_json"] or "{}")
                saved["requested_continuation_route"] = decision.route.value
                saved["effective_continuation_route"] = effective.route.value
                saved["continuation_route_override_reason"] = "BB_LIMIT_REACHED"
                db.execute(
                    "UPDATE delayed_send_watches SET context_json=? WHERE task_id=? "
                    "AND generation=? AND state='WATCHING'",
                    (json.dumps(saved, sort_keys=True), watch.task_id,
                     watch.generation),
                )
        return effective

    def read_execution_context(self, *, task_id: str, generation: int | None = None) -> dict | None:
        """Read one execution's durable resume context without routing it.

        A future wake-only public block can use this method.  It intentionally
        returns the finishing B turn's already-recorded direction instead of
        asking the resumed B turn to decide it again.
        """
        with self.store._readonly() as db:
            if generation is None:
                decision = db.execute(
                    "SELECT * FROM continuation_decisions WHERE task_id=? "
                    "ORDER BY generation DESC LIMIT 1", (task_id,),
                ).fetchone()
            else:
                decision = db.execute(
                    "SELECT * FROM continuation_decisions WHERE task_id=? AND generation=?",
                    (task_id, generation),
                ).fetchone()
            if decision is None:
                return None
            watch = db.execute(
                "SELECT context_json,state,conversation_key,response_turn_id "
                "FROM delayed_send_watches WHERE task_id=? AND generation=?",
                (decision["task_id"], decision["generation"]),
            ).fetchone()
            alarm = db.execute(
                "SELECT evidence_json,state FROM continuation_alarms "
                "WHERE task_id=? AND generation=? AND kind=?",
                (decision["task_id"], decision["generation"], "conversation.response_ready"),
            ).fetchone()
        if watch is None:
            return None
        value = {
            "task_id": str(decision["task_id"]),
            "generation": int(decision["generation"]),
            "watch_state": str(watch["state"]),
            "worker_conversation_key": str(watch["conversation_key"]),
            "response_turn_id": str(watch["response_turn_id"]),
            "decision": {
                "route": str(decision["route"]),
                "payload": str(decision["payload"]),
                "response_turn_key": str(decision["response_turn_key"]),
                "response_sha256": str(decision["response_sha256"]),
            },
            "binding": json.loads(watch["context_json"] or "{}"),
        }
        # The response is durable evidence for the prior B turn. It is a
        # record to be read, not a prompt to re-decide its already-recorded
        # BB/BA direction.
        if alarm is not None:
            value["prior_turn"] = {
                "alarm_state": str(alarm["state"]),
                **json.loads(alarm["evidence_json"]),
            }
        return value

    def mark_result(self, watch: Watch, status: str) -> None:
        if status not in {"SELF_SENT","RETURNED_TO_MANAGER","UNKNOWN"}:
            raise ValueError("DELAYED_RESULT_INVALID")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state=? WHERE task_id=? "
                "AND generation=? AND state='DISPATCHING'",
                (status,watch.task_id,watch.generation))

    def get(self, task_id: str, generation: int) -> dict | None:
        with self.store._readonly() as db:
            row=db.execute(
                "SELECT * FROM delayed_send_watches WHERE task_id=? AND generation=?",
                (task_id,generation)).fetchone()
            return dict(row) if row else None

    def bind(self, watch: Watch, *, send_receipt: str, response_turn_id: str) -> Watch:
        bound = bind_next_response(watch,send_receipt=send_receipt,
                                   response_turn_id=response_turn_id)
        with self.store.transaction() as db:
            result=db.execute(
                "UPDATE delayed_send_watches SET response_turn_id=?,"
                "source_send_receipt=?,state='WATCHING' "
                "WHERE task_id=? AND generation=? AND state='RESERVED'"
                " AND response_turn_id='' AND source_send_receipt=''",
                (bound.response_turn_id,bound.source_send_receipt,
                 watch.task_id,watch.generation))
            if result.rowcount!=1:
                raise ValueError("DELAYED_WATCH_NOT_RESERVED")
        return bound



class SendDelayedMessageRunner:
    """Connect existing RCC read/send callbacks to durable continuation state."""
    def __init__(self, ledger: DurableWatchLedger, *, read_response, send_message):
        self.ledger = ledger
        self.read_response = read_response
        self.send_message = send_message

    def poll_once(self, watch: Watch, *, manager_conversation_key: str) -> Continuation:
        current = self.ledger.get(watch.task_id, watch.generation)
        if current is None or current["state"] != "WATCHING":
            return Continuation("WAITING_WATCH")
        observation = self.read_response(watch)
        if not isinstance(observation, dict):
            return Continuation("WAITING_RESPONSE")
        if (observation.get("conversation_key") != watch.conversation_key
                or observation.get("response_turn_id") != watch.response_turn_id
                or observation.get("response_complete") is not True
                or observation.get("input_ready") is not True):
            return Continuation("WAITING_RESPONSE")
        turn_key = observation.get("response_turn_key")
        response_sha = observation.get("response_sha256")
        if not isinstance(turn_key, str) or not turn_key.strip() or not isinstance(response_sha, str):
            return Continuation("WAITING_RESPONSE")
        # The exact terminal response identity is durable evidence independent
        # of whether its continuation instruction can be decoded.  Binding it
        # first prevents an instruction-format problem from masquerading as a
        # missing/unterminated response in public status.
        if not self.ledger.bind_observed_turn(watch, turn_key, response_sha):
            return Continuation("WAITING_EXPECTED_RESPONSE")
        alarm = response_ready_alarm(
            watch_ref=f"{watch.task_id}:{watch.generation}",
            subject_ref=watch.conversation_key,
            expected_response_turn_id=watch.response_turn_id,
            response_turn_id=str(observation.get("response_turn_id") or ""),
            response_text=observation.get("response_text"),
            response_complete=observation.get("response_complete") is True,
            input_ready=observation.get("input_ready") is True,
        )
        if alarm is None:
            return Continuation("WAITING_RESPONSE")
        try:
            decision = next_instruction_decision(alarm)
        except InstructionError:
            # Preserve the exact completed response as a ready, unconsumed
            # alarm, then end the watch without inventing a route or effect.
            self.ledger.record_alarm(watch, alarm)
            if self.ledger.mark_manager_decision_required(
                    watch, reason="NEXT_INSTRUCTION_UNAVAILABLE"):
                return Continuation("MANAGER_DECISION_REQUIRED")
            return Continuation("WAITING_WATCH")
        decision = self.ledger.enforce_generation_limit(watch, decision)
        self.ledger.record_alarm(watch, alarm)
        self.ledger.record_decision(
            watch, decision, response_turn_key=turn_key, response_sha256=response_sha,
        )
        if not self.ledger.claim_response(watch):
            return Continuation("ALREADY_DISPATCHING")
        if not self.ledger.consume_alarm(watch, alarm):
            self.ledger.mark_result(watch, "UNKNOWN")
            return Continuation("ALREADY_DISPATCHING")
        try:
            result = dispatch_send_delayed_message(
                watch=watch, alarm=alarm, decision=decision,
                manager_conversation_key=manager_conversation_key,
                register_next_watch=lambda next_watch: self.ledger.reserve_next(
                    watch, next_watch,
                ),
                send_message=self.send_message,
            )
        except ValueError as exc:
            if str(exc) == "DELAYED_RCC_SEND_NOT_APPLIED":
                if self.ledger.mark_send_not_applied(
                    watch, alarm, route=decision.route.value,
                ):
                    return Continuation("MANAGER_DECISION_REQUIRED")
                return Continuation("WAITING_WATCH")
            self.ledger.mark_result(watch, "UNKNOWN")
            self.ledger.mark_alarm_result(watch, alarm, "UNKNOWN")
            raise
        except Exception:
            self.ledger.mark_result(watch, "UNKNOWN")
            self.ledger.mark_alarm_result(watch, alarm, "UNKNOWN")
            raise
        self.ledger.mark_result(watch, result.status)
        self.ledger.mark_alarm_result(watch, alarm, "CONSUMED")
        return result


def watch_diagnostic_for_status(state: str, context: dict) -> str:
    """Expose a watch rejection only while that watch can still be waiting."""
    if state != "WATCHING" or not isinstance(context, dict):
        return ""
    return str(context.get("watch_diagnostic_reason") or "")



def normalize_rcc_latest_assistant(
    result: dict, *, conversation_key: str, expected_response_sha256: str,
    response_turn_id: str, input_ready: bool,
) -> dict:
    """Normalize the *actual* RCC read-latest-assistant response contract.

    RCC returns a terminal flag, SHA and responseTurnKey. The task's
    source receipt remains distinct from this observed assistant turn key.
    """
    if not isinstance(result, dict) or result.get("ok") is not True:
        return {}
    if result.get("conversationKey") != conversation_key:
        return {}
    body = result.get("responseText")
    digest = result.get("responseSha256")
    if not isinstance(body, str) or not isinstance(digest, str):
        return {}
    actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
    turn_key = result.get("responseTurnKey")
    if (actual != digest or not digest or digest == expected_response_sha256
            or not isinstance(turn_key, str) or not turn_key.strip()):
        return {}
    return {
        "conversation_key": conversation_key,
        "response_turn_id": response_turn_id,
        "response_turn_key": turn_key,
        "response_text": body,
        "response_complete": result.get("observationState") == "TERMINAL"
                             and result.get("terminal") is True
                             and result.get("generating") is False,
        "input_ready": input_ready is True and result.get("inputReady") is True,
        "response_sha256": digest,
    }


class RccLatestAssistantReader:
    """Call the existing RCC observation command for one exact worker tab."""
    def __init__(self, client, *, instance_id: str, session_id: str,
                 tab_id: int, window_id: int, conversation_key: str,
                 baseline_response_sha256: str, input_ready):
        self.client = client
        self.instance_id = instance_id
        self.session_id = session_id
        self.tab_id = tab_id
        self.window_id = window_id
        self.conversation_key = conversation_key
        self.baseline_response_sha256 = baseline_response_sha256
        self.input_ready = input_ready

    def __call__(self, watch: Watch) -> dict:
        if watch.conversation_key != self.conversation_key:
            return {}
        result = self.client.request(
            instance_id=self.instance_id,
            request_id="delayed-read-" + hashlib.sha256(
                f"{watch.task_id}|{watch.generation}".encode()
            ).hexdigest()[:24],
            command="read-latest-assistant",
            extra={"sessionId":self.session_id,"tabId":self.tab_id,
                   "windowId":self.window_id,
                   "conversationKey":self.conversation_key,
                   "instanceId":self.instance_id},
            timeout_s=5.0,
        )
        return normalize_rcc_latest_assistant(
            result, conversation_key=self.conversation_key,
            expected_response_sha256=self.baseline_response_sha256,
            response_turn_id=watch.response_turn_id,
            input_ready=self.input_ready() is True,
        )


class SendDelayedMessageService:
    """Core tick: observe a single reserved B response, then send using BCT receipts."""
    def __init__(self, *, store, browser_feature, operations):
        self.store = store
        self.browser_feature = browser_feature
        self.operations = operations
        self.ledger = DurableWatchLedger(store)

    def _locate(self, instance_id: str, conversation_key: str):
        import secrets
        session_id, tabs = self.browser_feature._read_target_state(
            instance_id=instance_id,
            request_id="delayed-state-" + secrets.token_hex(12),
        )
        from urllib.parse import urlsplit
        def observed_key(tab):
            explicit = str(tab.get("conversationKey") or "").lower()
            if explicit:
                return explicit
            url = urlsplit(str(tab.get("url") or ""))
            if url.hostname not in {"chatgpt.com", "chat.openai.com"}:
                return ""
            parts = url.path.strip("/").split("/")
            return parts[1].lower() if len(parts)==2 and parts[0]=="c" else ""
        matches = [tab for tab in tabs if observed_key(tab) == conversation_key]
        if len(matches) != 1:
            raise ValueError("DELAYED_TARGET_NOT_EXACT")
        target = matches[0]
        return (session_id, int(target["tabId"]), int(target["windowId"]))

    def latest(self, *, instance_id: str, conversation_key: str):
        import secrets
        session, tab, window = self._locate(instance_id, conversation_key)
        return self.browser_feature.client.request(
            instance_id=instance_id,
            request_id="delayed-read-" + secrets.token_hex(12),
            command="read-latest-assistant",
            extra={"instanceId":instance_id, "sessionId":session,
                   "tabId":tab,"windowId":window,"conversationKey":conversation_key},
            timeout_s=5.0,
        )

    def _activity_for(self, row: dict) -> dict:
        """Read the existing RCC DOM activity signal for one exact watched chat."""
        ctx = row["context"]
        instance = str(ctx["instance_id"])
        response = self.browser_feature.client.request(
            instance_id=instance,
            request_id="delayed-activity-" + hashlib.sha256(
                f"{row['task_id']}|{row['generation']}".encode()
            ).hexdigest()[:24],
            command="state", timeout_s=2.0,
        )
        state = response.get("state") if isinstance(response, dict) else None
        endpoints = state.get("endpoints") if isinstance(state, dict) else None
        if not (isinstance(response, dict) and response.get("ok") is True
                and isinstance(endpoints, list)):
            return {}
        matches = [item for item in endpoints if isinstance(item, dict)
                   and str(item.get("conversationKey") or "").lower()
                   == str(row["conversation_key"]).lower()]
        if len(matches) == 1:
            endpoint = matches[0]
        elif len(matches) == 0:
            # A navigation/error page can remove the conversation UUID from
            # the RCC endpoint before its visible recovery UI is rendered.
            # Use only the exact tab/window captured by the original Chain
            # prearm; never select another blank Chat tab heuristically.
            watched_tab = int(ctx.get("watched_tab_id") or 0)
            watched_window = int(ctx.get("watched_window_id") or 0)
            endpoint_matches = [item for item in endpoints if isinstance(item, dict)
                                and int(item.get("tabId") or 0) == watched_tab
                                and int(item.get("windowId") or 0) == watched_window]
            if watched_tab <= 0 or watched_window <= 0 or len(endpoint_matches) != 1:
                return {}
            endpoint = endpoint_matches[0]
            if str(endpoint.get("conversationKey") or "").lower() != str(
                    row["conversation_key"]).lower():
                return {
                    "kind": "NEW_CHAT_REQUIRED",
                    "session_id": str(state.get("sessionId") or ctx.get(
                        "watched_session_id") or ""),
                    "tab_id": watched_tab,
                    "window_id": watched_window,
                }
        else:
            return {}
        telemetry = endpoint.get("telemetry") if isinstance(endpoint.get("telemetry"), dict) else {}
        attention = telemetry.get("user_attention") \
            if isinstance(telemetry.get("user_attention"), dict) else {}
        connection = endpoint.get("connection") \
            if isinstance(endpoint.get("connection"), dict) else {}
        kind = str(attention.get("kind") or "").strip().upper()
        if connection.get("disconnected") is True:
            kind = "CONNECTION_DISCONNECTED"
        if kind not in {
                "CONNECTION_DISCONNECTED", "RETRY_REQUIRED",
                "NEW_CHAT_REQUIRED", "RECOVERY_REQUIRED"}:
            return {}
        return {
            "kind": kind,
            "session_id": str(state.get("sessionId") or ""),
            "tab_id": int(endpoint.get("tabId") or 0),
            "window_id": int(endpoint.get("windowId") or 0),
        }

    @staticmethod
    def _recovery_message(row: dict, kind: str) -> str:
        work_id = str(row.get("context", {}).get("work_id") or "")
        return (
            "[BCT 자동 계속]\n"
            f"Work: {work_id}\nTask: {row['task_id']}\n멈춤 신호: {kind}\n"
            "기존 작업의 영수증과 현재 파일 상태를 먼저 확인하세요. 이미 끝난 단계와 "
            "UNKNOWN 외부 효과는 반복하지 말고, 다음 미완료 단계부터 다시 시작해 끝까지 "
            "진행하세요. 먼저 이번 턴의 구체적인 Execute Plan을 세우고 실행하세요. "
            "응답 마지막에는 NEXT TASK — SELF 또는 NEXT TASK — MANAGER와 다음 지시/보고를 남기세요."
        )

    @staticmethod
    def _recovery_operation_id(row: dict, suffix: str, attempt: int = 0) -> str:
        material = f"{row['task_id']}|{row['generation']}|{suffix}|{attempt}"
        return "recovery-" + hashlib.sha256(material.encode()).hexdigest()[:56]

    def _recover_same_conversation(self, row: dict, *, kind: str) -> dict:
        from bct.core.models import Principal, Outcome
        ctx = row["context"]
        work = self.store.get_work(ctx["work_id"])
        message = self._recovery_message(row, kind)
        operation_id = self._recovery_operation_id(row, "same-chat")
        baseline = self.latest(
            instance_id=ctx["instance_id"], conversation_key=row["conversation_key"],
        )
        next_generation = self.ledger.prepare_recovery_generation(
            row, conversation_key=row["conversation_key"], baseline=baseline,
            operation_id=operation_id,
            message_sha256=_rcc_submitted_text_sha256(message), recovery_kind=kind,
        )
        principal = Principal(work.owner_principal_id, "delayed-send-auto-recovery",
                              frozenset({"browser"}))
        session, tab, window = self._locate(ctx["instance_id"], row["conversation_key"])
        result = self.operations.run(
            principal=principal, work_id=work.work_id, operation_id=operation_id,
            capability="browser",
            arguments={"command": "send-message", "instance_id": ctx["instance_id"],
                       "session_id": session, "tab_id": tab, "window_id": window,
                       "conversation_key": row["conversation_key"], "text": message},
        )
        if result.outcome == Outcome.APPLIED:
            self.ledger.finish_recovery(row, next_generation=next_generation)
            return {"status": "RESTARTED", "route": "SAME_CONVERSATION",
                    "generation": next_generation}
        if result.outcome == Outcome.NOT_APPLIED:
            self.ledger.rollback_recovery(
                row, next_generation=next_generation, reason="SAME_CONVERSATION_NOT_APPLIED",
            )
            return {"status": "RESTART_NOT_APPLIED", "route": "SAME_CONVERSATION"}
        self.ledger.mark_recovery_unknown(row, next_generation=next_generation)
        return {"status": "RESTART_UNKNOWN", "route": "SAME_CONVERSATION"}

    def _recover_new_conversation(self, row: dict, *, kind: str) -> dict:
        """Create one successor Chat, send once, then move the existing flow to it."""
        from bct.core.models import Principal, Outcome
        from bct.conversation_network import ensure_observed_node_labels, transfer_conversation_state
        ctx = row["context"]
        work = self.store.get_work(ctx["work_id"])
        principal = Principal(work.owner_principal_id, "delayed-send-auto-recovery",
                              frozenset({"browser"}))
        current = self.ledger.get(row["task_id"], row["generation"])
        current_context = json.loads(current["context_json"] or "{}") if current else {}
        pending = current_context.get("recovery_pending_send")
        if isinstance(pending, dict):
            send_id = str(pending.get("send_operation_id") or "")
            if not send_id:
                self.ledger.mark_current_recovery_unknown(
                    row, reason="NEW_CHAT_RECONCILE_ID_MISSING",
                )
                return {"status": "RESTART_UNKNOWN", "route": "NEW_CONVERSATION"}
            reconcile_attempt = self.ledger.next_recovery_reconcile_attempt(
                row, observed_at=time.time(),
            )
            if reconcile_attempt == 0:
                return {"status": "RESTART_RECONCILING", "route": "NEW_CONVERSATION"}
            reconcile_id = self._recovery_operation_id(
                row, "reconcile-send-new-chat", reconcile_attempt,
            )
            reconciled = self.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id=reconcile_id, capability="browser",
                arguments={"command": "reconcile-send-to-created-tab",
                           "instance_id": ctx["instance_id"], "relay_id": send_id},
            )
            if reconciled.outcome != Outcome.APPLIED:
                return {"status": "RESTART_RECONCILING", "route": "NEW_CONVERSATION"}
            successor = str(reconciled.evidence.get("conversation_key") or "").lower()
            if not successor:
                self.ledger.mark_current_recovery_unknown(
                    row, reason="NEW_CHAT_RECONCILED_CONVERSATION_ID_UNKNOWN",
                )
                return {"status": "RESTART_UNKNOWN", "route": "NEW_CONVERSATION"}
            message = self._recovery_message(row, kind)
            next_generation = self.ledger.prepare_recovery_generation(
                row, conversation_key=successor,
                baseline={"responseTurnCount": 0, "generating": False,
                          "responseTurnKey": "", "responseSha256": ""},
                operation_id=send_id,
                message_sha256=_rcc_submitted_text_sha256(message), recovery_kind=kind,
                reconcile_operation_id=reconcile_id,
            )
            self.ledger.finish_recovery(row, next_generation=next_generation)
            metadata = "TRANSFERRED"
            try:
                ensure_observed_node_labels(
                    self.store,
                    conversations=[(row["conversation_key"], "ChatGPT"),
                                   (successor, "ChatGPT")],
                )
                transfer_conversation_state(
                    self.store, predecessor_conversation_key=row["conversation_key"],
                    successor_conversation_key=successor,
                )
            except (KeyError, ValueError):
                metadata = "PRESERVED_OLD"
            return {"status": "RESTARTED", "route": "NEW_CONVERSATION",
                    "generation": next_generation, "conversation_key": successor,
                    "metadata": metadata, "reconciled": True}

        attempt = self.ledger.next_recovery_attempt(row, route="NEW_CONVERSATION")
        saved = current_context.get("recovery_created_chat")
        if isinstance(saved, dict):
            create_id = str(saved.get("create_operation_id") or "")
            session_id = str(saved.get("session_id") or "")
            tab_id = int(saved.get("tab_id") or 0)
            window_id = int(saved.get("window_id") or 0)
        else:
            activity = self._activity_for(row)
            if not activity.get("window_id") or not activity.get("session_id"):
                return {"status": "RESTART_WAITING_STATE", "route": "NEW_CONVERSATION"}
            session_id = str(activity["session_id"])
            create_id = self._recovery_operation_id(row, "create-chat", attempt)
            created = self.operations.run(
                principal=principal, work_id=work.work_id, operation_id=create_id,
                capability="browser",
                arguments={"command": "create-chat-tab", "instance_id": ctx["instance_id"],
                           "window_id": activity["window_id"]},
            )
            if created.outcome == Outcome.UNKNOWN:
                self.ledger.mark_current_recovery_unknown(
                    row, reason="CREATE_CHAT_EFFECT_UNKNOWN",
                )
                return {"status": "RESTART_UNKNOWN", "route": "NEW_CONVERSATION"}
            if created.outcome == Outcome.NOT_APPLIED:
                return {"status": "RESTART_NOT_APPLIED", "route": "NEW_CONVERSATION"}
            tab_id = int(created.evidence["created_tab_id"])
            window_id = int(created.evidence["created_window_id"])
            self.ledger.remember_recovery_chat(
                row, create_operation_id=create_id, session_id=session_id,
                tab_id=tab_id, window_id=window_id,
            )
        message = self._recovery_message(row, kind)
        send_id = self._recovery_operation_id(row, "send-new-chat", attempt)
        sent = self.operations.run(
            principal=principal, work_id=work.work_id, operation_id=send_id,
            capability="browser",
            arguments={"command": "send-message", "instance_id": ctx["instance_id"],
                       "session_id": session_id, "tab_id": tab_id,
                       "window_id": window_id, "create_operation_id": create_id,
                       "text": message},
        )
        if sent.outcome == Outcome.UNKNOWN:
            self.ledger.remember_recovery_send_unknown(
                row, send_operation_id=send_id, create_operation_id=create_id,
            )
            return {"status": "RESTART_RECONCILING", "route": "NEW_CONVERSATION"}
        if sent.outcome == Outcome.NOT_APPLIED:
            return {"status": "RESTART_NOT_APPLIED", "route": "NEW_CONVERSATION"}
        successor = str(sent.evidence.get("conversation_key") or "").lower()
        if not successor:
            self.ledger.mark_current_recovery_unknown(
                row, reason="NEW_CHAT_CONVERSATION_ID_UNKNOWN",
            )
            return {"status": "RESTART_UNKNOWN", "route": "NEW_CONVERSATION"}
        next_generation = self.ledger.prepare_recovery_generation(
            row, conversation_key=successor,
            baseline={"responseTurnCount": 0, "generating": False,
                      "responseTurnKey": "", "responseSha256": ""},
            operation_id=send_id,
            message_sha256=_rcc_submitted_text_sha256(message), recovery_kind=kind,
        )
        self.ledger.finish_recovery(row, next_generation=next_generation)
        metadata = "TRANSFERRED"
        try:
            ensure_observed_node_labels(
                self.store,
                conversations=[(row["conversation_key"], "ChatGPT"),
                               (successor, "ChatGPT")],
            )
            transfer_conversation_state(
                self.store, predecessor_conversation_key=row["conversation_key"],
                successor_conversation_key=successor,
            )
        except (KeyError, ValueError):
            # Advisory Monitor metadata must not stop the already-confirmed
            # continuation.  The new exact watch remains authoritative.
            metadata = "PRESERVED_OLD"
        return {"status": "RESTARTED", "route": "NEW_CONVERSATION",
                "generation": next_generation, "conversation_key": successor,
                "metadata": metadata}

    def _recover_if_stopped(self, row: dict) -> dict:
        activity = self._activity_for(row)
        if not activity:
            self.ledger.clear_recovery_signal(row)
            return {}
        kind = str(activity["kind"])
        count = self.ledger.note_recovery_signal(row, kind=kind, observed_at=time.time())
        if count < 2:
            return {"status": "STOP_CONFIRMED_ONCE", "kind": kind}
        current = self.ledger.get(row["task_id"], row["generation"])
        context = json.loads(current["context_json"] or "{}") if current else {}
        use_new = (kind == "NEW_CHAT_REQUIRED"
                   or context.get("recovery_not_applied") == "SAME_CONVERSATION_NOT_APPLIED")
        return (self._recover_new_conversation(row, kind=kind) if use_new
                else self._recover_same_conversation(row, kind=kind))

    def prearm(self, *, task_id: str, work, instance_id: str,
               conversation_key: str, manager_conversation_key: str,
               manager_instance_id: str, operation_id: str,
               planned_send_operation_id: str = "",
               planned_send_text: str = "",
               execution_path: str = "", chain_direction_id: str = "",
               exclusive_conversation_watch: bool = False,
               max_generations: int = 0, watched_session_id: str = "",
               watched_tab_id: int = 0, watched_window_id: int = 0) -> dict:
        # Later SELF turns need only the stable Task ID; use the prior binding.
        from bct.integrations.rcc import validate_instance_id
        previous = self.ledger.latest_binding(task_id)
        instance_id = instance_id or str(previous.get("instance_id") or "")
        manager_instance_id = (manager_instance_id
                               or str(previous.get("manager_instance_id") or "")
                               or instance_id)
        conversation_key = (conversation_key
                            or str(previous.get("conversation_key") or ""))
        manager_conversation_key = (manager_conversation_key
                                    or str(previous.get("manager_conversation_key") or ""))
        validate_instance_id(instance_id)
        validate_instance_id(manager_instance_id)
        uuid_pat = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
        if not re.fullmatch(uuid_pat, conversation_key) or not re.fullmatch(
                uuid_pat, manager_conversation_key):
            raise ValueError("DELAYED_CONVERSATION_INVALID")
        self._locate(instance_id, conversation_key)
        if planned_send_operation_id:
            from bct.core.models import ConflictError
            try:
                self.store.get_operation_for(
                    operation_id=planned_send_operation_id,
                    work_id=work.work_id,
                    principal_id=work.owner_principal_id,
                )
            except KeyError:
                pass
            except ConflictError as exc:
                raise ValueError("DELAYED_PLANNED_SEND_OPERATION_FOREIGN") from exc
            else:
                raise ValueError("DELAYED_PLANNED_SEND_OPERATION_ALREADY_EXISTS")
        observed = self.latest(instance_id=instance_id,
                               conversation_key=conversation_key)
        if observed.get("ok") is not True:
            raise ValueError("DELAYED_OBSERVATION_UNAVAILABLE")
        return self.ledger.prearm_task(
            task_id=task_id, work_id=work.work_id,
            principal_id=work.owner_principal_id,
            assignment_epoch=work.assignment_epoch,
            instance_id=instance_id, conversation_key=conversation_key,
            manager_conversation_key=manager_conversation_key,
            manager_instance_id=manager_instance_id,baseline=observed,
            registration_receipt=operation_id,
            planned_send_operation_id=planned_send_operation_id,
            planned_send_text=planned_send_text,
            execution_path=execution_path, chain_direction_id=chain_direction_id,
            exclusive_conversation_watch=exclusive_conversation_watch,
            max_generations=max_generations,
            watched_session_id=watched_session_id,
            watched_tab_id=watched_tab_id,
            watched_window_id=watched_window_id,
        )

    def _response_for(self, row: dict) -> dict:
        ctx=row["context"]
        def reject(reason: str) -> dict:
            # Diagnostic only: never bypass source, receipt, or terminal checks.
            if getattr(self, "ledger", None) is not None:
                self.ledger.record_watch_diagnostic(row, reason)
            return {}
        instance, worker=ctx["instance_id"],row["conversation_key"]
        observed=self.latest(instance_id=instance,conversation_key=worker)
        if observed.get("ok") is not True:
            return reject("RCC_READ_UNAVAILABLE")
        current_count=observed.get("responseTurnCount")
        baseline_count=ctx.get("baseline_count")
        if not isinstance(current_count,int) or not isinstance(baseline_count,int):
            return reject("TURN_COUNT_UNAVAILABLE")
        changed = (current_count>baseline_count or (
            ctx.get("baseline_generating") is True
            and current_count>=baseline_count
            and str(observed.get("responseSha256") or "") != ctx.get("baseline_sha")
        ))
        # A DOM count can shrink after rerender. Only a source-user turn
        # observed at prearm and matched to this response can compensate.
        source_key = str(ctx.get("source_user_turn_key") or "")
        source_sha = str(ctx.get("source_user_sha256") or "")
        planned_source = ctx.get("source_proof_kind") == "BCT_PLANNED_SOURCE_SEND"
        if planned_source:
            source_key = str(observed.get("latestUserTurnKey") or "")
        if not source_key or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
            return reject("SOURCE_KEY_OR_SHA_MISSING")
        if (observed.get("latestUserTextOccurrenceCount") != 1
                or observed.get("responseSourceUserTextOccurrenceCount") != 1
                ) and (planned_source or source_key.startswith("fallback-turn-")):
            return reject("SOURCE_OCCURRENCE_AMBIGUOUS")
        observed_source_key = str(observed.get("responseSourceUserTurnKey") or "")
        observed_latest_key = str(observed.get("latestUserTurnKey") or "")
        source_keys_match = (
            observed_source_key == source_key
            and observed_latest_key == source_key
        )
        # Fallback keys are positional rather than durable identity.  Older
        # RCC scripts could count nested message units twice, so a page reload
        # may both add the current ``:K:user`` suffix and renumber N.  Permit
        # that representation upgrade only when both current observations
        # identify the same fallback user unit.  The exact source/send SHA and
        # unique-occurrence gates above remain the durable identity proof.
        if (not source_keys_match
                and re.fullmatch(r"fallback-turn-\d+", source_key)
                and observed_source_key == observed_latest_key
                and re.fullmatch(r"fallback-turn-\d+:\d+:user",
                                 observed_source_key)):
            source_keys_match = True
        source_match = (
            source_keys_match
            and observed.get("responseSourceUserSha256") == source_sha
            and observed.get("latestUserSha256") == source_sha
        )
        if source_key and not source_match:
            if (getattr(self, "ledger", None) is not None
                    and self.ledger.mark_source_superseded(row, observed)):
                return {}
            return reject("SOURCE_PROVENANCE_MISMATCH")
        source_send_op = str(ctx.get("source_send_operation_id") or "")
        source_send_sha = str(ctx.get("source_send_sha256") or "")
        trusted_self_source = (
            bool(source_send_op and re.fullmatch(r"[0-9a-f]{64}", source_send_sha))
            and source_match and source_send_sha == source_sha
        )
        if source_send_op and not trusted_self_source:
            return reject("SEND_PROOF_MISMATCH")
        if source_send_op:
            from bct.core.models import Outcome
            try:
                receipt = self.store.get_operation_for(
                    operation_id=source_send_op, work_id=ctx["work_id"],
                    principal_id=ctx["principal_id"],
                )
            except (KeyError, ValueError):
                return reject("SEND_RECEIPT_UNAVAILABLE")
            except Exception:
                return reject("SEND_RECEIPT_UNAVAILABLE")
            evidence = receipt.evidence
            direct_receipt_valid = (
                receipt.state.value == "FINISHED"
                and receipt.outcome == Outcome.APPLIED
                and isinstance(evidence, dict)
                and evidence.get("command") in {"send-to-tab", "send-to-created-tab"}
                and evidence.get("host_request_id") == source_send_op
                and evidence.get("instance_id") == ctx["instance_id"]
                and evidence.get("conversation_key") == row["conversation_key"]
                and evidence.get("source_message_sha256") == source_sha
            )
            reconciled_receipt_valid = False
            if not direct_receipt_valid:
                reconcile_op = str(ctx.get("source_send_reconcile_operation_id") or "")
                if not reconcile_op:
                    reconcile_state = ctx.get("recovery_reconcile")
                    recovered_from = int(ctx.get("recovered_from_generation") or 0)
                    if isinstance(reconcile_state, dict) and recovered_from > 0:
                        attempt = int(reconcile_state.get("attempt") or 0)
                        if attempt > 0:
                            reconcile_op = self._recovery_operation_id(
                                {"task_id": row["task_id"], "generation": recovered_from},
                                "reconcile-send-new-chat", attempt,
                            )
                if reconcile_op:
                    try:
                        reconciled = self.store.get_operation_for(
                            operation_id=reconcile_op, work_id=ctx["work_id"],
                            principal_id=ctx["principal_id"],
                        )
                    except (KeyError, ValueError):
                        reconciled = None
                    except Exception:
                        reconciled = None
                    reconciled_evidence = reconciled.evidence if reconciled else {}
                    reconciled_receipt_valid = (
                        reconciled is not None
                        and reconciled.state.value == "FINISHED"
                        and reconciled.outcome == Outcome.APPLIED
                        and isinstance(reconciled_evidence, dict)
                        and reconciled_evidence.get("command")
                            == "reconcile-send-to-created-tab"
                        and reconciled_evidence.get("reconciled_operation_id")
                            == source_send_op
                        and reconciled_evidence.get("instance_id") == ctx["instance_id"]
                        and reconciled_evidence.get("conversation_key")
                            == row["conversation_key"]
                    )
            if not (direct_receipt_valid or reconciled_receipt_valid):
                return reject("SEND_RECEIPT_INVALID")
        response_changed = (
            str(observed.get("responseSha256") or "") != ctx.get("baseline_sha")
            and str(observed.get("responseTurnKey") or "") != ctx.get("baseline_key")
        )
        if not (changed or (trusted_self_source and response_changed)):
            return reject("RESPONSE_NOT_NEW")
        response_key = str(observed.get("responseTurnKey") or "")
        same_inflight_turn_completed = (
            ctx.get("baseline_generating") is True
            and current_count >= baseline_count
            and response_key == str(ctx.get("baseline_key") or "")
            and str(observed.get("responseSha256") or "") != ctx.get("baseline_sha")
        )
        if (observed.get("terminal") is not True
                or observed.get("inputReady") is not True
                or observed.get("generating") is not False
                or not response_key.strip()
                or (response_key == ctx.get("baseline_key")
                    and not same_inflight_turn_completed)):
            return reject("RESPONSE_NOT_TERMINAL")
        return normalize_rcc_latest_assistant(
            observed,conversation_key=worker,
            expected_response_sha256=str(ctx.get("baseline_sha") or ""),
            response_turn_id=row["response_turn_id"],input_ready=True,
        )

    def _send_for(self, row: dict, *, destination: str, message: str,
                  operation_id: str) -> str:
        from bct.core.models import Principal, Outcome
        ctx=row["context"]
        work=self.store.get_work(ctx["work_id"])
        from bct.node_recovery import NodeRecoveryLedger
        NodeRecoveryLedger(self.store).assert_send_allowed(
            work_id=work.work_id, conversation_key=destination,
        )
        from bct.core.capabilities import capability_matches
        if (work.state!="ACTIVE" or work.assignment_epoch!=ctx["assignment_epoch"]
                or work.owner_principal_id!=ctx["principal_id"]
                or not any(capability_matches(action, "browser") for action in work.actions)):
            raise ValueError("DELAYED_WORK_CHANGED")
        instance=(ctx["instance_id"] if destination==row["conversation_key"]
                  else ctx["manager_instance_id"])
        session,tab,window=self._locate(instance,destination)
        if destination==row["conversation_key"]:
            # This plan belongs to the response that caused this exact SELF
            # continuation. It never starts a new Chain or chooses for B.
            from bct.chain_execution_plan import ChainExecutionPlanLedger
            plan = ChainExecutionPlanLedger.get_for_chain_turn(
                store=self.store, work_id=work.work_id,
                task_id=row["task_id"], generation=row["generation"],
            )
            message = _self_message_with_execute_plan(message, plan)
            message=(
                _self_prearm_guidance(
                    work_id=work.work_id, task_id=row["task_id"],
                )
                + "\n\n"
                "이후 아래 작업을 수행하고 응답 마지막에 "
                "NEXT TASK — SELF 또는 NEXT TASK — MANAGER 및 다음 지시서/보고서를 작성하세요.\n\n"
                +message
            )
        principal=Principal(work.owner_principal_id,"delayed-send-existing-work",
                            frozenset({"browser"}))
        result=self.operations.run(
            principal=principal,work_id=work.work_id,operation_id=operation_id,
            capability="browser",
            arguments={"command":"send-message","instance_id":instance,
                       "session_id":session,"tab_id":tab,"window_id":window,
                       "conversation_key":destination,"text":message},
        )
        if result.outcome!=Outcome.APPLIED:
            raise ValueError("DELAYED_RCC_SEND_" + result.outcome.value)
        if destination==row["conversation_key"]:
            self.ledger.bind_self_source_send(
                task_id=row["task_id"],next_generation=row["generation"]+1,
                operation_id=operation_id,
                message_sha256=_rcc_submitted_text_sha256(message),
            )
        return operation_id

    def poll_once(self, limit: int = 8) -> dict:
        events=[]
        for row in self.ledger.watching(limit=limit):
            try:
                recovery = self._recover_if_stopped(row)
                if recovery:
                    if recovery.get("status") != "STOP_CONFIRMED_ONCE":
                        events.append({"task_id": row["task_id"],
                                       "generation": row["generation"], **recovery})
                    continue
                observation=self._response_for(row)
                if not observation:
                    continue
                watch=Watch(row["task_id"],row["generation"],
                            row["conversation_key"],row["response_turn_id"],
                            row["source_send_receipt"])
                ctx=row["context"]
                runner=SendDelayedMessageRunner(
                    self.ledger,
                    read_response=lambda _watch:observation,
                    send_message=lambda dest,body,key:self._send_for(
                        row,destination=dest,message=body,operation_id=key),
                )
                result=runner.poll_once(
                    watch,manager_conversation_key=ctx["manager_conversation_key"])
                if result.status not in {"WAITING_RESPONSE", "WAITING_WATCH"}:
                    events.append({"task_id":watch.task_id,
                                   "generation":watch.generation,
                                   "status":result.status})
            except Exception as exc:
                events.append({"task_id":row["task_id"],"generation":row["generation"],
                               "status":"ERROR","reason":type(exc).__name__})
        return {"watched":len(self.ledger.watching(limit=limit)),
                "events":events}
