from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


class ModuleLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.config = tomllib.loads((cls.root / "bct.toml").read_text(encoding="utf-8"))

    def test_product_modules_are_outside_core(self):
        for name in ("bdc", "rcc", "monitor", "github", "mcp", "status-ui"):
            self.assertTrue((self.root / "modules" / name).is_dir(), name)
        self.assertFalse((self.root / "modules" / "decision").exists())
        self.assertFalse((self.root / "components").exists())
        self.assertFalse((self.root / "rcc").exists())

    def test_monitor_source_is_the_bct_module(self):
        self.assertEqual("modules/monitor", self.config["monitor"]["source_root"])

    def test_manager_wake_receipt_v2_is_disabled_by_default(self):
        self.assertIs(
            False,
            self.config["orchestration"]["manager_wake_receipt_v2_enabled"],
        )

    def test_runtime_profile_has_no_legacy_source_paths(self):
        files = self.config["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertIn("modules/status-ui/index.html", files)
        self.assertFalse(any(item.startswith("modules/monitor/") for item in files))
        self.assertFalse(any(item.startswith("modules/rcc/") for item in files))
        self.assertFalse(any(item.startswith("modules/bdc/") for item in files))
        self.assertFalse(any(item.startswith("components/") for item in files))
        for required in (
            "src/bct/core/consumption.py",
            "src/bct/core/durable_pr2.py",
            "src/bct/core/manager_decision.py",
            "src/bct/core/rcc_result.py",
            "src/bct/manager_decision_recovery.py",
        ):
            self.assertIn(required, files)

    def test_tunnel_profile_uses_file_referenced_header_map(self):
        profile = (self.root / "modules" / "mcp" / "bct-control.profile.example.yaml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(2, profile.count("X-BCT-Token: 'file:D:\\BCT\\runtime\\mcp.token'"))
        self.assertNotIn("- 'X-BCT-Token:", profile)

    def test_tunnel_supervisor_is_bct_owned_and_exact(self):
        script = (self.root / "modules" / "mcp" / "ops" / "run_bct_tunnel_supervisor.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("D:\\TOOLS\\OpenAI\\tunnel-client\\0.0.14\\tunnel-client.exe", script)
        self.assertIn("http://127.0.0.1:18790/mcp", script)
        self.assertIn("file:D:\\BCT\\runtime\\mcp.token", script)
        self.assertIn("BCT_TUNNEL_TARGET_MISMATCH", script)
        self.assertIn("BCT_TUNNEL_HEALTH_RECOVERED", script)
        self.assertIn("BCT_TUNNEL_DEGRADED", script)
        self.assertIn("Get-NetTCPConnection -State Listen -OwningProcess", script)
        self.assertIn("$healthy.Count -ne 1", script)
        self.assertIn("[Environment+SpecialFolder]::ApplicationData", script)
        self.assertIn("[Environment+SpecialFolder]::UserProfile", script)
        self.assertNotIn("C:\\Users\\", script)
        self.assertNotIn("D:\\ACT", script)

    def test_handoff_current_state_uses_live_proof_not_self_referential_sha(self):
        handoff = (self.root / "PROJECT_HANDOFF.md").read_text(encoding="utf-8")
        current_section = handoff.split("## 현재 결정", 1)[0]
        self.assertIn("origin/main", current_section)
        self.assertIn("runtime\\current.json", current_section)
        self.assertIn("release_sha", current_section)
        self.assertIsNone(re.search(r"\b[0-9a-f]{40}\b", current_section))


if __name__ == "__main__":
    unittest.main()
