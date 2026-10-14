from __future__ import annotations

import hashlib
import json
import base64
import shutil
import subprocess
import unittest
from pathlib import Path


class RccSourceBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.extension = cls.root / "modules" / "rcc" / "extension"

    def test_release_payload_hashes_match_recorded_baseline(self):
        expected = {
            "background.js": "75a1189b0a00a974e4183e65e49b9adb3ed755ad3151fec4dcca7884f284bf23",
            "content.js": "fc2c365ebf44a023c36a6522540c6e03e86eebb0e9997e00dfec38cdf6451c2a",
            "manifest.json": "64e462c602842d888f6ddd959dab555dcb06f85e4634162e83ad1cada2f7312b",
            "relay_core.js": "b74d8d5528eb7eaf60600ca3a046da351295c99f7bec1dfebf9b8f21192b2a31",
        }
        for name, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((self.extension / name).read_bytes()).hexdigest())
        native = self.root / "modules" / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        native_text = native.read_text(encoding="utf-8-sig")
        self.assertNotIn("bhlcnmbodlhbephppahojbigleklpmhj", native_text)
        self.assertIn("ocbidbaplechjjdacmokhnfbdmgjkphf", native_text)

    def test_committed_manifest_key_fixes_bct_install_identity(self):
        manifest = json.loads((self.extension / "manifest.json").read_text(encoding="utf-8-sig"))
        self.assertEqual("BCT RCC", manifest["name"])
        self.assertEqual("1.0.10", manifest["version"])
        self.assertEqual("1.0.10 · BCT", manifest["version_name"])
        self.assertEqual("BCT RCC", manifest["action"]["default_title"])
        self.assertNotEqual("0.1.0", manifest["version"])
        public_key = base64.b64decode(manifest["key"], validate=True)
        alphabet = "abcdefghijklmnop"
        extension_id = "".join(
            alphabet[nibble]
            for byte in hashlib.sha256(public_key).digest()[:16]
            for nibble in (byte >> 4, byte & 0x0f)
        )
        self.assertEqual("ocbidbaplechjjdacmokhnfbdmgjkphf", extension_id)

    def test_current_browser_contract_is_present(self):
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        for marker in (
            "runIdempotentOperation", "create-chat-window", "send-to-created-tab",
            "PENDING_CREATE_RECEIPT_REQUIRED", "SUBMIT_UNKNOWN", "move-tab",
            "recover-created-result", "recoverCreatedResult",
            "TARGET_BINDING_RECEIPT_MISMATCH",
        ):
            self.assertIn(marker, background)

    def test_existing_conversation_send_fences_exact_binding_before_submit(self):
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        dispatch = background.split(
            "async function dispatchRelayOnce(", 1
        )[1].split("async function deliverResult(", 1)[0]
        self.assertIn("TARGET_BINDING_RECEIPT_MISMATCH", dispatch)
        self.assertIn("TARGET_BINDING_CHANGED_BEFORE_DISPATCH", dispatch)
        self.assertIn("String(targetBindingReceipt || '')", dispatch)
        self.assertIn("String(messageHash || '')", dispatch)
        self.assertLess(
            dispatch.index("TARGET_BINDING_RECEIPT_MISMATCH"),
            dispatch.index("sendToChatTab("),
        )

    def test_recovery_requires_exact_turn_terminal_evidence_before_ignoring_stale_stop(self):
        content = (self.extension / "content.js").read_text(encoding="utf-8")
        recovery = content.split("function recoverCompletedReplyFromDom(record) {", 1)[1].split(
            "function collectReplyAfterNetworkComplete", 1
        )[0]
        self.assertIn("const exactTurnTerminal = completeState && completionUiReady;", recovery)
        self.assertIn(
            "if (!exactTurnTerminal && turnIsGenerating(routed.turn))",
            recovery,
        )
        self.assertLess(recovery.index("exactTurnTerminal"), recovery.index("assistantCandidatesForTurn"))

    def test_native_host_install_contract_is_bct_owned(self):
        manifest = json.loads(
            (self.root / "modules" / "rcc" / "native-host" /
             "com.ai_workspace_relay.host.v2.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual("com.ai_workspace_relay.host", manifest["name"])
        self.assertEqual(
            r"D:\ChromeExtensions\RCC\native\RelayNativeHostV2.exe", manifest["path"]
        )
        self.assertEqual(
            [
                "chrome-extension://ocbidbaplechjjdacmokhnfbdmgjkphf/",
            ],
            manifest["allowed_origins"],
        )
        self.assertNotIn(r"D:\ACT", json.dumps(manifest))

    def test_exact_send_button_transition_gate(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_issue57_editor_gate.js"],
            cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("7 tests PASS", completed.stdout)

    def test_first_message_navigation_ack_recovery(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_issue57_navigation_ack.js"],
            cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("7 negative fences PASS", completed.stdout)

    def test_first_message_bootstrap_identity_rebind(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_issue57_bootstrap_identity.js"],
            cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("5 fences PASS", completed.stdout)

    def test_parallel_submission_evidence(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_issue66_submission_evidence.js"],
            cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("4 tests PASS", completed.stdout)

    def test_orchestration_exact_binding_runtime_fences(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_orchestration_binding.js"],
            cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("4 orchestration binding fences PASS", completed.stdout)

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
