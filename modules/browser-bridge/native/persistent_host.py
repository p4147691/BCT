"""Persistent Native Messaging host. BCT Core remains the execution authority."""
import asyncio
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from native_host import APPROVED_ORIGIN, MCP_URL, TOKEN_PATH, WORK_ID, read_frame, validate, write_frame

LAST_REQUEST_ID = None


def error_reply(request_id, error, outcome):
    return {"ok": False, "request_id": request_id, "outcome": outcome, "error": error}


def core_reply(result, request_id, operation_type="bridge_read"):
    """Accept only a complete, exact Core operation receipt; never infer success."""
    content = getattr(result, "structuredContent", None)
    if getattr(result, "isError", True):
        return {"ok": False, "request_id": request_id, "outcome": "RECEIPT_ERROR", "result": content}
    if not isinstance(content, dict) or not content:
        return error_reply(request_id, "CORE_RECEIPT_SCHEMA_INVALID", "RECEIPT_ERROR")
    if (content.get("operation_id") != request_id or
            content.get("state") not in ("RECORDED", "RUNNING", "FINISHED") or
            not isinstance(content.get("evidence"), dict) or
            not isinstance(content.get("duplicate"), bool)):
        return error_reply(request_id, "CORE_RECEIPT_SCHEMA_INVALID", "RECEIPT_ERROR")
    outcome = content.get("outcome")
    if outcome not in ("APPLIED", "NOT_APPLIED", "FAILED", "UNKNOWN", None):
        return error_reply(request_id, "CORE_RECEIPT_OUTCOME_INVALID", "RECEIPT_ERROR")
    state = content["state"]
    if state != "FINISHED":
        if outcome is not None:
            return error_reply(request_id, "CORE_RECEIPT_STATE_CONFLICT", "RECEIPT_ERROR")
        return {"ok": False, "request_id": request_id, "outcome": "PENDING", "result": content}
    if outcome is None:
        return error_reply(request_id, "CORE_RECEIPT_OUTCOME_MISSING", "RECEIPT_ERROR")
    if outcome != "APPLIED":
        return {"ok": False, "request_id": request_id, "outcome": outcome, "result": content}
    if (operation_type == "bridge_read" and
            (not isinstance(content.get("output"), dict) or
             not isinstance(content["output"].get("text"), str))):
        return error_reply(request_id, "CORE_READ_OUTPUT_INVALID", "RECEIPT_ERROR")
    if operation_type not in ("bridge_read", "receipt_lookup", "comfy_canvas_read"):
        return error_reply(request_id, "CORE_REQUEST_TYPE_INVALID", "RECEIPT_ERROR")
    if operation_type == "comfy_canvas_read":
        from bct.features.comfy_graph_snapshot import validate_snapshot
        if not isinstance(content.get("output"), dict):
            return error_reply(request_id, "COMFY_RECEIPT_OUTPUT_INVALID", "RECEIPT_ERROR")
        try:
            validate_snapshot(content["output"]["graph"])
        except (KeyError, TypeError, ValueError):
            return error_reply(request_id, "COMFY_RECEIPT_GRAPH_INVALID", "RECEIPT_ERROR")
    return {"ok": True, "request_id": request_id, "result": content}


async def serve(inp, out):
    global LAST_REQUEST_ID
    first = await asyncio.to_thread(read_frame, inp, True)
    if first is None:
        return 0
    LAST_REQUEST_ID = first.get("request_id") if isinstance(first, dict) else None
    if not WORK_ID or not TOKEN_PATH.is_file():
        write_frame(out, error_reply(LAST_REQUEST_ID, "HOST_AUTH_NOT_CONFIGURED", "AUTH_DENIED"))
        return 4
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not token:
        write_frame(out, error_reply(LAST_REQUEST_ID, "HOST_AUTH_NOT_CONFIGURED", "AUTH_DENIED"))
        return 4
    pending_first = first
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=12) as client:
        async with streamable_http_client(MCP_URL, http_client=client) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                while True:
                    try:
                        message = pending_first if pending_first is not None else await asyncio.to_thread(read_frame, inp)
                        pending_first = None
                        if isinstance(message, dict):
                            LAST_REQUEST_ID = message.get("request_id")
                    except Exception:
                        return 5
                    if message is None:
                        return 0
                    try:
                        request_id, arguments = validate(message)
                        if TOKEN_PATH.read_text(encoding="utf-8").strip() != token:
                            write_frame(out, error_reply(request_id, "HOST_TOKEN_CHANGED_RECONNECT_REQUIRED", "AUTH_DENIED"))
                            return 0
                        try:
                            if message["type"] == "receipt_lookup":
                                result = await session.call_tool("bct_operation_get", {"work_id": WORK_ID, "operation_id": request_id})
                            elif message["type"] == "comfy_canvas_read":
                                result = await session.call_tool("bct_comfy_canvas_read", {"work_id": WORK_ID, "operation_id": request_id, "arguments": arguments})
                            else:
                                result = await session.call_tool("bct_read", {"work_id": WORK_ID, "operation_id": request_id, "arguments": arguments})
                        except Exception:
                            # The request may have been committed before transport failed.
                            reply = error_reply(request_id, "DISPATCH_RESULT_AMBIGUOUS_NO_RETRY", "UNKNOWN")
                        else:
                            reply = core_reply(result, request_id, message["type"])
                    except (ValueError, TypeError) as exc:
                        reply = error_reply(message.get("request_id") if isinstance(message, dict) else None, str(exc), "INPUT_DENIED")
                    except OSError:
                        reply = error_reply(message.get("request_id") if isinstance(message, dict) else None, "LOCAL_AUTH_IO_ERROR", "AUTH_DENIED")
                    write_frame(out, reply)


def main():
    origin = sys.argv[1] if len(sys.argv) > 1 else ""
    if not APPROVED_ORIGIN or origin != APPROVED_ORIGIN:
        return 4
    try:
        return asyncio.run(serve(sys.stdin.buffer, sys.stdout.buffer))
    except Exception:
        try:
            write_frame(sys.stdout.buffer, error_reply(LAST_REQUEST_ID, "HOST_AUTH_OR_CONNECT_FAILED", "CONNECTION_FAILED"))
            return 0
        except Exception:
            return 5


if __name__ == "__main__":
    raise SystemExit(main())
