from __future__ import annotations

from enum import StrEnum


class DeliveryState(StrEnum):
    NOT_SENT = "NOT_SENT"
    WAITING_TARGET = "WAITING_TARGET"
    SENT_WAITING = "SENT_WAITING"
    REPLY_CAPTURED = "REPLY_CAPTURED"
    RETURNED = "RETURNED"
    NOT_APPLIED = "NOT_APPLIED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class DeliveryEvent(StrEnum):
    TARGET_QUEUED = "TARGET_QUEUED"
    WORKER_TURN_CONFIRMED = "WORKER_TURN_CONFIRMED"
    WORKER_REPLY_CAPTURED = "WORKER_REPLY_CAPTURED"
    MANAGER_TURN_CONFIRMED = "MANAGER_TURN_CONFIRMED"
    PRE_SUBMIT_REJECTED = "PRE_SUBMIT_REJECTED"
    WORKER_TURN_FAILED = "WORKER_TURN_FAILED"
    EFFECT_BOUNDARY_UNPROVEN = "EFFECT_BOUNDARY_UNPROVEN"


class DeliveryTransitionError(ValueError):
    pass


_TRANSITIONS = {
    (DeliveryState.NOT_SENT, DeliveryEvent.TARGET_QUEUED):
        DeliveryState.WAITING_TARGET,
    (DeliveryState.NOT_SENT, DeliveryEvent.WORKER_TURN_CONFIRMED):
        DeliveryState.SENT_WAITING,
    (DeliveryState.WAITING_TARGET, DeliveryEvent.WORKER_TURN_CONFIRMED):
        DeliveryState.SENT_WAITING,
    (DeliveryState.WAITING_TARGET, DeliveryEvent.PRE_SUBMIT_REJECTED):
        DeliveryState.NOT_APPLIED,
    (DeliveryState.SENT_WAITING, DeliveryEvent.WORKER_REPLY_CAPTURED):
        DeliveryState.REPLY_CAPTURED,
    (DeliveryState.REPLY_CAPTURED, DeliveryEvent.MANAGER_TURN_CONFIRMED):
        DeliveryState.RETURNED,
    (DeliveryState.NOT_SENT, DeliveryEvent.PRE_SUBMIT_REJECTED):
        DeliveryState.NOT_APPLIED,
    (DeliveryState.SENT_WAITING, DeliveryEvent.WORKER_TURN_FAILED):
        DeliveryState.FAILED,
}

_EVENT_RESULT = {
    DeliveryEvent.TARGET_QUEUED: DeliveryState.WAITING_TARGET,
    DeliveryEvent.WORKER_TURN_CONFIRMED: DeliveryState.SENT_WAITING,
    DeliveryEvent.WORKER_REPLY_CAPTURED: DeliveryState.REPLY_CAPTURED,
    DeliveryEvent.MANAGER_TURN_CONFIRMED: DeliveryState.RETURNED,
    DeliveryEvent.PRE_SUBMIT_REJECTED: DeliveryState.NOT_APPLIED,
    DeliveryEvent.WORKER_TURN_FAILED: DeliveryState.FAILED,
    DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN: DeliveryState.NEEDS_REVIEW,
}

TERMINAL_DELIVERY_STATES = frozenset({
    DeliveryState.RETURNED,
    DeliveryState.NOT_APPLIED,
    DeliveryState.FAILED,
    DeliveryState.NEEDS_REVIEW,
})


def advance_delivery_state(
    current: DeliveryState | str, event: DeliveryEvent | str,
) -> DeliveryState:
    """Advance one logical delivery without retries, skips, or rollback.

    Re-observing the event that establishes the current state is idempotent.
    An unprovable effect boundary terminates any still-active delivery in
    NEEDS_REVIEW and never converts it to success or NOT_APPLIED.
    """
    try:
        state = DeliveryState(current)
        observed = DeliveryEvent(event)
    except ValueError as exc:
        raise DeliveryTransitionError("DELIVERY_STATE_OR_EVENT_INVALID") from exc

    if _EVENT_RESULT[observed] == state:
        return state
    if state in TERMINAL_DELIVERY_STATES:
        raise DeliveryTransitionError("DELIVERY_TERMINAL_STATE_IMMUTABLE")
    if observed == DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN:
        return DeliveryState.NEEDS_REVIEW
    try:
        return _TRANSITIONS[(state, observed)]
    except KeyError as exc:
        raise DeliveryTransitionError("DELIVERY_TRANSITION_INVALID") from exc

