"""Creation-bound send catalogue contract: discovery must not require code inspection."""
import unittest

from bct.features.rcc import BrowserFeature, command_catalog, validate_created_tab_send_input
from bct.core.models import PreconditionError


class CreatedTabInputContractTests(unittest.TestCase):
    def test_contract_is_on_existing_browser_command_not_fake_mcp_tool(self):
        matches = [row for row in command_catalog()
                   if row["command"] == "rcc_send_message_to_created_tab"]
        self.assertEqual(len(matches), 1)
        row = matches[0]
        self.assertEqual(row["legacy_alias"], "send-to-created-tab")
        self.assertFalse(row["exposed_as_separate_mcp_tool"])
        self.assertIn("bct_browser", row["input_contract"]["invocation"])

    def test_required_arguments_match_core_validation(self):
        contract = next(row["input_contract"] for row in command_catalog()
                        if row["legacy_alias"] == "send-to-created-tab")
        self.assertEqual(
            set(contract["required"]),
            {"instance_id", "session_id", "tab_id", "window_id",
             "create_operation_id", "text"},
        )
        self.assertIn("timeout_s", contract["optional"])
        self.assertEqual({"creation_receipt", "message"},
                         set(contract["forbidden"]) & {"creation_receipt", "message"})
        self.assertIn("UNKNOWN", contract["receipt_rule"])

    def test_preflight_rejects_wrong_user_keys_before_rcc(self):
        data = {
            "command": "rcc_send_message_to_created_tab",
            "instance_id": "i", "session_id": "s", "tab_id": 1,
            "window_id": 2, "creation_receipt": "old",
            "message": "hello",
        }
        verdict = validate_created_tab_send_input(data)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["missing"], ["create_operation_id", "text"])
        self.assertEqual(verdict["unexpected"], ["creation_receipt", "message"])
        data.pop("creation_receipt")
        data.pop("message")
        data["create_operation_id"] = "create1"
        data["text"] = "hello"
        self.assertTrue(validate_created_tab_send_input(data)["ok"])

    def test_actual_browser_prepare_rejects_bad_keys_before_effect(self):
        from types import SimpleNamespace
        feature = object.__new__(BrowserFeature)
        with self.assertRaises(PreconditionError) as captured:
            feature.prepare(
                work=SimpleNamespace(work_id="test"),
                arguments={
                    "command": "rcc_send_message_to_created_tab",
                    "instance_id": "fake-instance",
                    "creation_receipt": "one",
                    "message": "hello",
                },
            )
        error = str(captured.exception)
        self.assertIn("RCC_CREATED_TAB_INPUT_INVALID", error)
        self.assertIn("create_operation_id", error)
        self.assertIn("creation_receipt", error)

    def test_unreviewed_commands_do_not_advertise_invented_schema(self):
        rows = command_catalog()
        self.assertNotIn("input_contract", next(row for row in rows
                         if row["legacy_alias"] == "state"))


if __name__ == "__main__":
    unittest.main()
