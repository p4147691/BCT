"""Request-local, non-persistent MCP timing metadata only."""
from __future__ import annotations
import json
import logging
from contextvars import ContextVar
from collections import deque
from threading import Lock

TRACE_ID: ContextVar[str | None] = ContextVar("bct_mcp_trace_id", default=None)
_LOG = logging.getLogger("bct.mcp.trace")

# Bounded request metadata only; no operation body, credentials, or disk writes.
_RECENT: deque[dict[str, object]] = deque(maxlen=128)
_RECENT_LOCK = Lock()


def recent_stages(limit: int = 32) -> list[dict[str, object]]:
    """Return immutable-to-caller copies of recent, non-sensitive timing stages."""
    bounded = max(0, min(int(limit), 128))
    if bounded == 0:
        return []
    with _RECENT_LOCK:
        return [dict(item) for item in list(_RECENT)[-bounded:]]


def trace_stage(stage: str, *, tool_kind: str | None = None, **durations_ms: float) -> None:
    trace_id = TRACE_ID.get()
    if trace_id is None:
        return
    payload = {"trace_id": trace_id, "stage": stage}
    if tool_kind is not None:
        payload["tool_kind"] = tool_kind
    payload.update({key: round(value, 3) for key, value in durations_ms.items()})
    with _RECENT_LOCK:
        _RECENT.append(dict(payload))
    _LOG.info("MCP_TIMING %s", json.dumps(payload, separators=(",", ":")))
