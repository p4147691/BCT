import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Work, UnknownEffectError, PreconditionError
from bct.features.desktop_explorer_folder import DesktopExplorerFolderOpenFeature
from bct.integrations.desktop_session import DesktopSessionEffectUnknown
from tests.test_desktop_session import FakeDesktopSessionClient


class ExplorerAgent(FakeDesktopSessionClient):
    def __init__(self, root):
        super().__init__(root)
        self.folder = str(root.resolve())
        self.window_items = []
        self.fail_launch = False
        self.fail_activate = False
        self.fail_release = False
        self.other_desktop = False
        self.events = []

    def explorer_windows(self, *, request_id, **arguments):
        self.events.append("observe")
        res = super().explorer_windows(request_id=request_id, **arguments)
        return res

    def launch(self, *, request_id, **arguments):
        self.events.append("launch")
        self.window_items = [self.window()]
        if self.fail_launch:
            raise DesktopSessionEffectUnknown("LAUNCH_UNKNOWN")
        return {"programLaunch": {"pid": 321}}

    def window(self):
        return {
            "hwnd": "12345", "pid": 999, "processName": "explorer",
            "processStartTimeUtc": "2026-10-19T00:00:00.0000000Z",
            "sessionId": 1, "virtualDesktopId": "a" * 36,
            "title": "Folder", "className": "CabinetWClass", "visible": True,
            "minimized": False, "foreground": False, "zOrder": 1,
            "rect": {"x": 10, "y": 10, "width": 100, "height": 100},
            "folderPath": self.folder,
        }

    def activate(self, *, request_id, owner_id, lease_id):
        self.events.append("activate")
        if self.fail_activate:
            raise DesktopSessionEffectUnknown("ACTIVATE_UNKNOWN")
        return {"windowAction": {"operation": "activate"}}

    def manage(self, **kwargs):
        self.events.append("restore")
        return {}

    def control(self, *, request_id, command, arguments=None):
        self.events.append(command)
        if command == "lease_release" and self.fail_release:
            raise DesktopSessionEffectUnknown("RELEASE_UNKNOWN")
        res = super().control(request_id=request_id, command=command, arguments=arguments)
        if command == "lease_acquire" and (arguments or {}).get("targetType") == "window":
            res["control"]["lease"]["target"]["pid"] = 999
            if self.other_desktop:
                res["control"]["lease"]["target"]["virtualDesktopId"] = "b" * 36
        return res


class ExplorerFeatureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = ExplorerAgent(self.root)
        self.feature = DesktopExplorerFolderOpenFeature(self.client)
        self.work = Work("n68-test", "test", (str(self.root),),
                         frozenset({"desktop_explorer_folder_open"}), "test-user")

    def run_feature(self, foreground=True):
        req = self.feature.prepare(work=self.work, arguments={
            "folder_path": str(self.root), "foreground": foreground,
        })
        return self.feature.execute(type(req)(**{**req.__dict__, "operation_id": "n68-test-operation"}))

    def test_existing_window_reuses(self):
        self.client.window_items = [self.client.window()]
        self.assertTrue(self.run_feature().evidence["verified"])
        self.assertNotIn("launch", self.client.events)
        self.assertEqual(self.client.events[-1], "lease_release")

    def test_new_window_delegated_pid(self):
        self.assertEqual("12345", self.run_feature().output["hwnd"])
        self.assertEqual(self.client.events.count("launch"), 1)
        self.assertEqual(self.client.events.count("lease_release"), 2)

    def test_no_foreground(self):
        self.client.window_items = [self.client.window()]
        self.run_feature(False)
        self.assertNotIn("activate", self.client.events)
        self.assertNotIn("lease_acquire", self.client.events)

    def test_unknown_launch_no_retry_and_release(self):
        self.client.fail_launch = True
        with self.assertRaises(UnknownEffectError):
            self.run_feature()
        self.assertEqual(self.client.events.count("launch"), 1)
        self.assertEqual(self.client.events[-1], "lease_release")

    def test_activation_unknown_releases(self):
        self.client.window_items = [self.client.window()]
        self.client.fail_activate = True
        with self.assertRaises(UnknownEffectError):
            self.run_feature()
        self.assertEqual(self.client.events[-1], "lease_release")

    def test_wrong_desktop_fingerprint_rejects(self):
        self.client.window_items = [self.client.window()]
        self.client.other_desktop = True
        with self.assertRaises(UnknownEffectError):
            self.run_feature()
        self.assertNotIn("activate", self.client.events)
        self.assertEqual(self.client.events[-1], "lease_release")

    def test_minimized_restored(self):
        win = self.client.window()
        win["minimized"] = True
        self.client.window_items = [win]
        self.run_feature()
        self.assertIn("restore", self.client.events)
        self.assertLess(self.client.events.index("restore"), self.client.events.index("activate"))

    def test_release_unknown_fail_closed(self):
        self.client.window_items = [self.client.window()]
        self.client.fail_release = True
        with self.assertRaisesRegex(UnknownEffectError, "LEASE_RELEASE_UNVERIFIED"):
            self.run_feature()

    def test_real_shell_registration_delay_reconciled_without_relaunch(self):
        original = self.client.explorer_windows
        post_reads = []

        def late_read(*, request_id, **kwargs):
            if ":after-launch-" in request_id:
                post_reads.append(request_id)
                if len(post_reads) == 1:
                    prior = self.client.window_items
                    self.client.window_items = []
                    try:
                        return original(request_id=request_id, **kwargs)
                    finally:
                        self.client.window_items = prior
            return original(request_id=request_id, **kwargs)

        with patch.object(self.client, "explorer_windows", side_effect=late_read):
            with patch("bct.features.desktop_explorer_folder.time.sleep"):
                result = self.run_feature(False)
        self.assertTrue(result.evidence["verified"])
        self.assertEqual(1, self.client.events.count("launch"))
        self.assertEqual(2, len(post_reads))
        self.assertEqual("lease_release", self.client.events[-1])

    def test_shell_not_appearing_never_relaunches(self):
        from bct.core.models import ConfirmedFailure
        self.client.window_items = []
        with patch.object(self.client, "launch") as launch:
            launch.return_value = {"programLaunch": {"pid": 101}}
            with patch("bct.features.desktop_explorer_folder.time.sleep"):
                with self.assertRaisesRegex(ConfirmedFailure, "NOT_CONFIRMED"):
                    self.run_feature(False)
        launch.assert_called_once()
        self.assertEqual("lease_release", self.client.events[-1])

    def test_reject_missing_folder(self):
        with self.assertRaises(PreconditionError):
            self.feature.prepare(work=self.work, arguments={"folder_path": str(self.root / "missing")})
