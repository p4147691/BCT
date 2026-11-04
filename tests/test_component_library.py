from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs" / "component-library.v1.json"


class ComponentLibraryTests(unittest.TestCase):
    def test_catalogue_has_unique_bounded_components(self):
        data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
        self.assertEqual("bct.component-library.v1", data["schema"])
        self.assertEqual(1, data["version"])
        components = data["components"]
        ids = [item["id"] for item in components]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("browser.close_exact_chat_tab", ids)
        self.assertIn("node.recovery", ids)
        self.assertIn("bdc.desktop_component_catalogue", ids)
        self.assertIn("bdc.desktop_recipe_planner", ids)
        allowed_kinds = {"primitive", "module", "partial_recipe", "full_recipe"}
        allowed_maturity = {"isolated", "bounded", "embedded"}
        for item in components:
            self.assertIn(item["kind"], allowed_kinds, item["id"])
            self.assertIn(item["maturity"], allowed_maturity, item["id"])
            self.assertTrue(item["contract"].strip(), item["id"])
            self.assertIsInstance(item["effects"], list, item["id"])
            self.assertTrue(item["safety"], item["id"])
            for implementation in item["implementation"]:
                self.assertTrue((ROOT / implementation["path"]).is_file(), item["id"])
                self.assertTrue(implementation["symbol"].strip(), item["id"])


if __name__ == "__main__":
    unittest.main()
