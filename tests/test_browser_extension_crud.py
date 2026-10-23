import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bct.features.browser_extension_manage import BrowserExtensionManageFeature
from bct.core.models import Work, PreconditionError, ConfirmedFailure, Outcome

TM = "dhdgffkkebhmkfjojejmpbldmpobfkfo"
UUID = "68560629-7b17-48eb-b202-bc432403998d"
SHA = "a" * 64
SOURCE = "// ==UserScript==\n// @name Test\n// @match https://example.com/test\n// ==/UserScript==\nconsole.log('test')"


class ExtensionCrudContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "node.exe").write_bytes(b"mock")
        (root / "puppeteer").mkdir()
        (root / "chrome").mkdir()
        self.policy = root / "policy.toml"
        self.policy.write_text(
            '[browser_extension_manage]\nenabled = true\n'
            'profile_root = "' + str(root / "chrome").replace("\\", "\\\\") + '"\n'
            'puppeteer_module = "' + str(root / "puppeteer").replace("\\", "\\\\") + '"\n'
            'node_executable = "' + str(root / "node.exe").replace("\\", "\\\\") + '"\n',
            encoding="utf8",
        )
        manager = Mock()
        self.f = BrowserExtensionManageFeature(manager, policy_path=self.policy, data_root=root)
        self.f.script = root / "runner.cjs"
        self.f.script.write_text("// bounded adapter", encoding="utf8")
        self.work = Work("W", "approved extension management", (str(root),),
                         frozenset({"browser_extension_manage"}), "user")

    def req(self, action, **kwargs):
        return self.f.prepare(work=self.work, arguments={
            "operation": action, "extension_id": TM, **kwargs,
        })

    def test_inventory_and_pages_remain_read_only(self):
        manager = self.f.manager
        manager.generation = 1
        manager.request.return_value = {"content": []}
        q = self.f.prepare(work=self.work, arguments={"operation": "inventory"})
        self.assertEqual("APPLIED", self.f.execute(q).outcome.value)
        manager.request.assert_called_once()

    def test_mutations_require_enabled_policy(self):
        self.policy.write_text("[browser_extension_manage]\nenabled = false\n")
        with self.assertRaisesRegex(PreconditionError, "NOT_ENABLED"):
            self.req("create", expected_count=0, source=SOURCE)

    def test_no_arbitrary_script_evaluation(self):
        with self.assertRaisesRegex(PreconditionError, "NOT_SUPPORTED"):
            self.req("evaluate_script", source="1+1")

    def test_update_requires_exact_sha_and_uuid(self):
        for args in ({"script_uuid": UUID, "source": SOURCE},
                     {"script_uuid": UUID, "source": SOURCE, "expected_sha256": "wrong"}):
            with self.assertRaises(PreconditionError):
                self.req("update", **args)

    def test_delete_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(PreconditionError, "WRITE_ARGUMENTS"):
            self.req("remove", script_uuid=UUID, expected_sha256=SHA)
        q = self.req("remove", script_uuid=UUID, expected_sha256=SHA, confirm_remove=True)
        self.assertEqual(q.arguments["script_uuid"], UUID)

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_typed_create_runs_fixed_bounded_helper(self, run):
        run.return_value = SimpleNamespace(stdout=json.dumps({
            "status": "PASS", "operation": "create", "script_uuid": UUID, "sha256": SHA, "verified": True,
        }), returncode=0)
        request = self.req("create", expected_count=0, source=SOURCE)
        result = self.f.execute(request)
        self.assertEqual(result.outcome, Outcome.APPLIED)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 90)
        self.assertEqual(json.loads(kwargs["input"])["extension_id"], TM)
        self.assertEqual(json.loads(kwargs["input"])["source"], SOURCE)
        self.assertTrue(kwargs["capture_output"])

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_uncertain_effect_is_not_a_confirmed_failure(self, run):
        run.return_value = SimpleNamespace(stdout=json.dumps({
            "status": "ERROR", "effect_started": True, "code": "DELETE_RESULT_UNKNOWN"
        }), returncode=0)
        request = self.req("remove", script_uuid=UUID, expected_sha256=SHA, confirm_remove=True)
        with self.assertRaisesRegex(RuntimeError, "UNCERTAIN"):
            self.f.execute(request)

    @patch("bct.features.browser_extension_manage.subprocess.run")
    def test_pre_effect_failure_is_confirmed(self, run):
        run.return_value = SimpleNamespace(stdout=json.dumps({
            "status": "ERROR", "effect_started": False, "code": "SCRIPT_UUID_NOT_FOUND"
        }), returncode=0)
        request = self.req("remove", script_uuid=UUID, expected_sha256=SHA, confirm_remove=True)
        with self.assertRaises(ConfirmedFailure):
            self.f.execute(request)


if __name__ == "__main__":
    unittest.main()
