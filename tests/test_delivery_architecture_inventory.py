from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/exec-plans/active/BCT_RCC_DELIVERY_LEDGER_V1_20261022.md"


def javascript_set(source: str, name: str) -> set[str]:
    match = re.search(
        rf"const\s+{re.escape(name)}\s*=\s*new Set\(\[(.*?)\]\);",
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing JavaScript Set {name}")
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


class DeliveryArchitectureInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = (
            ROOT / "modules/rcc/extension/legacy/command_policy.js"
        ).read_text(encoding="utf-8")
        cls.state_service = (
            ROOT / "modules/rcc/extension/domain/state_service.js"
        ).read_text(encoding="utf-8")
        cls.delivery_service = (
            ROOT / "modules/rcc/extension/domain/delivery_ledger_service.js"
        ).read_text(encoding="utf-8")
        cls.store = (ROOT / "src/bct/core/store.py").read_text(encoding="utf-8")
        cls.plan = PLAN.read_text(encoding="utf-8")

    def test_native_command_inventory_matches_the_audited_source(self) -> None:
        expected = {
            "NEW_RELAY_COMMANDS": {
                "simple-relay-bind", "simple-relay-send",
                "simple-relay-return", "new-chat-send",
                "delivery-start", "delivery-cancel", "delivery-status", "delivery-return",
                "retire-composer-draft",
            },
            "CONVERSATION_COMMANDS": {
                "rename-conversation", "conversation-bind",
            },
            "ORCHESTRATION_COMMANDS": {"send"},
            "READ_ONLY_COMMANDS": {
                "ping", "state", "result", "rename-receipt", "probe",
                "probe-tabs", "diagnose-activity", "diagnose-composer",
                "delivery-manager-status", "delivery-recovery-inspect",
                "diagnose-conversation-ui", "api-probe", "main-capture-get",
            },
            "MAINTENANCE_COMMANDS": {"reload-extension"},
        }
        for name, commands in expected.items():
            with self.subTest(name=name):
                self.assertEqual(javascript_set(self.policy, name), commands)
                for command in commands:
                    self.assertIn(f"`{command}`", self.plan)

    def test_rcc_storage_inventory_is_documented(self) -> None:
        keys = {
            "relayResultReceiptsV1", "renameReceiptsV1",
            "bindingSubmitLeasesV1", "simpleRelayV0Binding",
            "simpleRelayV0Receipts", "newChatReceiptsV1",
            "deliveryLedgerMirrorV1",
        }
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, self.state_service + self.delivery_service)
                self.assertIn(f"`{key}`", self.plan)

    def test_orchestration_table_inventory_is_documented(self) -> None:
        table_names = set(re.findall(
            r"CREATE TABLE IF NOT EXISTS (orchestration_[a-z_]+)",
            self.store,
        ))
        self.assertGreaterEqual(len(table_names), 18)
        for table in table_names:
            with self.subTest(table=table):
                self.assertIn(f"`{table}`", self.plan)


if __name__ == "__main__":
    unittest.main()
