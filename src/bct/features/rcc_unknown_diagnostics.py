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


def build_separate_recovery_receipt(
    *, recovery_operation_id: str, original: dict[str, Any],
    proof: dict[str, Any], expected: dict[str, Any],
) -> dict[str, Any]:
    """Independent proof object; no source Operation/Claim mutation or effect."""
    from hashlib import sha256
    import re
    requirements = {
        "ORIGINAL_UNKNOWN": original.get("outcome") == "UNKNOWN"
            and original.get("state") == "FINISHED",
        "EXACT_ORIGINAL_REQUEST_DIGEST": (
            isinstance(original.get("request_digest"), str)
            and re.fullmatch(r"[a-f0-9]{64}", original["request_digest"]) is not None
            and original["request_digest"] == expected.get("request_digest")
            and proof.get("request_digest") == expected.get("request_digest")),
        "EXACT_TARGET_SESSION_TAB_UUID": all(
            expected.get(k) not in (None, "")
            and proof.get(k) == expected.get(k)
            for k in ("instance_id", "session_id", "tab_id",
                      "window_id", "conversation_key")),
        "SINGLE_USER_TURN_SHA256": (
            proof.get("user_turn_count") == 1
            and isinstance(expected.get("text_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", expected["text_sha256"]) is not None
            and proof.get("user_turn_sha256") == expected["text_sha256"]),
        "SUBMISSION_ACK": proof.get("submitted") is True
            and proof.get("ack_operation_id") == original.get("operation_id"),
        "EXACT_RESPONSE_RECEIPT": (
            proof.get("result_state") == "RESULT_PERSISTED"
            and isinstance(proof.get("response_text"), str)
            and bool(proof["response_text"].strip())
            and proof.get("response_sha256") ==
                sha256(proof["response_text"].encode("utf-8")).hexdigest()
            and proof.get("response_operation_id") == original.get("operation_id")),
    }
    missing = [k for k, valid in requirements.items() if not valid]
    return {
        "schema": "rcc-unknown-recovery-v1",
        "recovery_operation_id": recovery_operation_id,
        "original_operation_id": original.get("operation_id"),
        "status": "VERIFIED" if not missing else "INSUFFICIENT_EVIDENCE",
        "missing_proof": missing,
        "original_outcome_preserved": "UNKNOWN",
        "original_claim_unchanged": True,
        "no_resend": True,
        "response_sha256": proof.get("response_sha256") if not missing else None,
    }
