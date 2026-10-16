from __future__ import annotations

import hashlib
import json
from typing import Any


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _utf16_slice(value: str, limit: int) -> str:
    encoded = value.encode("utf-16-le", errors="surrogatepass")[: limit * 2]
    return encoded.decode("utf-16-le", errors="surrogatepass")


def _text(value: Any, *, field: str, limit: int | None = None) -> str:
    if value is None:
        result = ""
    elif isinstance(value, str):
        result = value
    else:
        raise ValueError(f"RCC_RESULT_{field.upper()}_TYPE_INVALID")
    return result if limit is None else _utf16_slice(result, limit)


def bounded_rcc_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Mirror RCC ``boundedRelayResultPayload`` including insertion order."""
    if not isinstance(result, dict):
        raise ValueError("RCC_RESULT_PAYLOAD_INVALID")
    reply = _text(result.get("reply"), field="reply")
    if _utf16_length(reply) > 1_048_576:
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
    encoded = json.dumps(
        bounded_rcc_result_payload(result),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Well-formed JSON.stringify escapes any lone surrogate produced by a
    # UTF-16 code-unit slice. Python otherwise leaves it as an unencodable
    # surrogate when ensure_ascii is disabled.
    return "".join(
        f"\\u{ord(char):04x}" if 0xD800 <= ord(char) <= 0xDFFF else char
        for char in encoded
    )


def rcc_result_hash(result: dict[str, Any]) -> str:
    return hashlib.sha256(rcc_result_payload_json(result).encode("utf-8")).hexdigest()
