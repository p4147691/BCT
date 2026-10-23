"""CDP integration contract and runtime safety tests; no real Chrome access."""
from __future__ import annotations

import concurrent.futures
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bct.core.models import AuthorizationError, Principal, PreconditionError
from bct.integrations.cdp_connection import CDPConnectionManager
from bct.service import BCT


_FAKE_MCP = (
    "import sys,json\n"
    "for line in sys.stdin:\n"
    " m=json.loads(line)\n"
    " if 'id' in m:\n"
    "  payload={'jsonrpc':'2.0','id':m['id'],'result':"
    "{'content':[{'type':'text','text':m['method']}]}}\n"
    "  print(json.dumps(payload),flush=True)\n"
)


class CDPRegistrationTests(unittest.TestCase):
    def test_configuration_fails_closed_without_launch(self):
        manager = CDPConnectionManager()
        self.assertFalse(manager.connected)
        with self.assertRaisesRegex(RuntimeError, "NOT_CONFIGURED"):
            manager.request("tools/list")
        manager.configure((sys.executable, "-u", "-c", _FAKE_MCP))
        manager.configure((sys.executable, "-u", "-c", _FAKE_MCP))
        with self.assertRaisesRegex(RuntimeError, "ALREADY_CONFIGURED"):
            manager.configure(("not-the-configured-program",))
        self.assertFalse(manager.connected)
        manager.close()

    def test_mutation_and_injected_args_denied_before_spawn(self):
        manager = CDPConnectionManager()
        manager.configure(("nonexistent-command",))
        for method, params in [
            ("tools/call", {"name": "new_page", "arguments": {}}),
            ("tools/call", {"name": "evaluate_script", "arguments": {}}),
            ("tools/call", {"name": "list_pages", "arguments": {"hidden": True}}),
            ("tools/list", {"unexpected": True}),
        ]:
            with self.subTest(method=method, params=params):
                with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
                    manager.request(method, params)
        self.assertFalse(manager.connected)
        manager.close()

    def test_connection_reuse_and_concurrent_queries(self):
        manager = CDPConnectionManager()
        manager.configure((sys.executable, "-u", "-c", _FAKE_MCP))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(
                    lambda _: manager.request("tools/call", {
                        "name": "list_pages", "arguments": {}
                    }), range(10)))
            self.assertEqual(len(results), 10)
            self.assertTrue(all("tools/call" in str(item) for item in results))
            self.assertEqual(manager.generation, 1)
            self.assertTrue(manager.connected)
        finally:
            manager.close()
        self.assertFalse(manager.connected)

    def test_close_and_reconfigure_without_launch(self):
        manager = CDPConnectionManager()
        manager.configure(("example-mcp",))
        manager.close()
        manager.configure(("another-mcp",))
        self.assertFalse(manager.connected)
        manager.close()

    def test_core_feature_registered_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as root:
            policy = Path(root) / "bct.toml"
            config = Path("bct.toml").read_text(encoding="utf-8")
            policy.write_text(config.replace("[cdp]" + chr(10) + "enabled = true", "[cdp]" + chr(10) + "enabled = false"), encoding="utf-8")
            bct = BCT(state_path=Path(root) / "test.sqlite",
                      policy_path=policy)
            try:
                self.assertIn("cdp_inspect", bct.operations.capabilities)
                self.assertFalse(bct.cdp_connections.connected)
                with self.assertRaisesRegex(RuntimeError, "NOT_CONFIGURED"):
                    bct.cdp_connections.request("tools/list")
            finally:
                bct.cdp_connections.close()

    def test_work_policy_controls_cdpx_reads(self):
        with tempfile.TemporaryDirectory() as root:
            bct = BCT(state_path=Path(root) / "test.sqlite",
                      policy_path=Path("bct.toml"))
            try:
                principal = Principal("cdp-test-user", "test",
                    frozenset(bct.operations.capabilities))
                bct.create_work(work_id="cdp-authorized-work", request_summary="test",
                    roots=[root], actions=["cdp_inspect"], principal=principal)
                with patch.object(bct.cdp_connections, "request",
                    return_value={"content": [{"type": "text", "text": "tab"}]}) as mock:
                    receipt = bct.operations.run(
                        principal=principal, work_id="cdp-authorized-work",
                        operation_id="cdp-inspect-read-01",
                        capability="cdp_inspect", arguments={"operation": "list_pages"})
                    self.assertEqual(receipt.outcome.value, "APPLIED")
                    self.assertEqual(receipt.output["result"]["content"][0]["text"], "tab")
                    self.assertEqual(receipt.evidence["operation"], "list_pages")
                    mock.assert_called_once_with("tools/call", {
                        "name": "list_pages", "arguments": {}})
                with self.assertRaises(PreconditionError):
                    bct.operations.run(
                        principal=principal, work_id="cdp-authorized-work",
                        operation_id="cdp-inspect-mutation-rejected",
                        capability="cdp_inspect", arguments={"operation": "send"})
                bct.create_work(work_id="cdp-no-permission-work",
                    request_summary="no cdp", roots=[root], actions=["read"],
                    principal=principal)
                with self.assertRaises(AuthorizationError):
                    bct.operations.run(
                        principal=principal, work_id="cdp-no-permission-work",
                        operation_id="cdp-denied-01", capability="cdp_inspect",
                        arguments={"operation": "list_pages"})
            finally:
                bct.cdp_connections.close()


if __name__ == "__main__":
    unittest.main()
