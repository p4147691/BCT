"""Fail-closed Native Messaging adapter; BCT Core owns authorization and receipts."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import struct
import sys
from urllib.parse import urlparse

MAX_FRAME = 65536
APPROVED_ORIGIN = os.environ.get("BCT_BRIDGE_EXTENSION_ORIGIN", "")
MCP_URL = os.environ.get("BCT_BRIDGE_MCP_URL", "")
def require_approved_mcp_url():
    # Required only for the legacy BCT-read operation. The independent
    # node mailbox never opens an HTTP/MCP connection.
    url = urlparse(MCP_URL)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
            or url.path != "/mcp" or url.port == 18790
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("HOST_MCP_URL_DENIED")
    return MCP_URL
TOKEN_PATH = Path(os.environ.get("BCT_BRIDGE_TOKEN_PATH", ""))
WORK_ID = os.environ.get("BCT_BRIDGE_WORK_ID", "")


def read_frame(inp, allow_launcher_bom=False):
    header = inp.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("FRAME_HEADER_TRUNCATED")
    if allow_launcher_bom and header[:3] == bytes((239, 187, 191)):
        header = header[3:] + inp.read(3)
        if len(header) != 4:
            raise ValueError("FRAME_HEADER_TRUNCATED")
    length = struct.unpack("<I", header)[0]
    if length > MAX_FRAME:
        raise ValueError("FRAME_TOO_LARGE")
    data = inp.read(length)
    if len(data) != length:
        raise ValueError("FRAME_TRUNCATED")
    return json.loads(data.decode("utf-8"))


def write_frame(out, data):
    encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_FRAME:
        raise ValueError("REPLY_TOO_LARGE")
    out.write(struct.pack("<I", len(encoded)) + encoded)
    out.flush()


def validate(message):
    expected = {"schema_version", "type", "request_id", "operation_id", "capability", "arguments"}
    if not isinstance(message, dict) or set(message) != expected:
        raise ValueError("REQUEST_SCHEMA_DENIED")
    if message["schema_version"] != 1 or message["type"] not in ("bridge_read", "receipt_lookup") or message["capability"] != "read":
        raise ValueError("CAPABILITY_DENIED")
    request_id = message["request_id"]
    if not isinstance(request_id, str) or len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id):
        raise ValueError("REQUEST_ID_INVALID")
    if message["operation_id"] != request_id:
        raise ValueError("ID_MISMATCH")
    arguments = message["arguments"]
    if message["type"] == "bridge_read":
        if not isinstance(arguments, dict) or set(arguments) != {"path"} or not isinstance(arguments["path"], str) or not 0 < len(arguments["path"]) <= 1024:
            raise ValueError("ARGUMENTS_DENIED")
    elif arguments != {}:
        raise ValueError("RECEIPT_ARGUMENTS_DENIED")
    return request_id, arguments


async def dispatch(message):
    request_id, arguments = validate(message)
    require_approved_mcp_url()
    if not WORK_ID or not TOKEN_PATH.is_file():
        raise ValueError("HOST_AUTH_NOT_CONFIGURED")
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("HOST_AUTH_NOT_CONFIGURED")
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=12) as client:
        async with streamable_http_client(MCP_URL, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if message["type"] == "receipt_lookup":
                    result = await session.call_tool("bct_operation_get", {"work_id": WORK_ID, "operation_id": request_id})
                else:
                    result = await session.call_tool("bct_read", {"work_id": WORK_ID, "operation_id": request_id, "arguments": arguments})
                return {"ok": not result.isError, "request_id": request_id, "result": result.structuredContent}


def main(argv=None, inp=None, out=None):
    argv = sys.argv[1:] if argv is None else argv
    inp = sys.stdin.buffer if inp is None else inp
    out = sys.stdout.buffer if out is None else out
    origin = argv[0] if argv else ""
    if not APPROVED_ORIGIN or origin != APPROVED_ORIGIN:
        return 4
    try:
        while True:
            message = read_frame(inp)
            if message is None:
                return 0
            try:
                response = asyncio.run(dispatch(message))
            except (ValueError, TypeError) as exc:
                response = {"ok": False, "request_id": message.get("request_id") if isinstance(message, dict) else None, "outcome": "INPUT_DENIED", "error": str(exc)}
            except OSError:
                response = {"ok": False, "request_id": message.get("request_id") if isinstance(message, dict) else None, "outcome": "UNKNOWN", "error": "DISPATCH_IO_AMBIGUOUS_NO_RETRY"}
            except Exception:
                response = {"ok": False, "request_id": message.get("request_id") if isinstance(message, dict) else None, "outcome": "UNKNOWN", "error": "DISPATCH_RESULT_AMBIGUOUS_NO_RETRY"}
            write_frame(out, response)
    except Exception:
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
