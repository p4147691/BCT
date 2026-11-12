"""Generic, Loop-only continuation gateway.

This is the only place a future Loop adapter may arm a Watch or deliver a
Continuation.  It is intentionally driven by small ports so production BCT
adapters can be added later without teaching processing blocks about transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bct.loop_recipe_contracts import Continuation, LoopContractError
from bct.loop_recipe_flow import LinkKind
from bct.loop_recipe_ledger import LoopRecipeLedger


@dataclass(frozen=True)
class WatchReceipt:
    continuation_id: str
    watch_id: str
    state: str

    def matches(self, continuation: Continuation) -> bool:
        return (self.continuation_id == continuation.continuation_id
                and self.watch_id == continuation.watch_id and self.state == "WATCHING")


@dataclass(frozen=True)
class DeliveryReceipt:
    operation_id: str
    receipt_ref: str
    outcome: str

    def matches(self, continuation: Continuation) -> bool:
        return (self.operation_id == continuation.operation_id
                and self.receipt_ref == continuation.receipt_ref
                and self.outcome in {"DELIVERED", "NOT_APPLIED", "UNKNOWN"})


class LoopWatchPort(Protocol):
    def prearm(self, continuation: Continuation) -> WatchReceipt: ...


class LoopTransportPort(Protocol):
    def deliver(self, continuation: Continuation) -> DeliveryReceipt: ...


@dataclass(frozen=True)
class GatewayResult:
    state: str
    continuation_id: str
    delivered: bool
    receipt_observation: str = ""


class LoopContinuationGateway:
    """Persist before effects; never retry an uncertain original operation."""

    def __init__(self, ledger: LoopRecipeLedger, watch: LoopWatchPort,
                 transport: LoopTransportPort):
        self.ledger, self.watch, self.transport = ledger, watch, transport

    def connect(self, *, continuation: Continuation, link: LinkKind) -> GatewayResult:
        self.ledger.stage(continuation=continuation, link=link)
        if link == LinkKind.BLOCKED:
            return GatewayResult("BLOCKED", continuation.continuation_id, False)
        armed = self.watch.prearm(continuation)
        if not armed.matches(continuation):
            raise LoopContractError("LOOP_WATCH_RECEIPT_UNVERIFIED")
        if link == LinkKind.WAIT:
            return GatewayResult("WATCHING", continuation.continuation_id, False)
        if link != LinkKind.HANDOFF:
            raise LoopContractError("LOOP_GATEWAY_LINK_INVALID")
        receipt = self.transport.deliver(continuation)
        if not receipt.matches(continuation):
            raise LoopContractError("LOOP_DELIVERY_RECEIPT_UNVERIFIED")
        self.ledger.observe_original_receipt(
            continuation_id=continuation.continuation_id, observation=receipt.outcome)
        return GatewayResult(
            "DELIVERED" if receipt.outcome == "DELIVERED" else receipt.outcome,
            continuation.continuation_id, receipt.outcome == "DELIVERED", receipt.outcome,
        )
