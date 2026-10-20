from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace

from bct.mcp_server import build_mcp


class DummyResult:
    def as_dict(self):
        return {"state": "FINISHED", "outcome": "APPLIED"}


class DummyOperations:
    capabilities = ("read", "write", "desktop_session_status", "desktop_capture")

    def __init__(self):
        self.called = []

    def run(self, **kwargs):
        self.called.append(kwargs)
        return DummyResult()


class LightweightCatalogueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.operations = DummyOperations()
        self.bct = SimpleNamespace(operations=self.operations)
        self.full = build_mcp(self.bct)
        self.compact = build_mcp(self.bct, compact_catalogue=True)

    async def test_full_default_unchanged(self):
        names = {t.name for t in await self.full.list_tools()}
        self.assertIn("bct_read", names)
        self.assertNotIn("bct_dispatch", names)
        self.assertIn("bct_desktop_capture", names)

    async def test_compact_lists_only_dispatch_and_shared_tools(self):
        names = {t.name for t in await self.compact.list_tools()}
        self.assertEqual(len(names), 8)
        self.assertIn("bct_dispatch", names)
        self.assertNotIn("bct_read", names)
        self.assertIn("bct_desktop_capture", names)

    async def test_hybrid_exposes_two_direct_tools_with_existing_contract(self):
        hybrid = build_mcp(self.bct, hybrid_catalogue=True)
        names = {tool.name for tool in await hybrid.list_tools()}
        self.assertEqual(9, len(names))
        self.assertIn("bct_dispatch", names)
        self.assertIn("bct_read", names)
        self.assertNotIn("bct_execute", names)  # not registered in this fixture
        for capability in ("read", "write"):
            name = "bct_read" if capability == "read" else "bct_dispatch"
            args = {"work_id": "W", "operation_id": "O-" + capability, "arguments": {"path": "x"}}
            if name == "bct_dispatch":
                args["capability"] = capability
            await hybrid.call_tool(name, args)
        self.assertEqual([x["capability"] for x in self.operations.called], ["read", "write"])

    async def test_dispatch_uses_existing_operations_authorization(self):
        await self.compact.call_tool("bct_dispatch", {
            "capability": "read", "work_id": "W", "operation_id": "O",
            "arguments": {"path": "a.txt"},
        })
        self.assertEqual(len(self.operations.called), 1)
        self.assertEqual(self.operations.called[0]["capability"], "read")
        self.assertEqual(self.operations.called[0]["work_id"], "W")
        self.assertEqual(self.operations.called[0]["operation_id"], "O")

    async def test_unknown_and_special_rejected_without_effect(self):
        for capability in ("nonexistent", "desktop_capture"):
            await self.compact.call_tool("bct_dispatch", {
                "capability": capability, "work_id": "W",
                "operation_id": "O", "arguments": {},
            })
        self.assertEqual(self.operations.called, [])




class LightweightAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_middleware_rejects_missing_and_invalid_token(self):
        from bct.mcp_server import LocalBearerMiddleware
        responses = []
        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        app = LocalBearerMiddleware(inner, "a" * 64)
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        for headers, expected in (([], 401), ([(b"authorization", b"Bearer wrong")], 401),
                                  ([(b"authorization", b"Bearer " + b"a" * 64)], 200),
                                  ([(b"x-bct-token", b"a" * 64)], 200)):
            result = []
            async def collect(message):
                result.append(message)
            await app({"type": "http", "path": "/mcp", "method": "POST", "headers": headers},
                      receive, collect)
            self.assertEqual(result[0]["status"], expected)


class CompactRuntimeHTTPTests(unittest.TestCase):
    def test_real_isolated_runtime_and_receipt(self):
        import os
        import httpx
        from unittest.mock import patch
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from test_mcp_integration import MCPIntegrationTests

        with patch.dict(os.environ, {"BCT_MCP_CATALOGUE": "compact"}):
            fixture = MCPIntegrationTests()
            fixture.setUp()
            try:
                async def probe():
                    url = f"http://127.0.0.1:{fixture.port}/mcp"
                    async with httpx.AsyncClient(timeout=10) as anon:
                        self.assertEqual(401, (await anon.post(url, json={})).status_code)
                    async with httpx.AsyncClient(
                        headers={"Authorization": "Bearer " + fixture.controller.mcp_secret()},
                        timeout=15,
                    ) as http:
                        async with streamable_http_client(url, http_client=http) as (read, write, _):
                            async with ClientSession(read, write) as client:
                                await client.initialize()
                                names = {t.name for t in (await client.list_tools()).tools}
                                self.assertEqual(8, len(names))
                                self.assertIn("bct_dispatch", names)
                                created = await client.call_tool("bct_work_create", {
                                    "work_id": "compact-test-work", "request_summary": "read only test",
                                    "roots": [str(fixture.project)], "actions": ["read"],
                                })
                                self.assertFalse(created.isError)
                                params = {"capability": "read", "work_id": "compact-test-work",
                                          "operation_id": "compact-read-1",
                                          "arguments": {"path": str(fixture.project / "hello.txt")}}
                                result = await client.call_tool("bct_dispatch", params)
                                self.assertEqual("APPLIED", result.structuredContent["outcome"])
                                replay = await client.call_tool("bct_dispatch", params)
                                self.assertTrue(replay.structuredContent["duplicate"])
                                receipt = await client.call_tool("bct_operation_get", {
                                    "work_id": "compact-test-work", "operation_id": "compact-read-1",
                                })
                                self.assertEqual("APPLIED", receipt.structuredContent["outcome"])
                                # A read-only Work must reject writes.
                                unauthorized = await client.call_tool("bct_dispatch", {
                                    "capability": "write", "work_id": "compact-test-work",
                                    "operation_id": "compact-denied-write-1",
                                    "arguments": {"path": str(fixture.project / "hello.txt"), "content": "NO"},
                                })
                                self.assertTrue(unauthorized.isError or (unauthorized.structuredContent or {}).get("outcome") != "APPLIED")
                                self.assertEqual(
                                    "hello from MCP\n",
                                    (fixture.project / "hello.txt").read_text(encoding="utf-8"),
                                )
                                # The same Work and operation id cannot be repurposed to a new request.
                                reused = await client.call_tool("bct_dispatch", {
                                    "capability": "read", "work_id": "compact-test-work",
                                    "operation_id": "compact-read-1",
                                    "arguments": {"path": str(fixture.project / "missing.txt")},
                                })
                                self.assertTrue(reused.isError or (reused.structuredContent or {}).get("outcome") != "APPLIED")
                asyncio.run(probe())
            finally:
                fixture.tearDown()


class CompactClaimContractTests(unittest.TestCase):
    def test_persisted_unknown_blocks_claim_and_retry(self):
        import tempfile
        from pathlib import Path
        from bct.core.models import Outcome, Work
        from bct.core.store import Store
        from bct.features.claim_reconciliation import ReadOnlyClaimReconcileFeature
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work("compact-unknown", "fixture", (root,),
                                         frozenset({"write", "claim_reconcile"}), "owner"))
            created, _ = store.begin_operation(
                operation_id="unknown-1", work=work, principal_id="owner",
                request_digest="digest-1", capability="write", target="fixture",
                resources=("resource:fixture",), policy_revision="test",
            )
            self.assertTrue(created)
            store.finish_operation(
                operation_id="unknown-1", outcome=Outcome.UNKNOWN,
                evidence={"phase": "fixture"}, error="uncertain", release_claims=False,
            )
            self.assertEqual(Outcome.UNKNOWN, store.get_operation_for(
                operation_id="unknown-1", work_id="compact-unknown",
                principal_id="owner").outcome)
            self.assertTrue(store.claim_diagnostics())
            with self.assertRaises(Exception):
                store.begin_operation(
                    operation_id="another-1", work=work, principal_id="owner",
                    request_digest="digest-2", capability="write", target="fixture",
                    resources=("resource:fixture",), policy_revision="test",
                )
            feature = ReadOnlyClaimReconcileFeature(store)
            request = feature.prepare(work=work, arguments={
                "original_operation_id": "unknown-1", "reason": "unproven",
            })
            request = type(request)(
                request.capability, request.target, request.arguments, request.resources,
                {"work_id": "compact-unknown", "principal_id": "owner"}, "resolver",
            )
            with self.assertRaises(Exception):
                feature.execute(request)
            self.assertTrue(store.claim_diagnostics())

class CompactUnknownHTTPTests(unittest.TestCase):
    def test_unknown_claim_conflict_and_recovery_rejection_over_http(self):
        import os
        import httpx
        from pathlib import Path
        from unittest.mock import patch
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from bct.core.models import Outcome
        from bct.core.store import Store
        from test_mcp_integration import MCPIntegrationTests

        with patch.dict(os.environ, {"BCT_MCP_CATALOGUE": "compact"}):
            fixture = MCPIntegrationTests()
            fixture.setUp()
            try:
                async def probe():
                    url = f"http://127.0.0.1:{fixture.port}/mcp"
                    async with httpx.AsyncClient(
                        headers={"Authorization": "Bearer " + fixture.controller.mcp_secret()},
                        timeout=15,
                    ) as http:
                        async with streamable_http_client(url, http_client=http) as (read, write, _):
                            async with ClientSession(read, write) as client:
                                await client.initialize()
                                created = await client.call_tool("bct_work_create", {
                                    "work_id": "unknown-http-work",
                                    "request_summary": "isolated unknown policy",
                                    "roots": [str(fixture.project)],
                                    "actions": ["read", "claim_reconcile"],
                                })
                                self.assertFalse(created.isError)
                                store = Store(fixture.runtime / "state" / "state.sqlite")
                                work = store.get_work("unknown-http-work")
                                target = str(fixture.project / "hello.txt")
                                # Inject a fixture-only uncertain effect into the isolated store.
                                # A read UNKNOWN is kept unresolved, while the resolver must
                                # never infer that the effect is safe to replay.
                                feature = fixture.service
                                # Retrieve the exact resource key from the existing read feature.
                                from bct import BCT
                                isolated = BCT(
                                    state_path=fixture.runtime / "state" / "state.sqlite",
                                    policy_path=fixture.release / "bct.toml",
                                    data_root=fixture.runtime.parent / "data",
                                )
                                prepared = isolated.operations._features["read"].prepare(
                                    work=work, arguments={"path": target},
                                )
                                _, initial_result = store.begin_operation(
                                    operation_id="original-unknown",
                                    work=work, principal_id=work.owner_principal_id,
                                    request_digest="fixture-unknown",
                                    capability="read", target=prepared.target,
                                    resources=prepared.resources,
                                    policy_revision="fixture",
                                )
                                self.assertFalse(initial_result.duplicate)
                                store.finish_operation(
                                    operation_id="original-unknown", outcome=Outcome.UNKNOWN,
                                    evidence={"phase": "fixture"}, error="uncertain",
                                    release_claims=False,
                                )
                                blocked = await client.call_tool("bct_dispatch", {
                                    "capability": "read", "work_id": "unknown-http-work",
                                    "operation_id": "blocked-read",
                                    "arguments": {"path": target},
                                })
                                self.assertTrue(blocked.isError or
                                                (blocked.structuredContent or {}).get("outcome") != "APPLIED")
                                original = await client.call_tool("bct_operation_get", {
                                    "work_id": "unknown-http-work", "operation_id": "original-unknown",
                                })
                                self.assertEqual("UNKNOWN", original.structuredContent["outcome"])
                                self.assertTrue(store.claim_diagnostics())
                                # Mutating UNKNOWN must remain non-reconcilable; covered by
                                # the focused policy test, not cleared here.
                                retry = await client.call_tool("bct_dispatch", {
                                    "capability": "read", "work_id": "unknown-http-work",
                                    "operation_id": "blocked-read",
                                    "arguments": {"path": target},
                                })
                                self.assertTrue(retry.isError or
                                                (retry.structuredContent or {}).get("outcome") != "APPLIED")
                                self.assertEqual("UNKNOWN", store.get_operation_for(
                                    operation_id="original-unknown",
                                    work_id="unknown-http-work",
                                    principal_id=work.owner_principal_id,
                                ).outcome.value)
                                # A separate mutating UNKNOWN is not eligible for
                                # claim release without exact no-effect proof.
                                store.begin_operation(
                                    operation_id="unknown-write",
                                    work=work, principal_id=work.owner_principal_id,
                                    request_digest="fixture-write",
                                    capability="write", target=target,
                                    resources=("write:separate-fixture",),
                                    policy_revision="test",
                                )
                                store.finish_operation(
                                    operation_id="unknown-write", outcome=Outcome.UNKNOWN,
                                    evidence={"phase": "fixture"}, error="effect unproven",
                                    release_claims=False,
                                )
                                refused = await client.call_tool("bct_dispatch", {
                                    "capability": "claim_reconcile",
                                    "work_id": "unknown-http-work",
                                    "operation_id": "refuse-unproven",
                                    "arguments": {
                                        "original_operation_id": "unknown-write",
                                        "reason": "unproven test",
                                    },
                                })
                                self.assertTrue(refused.isError or
                                                (refused.structuredContent or {}).get("outcome") != "APPLIED")
                                self.assertEqual("UNKNOWN", store.get_operation_for(
                                    operation_id="unknown-write",
                                    work_id="unknown-http-work",
                                    principal_id=work.owner_principal_id,
                                ).outcome.value)
                                self.assertTrue(store.claim_diagnostics())
                asyncio.run(probe())
            finally:
                fixture.tearDown()


class HybridRuntimeHTTPTests(unittest.TestCase):
    def test_direct_read_and_dispatch_same_receipt_boundary(self):
        import os
        import httpx
        from unittest.mock import patch
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from test_mcp_integration import MCPIntegrationTests
        with patch.dict(os.environ, {"BCT_MCP_CATALOGUE": "hybrid"}):
            fixture = MCPIntegrationTests()
            fixture.setUp()
            try:
                async def probe():
                    url = f"http://127.0.0.1:{fixture.port}/mcp"
                    async with httpx.AsyncClient(
                        headers={"Authorization": "Bearer " + fixture.controller.mcp_secret()},
                        timeout=15,
                    ) as http:
                        async with streamable_http_client(url, http_client=http) as (read, write, _):
                            async with ClientSession(read, write) as client:
                                await client.initialize()
                                names = {t.name for t in (await client.list_tools()).tools}
                                self.assertEqual(10, len(names))
                                self.assertIn("bct_execute", names)
                                self.assertIn("bct_read", names)
                                self.assertIn("bct_dispatch", names)
                                created = await client.call_tool("bct_work_create", {
                                    "work_id": "hybrid-work", "request_summary": "fixture",
                                    "roots": [str(fixture.project)], "actions": ["read"],
                                })
                                self.assertFalse(created.isError)
                                original = {"work_id": "hybrid-work", "operation_id": "hybrid-read",
                                            "arguments": {"path": str(fixture.project / "hello.txt")}}
                                a = await client.call_tool("bct_read", original)
                                self.assertEqual("APPLIED", a.structuredContent["outcome"])
                                b = await client.call_tool("bct_dispatch", {"capability": "read", **original})
                                self.assertTrue(b.structuredContent["duplicate"])
                                refused = await client.call_tool("bct_execute", {
                                    "work_id": "hybrid-work", "operation_id": "hybrid-denied",
                                    "arguments": {"argv": ["does-not-run"]},
                                })
                                self.assertTrue(refused.isError or
                                                (refused.structuredContent or {}).get("outcome") != "APPLIED")
                                self.assertEqual("hello from MCP\n",
                                                 (fixture.project / "hello.txt").read_text(encoding="utf-8"))
                asyncio.run(probe())
            finally:
                fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
