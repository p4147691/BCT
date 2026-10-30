"""Bounded, passive timings for the canonical RCC send-message route.

No extra browser probe, retry, message or content logging is authorized here.
Host timestamps are interpreted only as elapsed durations within one host clock.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


_MAX_OBSERVATION_MS = 360_000.0


def _ms(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > _MAX_OBSERVATION_MS:
        return None
    return round(number, 3)


def _difference(stage: Mapping[str, object], begin: str, end: str) -> float | None:
    first, last = stage.get(begin), stage.get(end)
    if isinstance(first, bool) or isinstance(last, bool):
        return None
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
        return None
    return _ms(float(last) - float(first))


def send_latency_evidence(
    *,
    command: str,
    preflight_state_ms: object = None,
    host_request_ms: object = None,
    stage_timing: object = None,
    readback_ms: object = None,
    readback_attempts: object = None,
) -> dict[str, object]:
    """Return only directly observed, bounded timings; never infer missing ACKs.

    For send-to-tab the host request returns the submission ACK, so its
    duration is the ACK wait. A created-tab host request includes reply
    collection, hence its duration is NOT mislabelled as ACK latency.
    """
    timings: dict[str, float] = {}
    for name, value in (
        ("preflight_state", preflight_state_ms),
        ("host_request", host_request_ms),
        ("readback", readback_ms),
    ):
        observed = _ms(value)
        if observed is not None:
            timings[name] = observed
    if command == "send-to-tab" and "host_request" in timings:
        timings["submit_ack"] = timings["host_request"]
    if command == "send-to-created-tab" and isinstance(stage_timing, Mapping):
        for name, first, last in (
            ("submit_to_conversation", "submitAttemptedAt", "conversationCapturedAt"),
            ("conversation_to_response", "conversationCapturedAt", "completedAt"),
        ):
            elapsed = _difference(stage_timing, first, last)
            if elapsed is not None:
                timings[name] = elapsed
    evidence: dict[str, object] = {"timing_ms": timings}
    if isinstance(readback_attempts, int) and not isinstance(readback_attempts, bool) and 0 < readback_attempts <= 10000:
        evidence["readback_attempts"] = readback_attempts
    return evidence
