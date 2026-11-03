from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.code_block_scan import resolve_scan_root, scan
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
        self.assertIn("component_catalog_candidates", report)
        self.assertIn("work_order", report)
        self.assertEqual(report["scan"]["files"], 2)
        self.assertGreaterEqual(report["scan"]["blocks"], 2)
        self.assertTrue(any(item["reason"] == "exact_duplicate_block" for item in report["refactor_targets"]))

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


if __name__ == "__main__":
    unittest.main()
