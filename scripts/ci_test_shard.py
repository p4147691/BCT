from __future__ import annotations

import argparse
import json
import sys
import time
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


@dataclass(frozen=True)
class TestUnit:
    identity: str
    module: str
    cases: tuple[unittest.TestCase, ...]
    weight: float


# These tests create and tear down real process/OS resources whose guarantees
# were originally proven with module-serial execution.  Keep only those narrow
# modules indivisible; ordinary pure tests remain eligible for fine balancing.
_ATOMIC_MODULES = frozenset({
    "test_rcc_native_pipe_acl_windows",
})


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


def load_durations(paths: list[Path] | tuple[Path, ...]) -> dict[str, float]:
    """Load optional timing artifacts without making the cache a CI dependency."""
    durations: dict[str, float] = {}
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        tests = value.get("tests") if isinstance(value, dict) else None
        if not isinstance(tests, dict):
            continue
        for identity, seconds in tests.items():
            try:
                duration = float(seconds)
            except (TypeError, ValueError, OverflowError):
                continue
            if isinstance(identity, str) and identity and 0 <= duration <= 3600:
                durations[identity] = max(duration, 0.001)
    return durations


def test_units(
    inventory: TestInventory, durations: dict[str, float] | None = None,
) -> list[TestUnit]:
    measured = durations or {}
    units: list[TestUnit] = []
    for module in inventory.modules:
        fallback = max(1.0, module.weight / max(1, module.test_count))
        if module.name in _ATOMIC_MODULES:
            identities = tuple(case.id() for case in module.cases)
            units.append(TestUnit(
                identity="module:" + module.name,
                module=module.name,
                cases=module.cases,
                weight=sum(measured.get(identity, fallback) for identity in identities),
            ))
            continue
        for case in module.cases:
            identity = case.id()
            units.append(TestUnit(
                identity=identity,
                module=module.name,
                cases=(case,),
                weight=measured.get(identity, fallback),
            ))
    return units


def test_shard_plan(units: list[TestUnit], shard_count: int) -> list[list[TestUnit]]:
    """Balance at test granularity; module-only sharding caused a 3.4x skew."""
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    shards: list[list[TestUnit]] = [[] for _ in range(shard_count)]
    weights = [0.0] * shard_count
    for unit in sorted(units, key=lambda item: (-item.weight, item.identity)):
        index = min(range(shard_count), key=lambda value: (weights[value], value))
        shards[index].append(unit)
        weights[index] += unit.weight
    for shard in shards:
        shard.sort(key=lambda item: item.identity)
    return shards


class _TimedTextResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_durations: dict[str, float] = {}
        self._test_started: dict[str, float] = {}

    def startTest(self, test):  # noqa: N802 - unittest API
        self._test_started[test.id()] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):  # noqa: N802 - unittest API
        started = self._test_started.pop(test.id(), time.perf_counter())
        self.test_durations[test.id()] = max(0.0, time.perf_counter() - started)
        super().stopTest(test)


def manifest(
    start_directory: Path, shard_count: int,
    duration_paths: list[Path] | tuple[Path, ...] = (),
) -> dict[str, object]:
    inventory = discover_inventory(start_directory)
    measured = load_durations(duration_paths)
    shards = test_shard_plan(test_units(inventory, measured), shard_count)
    return {
        "discovered_instances": inventory.discovered_instances,
        "unique_test_ids": inventory.unique_test_ids,
        "duplicate_instances_removed": inventory.duplicate_instances_removed,
        "module_count": len(inventory.modules),
        "measured_test_count": len(measured),
        "shards": [
            {
                "index": index,
                "estimated_weight": sum(unit.weight for unit in shard),
                "test_count": sum(len(unit.cases) for unit in shard),
                "modules": sorted({unit.module for unit in shard}),
                "tests": [case.id() for unit in shard for case in unit.cases],
            }
            for index, shard in enumerate(shards)
        ],
    }


def run(
    start_directory: Path, shard_index: int, shard_count: int, durations: int,
    *, duration_paths: list[Path] | tuple[Path, ...] = (),
    duration_output: Path | None = None,
) -> bool:
    inventory = discover_inventory(start_directory)
    measured = load_durations(duration_paths)
    shards = test_shard_plan(test_units(inventory, measured), shard_count)
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index outside shard_count")
    selected = shards[shard_index]
    cases = [case for unit in selected for case in unit.cases]
    print(json.dumps({
        "shard": shard_index,
        "shard_count": shard_count,
        "estimated_weight": sum(item.weight for item in selected),
        "test_count": len(cases),
        "discovered_instances": inventory.discovered_instances,
        "unique_test_ids": inventory.unique_test_ids,
        "duplicate_instances_removed": inventory.duplicate_instances_removed,
        "measured_test_count": len(measured),
        "modules": sorted({item.module for item in selected}),
    }, sort_keys=True))
    kwargs = {"verbosity": 2}
    if sys.version_info >= (3, 12):
        kwargs["durations"] = durations
    kwargs["resultclass"] = _TimedTextResult
    result = unittest.TextTestRunner(**kwargs).run(unittest.TestSuite(cases))
    if duration_output is not None:
        duration_output.write_text(json.dumps({
            "schema": 1,
            "shard": shard_index,
            "shard_count": shard_count,
            "tests": result.test_durations,
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result.wasSuccessful()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-directory", default="tests")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument("--durations", type=int, default=20)
    parser.add_argument("--duration-input", action="append", default=[])
    parser.add_argument("--duration-output")
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    start = Path(args.start_directory)
    if args.manifest:
        print(json.dumps(manifest(
            start, args.shard_count, [Path(value) for value in args.duration_input]
        ), indent=2, sort_keys=True))
        return 0
    if args.shard_index is None:
        parser.error("--shard-index is required unless --manifest is used")
    return 0 if run(
        start, args.shard_index, args.shard_count, args.durations,
        duration_paths=[Path(value) for value in args.duration_input],
        duration_output=Path(args.duration_output) if args.duration_output else None,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
