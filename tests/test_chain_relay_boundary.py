"""Architectural guard: Chain planning is independent of legacy Relay Control."""
from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1] / "src" / "bct"


class ChainRelayBoundaryTests(unittest.TestCase):
    def test_chain_direction_and_plan_do_not_import_relay_control(self):
        for name in ("chain_direction.py", "chain_execution_plan.py"):
            with self.subTest(module=name):
                tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imports.append(node.module or "")
                self.assertFalse(
                    any("relay_control" in name or "relay_executor" in name
                        or "relay_settings" in name for name in imports),
                    imports,
                )

    def test_relay_registry_does_not_own_chain_plan_commands(self):
        from bct.relay_executor import runtime_registry_catalog
        registry = runtime_registry_catalog()
        self.assertFalse(any("chain" in driver or "chain" in call
                             or "task_run" in call
                             for driver, call in registry))


if __name__ == "__main__":
    unittest.main()
