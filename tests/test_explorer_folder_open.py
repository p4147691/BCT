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
