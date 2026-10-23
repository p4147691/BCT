from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.relay_settings import (
    preview_relay_control,
    propose_relay_control_patch,
    propose_relay_settings_patch,
    read_relay_control,
    read_relay_settings,
)


SCOPE = "network.test"


def control_profile():
    return {
        "version": 1,
        "enabled": False,
        "variables": {
            "message_template": "한국어 ${task}\n두 번째 줄 📦",
        },
        "functions": {
            "compose.worker": {
                "driver": "message",
                "call": "compose.worker",
                "effect": "pure",
                "arguments": {"template": "${message_template}"},
                "timeout_seconds": 5,
            },
            "submit.rcc": {
                "driver": "rcc",
                "call": "delivery.start",
                "effect": "external",
                "arguments": {"text": "${worker_message.text}"},
                "timeout_seconds": 30,
            },
            "submit.api": {
                "driver": "chrome_api",
                "call": "tabs.sendMessage",
                "effect": "external",
                "arguments": {"text": "${worker_message.text}"},
                "timeout_seconds": 30,
            },
            "observe.reply": {
                "driver": "cdp",
                "call": "evaluate.reply_state",
                "effect": "read",
                "arguments": {},
                "timeout_seconds": 15,
            },
        },
        "routes": {
            "roundtrip.rcc": {
                "description": "RCC 제출 뒤 CDP로 응답 상태를 관찰하는 예시",
                "entry": "compose",
                "max_steps": 40,
                "steps": {
                    "compose": {
                        "use": "compose.worker",
                        "save_as": "worker_message",
                        "next": {"APPLIED": "submit"},
                    },
                    "submit": {
                        "use": "submit.rcc",
                        "next": {"APPLIED": "observe", "UNKNOWN": "END"},
                    },
                    "observe": {
                        "use": "observe.reply",
                        "guard": {"until": "${reply.complete}"},
                        "next": {"PENDING": "observe", "APPLIED": "END"},
                    },
                },
            },
            "roundtrip.api": {
                "entry": "compose",
                "max_steps": 40,
                "steps": {
                    "compose": {
                        "use": "compose.worker",
                        "save_as": "worker_message",
                        "next": {"APPLIED": "submit"},
                    },
                    "submit": {
                        "use": "submit.api",
                        "next": {"APPLIED": "observe", "UNKNOWN": "END"},
                    },
                    "observe": {
                        "use": "observe.reply",
                        "next": {"PENDING": "observe", "APPLIED": "END"},
                    },
                },
            },
        },
        "selected_routes": {"worker_roundtrip": "roundtrip.rcc"},
        "projects": {},
    }


class RelayControlSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "relay-message-settings.json"
        self.env = patch.dict(os.environ, {"BCT_RELAY_SETTINGS_PATH": str(self.settings)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, *, control=None):
        value = {"version": 1, "defaults": {}, "projects": {}}
        if control is not None:
            value["control"] = control
        self.settings.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def test_missing_control_is_disabled_and_preview_never_executes(self):
        self.write()
        current = read_relay_control(SCOPE)
        self.assertFalse(current["enabled"])
        self.assertEqual({}, current["functions"])
        preview = preview_relay_control(SCOPE)
        self.assertFalse(preview["execution_connected"])
        self.assertEqual("NONE_PREVIEW_ONLY", preview["effect"])
        self.assertEqual("NEXT_UNSTARTED_FLOW", preview["apply_boundary"])

    def test_resolves_selected_route_functions_arguments_and_loop_bound(self):
        value = control_profile()
        value["enabled"] = True
        self.write(control=value)
        preview = preview_relay_control(SCOPE)
        resolved = preview["resolved_preview"]
        self.assertTrue(resolved["enabled"])
        route = resolved["selected_routes"]["worker_roundtrip"]
        self.assertEqual(40, route["max_steps"])
        self.assertEqual("rcc", route["steps"]["submit"]["resolved_function"]["driver"])
        self.assertEqual(
            "${worker_message.text}",
            route["steps"]["submit"]["resolved_function"]["arguments"]["text"],
        )
        self.assertEqual("observe", route["steps"]["observe"]["next"]["PENDING"])
        self.assertIn("한국어", resolved["variables"]["message_template"])

    def test_global_merge_patch_preserves_messages_and_changes_nested_call(self):
        self.write(control=control_profile())
        before_message = propose_relay_settings_patch(
            scope_id=SCOPE, changes={"project_goal": "설정 기반 목표"}
        )
        self.settings.write_bytes(before_message["new_content"].encode("utf-8"))
        proposal = propose_relay_control_patch(
            changes={
                "enabled": True,
                "functions": {"submit.api": {"call": "tabs.sendMessageV2"}},
                "selected_routes": {"worker_roundtrip": "roundtrip.api"},
            }
        )
        self.assertFalse(proposal["execution_connected"])
        self.assertEqual(
            before_message["new_sha256"], proposal["expected_sha256"]
        )
        self.settings.write_bytes(proposal["new_content"].encode("utf-8"))
        self.assertEqual("설정 기반 목표", read_relay_settings(SCOPE)["project_goal"])
        current = read_relay_control()
        self.assertTrue(current["enabled"])
        self.assertEqual("tabs.sendMessageV2", current["functions"]["submit.api"]["call"])
        self.assertEqual("roundtrip.api", current["selected_routes"]["worker_roundtrip"])

    def test_project_overlay_selects_route_without_changing_global(self):
        self.write(control=control_profile())
        proposal = propose_relay_control_patch(
            scope_id=SCOPE,
            changes={
                "enabled": True,
                "variables": {"project_note": "이 프로젝트만 API 경로"},
                "functions": {"submit.api": {"call": "tabs.sendMessageForProject"}},
                "routes": {"roundtrip.api": {"steps": {
                    "submit": {"arguments": {"channel": "project-only"}},
                }}},
                "selected_routes": {"worker_roundtrip": "roundtrip.api"},
            },
        )
        self.settings.write_bytes(proposal["new_content"].encode("utf-8"))
        global_value = read_relay_control()
        project_value = read_relay_control(SCOPE)
        self.assertFalse(global_value["enabled"])
        self.assertEqual("roundtrip.rcc", global_value["selected_routes"]["worker_roundtrip"])
        self.assertTrue(project_value["enabled"])
        self.assertEqual("roundtrip.api", project_value["selected_routes"]["worker_roundtrip"])
        self.assertEqual("이 프로젝트만 API 경로", project_value["variables"]["project_note"])
        self.assertEqual(
            "tabs.sendMessageForProject", project_value["functions"]["submit.api"]["call"]
        )
        self.assertEqual(
            "project-only",
            project_value["routes"]["roundtrip.api"]["steps"]["submit"]["arguments"]["channel"],
        )

    def test_invalid_graph_and_function_references_fail_before_write(self):
        self.write(control=control_profile())
        original = self.settings.read_bytes()
        bad = [
            {"selected_routes": {"worker_roundtrip": "missing.route"}},
            {"routes": {"bad": {"entry": "x", "max_steps": 2,
                                  "steps": {"x": {"use": "missing.function"}}}}},
            {"routes": {"bad": {"entry": "missing", "max_steps": 2,
                                  "steps": {"x": {"use": "compose.worker"}}}}},
            {"functions": {"submit.rcc": {"timeout_seconds": 0}}},
            {"functions": {"submit.rcc": {"effect": "magical"}}},
            {"enabled": "yes"},
        ]
        for changes in bad:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    propose_relay_control_patch(changes=changes)
                self.assertEqual(original, self.settings.read_bytes())

    def test_message_patch_preserves_control_document_exact_semantics(self):
        self.write(control=control_profile())
        before = read_relay_control(SCOPE)
        proposal = propose_relay_settings_patch(
            scope_id=SCOPE, changes={"worker_additional_instruction": "새 문구 📦"}
        )
        self.settings.write_bytes(proposal["new_content"].encode("utf-8"))
        after = read_relay_control(SCOPE)
        for key in ("enabled", "variables", "functions", "routes", "selected_routes"):
            self.assertEqual(before[key], after[key])
        self.assertEqual("새 문구 📦", read_relay_settings(SCOPE)["worker_additional_instruction"])

    def test_control_patch_returns_exact_cas_and_hot_reload_bytes(self):
        self.write(control=control_profile())
        old_sha = read_relay_control()["config_sha256"]
        proposal = propose_relay_control_patch(
            changes={"variables": {"message_template": "수정된 템플릿 ${task} ✅"}}
        )
        self.assertEqual(old_sha, proposal["expected_sha256"])
        self.assertNotEqual(old_sha, proposal["new_sha256"])
        self.assertFalse(self.settings.read_text(encoding="utf-8").find("수정된 템플릿") >= 0)
        self.settings.write_bytes(proposal["new_content"].encode("utf-8"))
        self.assertEqual(
            "수정된 템플릿 ${task} ✅",
            read_relay_control()["variables"]["message_template"],
        )
        self.assertEqual(proposal["new_sha256"], read_relay_control()["config_sha256"])

    def test_malformed_control_fails_closed_for_message_and_control_reads(self):
        broken = control_profile()
        broken["selected_routes"]["worker_roundtrip"] = "missing.route"
        self.write(control=broken)
        with self.assertRaises(ValueError):
            read_relay_settings(SCOPE)
        with self.assertRaises(ValueError):
            read_relay_control(SCOPE)

    def test_cli_emits_utf8_when_python_utf8_mode_is_disabled(self):
        self.write(control=control_profile())
        environment = dict(os.environ)
        environment["PYTHONUTF8"] = "0"
        environment.pop("PYTHONIOENCODING", None)
        completed = subprocess.run(
            [sys.executable, "-m", "bct.relay_settings", "control", SCOPE],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", "replace"))
        output = completed.stdout.decode("utf-8")
        self.assertIn("한국어", output)
        self.assertIn("📦", output)
        parsed = json.loads(output)
        self.assertFalse(parsed["execution_connected"])


if __name__ == "__main__":
    unittest.main()
