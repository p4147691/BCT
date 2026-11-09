"""Regression contracts for the public Monitor roster route."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


class FaviconMonitorHttpProjectionTests(unittest.TestCase):
    def test_public_monitor_route_uses_read_only_ui_snapshot(self):
        source = (Path(__file__).resolve().parents[1]
                  / "src" / "bct" / "runtime_server.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        methods = {
            node.name: node
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {"monitor_state", "status_snapshot"}
        }
        self.assertEqual({"monitor_state", "status_snapshot"}, set(methods))

        def threaded_target(method):
            calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"]
            self.assertEqual(1, len(calls))
            self.assertIsInstance(calls[0].args[0], ast.Name)
            return calls[0].args[0].id, {keyword.arg for keyword in calls[0].keywords}

        ui_target, ui_keywords = threaded_target(methods["monitor_state"])
        self.assertEqual("build_monitor_ui_state", ui_target)
        self.assertEqual({"store", "service_state", "data_root"}, ui_keywords)

        status_calls = [node for node in ast.walk(methods["status_snapshot"])
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "build_monitor_state"]
        self.assertEqual(1, len(status_calls))
        status_keywords = {keyword.arg for keyword in status_calls[0].keywords}
        self.assertEqual(
            {"store", "service_state", "data_root", "rcc_source_path", "rcc_live_path"},
            status_keywords,
        )

    def test_monitor_identity_dependencies_are_in_core_runtime_release(self):
        import tomllib
        profile_path = Path(__file__).resolve().parents[1] / "bct.toml"
        policy = tomllib.loads(profile_path.read_text(encoding="utf-8"))
        release_files = policy["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        for relative in (
            "src/bct/node_label_notifications.py",
            "src/bct/dot_identity.py",
            "src/bct/codex_surface.py",
        ):
            self.assertIn(relative, release_files)
            self.assertTrue((profile_path.parent / relative).is_file())

    def test_source_paths_are_regular_constants(self):
        source = (Path(__file__).resolve().parents[1]
                  / "src" / "bct" / "runtime_server.py").read_text(encoding="utf-8")
        self.assertIn("RCC_BACKGROUND_SOURCE_PATH = Path(", source)
        self.assertIn("RCC_BACKGROUND_LIVE_PATH = Path(", source)


if __name__ == "__main__":
    unittest.main()
