import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("version_gate",
    Path(__file__).resolve().parents[1] / "scripts/check_extension_versions.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class VersionGateTests(unittest.TestCase):
    def test_changed_payload_requires_increase(self):
        for value in ("1.0.70", "1.0.69", "1.0.70.0"):
            with self.assertRaisesRegex(ValueError, "NOT_INCREASED"):
                gate.validate_identity({"version": "1.0.70"},
                                       {"version": value, "version_name": value})

    def test_version_name_must_show_actual_version(self):
        with self.assertRaisesRegex(ValueError, "NAME_MISMATCH"):
            gate.validate_identity({"version": "1.0.70"},
                                   {"version": "1.0.71", "version_name": "1.0.70 Old"})

    def test_rcc_ids_change_and_match(self):
        for builds in (("old", "old"), ("new", "old"), ("", "")):
            with self.assertRaisesRegex(ValueError, "BUILD_ID"):
                gate.validate_identity({"version": "1.0.70"},
                    {"version": "1.0.71", "version_name": "1.0.71 New"},
                    before_builds=("old", "old"), after_builds=builds)
        gate.validate_identity({"version": "1.0.70"},
            {"version": "1.0.71", "version_name": "1.0.71 New"},
            before_builds=("old", "old"), after_builds=("new", "new"))

    def test_invalid_chrome_versions(self):
        for value in ("1.01", "1.0.beta", "1.0.70000", "1.2.3.4.5", "0", None):
            with self.assertRaises(ValueError):
                gate.version(value)

    def test_unchanged_targets_need_no_cosmetic_bump(self):
        self.assertEqual(["UNCHANGED", "UNCHANGED"],
                         [r["status"] for r in gate.check("base", "head", lambda *a: "")])
