from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, PreconditionError, UnknownEffectError, Work
from bct.features.desktop_session import (
    DesktopApplicationTargetFeature, DesktopCaptureFeature, DesktopControlLeaseFeature,
    DesktopEmergencyStopFeature,
    DesktopExploreFeature, DesktopInputFeature, DesktopProgramLaunchFeature,
    DesktopSessionStatusFeature,
    DesktopWindowActivateFeature, DesktopWindowManageFeature,
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
        self.explore_calls = []
        self.chrome_inspection_available = True
        self.chrome_truncated = False
        self.window_items = [{
            "hwnd": "12345", "pid": 123, "processName": "probe",
            "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
            "sessionId": 1, "virtualDesktopId": "a" * 36,
            "title": "Probe", "className": "ProbeWindow", "visible": True,
            "minimized": False, "foreground": False, "zOrder": 1,
            "rect": {"x": 10, "y": 10, "width": 100, "height": 100},
        }]

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
                "target": ({
                    "type": "window", "hwnd": (arguments or {}).get("hwnd"),
                    "pid": 123,
                    "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
                    "sessionId": 1, "virtualDesktopId": "a" * 36,
                } if (arguments or {}).get("targetType") == "window" else {
                    "type": (arguments or {}).get("targetType", "session")
                }),
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
            "items": list(self.window_items),
            "count": len(self.window_items), "truncated": False,
            "observedAtUtc": "2026-10-19T00:00:00.0000000Z",
        }
        return value

    def explorer_windows(self, *, request_id: str, **arguments):
        self.window_calls.append((request_id, "explorer_windows_list", arguments))
        folder_path = arguments.get("folder_path", "")
        items = []
        for source in self.window_items:
            if str(source.get("processName") or "").casefold() != "explorer":
                continue
            item = {
                **source,
                "folderPath": source.get("folderPath"),
                "locationUrl": source.get("locationUrl", "file:///D:/"),
                "locationName": source.get("locationName", source.get("title", "")),
            }
            if folder_path and item["folderPath"] != folder_path:
                continue
            items.append(item)
        value = self._base("explorer_windows_list")
        value["requestId"] = request_id
        value["windows"] = {
            "items": items, "count": len(items), "truncated": False,
            "shellAvailable": True, "folderPath": folder_path,
            "observedAtUtc": "2026-10-19T00:00:00.0000000Z",
        }
        return value

    def chrome_windows(self, *, request_id: str, **arguments):
        self.window_calls.append((request_id, "chrome_windows_list", arguments))
        profile_query = arguments.get("profile_query", "").casefold()
        tab_query = arguments.get("tab_title_query", "").casefold()
        tab_scope = arguments.get("tab_scope", "active")
        title_query = arguments.get("title_query", "").casefold()
        items = []
        for source in self.window_items:
            if (
                str(source.get("processName") or "").casefold() != "chrome"
                or str(source.get("className") or "").casefold() != "chrome_widgetwin_1"
            ):
                continue
            tabs = source.get("tabs", [{"ordinal": 0, "title": "Home", "selected": True}])
            item = {
                **source,
                "available": source.get("available", True),
                "profileName": source.get("profileName", "Profile 1"),
                "tabs": tabs,
                "tabCount": len(tabs),
                "activeTab": next((tab for tab in tabs if tab["selected"]), None),
                "error": source.get("error", ""),
            }
            scoped_tabs = tabs if tab_scope == "any" else [tab for tab in tabs if tab["selected"]]
            if title_query and title_query not in item["title"].casefold():
                continue
            if profile_query and profile_query not in item["profileName"].casefold():
                continue
            if tab_query and not any(tab_query in tab["title"].casefold() for tab in scoped_tabs):
                continue
            items.append(item)
        value = self._base("chrome_windows_list")
        value["requestId"] = request_id
        value["windows"] = {
            "items": items, "count": len(items), "truncated": self.chrome_truncated,
            "inspectionAvailable": self.chrome_inspection_available,
            "inspectionError": "" if self.chrome_inspection_available else "CHROME_UIA_INSPECTION_INCOMPLETE",
            "profileQuery": arguments.get("profile_query", ""),
            "tabTitleQuery": arguments.get("tab_title_query", ""),
            "tabScope": tab_scope,
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

    def processes(self, *, request_id: str, **arguments):
        self.explore_calls.append((request_id, "processes", arguments))
        value = self._base("processes_list")
        value["requestId"] = request_id
        value["processes"] = {
            "items": [{
                "pid": 123, "processName": "probe",
                "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
                "sessionId": 1, "executablePath": r"D:\probe.exe",
                "responding": True, "windowCount": 1,
                "windows": [{
                    "hwnd": "12345", "pid": 123, "title": "Probe",
                    "virtualDesktopId": "a" * 36,
                }],
            }],
            "count": 1, "truncated": False, "query": arguments["query"],
            "includeBackground": arguments["include_background"], "sessionId": 1,
            "observedAtUtc": "2026-10-19T00:00:00.0000000Z",
        }
        return value

    def paths(self, *, request_id: str):
        self.explore_calls.append((request_id, "paths", {}))
        value = self._base("paths_list")
        value["requestId"] = request_id
        value["paths"] = {
            "knownFolders": [{
                "name": "profile", "path": r"C:\Users\tester",
                "exists": True, "kind": "known-folder",
            }],
            "drives": [{
                "path": "C:\\", "driveType": "Fixed", "ready": True,
                "totalBytes": 1000, "freeBytes": 500,
            }],
            "sessionId": 1, "observedAtUtc": "2026-10-19T00:00:00.0000000Z",
        }
        return value

    def manage(self, *, request_id: str, owner_id: str, lease_id: str,
               operation: str, x, y, width, height):
        self.window_calls.append((request_id, "window_manage", {
            "owner_id": owner_id, "lease_id": lease_id, "operation": operation,
            "x": x, "y": y, "width": width, "height": height,
        }))
        value = self._base("window_manage")
        value["requestId"] = request_id
        rect = {
            "left": x if x is not None else 10,
            "top": y if y is not None else 10,
            "right": (x + width) if x is not None else 110,
            "bottom": (y + height) if y is not None else 110,
            "width": width if width is not None else 100,
            "height": height if height is not None else 100,
        }
        before = {
            "hwnd": "12345", "visible": True, "minimized": False,
            "maximized": False, "rect": dict(rect),
        }
        after = {**before, "rect": dict(rect)}
        if operation == "minimize":
            after["minimized"] = True
        elif operation == "maximize":
            after["maximized"] = True
        value["windowAction"] = {
            "operation": operation, "leaseId": lease_id, "alreadyApplied": False,
            "before": before, "after": after,
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
                             "desktop_explore",
                             "desktop_application_target",
                             "desktop_control_lease", "desktop_emergency_stop",
                             "desktop_input",
                             "desktop_window_list", "desktop_window_activate",
                             "desktop_window_manage",
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

    def test_desktop_explore_processes_normalizes_and_returns_session_evidence(self):
        feature = DesktopExploreFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "processes", "query": " Probe ",
            "limit": 12, "include_background": False,
        })
        self.assertEqual(("desktop-session:observe",), request.resources)
        self.assertEqual("Probe", request.arguments["query"])
        request = request.__class__(**{**request.__dict__, "operation_id": "explore-processes-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(1, result.evidence["process_count"])
        self.assertEqual("processes", self.client.explore_calls[-1][1])

    def test_desktop_explore_paths_and_validation(self):
        feature = DesktopExploreFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"operation": "paths"})
        request = request.__class__(**{**request.__dict__, "operation_id": "explore-paths-1"})
        result = feature.execute(request)
        self.assertEqual(1, result.evidence["known_folder_count"])
        self.assertEqual(1, result.evidence["drive_count"])
        for arguments in (
            {}, {"operation": "unknown"}, {"operation": "paths", "limit": 1},
            {"operation": "processes", "limit": True},
            {"operation": "processes", "include_background": "yes"},
            {"operation": "processes", "query": "x" * 201},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(PreconditionError):
                feature.prepare(work=self.work, arguments=arguments)

    def test_desktop_explore_read_only_transport_loss_is_confirmed_failure(self):
        class UnknownClient(FakeDesktopSessionClient):
            def processes(self, **_arguments):
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_TRANSPORT_UNKNOWN")

        feature = DesktopExploreFeature(UnknownClient(self.root))
        request = feature.prepare(work=self.work, arguments={"operation": "processes"})
        request = request.__class__(**{**request.__dict__, "operation_id": "explore-unknown"})
        from bct.core.models import ConfirmedFailure
        with self.assertRaises(ConfirmedFailure) as caught:
            feature.execute(request)
        self.assertTrue(caught.exception.release_claims)

    def test_application_target_lists_exact_chrome_family(self):
        self.client.window_items = [
            {**self.client.window_items[0], "processName": "chrome",
             "className": "Chrome_WidgetWin_1", "title": "BCT - Chrome"},
            {**self.client.window_items[0], "hwnd": "22222", "processName": "explorer",
             "className": "CabinetWClass", "title": "Downloads"},
        ]
        feature = DesktopApplicationTargetFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "list", "application": "chrome", "title_query": " bct ",
            "include_minimized": False, "limit": 5,
        })
        self.assertEqual(("desktop-session:observe",), request.resources)
        request = request.__class__(**{**request.__dict__, "operation_id": "app-list-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(1, result.evidence["candidate_count"])
        self.assertEqual("12345", result.output["applicationWindows"]["items"][0]["hwnd"])
        self.assertEqual("chrome_windows_list", self.client.window_calls[-1][1])

    def test_application_target_selects_chrome_profile_and_tab_without_focus(self):
        chrome = {
            **self.client.window_items[0], "processName": "chrome",
            "className": "Chrome_WidgetWin_1", "title": "Chrome",
        }
        self.client.window_items = [
            {
                **chrome, "profileName": "BCT Test",
                "tabs": [
                    {"ordinal": 0, "title": "Dashboard", "selected": True},
                    {"ordinal": 1, "title": "Logs", "selected": False},
                ],
            },
            {
                **chrome, "hwnd": "22222", "profileName": "Personal",
                "tabs": [{"ordinal": 0, "title": "Dashboard", "selected": True}],
            },
        ]
        feature = DesktopApplicationTargetFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "bind", "application": "chrome",
            "profile_query": "bct", "tab_title_query": "dash",
            "tab_scope": "active", "ttl_seconds": 30,
        })
        request = request.__class__(**{**request.__dict__, "operation_id": "chrome-semantic-bind"})
        result = feature.execute(request)
        target = result.output["applicationTarget"]
        self.assertEqual("12345", target["window"]["hwnd"])
        self.assertEqual("bct", self.client.window_calls[-1][2]["profile_query"])
        self.assertEqual("dash", self.client.window_calls[-1][2]["tab_title_query"])
        self.assertEqual("active", target["tabScope"])

    def test_application_target_chrome_bind_fails_closed_on_inspection_or_truncation(self):
        from bct.core.models import ConfirmedFailure

        self.client.window_items = [{
            **self.client.window_items[0], "processName": "chrome",
            "className": "Chrome_WidgetWin_1", "title": "Chrome",
        }]
        feature = DesktopApplicationTargetFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "bind", "application": "chrome",
        })
        request = request.__class__(**{**request.__dict__, "operation_id": "chrome-fail-closed"})
        self.client.chrome_inspection_available = False
        with self.assertRaisesRegex(ConfirmedFailure, "INSPECTION_UNAVAILABLE"):
            feature.execute(request)
        self.client.chrome_inspection_available = True
        self.client.chrome_truncated = True
        with self.assertRaisesRegex(ConfirmedFailure, "AMBIGUOUS"):
            feature.execute(request)
        self.assertEqual([], self.client.control_calls)

    def test_application_target_binds_one_exact_explorer_window(self):
        folder = self.root / "프로젝트"
        folder.mkdir()
        self.client.window_items = [{
            **self.client.window_items[0], "processName": "explorer",
            "className": "CabinetWClass", "title": "프로젝트",
            "folderPath": str(folder.resolve()),
        }]
        feature = DesktopApplicationTargetFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "bind", "application": "explorer",
            "title_query": "프로젝트", "folder_path": str(folder), "ttl_seconds": 45,
        })
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        request = request.__class__(**{**request.__dict__, "operation_id": "app-bind-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("b" * 32, result.evidence["control"]["lease"]["leaseId"])
        self.assertEqual("12345", result.evidence["application_target"]["window"]["hwnd"])
        self.assertEqual(str(folder.resolve()), result.output["applicationTarget"]["folderPath"])
        self.assertEqual("explorer_windows_list", self.client.window_calls[-1][1])
        self.assertEqual(str(folder.resolve()), self.client.window_calls[-1][2]["folder_path"])
        self.assertEqual("lease_acquire", self.client.control_calls[-1][1])

    def test_application_target_fails_closed_on_absent_or_ambiguous_window(self):
        from bct.core.models import ConfirmedFailure

        feature = DesktopApplicationTargetFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "bind", "application": "chrome",
        })
        request = request.__class__(**{**request.__dict__, "operation_id": "app-none"})
        with self.assertRaisesRegex(ConfirmedFailure, "NOT_FOUND"):
            feature.execute(request)
        chrome = {
            **self.client.window_items[0], "processName": "chrome",
            "className": "Chrome_WidgetWin_1", "title": "Chrome",
        }
        self.client.window_items = [chrome, {**chrome, "hwnd": "22222"}]
        with self.assertRaisesRegex(ConfirmedFailure, "AMBIGUOUS"):
            feature.execute(request)
        self.assertEqual([], self.client.control_calls)

    def test_application_target_validates_fields_and_preserves_unknown_bind(self):
        feature = DesktopApplicationTargetFeature(self.client)
        invalid = (
            {},
            {"operation": "bind", "application": "edge"},
            {"operation": "list", "application": "chrome", "limit": True},
            {"operation": "bind", "application": "chrome", "ttl_seconds": 4},
            {"operation": "list", "application": "chrome", "ttl_seconds": 30},
            {"operation": "list", "application": "chrome", "folder_path": str(self.root)},
            {"operation": "list", "application": "explorer", "profile_query": "Profile 1"},
            {"operation": "list", "application": "chrome", "tab_scope": "selected"},
            {"operation": "list", "application": "chrome", "profile_query": "x" * 201},
            {"operation": "list", "application": "chrome", "tab_title_query": "x" * 501},
            {"operation": "list", "application": "explorer", "folder_path": "relative"},
            {"operation": "list", "application": "explorer", "folder_path": str(self.root / "missing")},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(PreconditionError):
                feature.prepare(work=self.work, arguments=arguments)

        class UnknownClient(FakeDesktopSessionClient):
            def control(self, **_arguments):
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_TRANSPORT_UNKNOWN")

        client = UnknownClient(self.root)
        client.window_items = [{
            **client.window_items[0], "processName": "chrome",
            "className": "Chrome_WidgetWin_1", "title": "Chrome",
        }]
        request = DesktopApplicationTargetFeature(client).prepare(
            work=self.work, arguments={"operation": "bind", "application": "chrome"},
        )
        request = request.__class__(**{**request.__dict__, "operation_id": "app-unknown"})
        with self.assertRaises(UnknownEffectError):
            DesktopApplicationTargetFeature(client).execute(request)

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

    def test_client_validates_chrome_semantic_inventory_shape(self):
        result = self.client._base("chrome_windows_list")
        item = {
            **self.client.window_items[0], "processName": "chrome",
            "className": "Chrome_WidgetWin_1", "available": True,
            "profileName": "Profile 1", "error": "",
            "tabs": [{"ordinal": 0, "title": "Home", "selected": True}],
            "tabCount": 1,
        }
        item["activeTab"] = item["tabs"][0]
        result["windows"] = {
            "items": [item], "count": 1, "truncated": False,
            "inspectionAvailable": True, "inspectionError": "",
            "profileQuery": "", "tabTitleQuery": "", "tabScope": "active",
            "observedAtUtc": "2026-10-19T00:00:00Z",
        }
        self.assertIs(result, DesktopSessionClient._validated_windows(result, adapter="chrome"))
        result["windows"]["items"][0]["tabs"][0]["ordinal"] = 1
        with self.assertRaisesRegex(DesktopSessionEffectUnknown, "CHROME_WINDOWS_INVALID"):
            DesktopSessionClient._validated_windows(result, adapter="chrome")

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

    def test_window_manage_normalizes_geometry_and_uses_control_claim(self):
        feature = DesktopWindowManageFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "lease_id": "b" * 32, "operation": "move_resize",
            "x": 20, "y": 30, "width": 640, "height": 480,
        })
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        self.assertEqual("desktop", request.arguments["owner_id"])
        request = request.__class__(**{**request.__dict__, "operation_id": "window-manage-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("window_manage", self.client.window_calls[-1][1])
        self.assertEqual(640, result.evidence["window_action"]["after"]["rect"]["width"])

    def test_window_manage_rejects_conflicting_or_unbounded_geometry(self):
        feature = DesktopWindowManageFeature(self.client)
        valid = {"lease_id": "b" * 32}
        invalid = (
            {**valid, "operation": "close"},
            {**valid, "operation": "restore", "x": 1},
            {**valid, "operation": "move_resize", "x": 1, "y": 2, "width": 99, "height": 80},
            {**valid, "operation": "move_resize", "x": 1, "y": 2, "width": 100, "height": True},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(PreconditionError):
                feature.prepare(work=self.work, arguments=arguments)

    def test_window_manage_unknown_and_terminal_failure_are_distinct(self):
        request = DesktopWindowManageFeature(self.client).prepare(work=self.work, arguments={
            "lease_id": "b" * 32, "operation": "restore",
        })
        request = request.__class__(**{**request.__dict__, "operation_id": "window-manage-fail"})

        class UnknownClient(FakeDesktopSessionClient):
            def manage(self, **_arguments):
                raise DesktopSessionEffectUnknown("WINDOW_MANAGE_EFFECT_UNKNOWN")

        with self.assertRaises(UnknownEffectError):
            DesktopWindowManageFeature(UnknownClient(self.root)).execute(request)

        class RejectingClient(FakeDesktopSessionClient):
            def manage(self, **_arguments):
                raise DesktopSessionRequestFailed("WINDOW_TARGET_NOT_RESTORED")

        from bct.core.models import ConfirmedFailure
        with self.assertRaises(ConfirmedFailure):
            DesktopWindowManageFeature(RejectingClient(self.root)).execute(request)

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
