from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import Principal


class MonitorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.live = self.root / "live"
        (self.source / "extension").mkdir(parents=True)
        (self.live / "extension").mkdir(parents=True)
        self.source_file = self.source / "extension" / "background.js"
        self.live_file = self.live / "extension" / "background.js"
        self.source_file.write_text("globalThis.bctMonitor = true;\n", encoding="utf-8")
        self.live_file.write_bytes(self.source_file.read_bytes())
        digest = hashlib.sha256(self.source_file.read_bytes()).hexdigest()
        (self.source / "BASELINE_SHA256.txt").write_text(
            f"{digest}  extension/background.js\n", encoding="utf-8",
        )
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["monitor"]\napproval_actions=[]\n\n'
            f'[monitor]\nsource_root="{self.source.as_posix()}"\nlive_root="{self.live.as_posix()}"\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.principal = Principal("developer", "test", frozenset({"monitor"}))
        self.bct.create_work(
            work_id="monitor-work", request_summary="monitor status", roots=[str(self.root)],
            actions=["monitor"], principal=self.principal,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, operation_id, operation):
        return self.bct.operations.run(
            principal=self.principal, work_id="monitor-work", operation_id=operation_id,
            capability="monitor", arguments={"operation": operation},
        )

    def test_status_proves_exact_source_and_live_bytes(self):
        result = self.call("monitor-exact", "status")
        self.assertTrue(result.output["source_live_exact"])
        self.assertEqual(result.output["owned_files"], 1)
        self.assertEqual(result.output["mismatches"], [])

    def test_status_reports_drift_without_changing_live(self):
        self.live_file.write_text("globalThis.bctMonitor = false;\n", encoding="utf-8")
        result = self.call("monitor-drift", "status")
        self.assertFalse(result.output["source_live_exact"])
        self.assertEqual(result.output["mismatches"][0]["path"], "extension/background.js")
        self.assertIn("false", self.live_file.read_text(encoding="utf-8"))

    def test_validate_checks_javascript_syntax(self):
        result = self.call("monitor-validate", "validate")
        self.assertEqual(result.outcome.value, "APPLIED")
        self.assertTrue(result.output["valid"])
        self.assertEqual(result.output["checked"], 1)


if __name__ == "__main__":
    unittest.main()
