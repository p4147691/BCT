from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import (
    FeatureRequest, FeatureResult, Outcome, PreconditionError,
    UnknownEffectError, Work,
)
from bct.features.owned_extension_action import OwnedExtensionActionFeature


class FakeBrowser:
    def __init__(self):
        self.executed = None

    def prepare(self, *, work, arguments):
        if arguments["command"] != "reload-extension":
            raise AssertionError(arguments)
        return FeatureRequest(
            "browser", "rcc:" + str(arguments["instance_id"]),
            {
                "command": "reload-extension",
                "instance_id": str(arguments["instance_id"]),
                "timeout_s": 10.0,
                "to": "", "text": "", "extra": {},
            },
            ("rcc-instance:" + str(arguments["instance_id"]) + ":maintenance:reload-extension",),
            {"mutating": True},
        )

    def execute(self, request):
        self.executed = request
        return FeatureResult(
            Outcome.APPLIED,
            {"command": "reload-extension", "session_id": "next-session"},
            output={"result": {"reloading": True}},
        )


class OwnedExtensionActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        live = self.root / "monitor-live"
        (live / "extension").mkdir(parents=True)
        (live / "tools").mkdir()
        source_manifest = (
            Path(__file__).resolve().parents[1]
            / "modules" / "monitor" / "extension" / "manifest.json"
        )
        (live / "extension" / "manifest.json").write_text(
            source_manifest.read_text(encoding="utf-8-sig"), encoding="utf-8"
        )
        (live / "tools" / "Request-MonitorDeploymentCheck.ps1").write_text(
            "param([int]$TimeoutSeconds = 15)\n", encoding="utf-8"
        )
        (self.root / "puppeteer").mkdir()
        (self.root / "node.exe").write_bytes(b"node")
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            "[monitor]\nlive_root = " + json.dumps(str(live)) + "\n"
            "[browser_extension_manage]\nenabled = true\n"
            "profile_root = " + json.dumps(str(self.root)) + "\n"
            "puppeteer_module = " + json.dumps(str(self.root / "puppeteer")) + "\n"
            "node_executable = " + json.dumps(str(self.root / "node.exe")) + "\n",
            encoding="utf-8",
        )
        self.browser = FakeBrowser()
        self.feature = OwnedExtensionActionFeature(self.browser, policy_path=self.policy)
        self.work = Work(
            "work", "owned extension test", (str(self.root),),
            frozenset({"owned_extension_action"}), "owner",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_public_contract_rejects_arbitrary_browser_inputs(self):
        forbidden = ("url", "extension_id", "javascript", "method", "function", "command")
        for name in forbidden:
            with self.subTest(name=name), self.assertRaises(PreconditionError):
                self.feature.prepare(
                    work=self.work,
                    arguments={"target": "monitor", "action": "reload", name: "x"},
                )
        with self.assertRaises(PreconditionError):
            self.feature.prepare(
                work=self.work, arguments={"target": "monitor", "action": "run"}
            )

    def test_rcc_routes_only_exact_reload_contract(self):
        request = self.feature.prepare(
            work=self.work,
            arguments={"target": "rcc", "action": "reload", "instance_id": "instance123"},
        )
        request = FeatureRequest(
            request.capability, request.target, request.arguments, request.resources,
            request.preconditions, "owned-reload-1",
        )
        result = self.feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("browser", self.browser.executed.capability)
        self.assertEqual("owned-reload-1", self.browser.executed.operation_id)
        self.assertEqual("reload-extension", self.browser.executed.arguments["command"])
        self.assertEqual("rcc", result.evidence["target"])

    @patch("bct.features.owned_extension_action.subprocess.run")
    def test_monitor_requires_ack_and_verified_runtime(self, run):
        request = self.feature.prepare(
            work=self.work, arguments={"target": "monitor", "action": "reload"}
        )
        token_path = self.root / "monitor-live" / "extension" / ".reload-token"
        telemetry_path = self.root / "DesktopWindowMonitor" / "shared-runtime.json"
        def dispatch(*args, **kwargs):
            token = token_path.read_text(encoding="utf-8-sig").strip()
            (token_path.parent / ".reload-ack").write_text(token, encoding="utf-8")
            telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            telemetry_path.write_text(json.dumps({"__MONITOR_INSTANCE__:GOOGLE": {
                "label": json.dumps({
                    "manifest_version": request.arguments["version"],
                    "reload_token": token,
                    "seen_at_ms": 9999999999999,
                })
            }}), encoding="utf-8")
            return subprocess.CompletedProcess(
                [], 0, stdout='{"status":"PASS","effect_started":true,"queued":true}', stderr="",
            )
        run.side_effect = dispatch
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            result = self.feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertTrue(result.evidence["reload_ack"])
        dispatch_input = json.loads(run.call_args.kwargs["input"])
        self.assertEqual({"profile_root", "puppeteer_module"}, set(dispatch_input))

    @patch("bct.features.owned_extension_action.time.sleep", return_value=None)
    @patch("bct.features.owned_extension_action.time.monotonic", side_effect=[0.0, 31.0])
    @patch("bct.features.owned_extension_action.subprocess.run")
    def test_monitor_ack_timeout_is_unknown_and_not_retryable(self, run, monotonic, sleep):
        request = self.feature.prepare(
            work=self.work, arguments={"target": "monitor", "action": "reload"}
        )
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout='{"status":"PASS","effect_started":true,"queued":true}', stderr="",
        )
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            with self.assertRaises(UnknownEffectError):
                self.feature.execute(request)


if __name__ == "__main__":
    unittest.main()
