"""Deterministic pre-dispatch routing policy for ordinary worker nodes.

This module deliberately decides *before* a browser send is reserved.  It
never treats a submitted or uncertain delivery as movable: routing a second
copy of either would turn a capacity decision into duplicate work.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Iterable


DEFAULT_SHORT_WAIT_S = 15.0
DEFAULT_REQUIRED_WAIT_S = 600.0


def validate_routing_waits(
    short_wait_s: object = DEFAULT_SHORT_WAIT_S,
    required_wait_s: object = DEFAULT_REQUIRED_WAIT_S,
) -> tuple[float, float]:
    """Validate operator-adjustable routing delays before dispatch decisions.

    These values are capacity policy, not a delivery timeout: a submitted or
    unknown effect is still never re-routed regardless of their value.
    """
    if (isinstance(short_wait_s, bool) or isinstance(required_wait_s, bool)
            or not isinstance(short_wait_s, (int, float))
            or not isinstance(required_wait_s, (int, float))):
        raise ValueError("NODE_ROUTING_POLICY_INTERVAL_INVALID")
    short = float(short_wait_s)
    required = float(required_wait_s)
    if (not math.isfinite(short) or not math.isfinite(required)
            or not 1.0 <= short <= 300.0
            or not 30.0 <= required <= 3600.0
            or required < short):
        raise ValueError("NODE_ROUTING_POLICY_INTERVAL_INVALID")
    return short, required


class NodeAffinity(StrEnum):
    """How strongly one logical assignment depends on its first worker."""

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    ANY = "ANY"


class NodeReadiness(StrEnum):
    IDLE = "IDLE"
    GENERATING = "GENERATING"
    DISCONNECTED = "DISCONNECTED"
    ORPHANED = "ORPHANED"


class RoutingAction(StrEnum):
    DISPATCH_PREFERRED = "DISPATCH_PREFERRED"
    WAIT_REQUIRED = "WAIT_REQUIRED"
    ESCALATE_REQUIRED = "ESCALATE_REQUIRED"
    REROUTE_TO_STANDBY = "REROUTE_TO_STANDBY"
    PROVISION_NODE = "PROVISION_NODE"
    PROTECT_EXISTING_EFFECT = "PROTECT_EXISTING_EFFECT"


@dataclass(frozen=True)
class RoutingPolicy:
    affinity: NodeAffinity
    short_wait_s: float = DEFAULT_SHORT_WAIT_S
    required_wait_s: float = DEFAULT_REQUIRED_WAIT_S
    allow_provision: bool = True

    def __post_init__(self) -> None:
        short, required = validate_routing_waits(self.short_wait_s, self.required_wait_s)
        object.__setattr__(self, "short_wait_s", short)
        object.__setattr__(self, "required_wait_s", required)
        if not isinstance(self.allow_provision, bool):
            raise ValueError("NODE_ROUTING_POLICY_PROVISION_INVALID")


@dataclass(frozen=True)
class RoutingCandidate:
    node_id: str
    attachment_id: str
    readiness: NodeReadiness


@dataclass(frozen=True)
class RoutingDecision:
    action: RoutingAction
    reason: str
    candidate: RoutingCandidate | None = None


def decide_route(
    *, policy: RoutingPolicy, preferred: RoutingCandidate,
    fallbacks: Iterable[RoutingCandidate], elapsed_s: float,
    delivery_effect: str = "NOT_SENT",
) -> RoutingDecision:
    """Choose only a safe next action for an unsubmitted assignment.

    ``delivery_effect`` comes from the durable dispatch receipt, not a caller
    guess.  APPLIED and UNKNOWN are intentionally terminal for routing: a
    duplicate worker must never be selected for them.
    """
    if elapsed_s < 0:
        raise ValueError("NODE_ROUTING_ELAPSED_INVALID")
    effect = str(delivery_effect).upper()
    if effect not in {"NOT_SENT", "NOT_APPLIED", "APPLIED", "UNKNOWN"}:
        raise ValueError("NODE_ROUTING_EFFECT_INVALID")
    if effect in {"APPLIED", "UNKNOWN"}:
        return RoutingDecision(
            RoutingAction.PROTECT_EXISTING_EFFECT,
            "DELIVERY_ALREADY_APPLIED_OR_UNKNOWN",
        )
    if preferred.readiness is NodeReadiness.IDLE:
        return RoutingDecision(RoutingAction.DISPATCH_PREFERRED, "PREFERRED_IDLE")
    if policy.affinity is NodeAffinity.REQUIRED:
        if elapsed_s < policy.required_wait_s:
            return RoutingDecision(RoutingAction.WAIT_REQUIRED, "REQUIRED_NODE_BUSY")
        return RoutingDecision(RoutingAction.ESCALATE_REQUIRED, "REQUIRED_WAIT_EXCEEDED")
    if elapsed_s < policy.short_wait_s:
        return RoutingDecision(RoutingAction.WAIT_REQUIRED, "SHORT_WAIT_ACTIVE")
    for candidate in fallbacks:
        if candidate.readiness is NodeReadiness.IDLE:
            return RoutingDecision(
                RoutingAction.REROUTE_TO_STANDBY,
                "PREFERRED_BUSY_STANDBY_IDLE",
                candidate,
            )
    if policy.allow_provision:
        return RoutingDecision(RoutingAction.PROVISION_NODE, "NO_IDLE_STANDBY")
    return RoutingDecision(RoutingAction.ESCALATE_REQUIRED, "NO_IDLE_STANDBY")
