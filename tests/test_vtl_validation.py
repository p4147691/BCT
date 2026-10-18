from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Outcome, PreconditionError, Work
from bct.features.vtl import VtlValidateFeature, _decode_process_output, _default_runner


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VtlValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.scenario = self.project / "scenario.json"
        self.scenario.write_text('{"actions": []}\n', encoding="utf-8")
        self.sha = "1" * 40
        self.runtime_root = self.root / "vtl"
        self.release = self.runtime_root / "releases" / self.sha
        files = {
            "vtl.ps1": "param()\n",
            "core/Invoke-VtlRun.ps1": "param()\n",
            "core/Test-VtlProfile.ps1": "param()\n",
            "drivers/browser-playwright/Invoke-VtlBrowserPlaywright.ps1": "param()\n",
        }
        manifest_files = {}
        for relative, content in files.items():
            path = self.release / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            manifest_files[relative] = _sha(path)
        self.manifest = self.release / "release-manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1,
            "source_repository": "p4147691/VIRTUAL-TEST-LAB",
            "source_sha": self.sha,
            "files": manifest_files,
        }), encoding="utf-8")
        self.pointer = self.runtime_root / "current.json"
        self.pointer.write_text(json.dumps({
            "schema_version": 1,
            "source_repository": "p4147691/VIRTUAL-TEST-LAB",
            "source_sha": self.sha,
            "release_path": str(self.release),
            "manifest_path": str(self.manifest),
            "manifest_sha256": _sha(self.manifest),
        }), encoding="utf-8")
        self.evidence = self.root / "evidence"
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            "[policy]\nnormal_actions=['vtl_validate']\napproval_actions=[]\n\n"
            "[vtl]\n"
            f"current_pointer={json.dumps(str(self.pointer))}\n"
            f"evidence_root={json.dumps(str(self.evidence))}\n",
            encoding="utf-8",
        )
        self.work = Work(
            "vtl-test-work", "validate through VTL", (str(self.project),),
            frozenset({"vtl_validate"}), "test-principal",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_process_output_decoder_accepts_utf8_and_korean_legacy_bytes(self):
        value = "사용자\\게임"
        self.assertEqual(value, _decode_process_output(value.encode("utf-8")))
        self.assertEqual(value, _decode_process_output(value.encode("cp949")))

    def test_process_output_decoder_accepts_unicode_bom_streams(self):
        value = "사용자\\게임"
        self.assertEqual(value, _decode_process_output(value.encode("utf-16")))
        self.assertEqual(value, _decode_process_output(value.encode("utf-32")))

    @patch("bct.features.vtl.subprocess.Popen")
    def test_default_runner_captures_bytes_and_decodes_mixed_windows_output(self, popen):
        process = popen.return_value
        process.communicate.return_value = (
            "UTF-8 사용자".encode("utf-8"),
            "CP949 게임".encode("cp949"),
        )
        process.returncode = 0

        result = _default_runner(["powershell.exe", "-File", "test.ps1"], self.root, 5)

        self.assertEqual("UTF-8 사용자", result["stdout"])
        self.assertEqual("CP949 게임", result["stderr"])
        self.assertIsInstance(popen.call_args.kwargs["env"], dict)
        self.assertEqual("1", popen.call_args.kwargs["env"]["PYTHONUTF8"])
        self.assertEqual("utf-8", popen.call_args.kwargs["env"]["PYTHONIOENCODING"])
        self.assertNotIn("text", popen.call_args.kwargs)

    @staticmethod
    def _result_runner(status: str):
        def run(argv: list[str], _cwd: Path, _timeout: float):
            if "-Evidence" in argv:
                result_path = Path(argv[argv.index("-Evidence") + 1]) / "result.json"
            else:
                root = Path(argv[argv.index("-EvidenceRoot") + 1])
                run_id = argv[argv.index("-RunId") + 1]
                result_path = root / run_id / "output" / "result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps({"version": 1, "status": status}), encoding="utf-8")
            return {
                "returncode": 0 if status == "PASS" else 1,
                "stdout": "completed",
                "stderr": "",
                "timed_out": False,
                "duration_ms": 12,
            }
        return run

    def test_browser_fast_returns_pass_with_exact_runtime_evidence(self):
        feature = VtlValidateFeature(self.policy, runner=self._result_runner("PASS"))
        request = replace(feature.prepare(work=self.work, arguments={
            "operation": "browser",
            "scenario_path": str(self.scenario),
            "mode": "Fast",
            "timeout_s": 30,
        }), operation_id="vtl-browser-pass")
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("PASS", result.evidence["status"])
        self.assertEqual(self.sha, result.evidence["vtl_sha"])
        self.assertTrue(Path(result.evidence["result_path"]).is_file())

    def test_validation_failure_is_an_applied_fail_result(self):
        feature = VtlValidateFeature(self.policy, runner=self._result_runner("FAIL"))
        request = replace(feature.prepare(work=self.work, arguments={
            "operation": "browser", "scenario_path": str(self.scenario),
        }), operation_id="vtl-browser-fail")
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("FAIL", result.evidence["status"])

    def test_profile_source_must_stay_inside_work_scope(self):
        outside = self.root / "outside"
        outside.mkdir()
        profile = self.project / "virtual-test.json"
        profile.write_text(json.dumps({
            "version": 1, "project": "bad", "backend": "sandbox",
            "source_path": str(outside), "sandbox": {"networking": False},
        }), encoding="utf-8")
        feature = VtlValidateFeature(self.policy, runner=self._result_runner("PASS"))
        with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
            feature.prepare(work=self.work, arguments={
                "operation": "profile", "profile_path": str(profile),
                "scenario_path": str(self.scenario),
            })

    def test_tampered_runtime_is_rejected_before_dispatch(self):
        (self.release / "vtl.ps1").write_text("tampered\n", encoding="utf-8")
        feature = VtlValidateFeature(self.policy, runner=self._result_runner("PASS"))
        with self.assertRaisesRegex(PreconditionError, "VTL_RELEASE_FILE_HASH_MISMATCH"):
            feature.prepare(work=self.work, arguments={
                "operation": "browser", "scenario_path": str(self.scenario),
            })

    def test_profile_run_uses_external_operation_evidence(self):
        profile = self.project / "virtual-test.json"
        profile.write_text(json.dumps({
            "version": 1, "project": "sample", "backend": "sandbox",
            "source_path": str(self.project), "sandbox": {"networking": False},
        }), encoding="utf-8")
        feature = VtlValidateFeature(self.policy, runner=self._result_runner("PASS"))
        request = replace(feature.prepare(work=self.work, arguments={
            "operation": "profile", "profile_path": str(profile),
            "scenario_path": str(self.scenario), "timeout_s": 30,
        }), operation_id="vtl-profile-pass")
        result = feature.execute(request)
        self.assertEqual("PASS", result.evidence["status"])
        # The feature canonicalizes configured paths.  GitHub's Windows runner can
        # expose the temp directory through a short/long path alias, so compare
        # canonical paths instead of their original spellings.
        self.assertTrue(
            Path(result.evidence["result_path"]).resolve().is_relative_to(
                self.evidence.resolve()
            )
        )


if __name__ == "__main__":
    unittest.main()
