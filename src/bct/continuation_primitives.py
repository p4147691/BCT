"""Pure, reusable pieces for durable continuation recipes.

This layer intentionally has no RCC, Work-store, browser, or message-send
dependency.  Adapters provide identity and observations; recipes decide which
bound action to execute after an alarm is ready.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class WatchCondition(str, Enum):
    RESPONSE_FINISHED = "conversation.response_finished"
    INPUT_READY = "conversation.input_ready"


class AlarmKind(str, Enum):
    RESPONSE_READY = "conversation.response_ready"


class ActionKind(str, Enum):
    WAKEUP_MESSAGE = "wakeup-message"
    RETURN = "return"
    SEND_MESSAGE = "send-message"
    CREATE_WATCH = "create-watch"


class ContinuationRoute(str, Enum):
    """The prior B turn's recorded direction for this execution flow."""
    SELF = "SELF"
    MANAGER = "MANAGER"


@dataclass(frozen=True)
class ContinuationDecision:
    """A durable, data-only BB or BA decision made by the finishing B turn.

    It deliberately contains no target lookup or send behavior.  A later
    routing block can deliver it to the already-bound worker or manager.
    """
    route: ContinuationRoute
    payload: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload, str) or not self.payload.strip() or len(self.payload) > 10800:
            raise ValueError("CONTINUATION_DECISION_INVALID")


@dataclass(frozen=True)
class ContinuationBranch:
    """One reusable SELF/MANAGER branch selected from a recorded decision.

    This is the decision-routing part of a continuation recipe.  It selects a
    named recipient role but does not decide which external action that role
    will receive.
    """
    route: ContinuationRoute
    recipient_role: str
    payload: str


def branch_for_decision(decision: ContinuationDecision) -> ContinuationBranch:
    """Read a prior B decision and select its SELF or MANAGER branch only."""
    recipient_role = "worker" if decision.route == ContinuationRoute.SELF else "manager"
    return ContinuationBranch(
        route=decision.route, recipient_role=recipient_role, payload=decision.payload,
    )


def send_message_for_branch(*, alarm: Alarm, branch: ContinuationBranch) -> ActionRequest:
    """Make the ordinary message action for an already-selected branch."""
    return ActionRequest(ActionKind.SEND_MESSAGE, alarm, branch.recipient_role, branch.payload)


def wakeup_message(*, alarm: Alarm, execution_ref: str) -> ActionRequest:
    """Request one exact wakeup message without choosing or contacting a target.

    A wakeup message is semantically different from an ordinary message: its
    receiver must inspect its already-recorded execution context and continue.
    The eventual delivery adapter may use ``bct_send_message`` as transport,
    but this primitive does not know a SELF/MANAGER decision and cannot send.
    """
    if not isinstance(execution_ref, str) or not execution_ref.strip():
        raise ValueError("CONTINUATION_WAKE_REFERENCE_INVALID")
    return ActionRequest(ActionKind.WAKEUP_MESSAGE, alarm, "worker", execution_ref)


@dataclass(frozen=True)
class ContinuationContext:
    """Caller-supplied identity binding for a continuation recipe.

    The context is deliberately data-only.  It identifies an authorized actor,
    the watched subject, and named recipients, but cannot discover a target or
    perform an external effect by itself.
    """
    work_id: str
    actor_ref: str
    assignment_epoch: int
    subject_ref: str
    subject_attachment_ref: str
    recipients: Mapping[str, str]
    recipient_attachments: Mapping[str, str]

    def __post_init__(self) -> None:
        if (not self.work_id or not self.actor_ref or self.assignment_epoch < 1
                or not self.subject_ref or not self.subject_attachment_ref):
            raise ValueError("CONTINUATION_CONTEXT_INVALID")
        if not self.recipients or any(not role or not value
                                      for role, value in self.recipients.items()):
            raise ValueError("CONTINUATION_RECIPIENTS_INVALID")
        if set(self.recipients) != set(self.recipient_attachments):
            raise ValueError("CONTINUATION_ATTACHMENT_ROLES_INVALID")
        object.__setattr__(self, "recipients", MappingProxyType(dict(self.recipients)))
        object.__setattr__(self, "recipient_attachments",
                           MappingProxyType(dict(self.recipient_attachments)))

    @classmethod
    def delayed_send(cls, *, work_id: str, principal_id: str,
                     assignment_epoch: int, instance_id: str,
                     conversation_key: str, manager_conversation_key: str,
                     manager_instance_id: str) -> "ContinuationContext":
        """Build the legacy Delayed Send recipe binding without target lookup."""
        return cls(
            work_id=work_id, actor_ref=principal_id,
            assignment_epoch=assignment_epoch, subject_ref=conversation_key,
            subject_attachment_ref=instance_id,
            recipients={"worker": conversation_key,
                        "manager": manager_conversation_key},
            recipient_attachments={"worker": instance_id,
                                   "manager": manager_instance_id},
        )

    def as_legacy_record(self) -> dict[str, object]:
        """Keep the current SQLite JSON keys stable through the migration."""
        return {
            "work_id": self.work_id,
            "principal_id": self.actor_ref,
            "assignment_epoch": self.assignment_epoch,
            "instance_id": self.subject_attachment_ref,
            "conversation_key": self.subject_ref,
            "manager_conversation_key": self.recipients["manager"],
            "manager_instance_id": self.recipient_attachments["manager"],
            "continuation_context_v1": {
                "actor_ref": self.actor_ref,
                "subject_ref": self.subject_ref,
                "subject_attachment_ref": self.subject_attachment_ref,
                "recipients": dict(self.recipients),
                "recipient_attachments": dict(self.recipient_attachments),
            },
        }


@dataclass(frozen=True)
class WatchEvidence:
    """Facts supplied by an adapter; no authority is inferred from them."""
    subject_ref: str
    response_turn_id: str
    response_text: str
    response_complete: bool
    input_ready: bool


@dataclass(frozen=True)
class Alarm:
    """Immutable proof that a watch condition became ready."""
    kind: AlarmKind
    watch_ref: str
    evidence: WatchEvidence


@dataclass(frozen=True)
class ActionRequest:
    """A recipe-level action request; an adapter performs the external effect."""
    kind: ActionKind
    alarm: Alarm
    recipient_role: str
    payload: str = ""


def response_ready_alarm(*, watch_ref: str, subject_ref: str,
                         expected_response_turn_id: str,
                         response_turn_id: str, response_text: str,
                         response_complete: bool,
                         input_ready: bool) -> Alarm | None:
    """Create an alarm only for the exact completed, input-ready response."""
    if (not watch_ref or not subject_ref
            or response_turn_id != expected_response_turn_id
            or not isinstance(response_text, str)
            or response_complete is not True
            or input_ready is not True):
        return None
    return Alarm(
        kind=AlarmKind.RESPONSE_READY,
        watch_ref=watch_ref,
        evidence=WatchEvidence(
            subject_ref=subject_ref,
            response_turn_id=response_turn_id,
            response_text=response_text,
            response_complete=True,
            input_ready=True,
        ),
    )
