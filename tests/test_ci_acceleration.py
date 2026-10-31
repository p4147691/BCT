from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scope = _load("bct_ci_scope", ROOT / "scripts" / "ci_scope.py")
sharding = _load("bct_ci_test_shard", ROOT / "scripts" / "ci_test_shard.py")


class CIScopeTests(unittest.TestCase):
    def test_documentation_only_is_lightweight(self):
        plan = scope.classify(["PROJECT_HANDOFF.md", "docs/guide.md"])
        self.assertTrue(plan.skip)
        self.assertFalse(plan.core)

    def test_core_change_runs_core_validation(self):
        plan = scope.classify(["src/bct/features/desktop_session.py"])
        self.assertFalse(plan.skip)
        self.assertTrue(plan.core)

    def test_monitor_and_browser_bridge_only_changes_are_parked(self):
        monitor = scope.classify(["modules/monitor/domains/node-identity.js"])
        bridge = scope.classify(["modules/browser-bridge/host.py"])
        baseline = scope.classify(["tests/test_browser_module_baselines.py"])
        self.assertTrue(monitor.skip)
        self.assertFalse(monitor.core)
        self.assertTrue(bridge.skip)
        self.assertFalse(bridge.core)
        self.assertTrue(baseline.skip)
        self.assertFalse(baseline.core)

    def test_workflow_has_no_browser_bridge_or_timing_jobs(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("fail-fast: false", workflow)
        self.assertNotIn("browser-bridge", workflow)
        self.assertNotIn("duration-history", workflow)
        self.assertNotIn("actions/upload-artifact", workflow)
        self.assertNotIn("actions/cache/restore", workflow)
        self.assertNotIn("actions/cache/save", workflow)

    def test_unknown_non_document_path_fails_closed(self):
        plan = scope.classify(["new-platform-boundary.bin"])
        self.assertFalse(plan.skip)
        self.assertTrue(plan.core)

    def test_ci_change_runs_core(self):
        plan = scope.classify([".github/workflows/ci.yml"])
        self.assertFalse(plan.skip)
        self.assertTrue(plan.core)

class CIShardTests(unittest.TestCase):
    def test_every_discovered_module_is_assigned_once_and_deterministically(self):
        modules = sharding.discover_modules(ROOT / "tests")
        first = sharding.shard_plan(modules, 4)
        second = sharding.shard_plan(list(reversed(modules)), 4)
        expected = sorted(module.name for module in modules)
        self.assertEqual(expected, sorted(module.name for shard in first for module in shard))
        self.assertEqual(
            [[item.name for item in shard] for shard in first],
            [[item.name for item in shard] for shard in second],
        )
        self.assertEqual(len(expected), len(set(expected)))

    def test_shard_union_matches_unittest_discovery_count(self):
        test_root = ROOT / "tests"
        inventory = sharding.discover_inventory(test_root)
        cases = [case for shard in sharding.test_shard_plan(
            sharding.test_units(inventory), 4
        ) for unit in shard for case in unit.cases]
        identities = [case.id() for case in cases]
        self.assertEqual(inventory.unique_test_ids, len(identities))
        self.assertEqual(len(identities), len(set(identities)))
        self.assertGreater(inventory.duplicate_instances_removed, 0)
        self.assertEqual(
            inventory.discovered_instances,
            inventory.unique_test_ids + inventory.duplicate_instances_removed,
        )

    def test_heavy_modules_are_distributed(self):
        modules = [
            sharding.TestModule("test_deployment_service", (), 135.0),
            sharding.TestModule("test_orchestration", (), 85.0),
            sharding.TestModule("test_small", (), 1.0),
        ]
        plan = sharding.shard_plan(modules, 2)
        locations = {
            item.name: index for index, shard in enumerate(plan) for item in shard
        }
        self.assertNotEqual(
            locations["test_deployment_service"], locations["test_orchestration"]
        )

    def test_slow_tests_from_one_module_are_distributed_by_measured_duration(self):
        class SlowCase(unittest.TestCase):
            def test_a(self):
                pass

            def test_b(self):
                pass

            def test_c(self):
                pass

        cases = tuple(SlowCase(name) for name in ("test_a", "test_b", "test_c"))
        inventory = sharding.TestInventory(
            modules=(sharding.TestModule("slow", cases, 3.0),),
            discovered_instances=3, unique_test_ids=3,
            duplicate_instances_removed=0,
        )
        durations = {case.id(): 30.0 - index for index, case in enumerate(cases)}
        plan = sharding.test_shard_plan(
            sharding.test_units(inventory, durations), 3
        )
        self.assertEqual([1, 1, 1], [len(shard) for shard in plan])

    def test_real_named_pipe_module_stays_in_one_serial_unit(self):
        inventory = sharding.discover_inventory(ROOT / "tests")
        units = [
            unit for unit in sharding.test_units(inventory)
            if unit.module == "test_rcc_native_pipe_acl_windows"
        ]
        self.assertEqual(1, len(units))
        self.assertGreater(len(units[0].cases), 1)
        self.assertEqual(
            sorted(case.id() for case in units[0].cases),
            sorted(case.id() for case in next(
                module for module in inventory.modules
                if module.name == "test_rcc_native_pipe_acl_windows"
            ).cases),
        )

    def test_seed_is_optional_bounded_and_covers_the_known_slowest_tests(self):
        path = ROOT / "scripts" / "ci_test_duration_seed.json"
        measured = sharding.load_durations([path, path.with_name("missing.json")])
        self.assertGreaterEqual(len(measured), 7)
        self.assertLessEqual(len(measured), 100)
        self.assertGreater(
            measured[
                "test_deployment_service.DeploymentServiceTests."
                "test_new_release_restarts_and_broken_release_rolls_back"
            ],
            30.0,
        )


if __name__ == "__main__":
    unittest.main()
