from __future__ import annotations

import unittest
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

    async def test_exact_read_uses_existing_work_operation_confirmation(self):
        tools = {t.name for t in await self.server.list_tools()}
        self.assertIn("bct_rcc_read_latest_assistant", tools)
        await self.server.call_tool("bct_rcc_read_latest_assistant", self.args)
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

    async def test_invalid_identity_fails_before_operation(self):
        for field, value in (
            ("session_id", "invalid"), ("conversation_key", "shared-link"),
            ("tab_id", 0), ("tab_id", True), ("window_id", -1),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(Exception):
                    await self.server.call_tool(
                        "bct_rcc_read_latest_assistant", {**self.args, field: value})
        self.assertEqual(self.operations.calls, [])

    async def test_work_confirmation_failure_has_no_fallback_or_replay(self):
        def deny(**kwargs):
            self.operations.calls.append(kwargs)
            raise PermissionError("WORK_SCOPE_DENIED")
        self.operations.run = deny
        with self.assertRaises(Exception):
            await self.server.call_tool("bct_rcc_read_latest_assistant", self.args)
        self.assertEqual(len(self.operations.calls), 1)

    async def test_sealed_generic_browser_command_remains_sealed(self):
        from bct.mcp_server import _SEALED_BROWSER_COMMANDS
        self.assertIn("read-latest-assistant", _SEALED_BROWSER_COMMANDS)
        self.assertIn("reconcile-send", _SEALED_BROWSER_COMMANDS)
        self.assertIn("delivery-cancel", _SEALED_BROWSER_COMMANDS)


if __name__ == "__main__":
    unittest.main()
