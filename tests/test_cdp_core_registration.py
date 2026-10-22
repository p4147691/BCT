import asyncio
import unittest
from bct.integrations.cdp_connection import CDPConnectionManager
from bct.service import BCT


class CDPRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lazy_manager_and_config_guard(self):
        manager = CDPConnectionManager()
        self.assertFalse(manager.connected)
        with self.assertRaisesRegex(RuntimeError, "NOT_CONFIGURED"):
            await manager.request("tools/list")
        manager.configure(("example-mcp", "--autoConnect"))
        manager.configure(("example-mcp", "--autoConnect"))
        with self.assertRaisesRegex(RuntimeError, "ALREADY_CONFIGURED"):
            manager.configure(("another-mcp",))
        self.assertFalse(manager.connected)
        await manager.close()

    async def test_mutation_is_denied_without_starting_process(self):
        manager = CDPConnectionManager()
        manager.configure(("nonexistent-mcp",))
        with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
            await manager.request("tools/call", {"name": "new_page", "arguments": {}})
        with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
            await manager.request("tools/call", {"name": "evaluate_script", "arguments": {}})
        with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
            await manager.request("tools/call", {"name": "list_pages", "arguments": {"extra": True}})
        self.assertFalse(manager.connected)
        await manager.close()

    async def test_close_and_reconfigure(self):
        manager = CDPConnectionManager()
        manager.configure(("example-mcp",))
        await manager.close()
        manager.configure(("second-mcp",))
        self.assertFalse(manager.connected)
        await manager.close()

    def test_core_registration_available_without_launch(self):
        # BCT's Core constructor provides a lazy CDP holder per Core instance.
        import inspect
        source = inspect.getsource(BCT.__init__)
        self.assertIn("self.cdp_connections = CDPConnectionManager()", source)
