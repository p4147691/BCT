import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_browser_extension_crud as fixtures
from bct.core.models import ConfirmedFailure, PreconditionError, Outcome


class ToolsRefreshTests(unittest.TestCase):
    def setUp(self):
        fixtures.ExtensionCrudContractTests.setUp(self)
        self.f.script.with_name("chatgpt_tools_refresh.cjs").write_text("// test adapter")

    def refresh_request(self, **extra):
        return self.f.prepare(work=self.work, arguments={
            "operation": "refresh_tools", "target": "bct_control", **extra,
        })

    def test_exact_target_and_arguments(self):
        q = self.refresh_request()
        self.assertEqual("chatgpt-plugin:bct-control", q.target)
        self.assertTrue(q.preconditions["mutating"])
        for extra in ({"target": "other"}, {"url": "https://example.com"},
                      {"javascript": "1+1"}, {"plugin_id": "another"}):
            with self.assertRaises(PreconditionError):
                self.refresh_request(**extra)

    def test_refresh_requires_existing_enabled_policy(self):
        self.policy.write_text("[browser_extension_manage]\nenabled = false\n")
        with self.assertRaises(PreconditionError):
            self.refresh_request()

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_refresh_click_is_not_catalogue_verification(self, run):
        run.return_value = SimpleNamespace(stdout=json.dumps({
            "status": "PASS", "operation": "refresh_tools", "target": "bct_control",
            "click_dispatched": True, "owned_tab_closed": True,
            "client_catalog_verified": False,
        }), returncode=0)
        result = self.f.execute(self.refresh_request())
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertFalse(result.evidence["client_catalog_verified"])
        self.assertTrue(run.call_args.args[0][1].endswith("chatgpt_tools_refresh.cjs"))

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_refresh_invalid_receipt_is_unknown(self, run):
        run.return_value = SimpleNamespace(stdout='{"status":"PASS"}', returncode=0)
        with self.assertRaisesRegex(RuntimeError, "RESULT_UNCERTAIN"):
            self.f.execute(self.refresh_request())

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_refresh_timeout_is_unknown(self, run):
        run.side_effect = subprocess.TimeoutExpired("adapter", 90)
        with self.assertRaisesRegex(RuntimeError, "UNCERTAIN"):
            self.f.execute(self.refresh_request())

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_refresh_preclick_failure_does_not_retry(self, run):
        run.return_value = SimpleNamespace(stdout=json.dumps({
            "status": "ERROR", "effect_started": False,
            "code": "PLUGIN_HEADING_NOT_UNIQUE",
        }), returncode=0)
        with self.assertRaises(ConfirmedFailure):
            self.f.execute(self.refresh_request())
        run.assert_called_once()
