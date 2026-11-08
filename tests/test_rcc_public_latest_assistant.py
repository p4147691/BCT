from __future__ import annotations

import unittest
import json
from types import SimpleNamespace

from bct.mcp_server import build_mcp


class Receipt:
    def as_dict(self):
        return {"state": "FINISHED", "outcome": "APPLIED", "operation_id": "op"}


class Operations:
    capabilities = ("browser",)
    def __init__(self):
        self.calls = []
    def run(self, **kwargs):
        self.calls.append(kwargs)
        return Receipt()


class PublicReadLatestAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.operations = Operations()
        self.server = build_mcp(SimpleNamespace(operations=self.operations))
        self.args = {
            "work_id": "W", "operation_id": "op", "instance_id": "instance",
            "session_id": "a" * 32, "tab_id": 17, "window_id": 21,
            "conversation_key": "12345678-1234-1234-1234-123456789abc",
        }

    async def test_exact_read_is_a_direct_public_browser_command(self):
        tools = {t.name for t in await self.server.list_tools()}
        self.assertIn("bct_browser", tools)
        await self.server.call_tool("bct_browser", {
            "work_id": self.args["work_id"], "operation_id": self.args["operation_id"],
            "arguments": {
                "command": "read-latest-assistant",
                "instance_id": self.args["instance_id"],
                "session_id": self.args["session_id"], "tab_id": self.args["tab_id"],
                "window_id": self.args["window_id"],
                "conversation_key": self.args["conversation_key"],
            },
        })
        self.assertEqual(len(self.operations.calls), 1)
        call = self.operations.calls[0]
        self.assertEqual(call["capability"], "browser")
        self.assertEqual(call["work_id"], "W")
        self.assertEqual(call["operation_id"], "op")
        self.assertIsNone(call["approval_ref"])
        self.assertEqual(call["arguments"], {
            "command": "read-latest-assistant", "instance_id": "instance",
            "session_id": "a" * 32, "tab_id": 17, "window_id": 21,
            "conversation_key": "12345678-1234-1234-1234-123456789abc",
        })

    async def test_generic_browser_passes_identity_to_the_rcc_feature(self):
        for field, value in (
            ("session_id", "invalid"), ("conversation_key", "shared-link"),
            ("tab_id", 0), ("tab_id", True), ("window_id", -1),
        ):
            with self.subTest(field=field, value=value):
                arguments = {key: value for key, value in self.args.items()
                             if key not in {"work_id", "operation_id"}}
                arguments[field] = value
                await self.server.call_tool("bct_browser", {
                    "work_id": self.args["work_id"], "operation_id": self.args["operation_id"],
                    "arguments": {"command": "read-latest-assistant", **arguments},
                })
        self.assertEqual(len(self.operations.calls), 5)

    async def test_work_confirmation_failure_has_no_fallback_or_replay(self):
        def deny(**kwargs):
            self.operations.calls.append(kwargs)
            raise PermissionError("WORK_SCOPE_DENIED")
        self.operations.run = deny
        with self.assertRaises(Exception):
            await self.server.call_tool("bct_browser", {
                "work_id": self.args["work_id"], "operation_id": self.args["operation_id"],
                "arguments": {"command": "read-latest-assistant", **{
                    key: value for key, value in self.args.items()
                    if key not in {"work_id", "operation_id"}
                }},
            })
        self.assertEqual(len(self.operations.calls), 1)

    async def test_generic_browser_exposes_rcc_catalogue_without_bypassing_validation(self):
        catalogue = await self.server.call_tool("bct_rcc_command_catalog", {})
        catalogue_value = json.loads(catalogue[0][0].text)
        self.assertIn({"command": "send", "category": "effect"}, catalogue_value["commands"])
        self.assertIn({"command": "read-latest-assistant", "category": "read"}, catalogue_value["commands"])
        self.assertIn({"command": "new-chat-send", "category": "effect"}, catalogue_value["commands"])
        self.assertIn({"command": "conversation-bind", "category": "effect"}, catalogue_value["commands"])
        tools = {t.name for t in await self.server.list_tools()}
        self.assertIn("bct_rcc_command_catalog", tools)
        self.assertIn("bct_rcc_recipe_catalog", tools)
        self.assertIn("bct_browser", tools)
        await self.server.call_tool("bct_browser", {
            "work_id": "W", "operation_id": "generic-read",
            "arguments": {"command": "state", "instance_id": "instance"},
        })
        self.assertEqual(self.operations.calls[-1]["arguments"]["command"], "state")

    async def test_recipe_catalog_names_direct_browser_steps(self):
        recipes = await self.server.call_tool("bct_rcc_recipe_catalog", {})
        value = json.loads(recipes[0][0].text)
        by_name = {item["recipe"]: item for item in value["recipes"]}
        self.assertEqual(
            by_name["read-latest-assistant"]["steps"],
            ["state", "read-latest-assistant"],
        )
        self.assertEqual(
            by_name["create-chat-and-send"]["steps"],
            ["target-discover", "new-chat-send", "result"],
        )
        self.assertEqual(
            by_name["bind-existing-conversation"]["steps"],
            ["state", "tab-get", "conversation-bind"],
        )
        self.assertIn("reconcile-send", by_name["recover-unknown-send"]["steps"])


if __name__ == "__main__":
    unittest.main()
