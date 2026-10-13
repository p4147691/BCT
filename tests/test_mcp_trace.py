from __future__ import annotations

import asyncio
import json
import logging
import unittest
from unittest.mock import AsyncMock

from bct.mcp_server import LocalBearerMiddleware, _MCP_TRACE_ID, _trace_stage


class TraceTests(unittest.TestCase):
    def test_trace_has_no_headers_body_or_token(self):
        events = []
        class Capture(logging.Handler):
            def emit(self, record):
                events.append(record.getMessage())
        logger = logging.getLogger("bct.mcp.trace")
        previous = logger.level
        capture = Capture()
        logger.addHandler(capture)
        logger.setLevel(logging.INFO)
        try:
            async def app(scope, receive, send):
                _trace_stage("handler_done", handler_ms=0.5)
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"secret prompt"})
            sent = []
            async def receive():
                return {"type": "http.request", "body": b"secret prompt"}
            async def send(message):
                sent.append(message)
            scope = {"type": "http", "path": "/mcp", "headers": [(b"authorization", b"Bearer secret-token")]}
            asyncio.run(LocalBearerMiddleware(app, "secret-token")(scope, receive, send))
            self.assertEqual(2, len(sent))
            self.assertEqual(2, len(events))
            payloads = [json.loads(event.split("MCP_TIMING ", 1)[1]) for event in events]
            self.assertEqual({"handler_done", "response_complete"}, {p["stage"] for p in payloads})
            self.assertEqual(payloads[0]["trace_id"], payloads[1]["trace_id"])
            self.assertNotIn("secret", " ".join(events))
            self.assertNotIn("prompt", " ".join(events))
            self.assertIsNone(_MCP_TRACE_ID.get())
        finally:
            logger.removeHandler(capture)
            logger.setLevel(previous)

    def test_rejected_auth_never_enters_traced_app(self):
        invoked = []
        async def app(scope, receive, send):
            invoked.append(True)
        async def receive():
            return {"type": "http.request", "body": b""}
        sent = []
        async def send(message):
            sent.append(message)
        asyncio.run(LocalBearerMiddleware(app, "valid")(
            {"type": "http", "path": "/mcp", "headers": [(b"authorization", b"Bearer wrong")]}, receive, send))
        self.assertEqual([], invoked)
        self.assertEqual(401, sent[0]["status"])

if __name__ == "__main__":
    unittest.main()
