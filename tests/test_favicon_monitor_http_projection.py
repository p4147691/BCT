"""Regression: public /monitor/state must use the same RCC provenance paths as bct_status.

This prevents a valid N-number projection from being silently suppressed with
SOURCE_MISSING when the HTTP handler omits both paths.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


class FaviconMonitorHttpProjectionTests(unittest.TestCase):
    def test_public_and_mcp_monitor_provenance_path_parity(self):
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

        for method_name, method in methods.items():
            calls = [
                node for node in ast.walk(method)
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name) and node.func.id == "build_monitor_state"
                    or isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"
                    and node.args and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "build_monitor_state"
                )
            ]
            self.assertEqual(1, len(calls), method_name)
            names = {keyword.arg: keyword.value for keyword in calls[0].keywords}
            self.assertEqual(
                "RCC_BACKGROUND_SOURCE_PATH",
                getattr(names.get("rcc_source_path"), "id", None),
                method_name,
            )
            self.assertEqual(
                "RCC_BACKGROUND_LIVE_PATH",
                getattr(names.get("rcc_live_path"), "id", None),
                method_name,
            )

    def test_source_paths_are_regular_constants(self):
        source = (Path(__file__).resolve().parents[1]
                  / "src" / "bct" / "runtime_server.py").read_text(encoding="utf-8")
        self.assertIn("RCC_BACKGROUND_SOURCE_PATH = Path(", source)
        self.assertIn("RCC_BACKGROUND_LIVE_PATH = Path(", source)


if __name__ == "__main__":
    unittest.main()
