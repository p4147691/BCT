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
        self.assertTrue(plan.docs_only)
        self.assertFalse(plan.core)
        self.assertFalse(plan.bridge)
        self.assertFalse(plan.vtl)

    def test_desktop_change_runs_core_and_vtl_but_not_independent_transport(self):
        plan = scope.classify(["src/bct/features/desktop_session.py"])
        self.assertFalse(plan.docs_only)
        self.assertTrue(plan.core)
        self.assertFalse(plan.bridge)
        self.assertTrue(plan.vtl)

    def test_browser_contract_runs_between_bounded_cleanup_and_rebuild(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("fail-fast: false", workflow)
        cleanup = workflow.index(
            "Remove only launcher artifacts created by the fail-fast build"
        )
        contract = workflow.index(
            "python -m unittest discover -s modules/browser-bridge/tests -v"
        )
        rebuild = workflow.index(
            "Rebuild launcher for the remaining Windows E2E checks"
        )
        self.assertLess(cleanup, contract)
        self.assertLess(contract, rebuild)

    def test_bridge_only_does_not_run_the_743_test_core(self):
        plan = scope.classify(["modules/browser-bridge/host.py"])
        self.assertFalse(plan.core)
        self.assertTrue(plan.bridge)
        self.assertFalse(plan.vtl)

    def test_unknown_non_document_path_fails_closed(self):
        plan = scope.classify(["new-platform-boundary.bin"])
        self.assertTrue(plan.core)
        self.assertFalse(plan.bridge)

    def test_ci_change_exercises_every_gate(self):
        plan = scope.classify([".github/workflows/ci.yml"])
        self.assertTrue(plan.core)
        self.assertFalse(plan.bridge)
        self.assertTrue(plan.vtl)

    def test_bridge_baseline_change_runs_only_its_own_gate(self):
        plan = scope.classify(["tests/test_browser_module_baselines.py"])
        self.assertFalse(plan.core)
        self.assertTrue(plan.bridge)
        self.assertFalse(plan.vtl)

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
        cases = [unit.case for shard in sharding.test_shard_plan(
            sharding.test_units(inventory), 4
        ) for unit in shard]
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
