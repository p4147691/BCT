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

    def test_current_candidate_critical_payload_hashes_match_recorded_baseline(self):
        release = json.loads((
            self.root / "modules" / "rcc" / "release" / "rcc_v2_rc.json"
        ).read_text(encoding="utf-8-sig"))
        self.assertEqual("RCC_REBUILD_V2_RC16_TERMINAL_IDLE_PROOF", release["candidate"])
        inventory = {item["path"]: item["sha256"]
                     for item in release["candidateInventory"]["files"]}
        critical = {
            "background.js", "background_loader.js", "content.js", "manifest.json",
            "relay_core.js", "boot/platform_context.js", "boot/background_app.js",
            "browser/tab_create_contract.js", "browser/tab_create_adapter.js",
            "domain/state_service.js", "domain/simple_relay_receipts.js",
            "domain/endpoint_service.js", "domain/diagnostic_support.js",
            "domain/simple_relay_service.js", "domain/orchestration_relay_service.js",
            "domain/delivery_ledger_service.js",
            "domain/new_chat_service.js",
            "domain/conversation_rename_service.js", "domain/readonly_diagnostics.js",
            "domain/runtime_message_service.js", "content/conversation_dom.js",
            "content/simple_relay_executor.js", "content/orchestration_relay_executor.js",
            "content/conversation_rename.js",
            "content/content_router.js", "content/activity_reporter.js",
        }
        self.assertTrue(critical.issubset(inventory))
        expected = {name: inventory[name] for name in critical}
        for name, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((self.extension / name).read_bytes()).hexdigest())

        native = self.root / "modules" / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        native_text = native.read_text(encoding="utf-8-sig")
        self.assertNotIn("bhlcnmbodlhbephppahojbigleklpmhj", native_text)
        self.assertIn("ocbidbaplechjjdacmokhnfbdmgjkphf", native_text)

    def test_committed_manifest_preserves_bct_install_identity(self):
        manifest = json.loads((self.extension / "manifest.json").read_text(encoding="utf-8-sig"))
        self.assertEqual("BCT RCC", manifest["name"])
        self.assertEqual("1.0.36", manifest["version"])
        self.assertEqual("1.0.36 Terminal Idle Proof", manifest["version_name"])
        self.assertEqual("BCT RCC", manifest["action"]["default_title"])
        self.assertNotIn("webRequest", manifest["permissions"])
        public_key = base64.b64decode(manifest["key"], validate=True)
        alphabet = "abcdefghijklmnop"
        extension_id = "".join(
            alphabet[nibble]
            for byte in hashlib.sha256(public_key).digest()[:16]
            for nibble in (byte >> 4, byte & 0x0F)
        )
        self.assertEqual("ocbidbaplechjjdacmokhnfbdmgjkphf", extension_id)
        self.assertEqual([
            "relay_core.js", "content/conversation_dom.js",
            "content/simple_relay_executor.js", "content/orchestration_relay_executor.js",
            "content/conversation_rename.js",
            "content/content_router.js",
            "content/activity_reporter.js", "content.js",
        ], manifest["content_scripts"][0]["js"])

    def test_active_native_and_runtime_surface_is_explicit(self):
        background = (self.extension / "domain" / "readonly_diagnostics.js").read_text(encoding="utf-8")
        runtime = (self.extension / "domain" / "runtime_message_service.js").read_text(encoding="utf-8")
        for command in (
            "ping", "state", "simple-relay-bind", "simple-relay-send",
            "simple-relay-return", "new-chat-send", "rename-conversation",
            "delivery-start", "delivery-status", "delivery-return",
            "delivery-manager-status",
            "conversation-bind", "send",
            "rename-receipt", "result", "main-capture-get",
            "api-probe", "probe-tabs", "diagnose-activity",
            "diagnose-conversation-ui", "diagnose-composer", "probe",
            "reload-extension",
        ):
            self.assertIn(f"message.command === '{command}'", background)
        for command in (
            "clear-relay-state", "close-conversation-tab",
            "conversation-bootstrap-bind", "create-chat-tab", "create-chat-window",
            "ensure", "main-capture-install", "manager-promote", "move-tab",
            "recover-created-result", "recover-pending", "register", "reload-workers",
            "result-ack", "send-to-created-tab",
            "send-to-tab", "send-wakeback",
        ):
            self.assertNotIn(f"message.command === '{command}'", background)

        for message_type in (
            "relay:getPendingStatus", "relay:getState", "relay:activity",
            "relay:orchestrationAuthorize", "relay:orchestrationResult",
        ):
            self.assertIn(f"message.type === '{message_type}'", runtime)
        for message_type in (
            "relay:manualSend", "relay:autoDirective", "relay:workerResult",
            "relay:actNaturalCommand", "relay:register", "relay:arm", "relay:hello",
        ):
            self.assertNotIn(f"message.type === '{message_type}'", runtime)
        popup = (self.extension / "popup.js").read_text(encoding="utf-8")
        self.assertIn("relay:getState", popup)
        for message_type in (
            "relay:register", "relay:forceRefresh", "relay:bootstrap",
            "relay:arm", "relay:manualSend",
        ):
            self.assertNotIn(message_type, popup)

    def test_active_content_surface_and_simple_relay_contract_remain(self):
        content = (self.extension / "content" / "content_router.js").read_text(encoding="utf-8")
        executor = (self.extension / "content" / "simple_relay_executor.js").read_text(encoding="utf-8")
        for message_type in (
            "relay:recoverExecution", "relay:activityProbe", "relay:probe",
            "relay:simpleExecute", "relay:simpleReadReply", "relay:orchestrationExecute",
            "relay:newChatExecute",
            "relay:newChatStatus", "relay:renameConversation",
        ):
            self.assertIn(f"message.type === '{message_type}'", content)
        for message_type in (
            "relay:execute", "relay:deliver", "relay:bootstrap",
            "relay:networkStarted", "relay:networkComplete",
        ):
            self.assertNotIn(f"message.type === '{message_type}'", content)
        self.assertIn("async function executeSimpleRelayV0(message)", executor)
        self.assertIn("async function readSimpleRelayV0Reply(message)", executor)
        self.assertIn("recoverCompletedReplyFromDom({ ...record, conversationKey })", content)

    def test_browser_management_is_explicitly_split_between_active_and_optional(self):
        loader = (self.extension / "background_loader.js").read_text(encoding="utf-8")
        active = ("browser/tab_create_contract.js", "browser/tab_create_adapter.js")
        for relative in active:
            self.assertTrue((self.extension / relative).is_file(), relative)
            self.assertIn(f"importScripts('{relative}');", loader)
        optional = (
            "browser/read_adapter.js",
            "browser/tab_move_contract.js", "browser/tab_move_adapter.js",
            "browser/tab_close_contract.js", "browser/tab_close_adapter.js",
            "browser/window_create_contract.js", "browser/window_create_adapter.js",
            "browser/tab_reload_contract.js", "browser/tab_reload_adapter.js",
        )
        for relative in optional:
            self.assertTrue((self.extension / relative).is_file(), relative)
            self.assertNotIn(f"importScripts('{relative}');", loader)
        self.assertNotIn("importScripts('act_bridge.js');", loader)

    def test_platform_boundaries_own_background_chrome_effects(self):
        loader = (self.extension / "background_loader.js").read_text(encoding="utf-8")
        background = (self.extension / "background.js").read_text(encoding="utf-8")
        self.assertNotIn("chrome.", background)
        platform = (
            "platform/chrome_state_repository.js", "platform/browser_gateway.js",
            "platform/native_transport.js", "platform/observation_gateway.js",
            "platform/lifecycle.js",
        )
        for relative in platform:
            self.assertTrue((self.extension / relative).is_file(), relative)
            self.assertIn(f"importScripts('{relative}');", loader)
            self.assertLess(loader.index(f"importScripts('{relative}');"),
                            loader.index("importScripts('background.js');"))

    def test_content_and_background_build_markers_match(self):
        marker = "2026-10-23-rcc-terminal-idle-proof-v1"
        for name in ("content/conversation_dom.js", "boot/platform_context.js"):
            self.assertIn(marker, (self.extension / name).read_text(encoding="utf-8"))

    def test_stale_content_completion_requires_exact_durable_receipt(self):
        background = (self.extension / "domain" / "runtime_message_service.js").read_text(encoding="utf-8")
        handler = background.split(
            "if (message.type === 'relay:getPendingStatus') {", 1
        )[1].split("if (message.type === 'relay:getState') {", 1)[0]
        self.assertIn("receipt?.resultState === 'RESULT_PERSISTED'", handler)
        self.assertIn("Number(receipt.tabId) === tabId", handler)
        self.assertIn("String(receipt.conversationKey) === key", handler)
        self.assertIn("completed: true", handler)

    def test_recovery_requires_exact_turn_terminal_evidence(self):
        content = (self.extension / "content" / "simple_relay_executor.js").read_text(encoding="utf-8")
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
            ("test_editor_rebind_submission_v1.js", "editor rebind, paragraph draft, and settle fence v3: PASS"),
            ("test_legacy_command_policy_v6.js", "legacy command policy v6: PASS"),
            ("test_conversation_rename_service_v1.js", "conversation rename service v1: PASS"),
            ("test_new_chat_service_v1.js", "rcc new chat service v1: PASS"),
            ("test_architecture_boundaries_v35.js", "rcc architecture boundaries v3.5: PASS"),
            ("test_platform_boundaries_v2.js", "rcc platform boundaries v2: PASS"),
            ("test_domain_content_boundaries_v3.js", "rcc domain/content boundaries v3: PASS"),
            ("test_active_bundle_load_v3.js", "rcc active bundle load v3: PASS"),
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
            ("test_terminal_idle_proof_v1.js", "terminal idle proof v1: PASS"),
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
            "platform/chrome_state_repository.js", "platform/browser_gateway.js",
            "platform/native_transport.js", "platform/observation_gateway.js",
            "platform/lifecycle.js",
            "boot/platform_context.js", "boot/background_app.js",
            "domain/state_service.js", "domain/simple_relay_receipts.js",
            "domain/endpoint_service.js", "domain/diagnostic_support.js",
            "domain/simple_relay_service.js", "domain/readonly_diagnostics.js",
            "domain/runtime_message_service.js", "content/conversation_dom.js",
            "content/simple_relay_executor.js", "content/content_router.js",
            "content/activity_reporter.js",
        ):
            completed = subprocess.run(
                [node, "--check", str(self.extension / name)], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
