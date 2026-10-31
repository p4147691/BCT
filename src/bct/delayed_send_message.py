"""One-response Delayed Send Message continuation for BCT Task Run.

This module owns the state transition, not RCC delivery. Callers supply the
existing durable watch registration and send-message implementations.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Callable


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
    if not body or len(body) > 16000:
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
                    PRIMARY KEY(task_id,generation)
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
                "INSERT INTO delayed_send_watches VALUES(?,?,?,?,?,?)",
                (watch.task_id,watch.generation,watch.conversation_key,
                 watch.response_turn_id,watch.source_send_receipt,"RESERVED"))
            return True

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

