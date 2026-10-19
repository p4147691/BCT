"""One-shot, opt-in Instant ACK probes for an observed ChatGPT bottleneck.

This module deliberately does not try to infer model settings or send a second
message to a generating conversation.  A configured, separate probe
conversation is required.  The only automated text is the fixed diagnostic
prompt below; all effects flow through the normal RCC receipt path.
"""
from __future__ import annotations

import hashlib
import re
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bct.core.models import BCTError, Principal


ACK_PROMPT = "0단계 Instant ACK 대조 요청입니다. 도구를 사용하지 말고 정확히 ACK만 답해줘."
_CONVERSATION_KEY = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
_INSTANCE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class EndpointSelector:
    instance_id: str
    conversation_key: str


@dataclass(frozen=True)
class BottleneckAckPolicy:
    enabled: bool
    threshold_seconds: float = 30.0
    cooldown_seconds: float = 300.0
    watch: EndpointSelector | None = None
    probe: EndpointSelector | None = None


def _selector(section: dict[str, Any], prefix: str) -> EndpointSelector:
    instance_id = str(section.get(prefix + "_instance_id") or "").strip()
    key = str(section.get(prefix + "_conversation_key") or "").strip().lower()
    if not _INSTANCE_ID.fullmatch(instance_id):
        raise ValueError("BOTTLENECK_ACK_" + prefix.upper() + "_INSTANCE_ID_INVALID")
    if not _CONVERSATION_KEY.fullmatch(key):
        raise ValueError("BOTTLENECK_ACK_" + prefix.upper() + "_CONVERSATION_KEY_INVALID")
    return EndpointSelector(instance_id, key)


def load_bottleneck_ack_policy(path: str | Path) -> BottleneckAckPolicy:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("bottleneck_ack", {})
    if not isinstance(raw, dict):
        raise ValueError("BOTTLENECK_ACK_SECTION_INVALID")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("BOTTLENECK_ACK_ENABLED_INVALID")
    if not enabled:
        return BottleneckAckPolicy(enabled=False)
    allowed = {
        "enabled", "threshold_seconds", "cooldown_seconds",
        "watch_instance_id", "watch_conversation_key",
        "probe_instance_id", "probe_conversation_key",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError("BOTTLENECK_ACK_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    try:
        threshold = float(raw.get("threshold_seconds", 30.0))
        cooldown = float(raw.get("cooldown_seconds", 300.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("BOTTLENECK_ACK_DURATION_INVALID") from exc
    if not 5.0 <= threshold <= 3600.0 or not 0.0 <= cooldown <= 86400.0:
        raise ValueError("BOTTLENECK_ACK_DURATION_INVALID")
    watch = _selector(raw, "watch")
    probe = _selector(raw, "probe")
    if watch == probe:
        raise ValueError("BOTTLENECK_ACK_PROBE_MUST_BE_SEPARATE")
    return BottleneckAckPolicy(True, threshold, cooldown, watch, probe)


def run_bottleneck_ack_probe(bct: Any, *, principal: Principal, payload: dict[str, Any]) -> dict[str, Any]:
    """Submit the fixed ACK text once to a freshly observed exact target."""
    allowed = {"instance_id", "session_id", "tab_id", "window_id", "conversation_key", "operation_id"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("BOTTLENECK_ACK_FIELD_NOT_ALLOWED:" + ",".join(sorted(unknown)))
    operation_id = str(payload.get("operation_id") or "").strip()
    if not re.fullmatch(r"bottleneck-ack-[a-f0-9]{24,64}", operation_id):
        raise ValueError("BOTTLENECK_ACK_OPERATION_ID_INVALID")
    return bct.operations.run(
        principal=principal,
        work_id="bct-monitor-extension-control",
        operation_id=operation_id,
        capability="relay_browser",
        arguments={
            "command": "send-to-tab",
            "instance_id": str(payload.get("instance_id") or "").strip(),
            "session_id": str(payload.get("session_id") or "").strip(),
            "tab_id": payload.get("tab_id"),
            "window_id": payload.get("window_id"),
            "conversation_key": str(payload.get("conversation_key") or "").strip().lower(),
            "text": ACK_PROMPT,
            "timeout_s": 30.0,
        },
    ).as_dict()


class BottleneckAckController:
    """Consumes passive RCC snapshots and performs at most one send per onset."""
    def __init__(self, policy: BottleneckAckPolicy, *, bct: Any, principal: Principal):
        self.policy = policy
        self.bct = bct
        self.principal = principal
        self._seen: set[str] = set()
        self._last_dispatch_ms = 0
        self._active: dict[str, Any] | None = None
        self._status: dict[str, Any] = {"state": "DISABLED" if not policy.enabled else "WAITING"}

    def status(self) -> dict[str, Any]:
        return dict(self._status)

    @staticmethod
    def _endpoint(instances: list[dict[str, Any]], selector: EndpointSelector) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for instance in instances:
            if instance.get("instance_id") != selector.instance_id or instance.get("state") != "OPEN":
                continue
            for tab in instance.get("tabs", []):
                if isinstance(tab, dict) and str(tab.get("conversation_key") or "").lower() == selector.conversation_key:
                    return instance, tab
        return None

    @staticmethod
    def _positive(value: Any) -> int | None:
        return int(value) if isinstance(value, int) and value > 0 else None

    def _complete_measurement(self, probe: dict[str, Any], now_ms: int) -> None:
        if self._active is None:
            return
        telemetry = probe.get("telemetry") if isinstance(probe.get("telemetry"), dict) else {}
        started = self._positive(telemetry.get("generation_started_at"))
        finished = self._positive(telemetry.get("generation_finished_at"))
        submitted = int(self._active["submitted_at_ms"])
        if started is not None and started >= submitted - 1000:
            self._active["ack_started_at_ms"] = started
        started = self._active.get("ack_started_at_ms")
        if started and finished is not None and finished >= started:
            self._status = {
                "state": "MEASURED", "operation_id": self._active["operation_id"],
                "source_duration_ms": self._active["source_duration_ms"],
                "ack_start_latency_ms": max(0, started - submitted),
                "ack_completion_latency_ms": max(0, finished - submitted),
                "ack_generation_ms": max(0, finished - started),
                "measured_at_ms": now_ms,
            }
            self._active = None

    def observe(self, instances: list[dict[str, Any]], *, now_ms: int | None = None) -> dict[str, Any]:
        if not self.policy.enabled or self.policy.watch is None or self.policy.probe is None:
            return self.status()
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        source = self._endpoint(instances, self.policy.watch)
        probe = self._endpoint(instances, self.policy.probe)
        if probe is not None:
            self._complete_measurement(probe[1], now_ms)
        if source is None:
            self._status = {"state": "WATCH_UNAVAILABLE"}
            return self.status()
        _, source_tab = source
        telemetry = source_tab.get("telemetry") if isinstance(source_tab.get("telemetry"), dict) else {}
        started = self._positive(telemetry.get("generation_started_at"))
        finished = self._positive(telemetry.get("generation_finished_at"))
        generating = bool(source_tab.get("generating"))
        if started is None:
            if self._active is None:
                self._status = {"state": "WAITING"}
            return self.status()
        if generating:
            duration = max(0, now_ms - started)
        elif finished is not None and finished >= started and now_ms - finished <= 10_000:
            # A short polling gap must not erase evidence that the configured
            # threshold was crossed.  Restrict this to a freshly completed
            # generation so a service restart cannot replay old telemetry.
            duration = finished - started
        else:
            if self._active is None:
                self._status = {"state": "WAITING"}
            return self.status()
        if duration < round(self.policy.threshold_seconds * 1000):
            self._status = {"state": "WATCHING", "generation_duration_ms": duration}
            return self.status()
        onset = f"{self.policy.watch.instance_id}:{self.policy.watch.conversation_key}:{started}"
        if onset in self._seen:
            return self.status()
        if self._last_dispatch_ms and now_ms - self._last_dispatch_ms < round(self.policy.cooldown_seconds * 1000):
            self._status = {"state": "COOLDOWN", "generation_duration_ms": duration}
            return self.status()
        if probe is None:
            self._status = {"state": "PROBE_UNAVAILABLE", "generation_duration_ms": duration}
            return self.status()
        probe_instance, probe_tab = probe
        if bool(probe_tab.get("generating")):
            self._status = {"state": "PROBE_BUSY", "generation_duration_ms": duration}
            return self.status()
        session_id = str(probe_instance.get("session_id") or "")
        tab_id, window_id = self._positive(probe_tab.get("tab_id")), self._positive(probe_tab.get("window_id"))
        if not re.fullmatch(r"[a-f0-9]{32}", session_id) or tab_id is None or window_id is None:
            self._status = {"state": "PROBE_IDENTITY_UNAVAILABLE", "generation_duration_ms": duration}
            return self.status()
        operation_id = "bottleneck-ack-" + hashlib.sha256(onset.encode("utf-8")).hexdigest()[:40]
        self._seen.add(onset)  # UNKNOWN is never blindly retried.
        self._last_dispatch_ms = now_ms
        try:
            result = run_bottleneck_ack_probe(self.bct, principal=self.principal, payload={
                "instance_id": probe_instance["instance_id"], "session_id": session_id,
                "tab_id": tab_id, "window_id": window_id,
                "conversation_key": self.policy.probe.conversation_key, "operation_id": operation_id,
            })
        except (BCTError, ValueError, KeyError) as exc:
            self._status = {"state": "UNKNOWN", "operation_id": operation_id, "error": type(exc).__name__}
            return self.status()
        outcome = str(result.get("outcome") or "UNKNOWN")
        if outcome != "APPLIED":
            self._status = {"state": "UNKNOWN", "operation_id": operation_id, "outcome": outcome}
            return self.status()
        self._active = {"operation_id": operation_id, "submitted_at_ms": now_ms, "source_duration_ms": duration}
        self._status = {"state": "SUBMITTED", "operation_id": operation_id, "source_duration_ms": duration}
        return self.status()
