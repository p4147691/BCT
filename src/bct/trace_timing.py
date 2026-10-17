"""Request-local, non-persistent MCP timing metadata only."""
from __future__ import annotations
import json
import logging
from contextvars import ContextVar

TRACE_ID: ContextVar[str | None] = ContextVar("bct_mcp_trace_id", default=None)
_LOG = logging.getLogger("bct.mcp.trace")

def trace_stage(stage: str, *, tool_kind: str | None = None, **durations_ms: float) -> None:
    trace_id = TRACE_ID.get()
    if trace_id is None:
        return
    payload = {"trace_id": trace_id, "stage": stage}
    if tool_kind is not None:
        payload["tool_kind"] = tool_kind
    payload.update({key: round(value, 3) for key, value in durations_ms.items()})
    _LOG.info("MCP_TIMING %s", json.dumps(payload, separators=(",", ":")))
