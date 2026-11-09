from __future__ import annotations

import unittest

from bct.chain_entry_policy import public_entry_policy, select_message_entry


class ChainEntryPolicyTests(unittest.TestCase):
    def test_ordinary_request_uses_chain_recipe(self):
        self.assertEqual(
            {
                "tool": "bct_chain_recipe",
                "reason": "ORDINARY_REQUEST_DEFAULT",
                "requires_explicit_request": False,
                "entry": "CHAIN_RECIPE",
                "default_entry": "CHAIN_RECIPE",
            },
            select_message_entry(),
        )

    def test_task_and_send_are_explicit_opt_ins(self):
        self.assertEqual("bct_task_message", select_message_entry("task-message")["tool"])
        self.assertEqual("bct_send_message", select_message_entry("SEND_MESSAGE")["tool"])
        self.assertTrue(select_message_entry("TASK_MESSAGE")["requires_explicit_request"])
        self.assertTrue(select_message_entry("SEND_MESSAGE")["requires_explicit_request"])

    def test_invalid_route_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "MESSAGE_ENTRY_INVALID"):
            select_message_entry("task-run")

    def test_public_contract_exposes_one_default_and_two_opt_ins(self):
        self.assertEqual(
            {
                "default_entry": "CHAIN_RECIPE",
                "ordinary_request_tool": "bct_chain_recipe",
                "explicit_only_tools": ["bct_task_message", "bct_send_message"],
                "rule": "Ordinary assigned work uses Chain Recipe. Task Message and Send Message require an explicit user request by name.",
            },
            public_entry_policy(),
        )
