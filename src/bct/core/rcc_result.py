from __future__ import annotations

import hashlib
import json
from typing import Any


def _text(value: Any, *, field: str, limit: int | None = None) -> str:
    if value is None:
        result = ""
    elif isinstance(value, str):
        result = value
    else:
        raise ValueError(f"RCC_RESULT_{field.upper()}_TYPE_INVALID")
    return result if limit is None else result[:limit]


def bounded_rcc_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Mirror RCC ``boundedRelayResultPayload`` including insertion order."""
    if not isinstance(result, dict):
        raise ValueError("RCC_RESULT_PAYLOAD_INVALID")
    reply = _text(result.get("reply"), field="reply")
    if len(reply) > 1_048_576:
        raise ValueError("RCC_RESULT_TOO_LARGE")
    raw_failure = result.get("failureEvidence")
    if raw_failure is not None and not isinstance(raw_failure, dict):
        raise ValueError("RCC_RESULT_FAILURE_EVIDENCE_INVALID")
    failure = None if raw_failure is None else {
        "phase": _text(raw_failure.get("phase"), field="phase", limit=80),
        "networkError": _text(
            raw_failure.get("networkError"), field="network_error", limit=300,
        ),
        "domError": _text(
            raw_failure.get("domError"), field="dom_error", limit=300,
        ),
        "networkSignal": _text(
            raw_failure.get("networkSignal"), field="network_signal", limit=40,
        ),
    }
    return {
        "failureEvidence": failure,
        "ok": result.get("ok") is True,
        "reply": reply,
        "error": _text(result.get("error"), field="error", limit=1000),
        "ambiguous": result.get("ambiguous") is True,
    }


def rcc_result_payload_json(result: dict[str, Any]) -> str:
    return json.dumps(
        bounded_rcc_result_payload(result),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def rcc_result_hash(result: dict[str, Any]) -> str:
    return hashlib.sha256(rcc_result_payload_json(result).encode("utf-8")).hexdigest()
