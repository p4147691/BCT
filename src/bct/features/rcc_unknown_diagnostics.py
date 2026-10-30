from __future__ import annotations

from typing import Any


def diagnose_unknown_receipt(
    *,
    original_operation_id: str,
    original_outcome: str,
    original_error: str | None,
    effect_journal: list[dict[str, Any]],
    host_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only, fail-closed diagnostic. Never changes or retries the source."""
    stages = [str(event.get("stage") or "") for event in effect_journal
              if isinstance(event, dict)]
    known = (
        "CLAIM_RESERVED", "DISPATCH_INTENT", "EFFECT_RESULT_OBSERVED",
        "RECEIPT_PERSIST_INTENT", "RECEIPT_PERSISTED",
    )
    completed = [stage for stage in known if stage in stages]
    last = completed[-1] if completed else "NONE"
    host = host_receipt if isinstance(host_receipt, dict) else {}
    host_state = str(host.get("state") or host.get("resultState") or "")
    error = str(original_error or "").strip()[:128]
    reason = error or "RCC_EFFECT_NOT_PROVEN"
    if original_outcome != "UNKNOWN":
        return {
            "status": "NOT_ELIGIBLE", "original_operation_id": original_operation_id,
            "last_success_stage": last, "failure_stage": "ORIGINAL_OUTCOME_CHECK",
            "reason": "ORIGINAL_NOT_UNKNOWN", "remaining_proof": [],
            "original_outcome_preserved": True, "no_resend": True,
        }
    proof = ["EXACT_ORIGINAL_REQUEST_DIGEST", "EXACT_TARGET_SESSION_TAB_UUID",
             "SINGLE_USER_TURN_SHA256", "SUBMISSION_ACK", "EXACT_RESPONSE_RECEIPT"]
    if not host:
        failure = "HOST_RECEIPT_OBSERVATION"
    elif host_state not in {"RESULT_PERSISTED", "SUBMITTED", "SUBMITTED_CONFIRMED"}:
        failure = "HOST_RECEIPT_STATE"
    else:
        failure = "EXACT_PROOF_VALIDATION"
    return {
        "status": "UNRESOLVED", "original_operation_id": original_operation_id,
        "last_success_stage": last, "failure_stage": failure, "reason": reason,
        "host_state": host_state or "UNAVAILABLE", "remaining_proof": proof,
        "original_outcome_preserved": True, "no_resend": True,
    }
