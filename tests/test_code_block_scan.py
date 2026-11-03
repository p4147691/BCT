from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.code_block_scan import resolve_scan_root, scan
from bct.code_block_organize import plan_block_replacement, prepare_block_apply
from bct.core.models import Work


class CodeBlockScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "one.py").write_text(
            "import json\n\n"
            "def repeated(value):\n"
            "    if value:\n"
            "        return str(value).strip()\n"
            "    return ''\n",
            encoding="utf-8",
        )
        (self.root / "two.py").write_text(
            "def repeated(value):\n"
            "    if value:\n"
            "        return str(value).strip()\n"
            "    return ''\n",
            encoding="utf-8",
        )
        self.work = Work(
            "scan-work", "scan fixture", (str(self.root),),
            frozenset({"read"}), "bct-mcp-local",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_read_only_report_has_required_products(self) -> None:
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        report = scan(self.root)
        after = {path.name: path.read_bytes() for path in self.root.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(report["schema"], "bct.code-block-scan.v1")
        self.assertTrue(report["read_only"])
        self.assertIn("block_map", report)
        self.assertIn("block_candidates", report)
        self.assertIn("refactor_targets", report)
        self.assertIn("block_cards", report)
        self.assertIn("block_index", report)
        self.assertIn("component_catalog_candidates", report)
        self.assertIn("work_order", report)
        self.assertEqual(report["scan"]["files"], 2)
        self.assertGreaterEqual(report["scan"]["blocks"], 2)
        self.assertTrue(any(item["reason"] == "exact_duplicate_block" for item in report["refactor_targets"]))
        first = report["block_index"][0]
        self.assertEqual(64, len(first["file_sha256"]))
        self.assertEqual(64, len(first["source_sha256"]))

    def test_work_root_and_read_capability_are_enforced(self) -> None:
        self.assertEqual(resolve_scan_root(self.work), self.root.resolve())
        outside = self.root.parent / "outside-code-scan"
        with self.assertRaisesRegex(PermissionError, "ROOT_OUTSIDE_WORK"):
            resolve_scan_root(self.work, str(outside))
        no_read = SimpleNamespace(roots=(str(self.root),), actions=frozenset({"write"}))
        with self.assertRaisesRegex(PermissionError, "READ_REQUIRED"):
            resolve_scan_root(no_read)

    def test_budgets_report_partial_instead_of_claiming_complete(self) -> None:
        (self.root / "three.py").write_text("def third():\n    return 3\n", encoding="utf-8")
        report = scan(self.root, max_files=1)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertFalse(report["scan"]["complete"])
        self.assertTrue(report["scan"]["limits"]["truncated"])

    def test_plan_and_partial_replacement_preserve_other_blocks(self) -> None:
        source = self.root / "one.py"
        source.write_text(
            "def keep():\n    return 'keep'\n\n"
            "def change(value):\n    return value + 1\n\n"
            "def keep_too():\n    return 'also'\n",
            encoding="utf-8",
        )
        report = scan(self.root)
        card = next(item for item in report["block_cards"]
                    if item["path"] == "one.py" and item["name"] == "change")
        before = source.read_text(encoding="utf-8")
        plan = plan_block_replacement(
            self.root, path="one.py", block_id=card["block_id"],
            replacement="def change(value):\n    return value * 2",
            expected_file_sha256=card["file_sha256"],
            expected_block_sha256=card["source_sha256"],
        )
        self.assertTrue(plan["read_only"])
        self.assertEqual(before, source.read_text(encoding="utf-8"))
        prepared = prepare_block_apply(
            self.root, path="one.py", block_id=card["block_id"],
            replacement=plan["replacement"],
            expected_file_sha256=plan["expected_file_sha256"],
            expected_block_sha256=plan["expected_block_sha256"],
            expected_after_sha256=plan["after_file_sha256"],
            plan_sha256=plan["plan_sha256"],
        )
        after = prepared["content"].replace("\r\n", "\n")
        self.assertIn("def keep():\n    return 'keep'", after)
        self.assertIn("def change(value):\n    return value * 2", after)
        self.assertIn("def keep_too():\n    return 'also'", after)
        self.assertNotIn("return value + 1", after)

    def test_plan_fails_closed_after_source_drift(self) -> None:
        report = scan(self.root)
        card = next(item for item in report["block_cards"] if item["path"] == "one.py")
        (self.root / "one.py").write_text("def changed():\n    return 9\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "FILE_SHA_MISMATCH"):
            plan_block_replacement(
                self.root, path="one.py", block_id=card["block_id"],
                replacement="def repeated(value):\n    return value",
                expected_file_sha256=card["file_sha256"],
                expected_block_sha256=card["source_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
