import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from bct.runtime_server import run_monitor_tools_refresh


class MonitorToolsRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Mock()
        self.store.get_work.side_effect = KeyError()
        self.operations = Mock()
        self.operations.run.return_value.as_dict.return_value = {
            "outcome": "APPLIED", "evidence": {"client_catalog_verified": False},
        }
        self.bct = SimpleNamespace(store=self.store, operations=self.operations)

    def test_routes_only_fixed_public_operation(self):
        result = run_monitor_tools_refresh(self.bct, runtime_root=self.root,
                                          payload={"operation_id": "refresh-1"})
        args = self.operations.run.call_args.kwargs
        self.assertEqual("browser_extension_manage", args["capability"])
        self.assertEqual({"operation": "refresh_tools", "target": "bct_control"}, args["arguments"])
        self.assertFalse(result["evidence"]["client_catalog_verified"])
        self.assertEqual("refresh-1", args["operation_id"])
        self.store.create_work.assert_called_once()

    def test_rejects_caller_url_js_plugin_or_tab(self):
        for key in ("url", "javascript", "plugin_id", "tab_id", "target"):
            with self.assertRaises(ValueError):
                run_monitor_tools_refresh(self.bct, runtime_root=self.root,
                    payload={"operation_id": "refresh-1", key: "wrong"})
        self.operations.run.assert_not_called()

    def test_existing_work_mismatch_fails_closed(self):
        self.store.get_work.side_effect = None
        self.store.get_work.return_value = object()
        with self.assertRaisesRegex(ValueError, "WORK_MISMATCH"):
            run_monitor_tools_refresh(self.bct, runtime_root=self.root,
                                      payload={"operation_id": "refresh-1"})
        self.operations.run.assert_not_called()
