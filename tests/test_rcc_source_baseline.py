from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path


class RccSourceBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.extension = cls.root / "modules" / "rcc" / "extension"

    def test_source_only_v2_1_payload_hashes_match_recorded_baseline(self):
        # Source-only RCC Rebuild V2-1 guard. This is not an installed/LIVE hash.
        expected = {
            "background.js": "af8992f6c1d6bdcc62d8e331bf0cb05b1fd96efa4899b93d59d6b644c265d479",
            "content.js": "641d56fbe3d31e36dcf32d99e378cf667ec30a21e4c8b0c908681d91a56c131c",
            "manifest.json": "ce459e432179478309273453e8ea53f06a9017346b4fb2d51b0ad34a9874e7ae",
            "relay_core.js": "b3ad92bc20564a905bffc37f3e524e2c8e8c5ae71c02517a301cedd5cf1341cd",
        }
        for name, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((self.extension / name).read_bytes()).hexdigest())

        native = self.root / "modules" / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        native_text = native.read_text(encoding="utf-8-sig")
        self.assertNotIn("bhlcnmbodlhbephppahojbigleklpmhj", native_text)
        self.assertIn("ocbidbaplechjjdacmokhnfbdmgjkphf", native_text)

    def test_committed_manifest_preserves_bct_install_identity(self):
        manifest = json.loads((self.extension / "manifest.json").read_text(encoding="utf-8-sig"))
        self.assertEqual("BCT RCC", manifest["name"])
        self.assertEqual("1.0.24", manifest["version"])
        self.assertEqual("1.0.24 · RCC Core Read-Only Shadow", manifest["version_name"])
        self.assertEqual("BCT RCC", manifest["action"]["default_title"])
        public_key = base64.b64decode(manifest["key"], validate=True)
        alphabet = "abcdefghijklmnop"
        extension_id = "".join(
            alphabet[nibble]
            for byte in hashlib.sha256(public_key).digest()[:16]
            for nibble in (byte >> 4, byte & 0x0F)
        )
        self.assertEqual("ocbidbaplechjjdacmokhnfbdmgjkphf", extension_id)
        self.assertEqual(["relay_core.js", "content.js"], manifest["content_scripts"][0]["js"])

    def test_active_native_and_runtime_surface_is_explicit(self):
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        for command in (
            "ping", "state", "simple-relay-bind", "simple-relay-send",
            "simple-relay-return", "rename-receipt", "result", "main-capture-get",
            "api-probe", "probe-tabs", "diagnose-activity",
            "diagnose-conversation-ui", "diagnose-composer", "probe",
            "reload-extension",
        ):
            self.assertIn(f"message.command === '{command}'", background)
        for command in (
            "clear-relay-state", "close-conversation-tab", "conversation-bind",
            "conversation-bootstrap-bind", "create-chat-tab", "create-chat-window",
            "ensure", "main-capture-install", "manager-promote", "move-tab",
            "recover-created-result", "recover-pending", "register", "reload-workers",
            "rename-conversation", "result-ack", "send", "send-to-created-tab",
            "send-to-tab", "send-wakeback",
        ):
            self.assertNotIn(f"message.command === '{command}'", background)

        for message_type in ("relay:getPendingStatus", "relay:getState", "relay:activity"):
            self.assertIn(f"message.type === '{message_type}'", background)
        for message_type in (
            "relay:manualSend", "relay:autoDirective", "relay:workerResult",
            "relay:actNaturalCommand", "relay:register", "relay:arm", "relay:hello",
        ):
            self.assertNotIn(f"message.type === '{message_type}'", background)

    def test_active_content_surface_and_simple_relay_contract_remain(self):
        content = (self.extension / "content.js").read_text(encoding="utf-8")
        for message_type in (
            "relay:recoverExecution", "relay:activityProbe", "relay:probe",
            "relay:simpleExecute", "relay:simpleReadReply",
        ):
            self.assertIn(f"message.type === '{message_type}'", content)
        for message_type in (
            "relay:execute", "relay:deliver", "relay:bootstrap",
            "relay:renameConversation", "relay:networkStarted", "relay:networkComplete",
        ):
            self.assertNotIn(f"message.type === '{message_type}'", content)
        self.assertIn("async function executeSimpleRelayV0(message)", content)
        self.assertIn("async function readSimpleRelayV0Reply(message)", content)
        self.assertIn("recoverCompletedReplyFromDom({ ...record, conversationKey })", content)

    def test_optional_browser_management_is_preserved_but_unloaded(self):
        loader = (self.extension / "background_loader.js").read_text(encoding="utf-8")
        self.assertIn("importScripts('browser/read_adapter.js');", loader)
        optional = (
            "browser/tab_move_contract.js", "browser/tab_move_adapter.js",
            "browser/tab_create_contract.js", "browser/tab_create_adapter.js",
            "browser/tab_close_contract.js", "browser/tab_close_adapter.js",
            "browser/window_create_contract.js", "browser/window_create_adapter.js",
            "browser/tab_reload_contract.js", "browser/tab_reload_adapter.js",
        )
        for relative in optional:
            self.assertTrue((self.extension / relative).is_file(), relative)
            self.assertNotIn(f"importScripts('{relative}');", loader)
        self.assertNotIn("importScripts('act_bridge.js');", loader)

    def test_content_and_background_build_markers_match(self):
        marker = "2026-10-20-rcc-core-shadow-v1"
        for name in ("content.js", "background.js"):
            self.assertIn(marker, (self.extension / name).read_text(encoding="utf-8"))

    def test_stale_content_completion_requires_exact_durable_receipt(self):
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        handler = background.split(
            "if (message.type === 'relay:getPendingStatus') {", 1
        )[1].split("if (message.type === 'relay:getState') {", 1)[0]
        self.assertIn("receipt?.resultState === 'RESULT_PERSISTED'", handler)
        self.assertIn("Number(receipt.tabId) === tabId", handler)
        self.assertIn("String(receipt.conversationKey) === key", handler)
        self.assertIn("completed: true", handler)

    def test_recovery_requires_exact_turn_terminal_evidence(self):
        content = (self.extension / "content.js").read_text(encoding="utf-8")
        recovery = content.split("function recoverCompletedReplyFromDom(record) {", 1)[1].split(
            "function normalizedUiText", 1
        )[0]
        self.assertIn("const exactTurnTerminal = completeState && completionUiReady;", recovery)
        self.assertIn("if (!exactTurnTerminal && turnIsGenerating(routed.turn))", recovery)
        self.assertLess(recovery.index("exactTurnTerminal"), recovery.index("assistantCandidatesForTurn"))

    def test_native_host_install_contract_is_bct_owned(self):
        manifest = json.loads(
            (self.root / "modules" / "rcc" / "native-host" /
             "com.ai_workspace_relay.host.v2.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual("com.ai_workspace_relay.host", manifest["name"])
        self.assertEqual(r"D:\ChromeExtensions\RCC\native\RelayNativeHostV2.exe", manifest["path"])
        self.assertEqual(
            ["chrome-extension://ocbidbaplechjjdacmokhnfbdmgjkphf/"],
            manifest["allowed_origins"],
        )
        self.assertNotIn(r"D:\ACT", json.dumps(manifest))

    def _run_node(self, name: str, marker: str) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        completed = subprocess.run(
            [node, name], cwd=str(self.extension), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn(marker, completed.stdout)

    def test_simple_relay_and_policy_contracts(self):
        for name, marker in (
            ("test_simple_relay_v0.js", "simple_relay_v0: PASS"),
            ("test_simple_relay_route_adapter_v5.js", "simple relay route adapter v5: PASS"),
            ("test_legacy_command_policy_v6.js", "legacy command policy v6: PASS"),
            ("test_architecture_boundaries_v35.js", "rcc architecture boundaries v3.5: PASS"),
        ):
            self._run_node(name, marker)

    def test_readonly_and_dom_contracts(self):
        for name, marker in (
            ("test_browser_read_adapter_v1.js", "rcc browser read adapter v1: PASS"),
            ("test_core_shadow_protocol_v3.js", "core shadow content protocol v3: PASS"),
            ("test_capture_recovery_contract.js", "capture recovery contract tests: PASS"),
            ("test_collapsed_prompt_identity.js", "collapsed prompt identity tests: PASS"),
            ("test_completion_marker_guard.js", "markerless completion lifecycle tests: PASS"),
            ("test_route_turn_deduplication.js", "route turn deduplication tests: PASS"),
            ("test_conversation_network_v7.js", "conversation network v7: PASS"),
        ):
            self._run_node(name, marker)

    def test_optional_browser_adapter_contracts(self):
        for name, marker in (
            ("test_browser_tab_move_adapter_v1.js", "rcc browser tab move adapter v1: PASS"),
            ("test_browser_tab_create_adapter_v1.js", "rcc browser tab create adapter v1: PASS"),
            ("test_browser_tab_close_adapter_v1.js", "rcc browser tab close adapter v1: PASS"),
            ("test_browser_window_create_adapter_v1.js", "rcc browser window create adapter v1: PASS"),
            ("test_browser_tab_reload_adapter_v1.js", "rcc browser tab reload adapter v1: PASS"),
        ):
            self._run_node(name, marker)

    def test_runtime_javascript_has_valid_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        for name in (
            "background.js", "content.js", "relay_core.js", "activity_bridge.js", "popup.js",
            "core/identity.js", "core/state.js", "core/conversation.js", "core/transport.js",
            "core/shadow.js", "browser/read_adapter.js", "browser/tab_move_contract.js",
            "browser/tab_move_adapter.js", "browser/tab_create_contract.js",
            "browser/tab_create_adapter.js", "browser/tab_close_contract.js",
            "browser/tab_close_adapter.js", "browser/window_create_contract.js",
            "browser/window_create_adapter.js", "browser/tab_reload_contract.js",
            "browser/tab_reload_adapter.js", "relay/contract.js", "legacy/command_policy.js",
        ):
            completed = subprocess.run(
                [node, "--check", str(self.extension / name)], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
