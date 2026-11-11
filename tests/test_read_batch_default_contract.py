"""Existing bct_read file/batch safety and the default discovery contract."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, PreconditionError, Work
from bct.features.files import FileReadFeature
from bct.mcp_server import _CAPABILITY_USAGE


class ReadBatchDefaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = Work("batch-test", "isolated", (str(self.root),),
                         frozenset({"read"}), "test-owner")
        self.feature = FileReadFeature()

    def make(self, name, size=16):
        path = self.root / name
        path.write_bytes((name.encode() * (size // len(name) + 1))[:size])
        return path

    def items(self, count, size=16):
        return [{"id": f"f{i}", "operation": "file",
                 "path": str(self.make(f"doc{i}.txt", size))}
                for i in range(count)]

    def prepare(self, items):
        return self.feature.prepare(work=self.work,
                                    arguments={"operation": "batch", "items": items})

    def test_mcp_description_guides_choice_without_new_tool(self):
        desc = _CAPABILITY_USAGE["read"]
        for token in ("operation=file", "operation=batch", "same", "20 items",
                      "512 KiB", "1 MiB", "PARTIAL_FAILURE", "snapshot"):
            self.assertIn(token.lower(), desc.lower())

    def test_existing_mcp_tool_exposes_default_choice_without_new_tool(self):
        import asyncio
        from types import SimpleNamespace
        from bct.mcp_server import build_mcp
        class Operations:
            capabilities = ("read",)
        with tempfile.TemporaryDirectory() as base:
            server = build_mcp(SimpleNamespace(
                operations=Operations(), mcp_catalogue_path=Path(base) / "tools.toml"
            ))
            tools = asyncio.run(server.list_tools())
        matches = [tool for tool in tools if tool.name == "bct_read"]
        self.assertEqual(len(matches), 1)
        self.assertIn("operation=batch", matches[0].description)
        self.assertNotIn("bct_read_batch", [tool.name for tool in tools])

    def test_one_file_still_uses_original_file_contract(self):
        file = self.make("one.txt")
        req = self.feature.prepare(work=self.work,
                                   arguments={"operation": "file", "path": str(file)})
        result = self.feature.execute(req)
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(result.evidence["sha256"], hashlib.sha256(file.read_bytes()).hexdigest())

    def test_two_five_twenty_items_complete(self):
        for count in (2, 5, 20):
            with self.subTest(count=count):
                request = self.prepare(self.items(count))
                result = self.feature.execute(request)
                self.assertEqual(result.outcome, Outcome.APPLIED)
                self.assertEqual(result.evidence["status"], "COMPLETE")
                self.assertEqual(result.evidence["items_succeeded"], count)
                self.assertEqual(len(result.output["items"]), count)

    def test_limit_21_rejected_preflight(self):
        with self.assertRaisesRegex(PreconditionError, "ITEMS_INVALID"):
            self.prepare(self.items(21))

    def test_file_512k_boundary_and_one_byte_over(self):
        self.assertEqual(self.feature.execute(self.prepare(self.items(1, 512*1024))).outcome,
                         Outcome.APPLIED)
        with self.assertRaisesRegex(PreconditionError, "FILE_TOO_LARGE"):
            self.prepare(self.items(1, 512*1024+1))

    def test_combined_one_megabyte_boundary(self):
        items = self.items(2, 512*1024)
        self.assertEqual(self.feature.execute(self.prepare(items)).evidence["total_bytes"],
                         1024*1024)
        self.make("doc2.txt", 1)
        with self.assertRaisesRegex(PreconditionError, "TOTAL_BYTES_EXCEEDED"):
            self.prepare(items + [{"id":"f2","operation":"file",
                                  "path":str(self.root / "doc2.txt")}])

    def test_duplicate_id_and_target_are_rejected(self):
        items = self.items(2)
        with self.assertRaisesRegex(PreconditionError, "ID_DUPLICATE"):
            self.prepare([items[0], {**items[1], "id": items[0]["id"]}])
        with self.assertRaisesRegex(PreconditionError, "TARGET_DUPLICATE"):
            self.prepare([items[0], {**items[0], "id": "other"}])

    def test_work_scope_cannot_be_expanded_by_batch(self):
        outside = self.root.parent / (self.root.name + "-outside.txt")
        outside.write_text("outside", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        with self.assertRaises(PreconditionError):
            self.prepare([{"id":"outside","operation":"file","path":str(outside)}])

    def test_core_work_owner_and_read_capability_fence(self):
        from bct import BCT
        from bct.core.models import AuthorizationError, Principal
        state = self.root / "state.sqlite"
        policy = self.root / "policy.toml"
        policy.write_text("[policy]" + chr(10) + 'normal_actions=["read"]' + chr(10) + "approval_actions=[]" + chr(10),
                          encoding="utf-8")
        app = BCT(state_path=state, policy_path=policy)
        owner = Principal("owner", "test", frozenset({"read"}))
        outsider = Principal("other", "test", frozenset({"read"}))
        app.create_work(work_id="read-work", request_summary="read only",
                        roots=[str(self.root)], actions=["read"], principal=owner)
        arguments = {"operation": "batch", "items": self.items(2)}
        # Existing coordinator contract: a separately authorized successor may
        # take over a terminal Work with an epoch change; it is not a file
        # path or new capability grant from batch itself.
        result = app.operations.run(
            principal=outsider, work_id="read-work", operation_id="successor-read",
            capability="read", arguments=arguments,
        )
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(app.store.get_work("read-work").owner_principal_id, "other")
        without_read = Principal("other", "test", frozenset())
        with self.assertRaises(AuthorizationError):
            app.operations.run(
                principal=without_read, work_id="read-work",
                operation_id="missing-read-capability",
                capability="read", arguments=arguments,
            )

    def test_changed_file_partial_failure_not_success(self):
        items = self.items(2)
        req = self.prepare(items)
        Path(items[1]["path"]).unlink()
        result = self.feature.execute(req)
        self.assertEqual(result.outcome, Outcome.FAILED)
        self.assertEqual(result.evidence["status"], "PARTIAL_FAILURE")
        self.assertEqual(result.evidence["items_failed"], 1)
        self.assertEqual(result.evidence["items_succeeded"], 1)
        self.assertEqual([x["status"] for x in result.output["items"]], ["OK", "ERROR"])

    def test_file_grows_after_prepare_over_limit_is_partial_failure(self):
        items = self.items(2)
        req = self.prepare(items)
        Path(items[1]["path"]).write_bytes(b"x" * (512 * 1024 + 1))
        result = self.feature.execute(req)
        self.assertEqual(result.outcome, Outcome.FAILED)
        self.assertEqual(result.evidence["status"], "PARTIAL_FAILURE")
        self.assertEqual(result.evidence["items_failed"], 1)
        self.assertIn("READ_BATCH_FILE_TOO_LARGE",
                      result.evidence["items"][1]["code"])

    def test_file_modified_after_prepare_is_read_at_execution_not_snapshot(self):
        items = self.items(1)
        req = self.prepare(items)
        new_bytes = b"changed-after-prepare"
        Path(items[0]["path"]).write_bytes(new_bytes)
        result = self.feature.execute(req)
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(result.evidence["items"][0]["sha256"],
                         hashlib.sha256(new_bytes).hexdigest())
        self.assertNotEqual(result.evidence["items"][0]["bytes"], 16)


if __name__ == "__main__":
    unittest.main()
