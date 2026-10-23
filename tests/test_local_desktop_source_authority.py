from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TestLocalDesktopSourceAuthority(unittest.TestCase):
    def test_bct_local_main(self):
        cfg = tomllib.loads((ROOT / "bct.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg["git_authority"]["mode"], "local")
        self.assertEqual(Path(cfg["git_authority"]["source_root"]), ROOT)

    def test_monitor_source_runtime_separate(self):
        cfg = tomllib.loads((ROOT / "bct.toml").read_text(encoding="utf-8"))["monitor"]
        source = Path(cfg["canonical_source_root"]) / cfg["source_root"]
        live = Path(cfg["live_root"])
        self.assertEqual(source, ROOT / "modules" / "monitor")
        self.assertNotEqual(source.resolve(), live.resolve())

    def test_monitor_policy_is_local_first(self):
        text = (ROOT / "modules/monitor/extension/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Official source authority: local Git main", text)
        self.assertIn("expected-live-SHA", text)
        self.assertNotIn("Official source: GitHub", text)

if __name__ == "__main__":
    unittest.main()
