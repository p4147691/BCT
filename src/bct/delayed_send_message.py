"""One-response Delayed Send Message continuation for BCT Task Run.

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


def _rcc_submitted_text_sha256(message: str) -> str:
    """Match RCC RelayCore.normalizeMessageText before comparing DOM source SHA."""
    normalized = message.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    normalized = "\n".join(re.sub(r"[ \t]+$", "", line)
                           for line in normalized.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
    markers = [i for i, line in enumerate(lines)
               if line.strip() in {"NEXT TASK — SELF", "NEXT TASK — MANAGER"}]
    if len(markers) != 1 or markers[0] == len(lines)-1:
        raise InstructionError("NEXT_INSTRUCTION_MISSING_OR_AMBIGUOUS")
    idx = markers[0]
    body = "\n".join(lines[idx+1:]).strip()
    if not body or len(body) > 10800:
        raise InstructionError("NEXT_INSTRUCTION_INVALID")
    return NextInstruction(
        NextTarget.SELF if lines[idx].strip().endswith("SELF") else NextTarget.MANAGER,
        body,
    )



def bind_next_response(watch: Watch, *, send_receipt: str,
                       response_turn_id: str) -> Watch:
    """Bind the pre-reserved next watch to the exact new send and response."""
    if watch.response_turn_id or watch.source_send_receipt:
        raise ValueError("NEXT_WATCH_ALREADY_BOUND")
    if not send_receipt or not response_turn_id:
        raise ValueError("NEXT_WATCH_RECEIPT_REQUIRED")
    return Watch(watch.task_id, watch.generation, watch.conversation_key,
                 response_turn_id, send_receipt)


def advance(
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
    try:
        instruction = extract_next_instruction(response_text)
    except InstructionError:
        return Continuation("INSTRUCTION_UNAVAILABLE")
    key = hashlib.sha256(
        f"{watch.task_id}|{watch.generation}|{response_turn_id}".encode()
    ).hexdigest()[:24]
    if instruction.target == NextTarget.SELF:
        next_watch = Watch(watch.task_id, watch.generation+1,
                          watch.conversation_key, "", "")
        register_next_watch(next_watch)
        receipt = send_message(watch.conversation_key, instruction.text,
                               "delayed-self-" + key)
        return Continuation("SELF_SENT", next_watch, receipt)
    receipt = send_message(manager_conversation_key, instruction.text,
                           "delayed-manager-" + key)
    return Continuation("RETURNED_TO_MANAGER", None, receipt)

def advance_from_rcc(
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
    return advance(
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
                    registration_receipt: str) -> dict:
        """Worker prearms one current response, reusing any reserved next turn."""
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id):
            raise ValueError("DELAYED_TASK_ID_INVALID")
        context = {
            "work_id": work_id, "principal_id": principal_id,
            "assignment_epoch": assignment_epoch,
            "instance_id": instance_id, "manager_instance_id": manager_instance_id,
            "conversation_key": conversation_key,
            "manager_conversation_key": manager_conversation_key,
            "baseline_count": baseline.get("responseTurnCount"),
            "baseline_generating": baseline.get("generating") is True,
            "baseline_key": str(baseline.get("responseTurnKey") or ""),
            "baseline_sha": str(baseline.get("responseSha256") or ""),
            "source_user_turn_key": str(baseline.get("latestUserTurnKey") or ""),
            "source_user_sha256": str(baseline.get("latestUserSha256") or ""),
        }
        if not isinstance(context["baseline_count"], int) or context["baseline_count"] < 0:
            raise ValueError("DELAYED_RCC_TURN_COUNT_UNAVAILABLE")
        # A manually submitted first task has no BCT send receipt. Anchor its
        # source to an exact user turn observed over the authorized RCC channel
        # at prearm time; this is observational evidence, not sender identity.
        if (not context["source_user_turn_key"]
                or context["source_user_turn_key"].startswith("fallback-turn-")
                or not re.fullmatch(r"[0-9a-f]{64}", context["source_user_sha256"])):
            raise ValueError("DELAYED_SOURCE_USER_PROOF_REQUIRED")
        context["source_proof_kind"] = "RCC_PREARM_USER_TURN"
        with self.store.transaction() as db:
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
                    ("source_send_operation_id", "source_send_sha256") if key in old
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
                        or old.get("manager_conversation_key") != manager_conversation_key):
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



class DelayedSendRunner:
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
        try:
            extract_next_instruction(observation.get("response_text"))
        except InstructionError:
            return Continuation("INSTRUCTION_UNAVAILABLE")
        if not self.ledger.bind_observed_turn(watch, turn_key, response_sha):
            return Continuation("WAITING_EXPECTED_RESPONSE")
        if not self.ledger.claim_response(watch):
            return Continuation("ALREADY_DISPATCHING")
        try:
            result = advance_from_rcc(
                watch=watch, observation=observation,
                manager_conversation_key=manager_conversation_key,
                register_next_watch=self.ledger.reserve,
                send_message=self.send_message,
            )
        except Exception:
            self.ledger.mark_result(watch, "UNKNOWN")
            raise
        self.ledger.mark_result(watch, result.status)
        return result



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


class DelayedSendService:
    """Core tick: observe a single reserved B response, then send using BCT receipts."""
    def __init__(self, *, store, relay_feature, operations):
        self.store = store
        self.relay_feature = relay_feature
        self.operations = operations
        self.ledger = DurableWatchLedger(store)

    def _locate(self, instance_id: str, conversation_key: str):
        import secrets
        session_id, tabs = self.relay_feature._read_target_state(
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
        return self.relay_feature.client.request(
            instance_id=instance_id,
            request_id="delayed-read-" + secrets.token_hex(12),
            command="read-latest-assistant",
            extra={"instanceId":instance_id, "sessionId":session,
                   "tabId":tab,"windowId":window,"conversationKey":conversation_key},
            timeout_s=5.0,
        )

    def prearm(self, *, task_id: str, work, instance_id: str,
               conversation_key: str, manager_conversation_key: str,
               manager_instance_id: str, operation_id: str) -> dict:
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
        )

    def _response_for(self, row: dict) -> dict:
        ctx=row["context"]
        instance, worker=ctx["instance_id"],row["conversation_key"]
        observed=self.latest(instance_id=instance,conversation_key=worker)
        if observed.get("ok") is not True:
            return {}
        current_count=observed.get("responseTurnCount")
        baseline_count=ctx.get("baseline_count")
        if not isinstance(current_count,int) or not isinstance(baseline_count,int):
            return {}
        changed = (current_count>baseline_count or (
            ctx.get("baseline_generating") is True
            and current_count>=baseline_count
            and str(observed.get("responseSha256") or "") != ctx.get("baseline_sha")
        ))
        # A DOM count can shrink after rerender. Only a source-user turn
        # observed at prearm and matched to this response can compensate.
        source_key = str(ctx.get("source_user_turn_key") or "")
        source_sha = str(ctx.get("source_user_sha256") or "")
        if (not source_key or source_key.startswith("fallback-turn-")
                or not re.fullmatch(r"[0-9a-f]{64}", source_sha)):
            return {}
        source_match = (
            bool(source_key and source_sha)
            and not source_key.startswith("fallback-turn-")
            and observed.get("responseSourceUserTurnKey") == source_key
            and observed.get("responseSourceUserSha256") == source_sha
            and observed.get("latestUserTurnKey") == source_key
            and observed.get("latestUserSha256") == source_sha
        )
        if source_key and not source_match:
            return {}
        source_send_op = str(ctx.get("source_send_operation_id") or "")
        source_send_sha = str(ctx.get("source_send_sha256") or "")
        trusted_self_source = (
            bool(source_send_op and re.fullmatch(r"[0-9a-f]{64}", source_send_sha))
            and source_match and source_send_sha == source_sha
        )
        if source_send_op and not trusted_self_source:
            return {}
        if source_send_op:
            from bct.core.models import Outcome
            try:
                receipt = self.store.get_operation_for(
                    operation_id=source_send_op, work_id=ctx["work_id"],
                    principal_id=ctx["principal_id"],
                )
            except (KeyError, ValueError):
                return {}
            except Exception:
                return {}
            evidence = receipt.evidence
            if (receipt.state.value != "FINISHED"
                    or receipt.outcome != Outcome.APPLIED
                    or not isinstance(evidence, dict)
                    or evidence.get("command") not in {"send-to-tab", "send-to-created-tab"}
                    or evidence.get("host_request_id") != source_send_op
                    or evidence.get("instance_id") != ctx["instance_id"]):
                return {}
        response_changed = (
            str(observed.get("responseSha256") or "") != ctx.get("baseline_sha")
            and str(observed.get("responseTurnKey") or "") != ctx.get("baseline_key")
        )
        if not (changed or (trusted_self_source and response_changed)):
            return {}
        if (observed.get("terminal") is not True
                or observed.get("inputReady") is not True
                or observed.get("generating") is not False
                or not str(observed.get("responseTurnKey") or "").strip()
                or str(observed.get("responseTurnKey")) == ctx.get("baseline_key")):
            return {}
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
        if (work.state!="ACTIVE" or work.assignment_epoch!=ctx["assignment_epoch"]
                or work.owner_principal_id!=ctx["principal_id"]
                or "relay_browser" not in work.actions):
            raise ValueError("DELAYED_WORK_CHANGED")
        instance=(ctx["instance_id"] if destination==row["conversation_key"]
                  else ctx["manager_instance_id"])
        session,tab,window=self._locate(instance,destination)
        if destination==row["conversation_key"]:
            message=(
                "작업 시작 전에 BCT Delayed Send Message를 다시 선예약하세요. "
                f"work_id={work.work_id}, task_id={row['task_id']}. "
                "이후 아래 작업을 수행하고 응답 마지막에 "
                "NEXT TASK — SELF 또는 NEXT TASK — MANAGER 및 다음 지시서/보고서를 작성하세요.\n\n"
                +message
            )
        principal=Principal(work.owner_principal_id,"delayed-send-existing-work",
                            frozenset({"relay_browser"}))
        result=self.operations.run(
            principal=principal,work_id=work.work_id,operation_id=operation_id,
            capability="relay_browser",
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
                observation=self._response_for(row)
                if not observation:
                    continue
                watch=Watch(row["task_id"],row["generation"],
                            row["conversation_key"],row["response_turn_id"],
                            row["source_send_receipt"])
                ctx=row["context"]
                runner=DelayedSendRunner(
                    self.ledger,
                    read_response=lambda _watch:observation,
                    send_message=lambda dest,body,key:self._send_for(
                        row,destination=dest,message=body,operation_id=key),
                )
                result=runner.poll_once(
                    watch,manager_conversation_key=ctx["manager_conversation_key"])
                if result.status not in {"WAITING_RESPONSE","INSTRUCTION_UNAVAILABLE",
                                         "WAITING_WATCH"}:
                    events.append({"task_id":watch.task_id,
                                   "generation":watch.generation,
                                   "status":result.status})
            except Exception as exc:
                events.append({"task_id":row["task_id"],"generation":row["generation"],
                               "status":"ERROR","reason":type(exc).__name__})
        return {"watched":len(self.ledger.watching(limit=limit)),
                "events":events}
