"""Loop-only recovery planner for durable Continuations.

The planner has no external effect.  A later Loop recovery adapter must carry
out a returned action through existing BCT check/recheck/reconcile/replace
capabilities and write the resulting evidence back before asking again.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bct.loop_recipe_contracts import LoopContractError


class RecoveryAction(str, Enum):
    RESUME = "resume"
    RECONCILE_ORIGINAL_RECEIPT = "reconcile_original_receipt"
    RECHECK = "recheck"
    PREPARE_REPLACE = "prepare_replace"
    HOLD = "hold"


@dataclass(frozen=True)
class RecoveryEvidence:
    receipt_observation: str
    node_observation: str
    unchanged_rechecks: int = 0

    def __post_init__(self) -> None:
        if self.receipt_observation not in {"DELIVERED", "NOT_APPLIED", "UNKNOWN", "UNOBSERVED"}:
            raise LoopContractError("LOOP_RECOVERY_RECEIPT_INVALID")
        if self.node_observation not in {"OK", "WAIT", "CHECK", "UNOBSERVED"}:
            raise LoopContractError("LOOP_RECOVERY_NODE_INVALID")
        if type(self.unchanged_rechecks) is not int or self.unchanged_rechecks < 0:
            raise LoopContractError("LOOP_RECOVERY_RECHECK_COUNT_INVALID")


def plan_recovery(evidence: RecoveryEvidence) -> RecoveryAction:
    """Choose the next safe observation/preparation action, never a replay."""
    if evidence.receipt_observation == "UNKNOWN":
        return RecoveryAction.RECONCILE_ORIGINAL_RECEIPT
    if evidence.receipt_observation == "UNOBSERVED":
        return RecoveryAction.HOLD
    if evidence.node_observation == "OK":
        return RecoveryAction.RESUME
    if evidence.node_observation == "WAIT":
        return RecoveryAction.RECHECK
    if evidence.node_observation == "CHECK" and evidence.unchanged_rechecks >= 2:
        return RecoveryAction.PREPARE_REPLACE
    if evidence.node_observation in {"CHECK", "UNOBSERVED"}:
        return RecoveryAction.RECHECK
    return RecoveryAction.HOLD
