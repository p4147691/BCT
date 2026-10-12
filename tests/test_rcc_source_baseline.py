from __future__ import annotations

import hashlib
import shutil
import subprocess
import unittest
from pathlib import Path


class RccSourceBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.extension = cls.root / "rcc" / "extension"

    def test_accepted_live_baseline_hashes_are_preserved(self):
        expected = {
            "background.js": "3de6118e2d3bac81cc212a0e4dc1d9d6e2d355731e5fd5dd7f196c71be89a9dd",
            "content.js": "1c0ca238dbf287ad6f0a01660c1a7f1ebf78b5e8c1806c5d8c81d5d012391406",
            "relay_core.js": "27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91",
            "manifest.json": "959903799ad2983319e0dfda331785c0587b04bea1fe4aef7e8fc0d320e75957",
        }
        for name, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((self.extension / name).read_bytes()).hexdigest())
        native = self.root / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        self.assertEqual(
            "164695e660a775b08d5d3289ff95340e28adb319a65d45e6e88790f4d1ee24ab",
            hashlib.sha256(native.read_bytes()).hexdigest(),
        )

    def test_current_browser_contract_is_present(self):
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        for marker in (
            "runIdempotentOperation", "create-chat-window", "send-to-created-tab",
            "PENDING_CREATE_RECEIPT_REQUIRED", "SUBMIT_UNKNOWN", "move-tab",
        ):
            self.assertIn(marker, background)

    def test_runtime_javascript_has_valid_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        for name in (
            "background.js", "content.js", "relay_core.js", "act_content.js",
            "act_bridge.js", "act_command_bridge.js", "activity_bridge.js", "popup.js",
        ):
            completed = subprocess.run(
                [node, "--check", str(self.extension / name)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
