from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


class ModuleLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.config = tomllib.loads((cls.root / "bct.toml").read_text(encoding="utf-8"))

    def test_product_modules_are_outside_core(self):
        for name in ("bdc", "rcc", "monitor", "decision", "github", "status-ui"):
            self.assertTrue((self.root / "modules" / name).is_dir(), name)
        self.assertFalse((self.root / "components").exists())
        self.assertFalse((self.root / "rcc").exists())

    def test_monitor_source_is_the_bct_module(self):
        self.assertEqual("modules/monitor", self.config["monitor"]["source_root"])

    def test_runtime_profile_has_no_legacy_source_paths(self):
        files = self.config["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertIn("modules/status-ui/index.html", files)
        self.assertTrue(any(item.startswith("modules/monitor/") for item in files))
        self.assertFalse(any(item.startswith("components/") for item in files))


if __name__ == "__main__":
    unittest.main()
