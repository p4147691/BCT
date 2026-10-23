"""Configuration-only MCP registry and read-only extension-management tests."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from bct.mcp_server import build_mcp
from bct.features.browser_extension_manage import BrowserExtensionManageFeature
from bct.core.models import PreconditionError, Work


class DummyResult:
    def as_dict(self):
        return {"state": "FINISHED", "outcome": "APPLIED"}


class DummyOperations:
    capabilities = ("read", "browser_extension_manage")

    def run(self, **kwargs):
        return DummyResult()


class CatalogueSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.tmp.name) / "mcp_tools.toml"
        self.server = build_mcp(SimpleNamespace(
            operations=DummyOperations(), mcp_catalogue_path=self.path
        ))

    async def _cleanup(self):
        self.tmp.cleanup()

    async def names(self):
        return {t.name: t for t in await self.server.list_tools()}

    async def test_default_catalogue_has_new_named_tool(self):
        names = await self.names()
        self.assertIn("bct_browser_extension_manage", names)
        self.assertIn("bct_status", names)

    async def test_settings_hide_and_restore_without_recreating_server(self):
        self.path.write_text(
            '[tools.bct_browser_extension_manage]\nenabled = false\n',
            encoding="utf-8",
        )
        self.assertNotIn("bct_browser_extension_manage", await self.names())
        # Even direct calls cannot invoke a tool hidden since the last refresh.
        with self.assertRaises((ValueError, KeyError, ToolError)):
            await self.server.call_tool(
                "bct_browser_extension_manage",
                {"work_id": "W", "operation_id": "O", "arguments": {}},
            )
        self.path.write_text(
            '[tools.bct_browser_extension_manage]\nenabled = true\n'
            'description = "Chrome 확장 목록 조회 (읽기 전용)"\n',
            encoding="utf-8",
        )
        names = await self.names()
        self.assertIn("bct_browser_extension_manage", names)
        self.assertIn("읽기 전용", names["bct_browser_extension_manage"].description)

    async def test_client_tools_list_sees_runtime_config_refresh(self):
        # Real MCP protocol over memory streams, no HTTP or browser side effects.
        async with create_connected_server_and_client_session(self.server) as client:
            before = {t.name for t in (await client.list_tools()).tools}
            self.assertIn("bct_browser_extension_manage", before)
            self.path.write_text(
                '[tools.bct_browser_extension_manage]\nenabled = false\n',
                encoding="utf-8",
            )
            hidden = {t.name for t in (await client.list_tools()).tools}
            self.assertNotIn("bct_browser_extension_manage", hidden)
            self.path.write_text(
                '[tools.bct_browser_extension_manage]\nenabled = true\n',
                encoding="utf-8",
            )
            after = {t.name for t in (await client.list_tools()).tools}
            self.assertIn("bct_browser_extension_manage", after)

    async def test_invalid_settings_fail_closed_and_keep_last_good_catalogue(self):
        original = await self.names()
        self.path.write_text(
            '[tools.bct_status]\nenabled = false\n', encoding="utf-8",
        )
        names = await self.names()
        self.assertEqual(set(original), set(names))
        self.assertIn("MANDATORY_TOOL", self.server.catalogue_settings.last_error)
        self.assertEqual(set(original), set(self.server._tool_manager._tools))

    async def test_cannot_invent_new_abilities_through_config(self):
        await self.names()
        self.path.write_text(
            '[tools.bct_arbitrary_eval]\nenabled = true\n',
            encoding="utf-8",
        )
        names = await self.names()
        self.assertIn("bct_browser_extension_manage", names)
        self.assertIn("UNREGISTERED_TOOL", self.server.catalogue_settings.last_error)

    async def test_description_change_keeps_same_argument_schema(self):
        initial = (await self.names())["bct_browser_extension_manage"].inputSchema
        self.path.write_text(
            '[tools.bct_browser_extension_manage]\n'
            'description = "Configured title"\n', encoding="utf-8",
        )
        changed = (await self.names())["bct_browser_extension_manage"]
        self.assertEqual(initial, changed.inputSchema)
        self.assertEqual("Configured title", changed.description)


class BrowserExtensionReadFeatureTests(unittest.TestCase):
    def test_inventory_is_read_only_and_work_fenced(self):
        manager = Mock()
        manager.generation = 3
        manager.request.return_value = {
            "content": [{"type": "text", "text": "## Extensions\n"}]
        }
        feature = BrowserExtensionManageFeature(manager)
        work = Work("W", "inspect extensions", ("/tmp",),
                    frozenset({"browser_extension_manage"}), "user")
        request = feature.prepare(work=work, arguments={"operation": "inventory"})
        result = feature.execute(request)
        self.assertEqual(result.outcome.value, "APPLIED")
        self.assertEqual(result.evidence["operation"], "inventory")
        manager.request.assert_called_once_with("tools/call", {
            "name": "list_extensions", "arguments": {},
        })

    def test_mutations_rejected_before_connection(self):
        manager = Mock()
        feature = BrowserExtensionManageFeature(manager)
        work = Work("W", "inspect", ("/tmp",),
                    frozenset({"browser_extension_manage"}), "user")
        for operation in ("create", "update", "delete", "evaluate_script"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(PreconditionError, "NOT_ENABLED|NOT_SUPPORTED"):
                    feature.prepare(work=work, arguments={"operation": operation})
        manager.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
