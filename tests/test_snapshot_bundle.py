from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct import BCT
from bct.core.models import Outcome, PreconditionError, Principal


class SnapshotBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["read"]\napproval_actions=[]\n', encoding="utf-8",
        )
        self.bct = BCT(
            state_path=self.root / "state.sqlite", policy_path=self.policy,
        )
        self.principal = Principal("snapshot-owner", "test", frozenset({"read"}))
        self.bct.create_work(
            work_id="snapshot-work", request_summary="isolated snapshot test",
            roots=[str(self.root)], actions=["read"], principal=self.principal,
        )
        self.text_path = self.root / "source.txt"
        self.text_path.write_text("SNAPSHOT_SECRET_FILE_BODY", encoding="utf-8")

    def run_read(self, operation_id, arguments, work_id="snapshot-work"):
        return self.bct.operations.run(
            principal=self.principal, work_id=work_id,
            operation_id=operation_id, capability="read", arguments=arguments,
        )

    def snapshot(self, operation_id="snapshot-01", **arguments):
        return self.run_read(operation_id, {"operation": "snapshot", **arguments})

    def test_work_status_file_hash_and_receipt_without_body(self):
        initial = self.run_read("original-read", {"path": str(self.text_path)})
        self.assertEqual(initial.outcome, Outcome.APPLIED)
        result = self.snapshot(
            files=[{"id": "source", "path": str(self.text_path)}],
            receipt_ids=["original-read"],
        )
        self.assertEqual(result.outcome, Outcome.APPLIED)
        output = result.output
        self.assertEqual(output["work"]["work_id"], "snapshot-work")
        self.assertEqual(output["work"]["state"], "ACTIVE")
        self.assertEqual(output["scope"], "work")
        self.assertEqual(output["core_health"], "NOT_INCLUDED")
        self.assertEqual(output["consistency"], "NON_ATOMIC_FILES_AND_STORE")
        self.assertEqual(
            output["files"][0]["sha256"],
            hashlib.sha256(self.text_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(output["receipts"][0]["state"], "FINISHED")
        self.assertEqual(output["receipts"][0]["outcome"], "APPLIED")
        self.assertNotIn("SNAPSHOT_SECRET_FILE_BODY", json.dumps(result.as_dict()))
        self.assertEqual(result.evidence["receipt_count"], 1)

    def test_status_only_snapshot_and_existing_batch_unchanged(self):
        result = self.snapshot(files=[], receipt_ids=[], include_claims=False)
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(result.output["claims"], {"count": 0, "items": [], "truncated": False})
        batch = self.run_read(
            "original-batch", {"operation": "batch", "items": [
                {"id": "a", "path": str(self.text_path)},
            ]},
        )
        self.assertEqual(batch.outcome, Outcome.APPLIED)
        self.assertEqual(batch.output["items"][0]["output"]["text"], "SNAPSHOT_SECRET_FILE_BODY")

    def test_other_work_receipts_fail_closed(self):
        self.bct.create_work(
            work_id="other-work", request_summary="other",
            roots=[str(self.root)], actions=["read"], principal=self.principal,
        )
        other = self.run_read("other-receipt", {"path": str(self.text_path)}, "other-work")
        self.assertEqual(other.outcome, Outcome.APPLIED)
        result = self.snapshot(receipt_ids=["other-receipt"])
        self.assertNotEqual(result.outcome, Outcome.APPLIED)
        self.assertNotIn("SNAPSHOT_SECRET_FILE_BODY", json.dumps(result.as_dict()))

    def test_other_work_claims_not_returned(self):
        self.bct.create_work(
            work_id="other-work", request_summary="other",
            roots=[str(self.root)], actions=["read"], principal=self.principal,
        )
        other_file = self.root / "other.txt"
        other_file.write_text("different", encoding="utf-8")
        created, _ = self.bct.operations.begin(
            principal=self.principal, work_id="other-work",
            operation_id="pending-other", capability="read",
            arguments={"path": str(other_file)},
        )
        self.assertTrue(created)
        result = self.snapshot(include_claims=True)
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertNotIn("pending-other", json.dumps(result.output))
        self.assertFalse(any("other.txt" in x["resource_key"] for x in result.output["claims"]["items"]))

    def test_reject_unscoped_or_oversized_inputs(self):
        outside = self.root.parent / "not-in-work.txt"
        invalid = [
            {"files": [{"id": "a", "path": str(outside)}]},
            {"files": [{"id": "a", "path": str(self.text_path)}] * 2},
            {"files": [{"id": str(i), "path": str(self.text_path)} for i in range(21)]},
            {"receipt_ids": ["duplicate", "duplicate"]},
            {"include_claims": "yes"},
            {"files": [], "unexpected": True},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(PreconditionError):
                    self.snapshot(operation_id="invalid-snapshot", **arguments)

    def test_snapshot_does_not_report_its_temporary_claim_as_unresolved(self):
        result = self.snapshot(
            operation_id="own-claim-observation", include_claims=True,
        )
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(result.output["claims"]["count"], 0)
        self.assertEqual(result.output["claims"]["items"], [])
        self.assertEqual(self.bct.store.monitor_snapshot()["unresolved_claims"], [])

    def test_binary_metadata_and_idempotent_receipt(self):
        binary = self.root / "bytes.bin"
        binary.write_bytes(b"\xff\x00\xfe")
        result = self.snapshot(
            files=[{"id": "binary", "path": str(binary)}],
        )
        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(result.output["files"][0]["bytes"], 3)
        binary.write_bytes(b"\x00\x00\x00")
        with patch("bct.features.snapshot._fingerprint_file", side_effect=AssertionError("replayed")):
            repeated = self.snapshot(files=[{"id": "binary", "path": str(binary)}])
        self.assertTrue(repeated.duplicate)
        self.assertEqual(result.evidence, repeated.evidence)
        self.assertEqual(repeated.output, {})  # Stored receipts do not cache file metadata.


if __name__ == "__main__":
    unittest.main()
