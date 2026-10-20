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
        # Accepted Simple Relay Return V0 source/LIVE baseline (2026-10-20).
        # These are release guards, not a deployment action.
        expected = {
            "background.js": "8c3a027a89ece83b58e44a396ddd0dfdfdc0ea12d729b6653675afe9f13f258f",
            "content.js": "d059091b689e4dec9f702b33c65b421d86fefc3408e2aa6dfdebe40cfec7b941",
            "manifest.json": "b45d1a3cd4ad5aa0d57ddd106c89ed749c264ea8af4994aeb8175cf9fc274ec1",
            "relay_core.js": "b3ad92bc20564a905bffc37f3e524e2c8e8c5ae71c02517a301cedd5cf1341cd",
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
        self.assertEqual("1.0.24", manifest["version"])
        self.assertEqual("1.0.24 · RCC Core Read-Only Shadow", manifest["version_name"])
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

    def test_content_and_background_build_markers_match(self):
        marker = "2026-10-20-rcc-core-shadow-v1"
        for name in ("content.js", "background.js"):
            self.assertIn(marker, (self.extension / name).read_text(encoding="utf-8"))

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

    def test_stale_content_completion_requires_exact_durable_receipt(self):
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        handler = background.split(
            "if (message.type === 'relay:getPendingStatus') {", 1
        )[1].split("if (message.type === 'relay:getState') {", 1)[0]
        self.assertIn("receipt?.resultState === 'RESULT_PERSISTED'", handler)
        self.assertIn("Number(receipt.tabId) === tabId", handler)
        self.assertIn("String(receipt.conversationKey) === key", handler)
        self.assertIn("completed: true", handler)

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
        self.assertIn("12 tests PASS", completed.stdout)

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

    def test_native_wakeback_preserves_exact_manager_return_role(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_manager_wakeback_native.js"], cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("exact-manager routing fence PASS", completed.stdout)

    def test_nested_turn_capture_and_recovery_contract(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        for name, marker in (
            ("test_route_turn_deduplication.js", "route turn deduplication tests: PASS"),
            ("test_capture_recovery_contract.js", "capture recovery contract tests: PASS"),
            ("test_durable_execution_retirement.js", "durable execution retirement tests: PASS"),
            ("test_collapsed_prompt_identity.js", "collapsed prompt identity tests: PASS"),
        ):
            completed = subprocess.run(
                [node, name], cwd=str(self.extension),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            self.assertIn(marker, completed.stdout)

    def test_rename_receipt_survives_generic_operation_cache_eviction(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, "test_rename_receipt_retention.js"], cwd=str(self.extension),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn("rename receipt retention tests: PASS", completed.stdout)

    def test_runtime_javascript_has_valid_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        for name in (
            "background.js", "content.js", "relay_core.js", "act_content.js",
            "act_bridge.js", "act_command_bridge.js", "activity_bridge.js", "popup.js",
            "core/identity.js", "core/state.js", "core/conversation.js", "core/transport.js",
            "core/shadow.js", "relay/contract.js", "legacy/command_policy.js",
        ):
            completed = subprocess.run(
                [node, "--check", str(self.extension / name)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
