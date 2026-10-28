import tempfile
import unittest
from pathlib import Path
from bct.integrations.explorer_folder_open import (
    ExplorerFolderError, normalize_folder_path, select_exact_explorer,
)


class TestExplorerFolderOpen(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = normalize_folder_path(self.temp.name)
        self.win = dict(processName="explorer", className="CabinetWClass", hwnd="123",
                        pid=400, virtualDesktopId="current")

    def inventory(self, items=None, **changes):
        items = [self.win] if items is None else items
        result = {"windows": {"truncated": False, "inspectionAvailable": True},
                  "applicationWindows": {"application": "explorer",
                                         "folderPath": self.folder, "items": items,
                                         "count": len(items), "truncated": False}}
        result.update(changes)
        return result

    def test_existing_folder_reuse(self):
        d = select_exact_explorer(self.folder, self.inventory())
        self.assertEqual(("reuse", "123"), (d.action, d.hwnd))

    def test_new_folder_needs_authorized_launch(self):
        self.assertEqual("open", select_exact_explorer(self.folder, self.inventory([])).action)

    def test_pid_independent(self):
        alternate = dict(self.win, pid=999)
        self.assertEqual("reuse", select_exact_explorer(self.folder, self.inventory([alternate])).action)

    def test_ambiguous_rejected(self):
        with self.assertRaisesRegex(ExplorerFolderError, "AMBIGUOUS"):
            select_exact_explorer(self.folder, self.inventory([self.win, dict(self.win, hwnd="456")]))

    def test_truncated_rejected(self):
        data = self.inventory()
        data["windows"]["truncated"] = True
        with self.assertRaisesRegex(ExplorerFolderError, "INCOMPLETE"):
            select_exact_explorer(self.folder, data)

    def test_inspection_unavailable_rejected(self):
        data = self.inventory()
        data["windows"]["inspectionAvailable"] = False
        with self.assertRaisesRegex(ExplorerFolderError, "INCOMPLETE"):
            select_exact_explorer(self.folder, data)

    def test_wrong_folder_rejected(self):
        data = self.inventory()
        data["applicationWindows"]["folderPath"] += "other"
        with self.assertRaisesRegex(ExplorerFolderError, "MISMATCH"):
            select_exact_explorer(self.folder, data)

    def test_invalid_window_rejected(self):
        bad = dict(self.win, processName="chrome")
        with self.assertRaisesRegex(ExplorerFolderError, "IDENTITY"):
            select_exact_explorer(self.folder, self.inventory([bad]))

    def test_nonexistent_folder(self):
        with self.assertRaises(ExplorerFolderError):
            normalize_folder_path(str(Path(self.folder) / "absent"))

    def test_file_rejected(self):
        f = Path(self.folder) / "file.txt"
        f.write_text("test", encoding="utf8")
        with self.assertRaises(ExplorerFolderError):
            normalize_folder_path(str(f))


class TestExplorerOrchestration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = normalize_folder_path(self.tmp.name)
        self.calls = []
        self.existing = True
        self.launch_error = False
        self.activate_error = False
        self.window = dict(processName="explorer", className="CabinetWClass",
                           hwnd="123", pid=999, isMinimized=False)

    def invoke(self, capability, args):
        self.calls.append((capability, args))
        if capability == "desktop_application_target":
            if args["operation"] == "bind":
                return {"control": {"lease": {"leaseId": "b"*32}},
                        "applicationTarget": {"window": self.window}}
            items = [self.window] if self.existing else []
            return {"windows": {"truncated": False, "inspectionAvailable": True},
                    "applicationWindows": {"application": "explorer",
                                           "folderPath": self.folder, "items": items,
                                           "count": len(items), "truncated": False}}
        if capability == "desktop_control_lease":
            return {"control": {"lease": {"leaseId": "a"*32}}}
        if capability == "desktop_program_launch":
            self.existing = True
            if self.launch_error:
                raise RuntimeError("LAUNCH_PID_EXIT")
            return {}
        if capability == "desktop_window_activate" and self.activate_error:
            raise RuntimeError("ACTIVATE_FAILED")
        return {}

    def test_reuses_without_launch(self):
        from bct.integrations.explorer_folder_open import open_explorer_folder
        result = open_explorer_folder(self.folder, self.invoke)
        self.assertEqual("123", result["hwnd"])
        self.assertFalse(any(c == "desktop_program_launch" for c, _ in self.calls))
        self.assertEqual("release", self.calls[-1][1]["operation"])

    def test_open_with_other_pid(self):
        from bct.integrations.explorer_folder_open import open_explorer_folder
        self.existing = False
        self.assertEqual("123", open_explorer_folder(self.folder, self.invoke)["hwnd"])
        self.assertEqual(1, sum(c == "desktop_program_launch" for c, _ in self.calls))
        self.assertEqual(2, sum(c == "desktop_control_lease" and a["operation"] == "release" for c,a in self.calls))

    def test_pid_exit_reconciles_without_retry(self):
        from bct.integrations.explorer_folder_open import open_explorer_folder
        self.existing = False
        self.launch_error = True
        self.assertTrue(open_explorer_folder(self.folder, self.invoke)["verified"])
        self.assertEqual(1, sum(c == "desktop_program_launch" for c,_ in self.calls))

    def test_activation_failure_releases(self):
        from bct.integrations.explorer_folder_open import open_explorer_folder
        self.activate_error = True
        with self.assertRaisesRegex(RuntimeError, "ACTIVATE_FAILED"):
            open_explorer_folder(self.folder, self.invoke)
        self.assertEqual("release", self.calls[-1][1]["operation"])

    def test_no_foreground_keeps_focus(self):
        from bct.integrations.explorer_folder_open import open_explorer_folder
        open_explorer_folder(self.folder, self.invoke, foreground=False)
        self.assertFalse(any(c == "desktop_window_activate" for c,_ in self.calls))
