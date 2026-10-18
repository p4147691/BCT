from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, PreconditionError, UnknownEffectError, Work
from bct.features.desktop_session import (
    DesktopCaptureFeature, DesktopControlLeaseFeature, DesktopEmergencyStopFeature,
    DesktopInputFeature, DesktopProgramLaunchFeature, DesktopSessionStatusFeature,
    DesktopWindowActivateFeature,
    DesktopWindowListFeature,
)
from bct.integrations.desktop_session import (
    DesktopSessionClient, DesktopSessionEffectUnknown, DesktopSessionRequestFailed,
    DesktopSessionUnavailable,
)


class FakeDesktopSessionClient:
    def __init__(self, root: Path):
        self.root = root
        self.status_calls = 0
        self.capture_calls = 0
        self.control_calls = []
        self.input_calls = []
        self.window_calls = []
        self.launch_calls = []

    @staticmethod
    def _base(command: str):
        return {
            "type": "desktop-session:result", "ok": True,
            "requestId": "unused", "command": command, "instanceId": "a" * 32,
            "session": {
                "pid": 123, "sessionId": 1, "userSid": "S-1-5-21-test",
                "logonSid": "S-1-5-5-1-2", "userInteractive": True,
                "inputDesktopAvailable": True, "foregroundWindow": None,
            },
            "monitors": [{"index": 0, "primary": True}],
        }

    def status(self, *, request_id: str):
        self.status_calls += 1
        value = self._base("status")
        value["requestId"] = request_id
        return value

    def capture(self, *, request_id: str, **arguments):
        self.capture_calls += 1
        path = self.root / f"{request_id}.png"
        path.write_bytes(b"fake png")
        value = self._base("capture")
        value["requestId"] = request_id
        value["capture"] = {
            "targetType": arguments["target_type"], "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": 10, "height": 10, "bytes": path.stat().st_size,
            "mimeType": "image/png",
        }
        return value

    def control(self, *, request_id: str, command: str, arguments=None):
        self.control_calls.append((request_id, command, arguments or {}))
        value = self._base(command)
        value["requestId"] = request_id
        value["control"] = {
            "lease": ({
                "leaseId": "b" * 32, "ownerId": (arguments or {}).get("ownerId"),
                "ttlSeconds": (arguments or {}).get("ttlSeconds", 30),
                "target": {"type": (arguments or {}).get("targetType", "session")},
            } if command in {"lease_acquire", "lease_renew"} else None),
            "emergencyStop": {
                "active": command == "emergency_stop", "generation": 1,
                "reason": (arguments or {}).get("reason", ""),
            },
        }
        return value

    def input(self, *, request_id: str, command: str, arguments):
        self.input_calls.append((request_id, command, arguments))
        value = self._base(command)
        value["requestId"] = request_id
        value["input"] = {
            "operation": command.removeprefix("input_mouse_").removeprefix("input_"),
            "leaseId": arguments["leaseId"], "eventCount": 2,
        }
        return value

    def windows(self, *, request_id: str, **arguments):
        self.window_calls.append((request_id, "windows_list", arguments))
        value = self._base("windows_list")
        value["requestId"] = request_id
        value["windows"] = {
            "items": [{
                "hwnd": "12345", "pid": 123, "processName": "probe",
                "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
                "sessionId": 1, "virtualDesktopId": "a" * 36,
                "title": "Probe", "className": "ProbeWindow", "visible": True,
                "minimized": False, "foreground": False, "zOrder": 1,
                "rect": {"x": 10, "y": 10, "width": 100, "height": 100},
            }],
            "count": 1, "truncated": False,
            "observedAtUtc": "2026-10-19T00:00:00.0000000Z",
        }
        return value

    def activate(self, *, request_id: str, owner_id: str, lease_id: str):
        self.window_calls.append((request_id, "window_activate", {
            "owner_id": owner_id, "lease_id": lease_id,
        }))
        value = self._base("window_activate")
        value["requestId"] = request_id
        value["windowAction"] = {
            "operation": "activate", "leaseId": lease_id,
            "alreadyForeground": False, "beforeHwnd": "22", "afterHwnd": "12345",
        }
        return value

    def launch(self, *, request_id: str, **arguments):
        self.launch_calls.append((request_id, arguments))
        value = self._base("program_launch")
        value["requestId"] = request_id
        value["programLaunch"] = {
            "leaseId": arguments["lease_id"],
            "executable": arguments["executable"],
            "arguments": arguments["arguments"],
            "workingDirectory": arguments["working_directory"],
            "pid": 456,
            "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
            "sessionId": 1,
            "startedAtUtc": "2026-10-19T00:00:00.0000000Z",
            "bindingState": "WINDOW_BOUND",
            "windowTarget": {
                "type": "window", "hwnd": "23456", "pid": 456,
                "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
                "sessionId": 1, "virtualDesktopId": "b" * 36,
            },
        }
        return value


class DesktopSessionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = FakeDesktopSessionClient(self.root)
        self.program = self.root / "프로그램 probe.exe"
        self.program.write_bytes(b"MZ test fixture")
        self.work = Work("desktop", "observe desktop", (str(self.root),),
                         frozenset({
                             "desktop_session_status", "desktop_capture",
                             "desktop_control_lease", "desktop_emergency_stop",
                             "desktop_input",
                             "desktop_window_list", "desktop_window_activate",
                             "desktop_program_launch",
                         }), "owner")

    def tearDown(self):
        self.temp.cleanup()

    def test_status_returns_exact_session_and_monitor_evidence(self):
        feature = DesktopSessionStatusFeature(self.client)
        request = feature.prepare(work=self.work, arguments={})
        request = request.__class__(**{**request.__dict__, "operation_id": "status-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(1, result.evidence["session"]["sessionId"])
        self.assertEqual(1, len(result.evidence["monitors"]))

    def test_capture_normalizes_target_and_returns_hash_evidence(self):
        feature = DesktopCaptureFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"target_type": "monitor", "monitor_index": 0})
        request = request.__class__(**{**request.__dict__, "operation_id": "capture-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("monitor", result.evidence["capture"]["targetType"])
        self.assertTrue(Path(result.evidence["capture"]["path"]).is_file())

    def test_window_requires_exact_numeric_hwnd(self):
        feature = DesktopCaptureFeature(self.client)
        with self.assertRaisesRegex(PreconditionError, "HWND_INVALID"):
            feature.prepare(work=self.work, arguments={"target_type": "window", "hwnd": "foreground"})

    def test_agent_terminal_capture_failure_releases_as_failed_not_unknown(self):
        class RejectingClient(FakeDesktopSessionClient):
            def capture(self, **_arguments):
                raise DesktopSessionRequestFailed("DESKTOP_SESSION_AGENT_ERROR:INPUT_DESKTOP_UNAVAILABLE")

        feature = DesktopCaptureFeature(RejectingClient(self.root))
        request = feature.prepare(work=self.work, arguments={})
        request = request.__class__(**{**request.__dict__, "operation_id": "capture-rejected"})
        from bct.core.models import ConfirmedFailure
        with self.assertRaisesRegex(ConfirmedFailure, "INPUT_DESKTOP_UNAVAILABLE") as caught:
            feature.execute(request)
        self.assertTrue(caught.exception.release_claims)

    def test_client_fails_closed_without_endpoint(self):
        client = DesktopSessionClient(
            endpoint_path=self.root / "missing.json", evidence_root=self.root / "evidence",
        )
        with self.assertRaisesRegex(DesktopSessionUnavailable, "ENDPOINT_UNAVAILABLE"):
            client.status(request_id="status-missing")

    def test_control_lease_derives_owner_and_normalizes_session_acquire(self):
        feature = DesktopControlLeaseFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "acquire", "ttl_seconds": 45, "target_type": "session",
        })
        self.assertEqual("desktop", request.arguments["owner_id"])
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        request = request.__class__(**{**request.__dict__, "operation_id": "lease-acquire-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("b" * 32, result.evidence["control"]["lease"]["leaseId"])
        self.assertEqual("lease_acquire", self.client.control_calls[-1][1])

    def test_control_lease_validates_id_ttl_and_reset_generation(self):
        feature = DesktopControlLeaseFeature(self.client)
        with self.assertRaisesRegex(PreconditionError, "TTL_INVALID"):
            feature.prepare(work=self.work, arguments={"operation": "acquire", "ttl_seconds": 1})
        with self.assertRaisesRegex(PreconditionError, "LEASE_ID_INVALID"):
            feature.prepare(work=self.work, arguments={"operation": "renew", "lease_id": "bad"})
        with self.assertRaisesRegex(PreconditionError, "GENERATION_INVALID"):
            feature.prepare(work=self.work, arguments={
                "operation": "reset_emergency", "expected_stop_generation": 0,
            })

    def test_control_mutation_transport_loss_is_unknown(self):
        class UnknownClient(FakeDesktopSessionClient):
            def control(self, **_arguments):
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_TRANSPORT_UNKNOWN")

        feature = DesktopControlLeaseFeature(UnknownClient(self.root))
        request = feature.prepare(work=self.work, arguments={"operation": "acquire"})
        request = request.__class__(**{**request.__dict__, "operation_id": "lease-unknown"})
        with self.assertRaisesRegex(UnknownEffectError, "TRANSPORT_UNKNOWN"):
            feature.execute(request)

    def test_emergency_stop_uses_independent_claim_and_returns_latched_state(self):
        feature = DesktopEmergencyStopFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"reason": "operator"})
        self.assertEqual(("desktop-emergency-stop:interactive-session",), request.resources)
        request = request.__class__(**{**request.__dict__, "operation_id": "emergency-stop-1"})
        result = feature.execute(request)
        self.assertTrue(result.evidence["control"]["emergencyStop"]["active"])
        self.assertIsNone(result.evidence["control"]["lease"])

    def test_input_derives_owner_and_normalizes_unicode_text(self):
        feature = DesktopInputFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "text", "lease_id": "b" * 32, "text": "한글 A9",
        })
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        self.assertEqual("desktop", request.arguments["owner_id"])
        request = request.__class__(**{**request.__dict__, "operation_id": "input-text-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("input_text", self.client.input_calls[-1][1])
        self.assertEqual("한글 A9", self.client.input_calls[-1][2]["text"])

    def test_input_validates_conflicting_fields_keys_modifiers_and_coordinates(self):
        feature = DesktopInputFeature(self.client)
        invalid = (
            {"operation": "move", "lease_id": "b" * 32, "x": 1, "y": 2, "text": "x"},
            {"operation": "key", "lease_id": "b" * 32, "key": "POWER", "modifiers": []},
            {"operation": "key", "lease_id": "b" * 32, "key": "A", "modifiers": ["ctrl", "CTRL"]},
            {"operation": "click", "lease_id": "b" * 32, "x": True, "y": 2},
            {"operation": "text", "lease_id": "b" * 32, "text": "line\n"},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(PreconditionError):
                feature.prepare(work=self.work, arguments=arguments)

    def test_input_transport_loss_is_unknown_and_terminal_rejection_is_failed(self):
        feature = DesktopInputFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "key", "lease_id": "b" * 32, "key": "ENTER", "modifiers": [],
        })
        request = request.__class__(**{**request.__dict__, "operation_id": "input-key-unknown"})

        class UnknownClient(FakeDesktopSessionClient):
            def input(self, **_arguments):
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN")

        with self.assertRaises(UnknownEffectError):
            DesktopInputFeature(UnknownClient(self.root)).execute(request)

        class RejectingClient(FakeDesktopSessionClient):
            def input(self, **_arguments):
                raise DesktopSessionRequestFailed("INPUT_TARGET_NOT_FOREGROUND")

        from bct.core.models import ConfirmedFailure
        with self.assertRaises(ConfirmedFailure):
            DesktopInputFeature(RejectingClient(self.root)).execute(request)

    def test_window_list_is_bounded_and_returns_current_desktop_inventory(self):
        feature = DesktopWindowListFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "include_minimized": False, "title_query": " Probe ", "limit": 12,
        })
        self.assertEqual(("desktop-session:observe",), request.resources)
        self.assertEqual("Probe", request.arguments["title_query"])
        request = request.__class__(**{**request.__dict__, "operation_id": "windows-list-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(1, result.evidence["window_count"])
        self.assertEqual("12345", result.output["windows"]["items"][0]["hwnd"])

    def test_window_list_rejects_invalid_types_and_bounds(self):
        feature = DesktopWindowListFeature(self.client)
        for arguments in (
            {"include_minimized": "yes"}, {"title_query": "x" * 201},
            {"limit": True}, {"limit": 0}, {"limit": 257},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(PreconditionError):
                feature.prepare(work=self.work, arguments=arguments)

    def test_window_activation_derives_owner_and_uses_control_claim(self):
        feature = DesktopWindowActivateFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"lease_id": "b" * 32})
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        self.assertEqual("desktop", request.arguments["owner_id"])
        request = request.__class__(**{**request.__dict__, "operation_id": "window-activate-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("window_activate", self.client.window_calls[-1][1])

    def test_window_activation_unknown_and_terminal_failure_are_distinct(self):
        feature = DesktopWindowActivateFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"lease_id": "b" * 32})
        request = request.__class__(**{**request.__dict__, "operation_id": "window-activate-fail"})

        class UnknownClient(FakeDesktopSessionClient):
            def activate(self, **_arguments):
                raise DesktopSessionEffectUnknown("WINDOW_ACTIVATION_EFFECT_UNKNOWN")

        with self.assertRaises(UnknownEffectError):
            DesktopWindowActivateFeature(UnknownClient(self.root)).execute(request)

        class RejectingClient(FakeDesktopSessionClient):
            def activate(self, **_arguments):
                raise DesktopSessionRequestFailed("WINDOW_TARGET_MINIMIZED")

        from bct.core.models import ConfirmedFailure
        with self.assertRaises(ConfirmedFailure):
            DesktopWindowActivateFeature(RejectingClient(self.root)).execute(request)

    def test_program_launch_preserves_argument_array_and_returns_exact_binding(self):
        feature = DesktopProgramLaunchFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "lease_id": "b" * 32,
            "executable": str(self.program),
            "arguments": ["--title", "한글 창", "space value"],
            "working_directory": str(self.root),
            "window_timeout_ms": 5000,
        })
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        self.assertEqual(["--title", "한글 창", "space value"], request.arguments["arguments"])
        request = request.__class__(**{**request.__dict__, "operation_id": "program-launch-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("WINDOW_BOUND", result.evidence["program_launch"]["bindingState"])
        self.assertEqual(456, result.evidence["program_launch"]["windowTarget"]["pid"])

    def test_program_launch_rejects_shell_paths_and_unbounded_arguments(self):
        feature = DesktopProgramLaunchFeature(self.client)
        valid = {
            "lease_id": "b" * 32, "executable": str(self.program),
            "arguments": [], "working_directory": str(self.root),
        }
        invalid = (
            {**valid, "executable": "cmd.exe"},
            {**valid, "executable": str(self.root / "missing.exe")},
            {**valid, "arguments": "--not-an-array"},
            {**valid, "arguments": ["x"] * 33},
            {**valid, "window_timeout_ms": 99},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(PreconditionError):
                feature.prepare(work=self.work, arguments=arguments)

    def test_program_launch_unknown_and_terminal_failure_are_distinct(self):
        request = DesktopProgramLaunchFeature(self.client).prepare(work=self.work, arguments={
            "lease_id": "b" * 32, "executable": str(self.program),
            "arguments": [], "working_directory": str(self.root),
        })
        request = request.__class__(**{**request.__dict__, "operation_id": "program-launch-fail"})

        class UnknownClient(FakeDesktopSessionClient):
            def launch(self, **_arguments):
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_TRANSPORT_UNKNOWN")

        with self.assertRaises(UnknownEffectError):
            DesktopProgramLaunchFeature(UnknownClient(self.root)).execute(request)

        class RejectingClient(FakeDesktopSessionClient):
            def launch(self, **_arguments):
                raise DesktopSessionRequestFailed("PROGRAM_SESSION_LEASE_REQUIRED")

        from bct.core.models import ConfirmedFailure
        with self.assertRaises(ConfirmedFailure):
            DesktopProgramLaunchFeature(RejectingClient(self.root)).execute(request)


if __name__ == "__main__":
    unittest.main()
