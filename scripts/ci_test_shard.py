from __future__ import annotations

import argparse
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_HEAVY_SECONDS = {
    "test_deployment_service": 135.0,
    "test_orchestration": 85.0,
    "test_durable_pr2": 25.0,
    "test_github_integration": 18.0,
    "test_mcp_integration": 12.0,
    "test_protected_operating_paths": 10.0,
    "test_rcc_integration": 10.0,
}


@dataclass(frozen=True)
class TestModule:
    name: str
    cases: tuple[unittest.TestCase, ...]
    weight: float

    @property
    def test_count(self) -> int:
        return len(self.cases)


@dataclass(frozen=True)
class TestInventory:
    modules: tuple[TestModule, ...]
    discovered_instances: int
    unique_test_ids: int
    duplicate_instances_removed: int


def _flatten(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def discover_inventory(start_directory: Path) -> TestInventory:
    root = start_directory.resolve()
    # The historical discovery contract exposes both `test_core` and
    # `tests.test_core` imports. Keep both roots available while cases execute.
    for value in (str(root.parent), str(root)):
        if value not in sys.path:
            sys.path.insert(0, value)
    loader = unittest.TestLoader()
    suite = loader.discover(str(root))
    if loader.errors:
        raise RuntimeError("\n".join(loader.errors))
    discovered = list(_flatten(suite))
    unique: dict[str, unittest.TestCase] = {}
    for case in discovered:
        identity = case.id()
        previous = unique.get(identity)
        if previous is None:
            unique[identity] = case
            continue
        if (
            type(previous) is not type(case)
            or getattr(previous, "_testMethodName", None) != getattr(case, "_testMethodName", None)
            or vars(previous) != vars(case)
        ):
            raise RuntimeError("AMBIGUOUS_DUPLICATE_TEST_ID:" + identity)

    grouped: dict[str, list[unittest.TestCase]] = {}
    for case in unique.values():
        grouped.setdefault(type(case).__module__, []).append(case)
    modules = tuple(
        TestModule(
            name=name,
            cases=tuple(sorted(cases, key=lambda case: case.id())),
            weight=max(float(len(cases)), _HEAVY_SECONDS.get(name, 0.0)),
        )
        for name, cases in sorted(grouped.items())
    )
    return TestInventory(
        modules=modules,
        discovered_instances=len(discovered),
        unique_test_ids=len(unique),
        duplicate_instances_removed=len(discovered) - len(unique),
    )


def discover_modules(start_directory: Path) -> list[TestModule]:
    return list(discover_inventory(start_directory).modules)


def shard_plan(modules: list[TestModule], shard_count: int) -> list[list[TestModule]]:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    shards: list[list[TestModule]] = [[] for _ in range(shard_count)]
    weights = [0.0] * shard_count
    for module in sorted(modules, key=lambda item: (-item.weight, item.name)):
        index = min(range(shard_count), key=lambda value: (weights[value], value))
        shards[index].append(module)
        weights[index] += module.weight
    for shard in shards:
        shard.sort(key=lambda item: item.name)
    return shards


def manifest(start_directory: Path, shard_count: int) -> dict[str, object]:
    inventory = discover_inventory(start_directory)
    shards = shard_plan(list(inventory.modules), shard_count)
    return {
        "discovered_instances": inventory.discovered_instances,
        "unique_test_ids": inventory.unique_test_ids,
        "duplicate_instances_removed": inventory.duplicate_instances_removed,
        "module_count": len(inventory.modules),
        "shards": [
            {
                "index": index,
                "estimated_weight": sum(module.weight for module in shard),
                "test_count": sum(module.test_count for module in shard),
                "modules": [module.name for module in shard],
            }
            for index, shard in enumerate(shards)
        ],
    }


def run(start_directory: Path, shard_index: int, shard_count: int, durations: int) -> bool:
    inventory = discover_inventory(start_directory)
    shards = shard_plan(list(inventory.modules), shard_count)
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index outside shard_count")
    selected = shards[shard_index]
    cases = [case for module in selected for case in module.cases]
    print(json.dumps({
        "shard": shard_index,
        "shard_count": shard_count,
        "estimated_weight": sum(item.weight for item in selected),
        "test_count": len(cases),
        "discovered_instances": inventory.discovered_instances,
        "unique_test_ids": inventory.unique_test_ids,
        "duplicate_instances_removed": inventory.duplicate_instances_removed,
        "modules": [item.name for item in selected],
    }, sort_keys=True))
    kwargs = {"verbosity": 2}
    if sys.version_info >= (3, 12):
        kwargs["durations"] = durations
    result = unittest.TextTestRunner(**kwargs).run(unittest.TestSuite(cases))
    return result.wasSuccessful()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-directory", default="tests")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument("--durations", type=int, default=20)
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    start = Path(args.start_directory)
    if args.manifest:
        print(json.dumps(manifest(start, args.shard_count), indent=2, sort_keys=True))
        return 0
    if args.shard_index is None:
        parser.error("--shard-index is required unless --manifest is used")
    return 0 if run(start, args.shard_index, args.shard_count, args.durations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
