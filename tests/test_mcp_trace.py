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

    def test_stage_metadata_is_request_local_and_redacted(self):
        import concurrent.futures
        from contextvars import copy_context
        from bct.trace_timing import TRACE_ID, trace_stage

        events = []
        class Capture(logging.Handler):
            def emit(self, record):
                events.append(record.getMessage())

        logger = logging.getLogger("bct.mcp.trace")
        capture = Capture()
        previous = logger.level
        logger.addHandler(capture)
        logger.setLevel(logging.INFO)
        try:
            token = TRACE_ID.set("synthetic-trace-id")
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    copy_context().run(
                        lambda: pool.submit(copy_context().run, trace_stage,
                                            "authorization_prepare",
                                            tool_kind="read", elapsed_ms=0.125).result()
                    )
                trace_stage("claim_reservation", tool_kind="read", elapsed_ms=0.25)
            finally:
                TRACE_ID.reset(token)
            self.assertEqual(2, len(events))
            payloads = [json.loads(x.split("MCP_TIMING ", 1)[1]) for x in events]
            self.assertEqual(["authorization_prepare", "claim_reservation"],
                             [x["stage"] for x in payloads])
            self.assertTrue(all(x["trace_id"] == "synthetic-trace-id" for x in payloads))
            self.assertTrue(all(set(x) == {"trace_id", "stage", "tool_kind", "elapsed_ms"} for x in payloads))
            self.assertIsNone(TRACE_ID.get())
        finally:
            logger.removeHandler(capture)
            logger.setLevel(previous)

    def test_mcp_auth_is_device_agnostic_but_not_token_optional(self):
        """Synthetic desktop/phone metadata never overrides the exact MCP bearer."""
        entered = []

        async def app(scope, receive, send):
            entered.append(scope["client"][0])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def one_case(*, origin_ip, user_agent, auth_header):
            sent = []

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http", "path": "/mcp",
                "client": (origin_ip, 41234),
                "headers": [
                    (b"user-agent", user_agent.encode("ascii")),
                    (b"x-forwarded-for", origin_ip.encode("ascii")),
                    auth_header,
                ],
            }
            await LocalBearerMiddleware(app, "fixture-only")(
                scope, receive, send,
            )
            return sent[0]["status"]

        async def exercise():
            self.assertEqual(200, await one_case(
                origin_ip="203.0.113.5", user_agent="ChatGPT-Mobile",
                auth_header=(b"x-bct-token", b"fixture-only"),
            ))
            self.assertEqual(200, await one_case(
                origin_ip="198.51.100.7", user_agent="ChatGPT-Desktop",
                auth_header=(b"authorization", b"Bearer fixture-only"),
            ))
            self.assertEqual(401, await one_case(
                origin_ip="203.0.113.5", user_agent="ChatGPT-Mobile",
                auth_header=(b"x-bct-token", b"wrong"),
            ))

        asyncio.run(exercise())
        self.assertEqual(["203.0.113.5", "198.51.100.7"], entered)

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
