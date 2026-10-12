from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bct.service_runtime import atomic_json
from bct.supervisor import ensure_service


class SupervisorTests(unittest.TestCase):
    def _current(self, root: Path) -> dict:
        release = root / "releases" / ("a" * 40)
        release.mkdir(parents=True)
        (release / "bct.toml").write_text("[deployment.profiles.test]\n", encoding="utf-8")
        value = {
            "source_head": "a" * 40,
            "manifest_sha256": "b" * 64,
            "release_path": str(release),
        }
        atomic_json(root / "current.json", value)
        return value

    def test_running_exact_release_is_accepted_without_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._current(root)
            profile = SimpleNamespace(runtime_root=root.resolve(), service_name="bct-core", port=18790)
            controller = Mock()
            controller.inspect.return_value = {
                "state": "RUNNING", "release_sha": current["source_head"],
                "manifest_sha256": current["manifest_sha256"], "pid": 42,
            }
            with patch("bct.supervisor.DeploymentProfiles.get", return_value=profile), patch(
                "bct.supervisor._validate_release"
            ), patch("bct.supervisor.RuntimeServiceController", return_value=controller):
                result = ensure_service(runtime_root=root, profile_name="test")
            self.assertTrue(result["already_running"])
            controller.start.assert_not_called()

    def test_stopped_exact_release_starts_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._current(root)
            profile = SimpleNamespace(runtime_root=root.resolve(), service_name="bct-core", port=18790)
            controller = Mock()
            controller.inspect.return_value = {"state": "STOPPED"}
            with patch("bct.supervisor.DeploymentProfiles.get", return_value=profile), patch(
                "bct.supervisor._validate_release"
            ), patch("bct.supervisor.RuntimeServiceController", return_value=controller), patch(
                "bct.supervisor._start_with_one_safe_retry", return_value={"state": "RUNNING", "pid": 43}
            ) as start:
                result = ensure_service(runtime_root=root, profile_name="test")
            self.assertEqual(43, result["pid"])
            start.assert_called_once_with(controller, current)

    def test_different_running_release_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._current(root)
            profile = SimpleNamespace(runtime_root=root.resolve(), service_name="bct-core", port=18790)
            controller = Mock()
            controller.inspect.return_value = {
                "state": "RUNNING", "release_sha": "c" * 40,
                "manifest_sha256": "d" * 64,
            }
            with patch("bct.supervisor.DeploymentProfiles.get", return_value=profile), patch(
                "bct.supervisor._validate_release"
            ), patch("bct.supervisor.RuntimeServiceController", return_value=controller):
                with self.assertRaisesRegex(RuntimeError, "BCT_DIFFERENT_RELEASE_RUNNING"):
                    ensure_service(runtime_root=root, profile_name="test")


if __name__ == "__main__":
    unittest.main()
