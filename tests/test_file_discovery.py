from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import PreconditionError, Work
from bct.features.files import FileReadFeature


class FileDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = Work("pc-file-audit", "test", (str(self.root),),
                         frozenset({"read"}), "local")
        self.feature = FileReadFeature()
        (self.root / "Models").mkdir()
        (self.root / "Models" / "ZIT_alpha.safetensors").write_bytes(b"same model")
        (self.root / "Models" / "ZIT_beta.safetensors").write_bytes(b"same model")
        (self.root / "Models" / "Other.safetensors").write_bytes(b"other")
        (self.root / "notes.txt").write_text("some text", encoding="utf8")

    def run_read(self, operation, **arguments):
        request = self.feature.prepare(work=self.work, arguments={
            "operation": operation, "path": str(self.root), **arguments,
        })
        return self.feature.execute(request)

    def test_filename_substring_casefold(self):
        result = self.run_read("search", query="zit")
        self.assertEqual(2, result.output["count"])
        self.assertEqual(["Models/ZIT_alpha.safetensors", "Models/ZIT_beta.safetensors"],
                         sorted(item["path"] for item in result.output["matches"]))
        self.assertTrue(result.evidence["read_only"])

    def test_filename_glob(self):
        result = self.run_read("search", query="*.txt")
        self.assertEqual(["notes.txt"], [m["path"] for m in result.output["matches"]])

    def test_folder_name_match(self):
        result = self.run_read("search", query="Models")
        self.assertEqual("directory", result.output["matches"][0]["kind"])

    def test_duplicate_proven_exact_hash(self):
        result = self.run_read("duplicates")
        self.assertTrue(result.output["complete"])
        self.assertFalse(result.output["delete_authorized"])
        groups = result.output["groups"]
        self.assertEqual(1, len(groups))
        self.assertEqual(2, groups[0]["count"])
        self.assertEqual(10, groups[0]["bytes_per_file"])
        self.assertEqual(64, len(groups[0]["sha256"]))

    def test_hash_budget_marks_uncertain_not_duplicate(self):
        result = self.run_read("duplicates", max_hash_bytes=10)
        self.assertFalse(result.output["complete"])
        self.assertTrue(result.output["truncated"])
        self.assertGreater(result.output["unverified_files"], 0)
        self.assertEqual([], result.output["groups"])

    def test_truncated_search_is_not_complete(self):
        result = self.run_read("search", query="safetensors", max_entries=2)
        self.assertTrue(result.output["truncated"])
        self.assertFalse(result.output["complete"])

    def test_rejects_outside_work_root(self):
        outside = Path(self.temp.name).parent
        with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
            self.feature.prepare(work=self.work, arguments={
                "operation": "search", "path": str(outside), "query": "txt",
            })

    def test_rejects_invalid_glob_path(self):
        with self.assertRaisesRegex(PreconditionError, "QUERY_INVALID"):
            self.run_read("search", query="../secret")

    def test_rejects_hash_bytes_on_search(self):
        with self.assertRaisesRegex(PreconditionError, "FIELDS_INVALID"):
            self.run_read("search", query="txt", max_hash_bytes=500)

    def test_rejects_bool_budgets(self):
        with self.assertRaises(PreconditionError):
            self.run_read("duplicates", max_entries=True)

    def test_nested_reparse_does_not_traverse(self):
        outside = self.root / "linked"
        try:
            outside.symlink_to(self.root / "Models", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        r = self.run_read("search", query="ZIT")
        self.assertEqual(2, r.output["count"])
        self.assertGreater(r.output["unreadable_or_skipped"], 0)
        self.assertFalse(r.output["complete"])

    def test_existing_read_contract_untouched(self):
        r = self.run_read("directory_tree", depth=2, limit=100)
        self.assertIn("entries", r.output)
        self.assertEqual("directory_tree", r.evidence["operation"])


class FileComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / "one.bin"
        self.b = self.root / "two.bin"
        self.a.write_bytes(bytes([0, 255, 100, 1]))
        self.b.write_bytes(bytes([0, 255, 100, 1]))
        self.work = Work("pc-comparison", "test", (str(self.root),), frozenset({"read"}), "local")
        self.feature = FileReadFeature()

    def compare(self, **other):
        arguments = {"operation": "compare", "path_a": str(self.a), "path_b": str(self.b), **other}
        request = self.feature.prepare(work=self.work, arguments=arguments)
        return self.feature.execute(request).output

    def test_identical_binary(self):
        result = self.compare()
        self.assertTrue(result["complete"])
        self.assertTrue(result["equal"])
        self.assertEqual(64, len(result["sha256_a"]))
        self.assertTrue(result["read_only"])

    def test_different_same_size(self):
        self.b.write_bytes(bytes([0, 255, 100, 2]))
        result = self.compare()
        self.assertTrue(result["complete"])
        self.assertFalse(result["equal"])

    def test_different_size(self):
        self.b.write_bytes(b"abc")
        result = self.compare()
        self.assertTrue(result["complete"])
        self.assertFalse(result["equal"])

    def test_budget_does_not_invent_equality(self):
        result = self.compare(max_hash_bytes=1)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["equal"])
        self.assertEqual("HASH_BUDGET_EXCEEDED", result["reason"])

    def test_outside_scope_rejected(self):
        outside = self.root.parent / "not-ours.txt"
        with self.assertRaises(PreconditionError):
            self.compare(path_b=str(outside))

    def test_reject_same_path(self):
        with self.assertRaisesRegex(PreconditionError, "DISTINCT_FILES"):
            self.compare(path_b=str(self.a))

    def test_reject_extra_mutation_field(self):
        with self.assertRaisesRegex(PreconditionError, "FIELDS_INVALID"):
            self.compare(delete_after=True)
