from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import ConflictError, Principal
from bct.core.store import Store
from concurrent.futures import ThreadPoolExecutor
from bct.integration_queue import (
    list_integration_requests,
    submit_integration_request,
    validate_integration_request,
)
from bct.mcp_server import build_mcp


class IntegrationQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.storepath = root / "state.sqlite"
        self.repo = root / "canonical"
        self.repo.mkdir()
        policy = root / "policy.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["read","write"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.storepath, policy_path=policy)
        self.principal = Principal("owner", "test", frozenset({"read", "write"}))
        self.work = self.bct.create_work(
            work_id="manager.task", request_summary="project readiness",
            roots=[str(root)], actions=["read", "write"],
            principal=self.principal,
        )

    def request(self, ident="request-001", *, repository_root=None):
        return {
            "request_id": ident,
            "project_id": "project.monitor",
            "repository_root": repository_root or str(self.repo),
            "expected_main_sha": "a" * 40,
            "feature_branch": "feature/monitor-queued",
            "feature_head_sha": "b" * 40,
            "changed_files": ["modules/monitor/extension/example.js"],
            "test_receipts": ["focused:PASS", "CI:401"],
            "candidate_ci_run_id": 401,
            "target_live_products": ["monitor"],
            "acceptance_criteria": "Verified minimized label and Chrome roster",
            "rollback_plan": "Restore the last exact installed Monitor payload",
        }

    def test_atomic_fifo_order_across_projects(self):
        a = submit_integration_request(self.bct.store, work=self.work,
                                       request=self.request("request-001"))
        b = submit_integration_request(self.bct.store, work=self.work,
                                       request=self.request("request-002"))
        rows = list_integration_requests(self.bct.store)["requests"]
        self.assertLess(a["sequence"], b["sequence"])
        self.assertEqual(["request-001", "request-002"],
                         [x["request_id"] for x in rows])
        self.assertTrue(all(x["state"] == "QUEUED" and
                            x["execution"] == "NOT_STARTED" for x in rows))

    def test_same_id_same_payload_returns_same_receipt(self):
        once = submit_integration_request(self.bct.store, work=self.work,
                                          request=self.request())
        twice = submit_integration_request(self.bct.store, work=self.work,
                                           request=self.request())
        self.assertEqual(once["sequence"], twice["sequence"])
        self.assertFalse(once["duplicate"])
        self.assertTrue(twice["duplicate"])
        self.assertEqual(1, len(list_integration_requests(self.bct.store)["requests"]))

    def test_same_id_different_payload_or_owner_fails_closed(self):
        submit_integration_request(self.bct.store, work=self.work, request=self.request())
        changed = self.request()
        changed["feature_head_sha"] = "c" * 40
        with self.assertRaises(ConflictError):
            submit_integration_request(self.bct.store, work=self.work, request=changed)
        other = self.bct.create_work(
            work_id="other", request_summary="other", roots=[str(self.repo)],
            actions=["read", "write"], principal=self.principal,
        )
        with self.assertRaises(ConflictError):
            submit_integration_request(self.bct.store, work=other,
                                       request=self.request())

    def test_repo_filter_is_fifo_and_does_not_change_queue(self):
        otherrepo = self.repo.parent / "other"
        otherrepo.mkdir()
        submit_integration_request(self.bct.store, work=self.work,
                                   request=self.request("request-001"))
        submit_integration_request(self.bct.store, work=self.work,
                                   request=self.request("request-002", repository_root=str(otherrepo)))
        filtered = list_integration_requests(
            self.bct.store, repository_root=str(otherrepo))["requests"]
        self.assertEqual(["request-002"], [x["request_id"] for x in filtered])
        self.assertEqual(2, len(list_integration_requests(self.bct.store)["requests"]))

    def test_rejects_dangerous_or_incomplete_metadata(self):
        for key, value in (
            ("request_id", "../../overwrite"),
            ("repository_root", "relative-repo"),
            ("feature_branch", "main"),
            ("feature_head_sha", "not-a-hash"),
            ("changed_files", ["../outside"]),
            ("target_live_products", []),
            ("candidate_ci_run_id", 0),
        ):
            request = self.request()
            request[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_integration_request(request)

    def test_survives_store_reopen_without_pending_external_effect(self):
        first = submit_integration_request(
            self.bct.store, work=self.work, request=self.request()
        )
        reopened = Store(self.storepath)
        rows = list_integration_requests(reopened)["requests"]
        self.assertEqual([first["sequence"]], [x["sequence"] for x in rows])
        self.assertEqual("NOT_STARTED", rows[0]["execution"])
        db = reopened._connect()
        try:
            self.assertEqual(1, db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='INTEGRATION_REQUEST_QUEUED'"
            ).fetchone()[0])
        finally:
            db.close()

    def test_concurrent_submissions_keep_distinct_monotonic_sequence(self):
        def send(i):
            return submit_integration_request(
                self.bct.store, work=self.work,
                request=self.request("concurrent-" + str(i)),
            )["sequence"]
        with ThreadPoolExecutor(max_workers=4) as executor:
            numbers = list(executor.map(send, range(8)))
        self.assertEqual(8, len(set(numbers)))
        rows = list_integration_requests(self.bct.store)["requests"]
        self.assertEqual(sorted(numbers), [x["sequence"] for x in rows])

    def test_no_operation_or_resource_claim_or_main_mutation(self):
        submit_integration_request(self.bct.store, work=self.work,
                                   request=self.request())
        db = self.bct.store._connect()
        try:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM operations").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM resource_claims").fetchone()[0])
        finally:
            db.close()
        self.assertEqual([], list(self.repo.iterdir()))
        self.assertFalse(list_integration_requests(self.bct.store)["claim_enabled"])
        self.assertFalse(list_integration_requests(self.bct.store)["auto_send_enabled"])


    def test_mcp_tool_catalogues_and_work_owner_scope(self):
        async def exercise():
            full = build_mcp(self.bct)
            compact = build_mcp(self.bct, compact_catalogue=True)
            self.assertIn("bct_integration_queue",
                          {x.name for x in await full.list_tools()})
            self.assertIn("bct_integration_queue",
                          {x.name for x in await compact.list_tools()})
            owner = Principal("bct-mcp-local", "test",
                              frozenset(self.bct.operations.capabilities))
            work = self.bct.create_work(
                work_id="bct-mcp-queue", request_summary="queue",
                roots=[str(self.repo)], actions=["read"], principal=owner,
            )
            result = await full.call_tool("bct_integration_queue", {
                "work_id": work.work_id, "operation": "submit",
                "request": self.request(),
            })
            self.assertIsInstance(result, tuple)
            queued = list_integration_requests(self.bct.store)["requests"]
            self.assertEqual(1, len(queued))
            result = await full.call_tool("bct_integration_queue", {
                "work_id": work.work_id, "operation": "list",
            })
            self.assertIsInstance(result, tuple)
            # Existing Work with a different principal cannot submit this tool.
            with self.assertRaisesRegex(Exception, "INTEGRATION_QUEUE_WORK_OWNER_INVALID"):
                await full.call_tool("bct_integration_queue", {
                    "work_id": self.work.work_id, "operation": "submit",
                    "request": self.request("other-request"),
                })
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
