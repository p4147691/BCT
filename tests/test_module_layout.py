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

    def test_desktop_clipboard_is_enabled_in_default_policy(self):
        self.assertIn("desktop_clipboard", self.config["policy"]["normal_actions"])

    def test_manager_wake_receipt_v2_enabled_for_approved_live_rollout(self):
        self.assertIs(
            True,
            self.config["orchestration"]["manager_wake_receipt_v2_enabled"],
        )
        self.assertNotIn(
            "manager_wake_receipt_v2_allowed_work_ids",
            self.config["orchestration"],
        )

    def test_live_rcc_uses_session_fence_instead_of_permanent_retirement(self):
        orchestration = self.config["orchestration"]
        self.assertEqual([], orchestration["excluded_new_assignment_instance_ids"])
        self.assertEqual(
            ["6174664e1c1b4e6db1d4729c841db3c9"],
            orchestration["require_current_session_instance_ids"],
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
            "src/bct/core/delivery_state.py",
            "src/bct/core/delivery_ledger.py",
            "src/bct/core/chat_stream_checkpoint.py",
            "src/bct/core/chat_stream_rcc_watch.py",
            "src/bct/core/manager_decision.py",
            "src/bct/core/rcc_result.py",
            "src/bct/features/claim_reconciliation.py",
            "src/bct/manager_decision_recovery.py",
            "src/bct/worker_dispatch_recovery.py",
            "src/bct/delivery_continuation_recovery.py",
            "src/bct/features/desktop_session.py",
            "src/bct/integrations/desktop_session.py",
            "src/bct/project_run.py",
        ):
            self.assertIn(required, files)

    def test_deployment_config_keeps_d_drive_runtime_as_the_only_active_profile(self):
        profiles = self.config["deployment"]["profiles"]
        self.assertEqual({"bct_runtime_v1"}, set(profiles))
        self.assertEqual(r"D:\BCT\runtime", profiles["bct_runtime_v1"]["runtime_root"])
        self.assertNotIn("cutover_successor_profile", profiles["bct_runtime_v1"])

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
        self.assertIn("BCT_TUNNEL_CLIENT_POINTER_V1", script)
        self.assertIn("tunnel-client-current.json", script)
        self.assertIn("BCT_TUNNEL_CLIENT_HASH_MISMATCH", script)
        self.assertIn("http://127.0.0.1:18790/mcp", script)
        self.assertIn("'file:' + (Join-Path $RuntimeDir 'mcp.token')", script)
        self.assertIn("BCT_TUNNEL_TARGET_MISMATCH", script)
        self.assertIn("BCT_TUNNEL_HEALTH_RECOVERED", script)
        self.assertIn("BCT_TUNNEL_DEGRADED", script)
        self.assertIn("Get-NetTCPConnection -State Listen -OwningProcess", script)
        self.assertIn("$healthy.Count -ne 1", script)
        self.assertIn("[Environment+SpecialFolder]::ApplicationData", script)
        self.assertIn("[Environment+SpecialFolder]::UserProfile", script)
        self.assertNotIn("C:\\Users\\", script)
        self.assertNotIn("D:\\ACT", script)

        cutover = (self.root / "modules" / "mcp" / "ops" / "invoke_bct_tunnel_cutover.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("BCT_TUNNEL_CUTOVER_RECEIPT_V1", cutover)
        self.assertIn("Local\\BCT-OpenAI-Tunnel-Cutover", cutover)
        self.assertIn("Write-Pointer '0.0.16'", cutover)
        self.assertIn("Write-Pointer '0.0.14'", cutover)
        self.assertIn("Start-And-Verify", cutover)

    def test_handoff_current_state_uses_live_proof_not_self_referential_sha(self):
        handoff = (self.root / "PROJECT_HANDOFF.md").read_text(encoding="utf-8")
        proof = re.search(
            r"현재 SHA와 generation은 `origin/main`, 두 `runtime\\current\.json`,\s*"
            r"health `release_sha`로 확인한다\.",
            handoff,
        )
        self.assertIsNotNone(proof)
        self.assertIsNone(re.search(r"\b[0-9a-f]{40}\b", proof.group(0)))


if __name__ == "__main__":
    unittest.main()
