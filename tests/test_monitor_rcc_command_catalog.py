"""Read-only Monitor projection of the authoritative RCC/BCT command catalogue."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from bct.features.rcc import command_catalog


class MonitorRccCommandCatalogTests(unittest.TestCase):
    def test_catalogue_has_complete_presentation_metadata(self):
        rows = command_catalog()
        self.assertTrue(rows)
        self.assertEqual({"rcc-native", "bct"}, {row["origin"] for row in rows})
        for row in rows:
            with self.subTest(command=row["command"]):
                self.assertRegex(row["command"], r"^(?:rcc|bct)_")
                self.assertTrue(row["display_group"])
                self.assertTrue(row["summary"])
                self.assertIn(row["effect"], {"조회만", "Chrome 상태 변경", "메시지 전송", "기록·영수증 처리"})
                self.assertTrue(row["target"])
                self.assertTrue(row["source"])

    def test_monitor_route_reuses_catalogue_without_execution(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "bct" / "runtime_server.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        route = next(node for node in ast.walk(module)
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "monitor_rcc_command_catalog")
        names = {node.id for node in ast.walk(route) if isinstance(node, ast.Name)}
        self.assertIn("command_catalog", names)
        self.assertNotIn("operations", names)
        self.assertNotIn("run", names)

    def test_monitor_feature_is_loaded_before_generated_runtime(self):
        root = Path(__file__).resolve().parents[1] / "modules" / "monitor" / "extension"
        html = (root / "desktop.html").read_text(encoding="utf-8")
        feature = root / "features" / "rcc-command-catalog" / "monitor-rcc-command-catalog.js"
        self.assertTrue(feature.is_file())
        self.assertLess(html.index("monitor-rcc-command-catalog.js"), html.index('src="monitor.js"'))
        self.assertIn('id="monitorCommandCatalogList"', (root / "monitor.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
