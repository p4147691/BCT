from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class CIPlan:
    skip: bool
    core: bool


_LIGHTWEIGHT_PREFIXES = (
    "modules/browser-bridge/",
    "modules/monitor/",
)
_LIGHTWEIGHT_PATHS = {
    "tests/test_browser_module_baselines.py",
}


def _normal(path: str) -> str:
    value = str(PurePosixPath(path.replace("\\", "/")))
    return value[2:] if value.startswith("./") else value


def _documentation(path: str) -> bool:
    value = _normal(path)
    return (
        value.startswith("docs/")
        or value.startswith("modules/browser-bridge/docs/")
        or PurePosixPath(value).suffix.casefold() in {".md", ".mdc"}
    )


def _can_skip_validation(path: str) -> bool:
    value = _normal(path)
    return (
        _documentation(value)
        or value.startswith(_LIGHTWEIGHT_PREFIXES)
        or value in _LIGHTWEIGHT_PATHS
    )


def select_impact(paths: list[str], report: dict[str, Any] | None) -> dict[str, Any]:
    """Expand changed files through a verified Code Block Scan dependency map.

    The map may reduce a lightweight change only when it is complete and every
    changed source file is indexed.  Missing, partial, malformed, or unknown
    evidence fails closed to the ordinary Core scope.
    """
    changed = {_normal(path) for path in paths if path.strip()}
    if report is None:
        return {"mode": "PATH_ONLY", "reason": "BLOCK_MAP_NOT_SUPPLIED",
                "affected": sorted(changed), "trusted": False}
    if (report.get("schema") != "bct.code-block-scan.v1"
            or report.get("status") != "OK"
            or report.get("scan", {}).get("complete") is not True):
        return {"mode": "FAIL_CLOSED", "reason": "BLOCK_MAP_INCOMPLETE",
                "affected": sorted(changed), "trusted": False}
    block_map = report.get("block_map")
    if not isinstance(block_map, dict):
        return {"mode": "FAIL_CLOSED", "reason": "BLOCK_MAP_INVALID",
                "affected": sorted(changed), "trusted": False}
    indexed = {
        _normal(str(row.get("path", "")))
        for row in block_map.get("files", []) if isinstance(row, dict)
    }
    source_changes = {path for path in changed if not _documentation(path)}
    missing = sorted(path for path in source_changes if path not in indexed)
    if missing:
        return {"mode": "FAIL_CLOSED", "reason": "CHANGED_SOURCE_NOT_INDEXED",
                "affected": sorted(changed), "missing": missing, "trusted": False}

    affected = set(changed)
    edges: list[tuple[str, str]] = []
    for edge in block_map.get("dependency_edges", []):
        if not isinstance(edge, dict) or str(edge.get("resolved", "")).lower() != "true":
            continue
        source = _normal(str(edge.get("from", "")))
        target = _normal(str(edge.get("to", "")))
        if source in indexed and target in indexed:
            edges.append((source, target))
    changed_count = -1
    while changed_count != len(affected):
        changed_count = len(affected)
        affected.update(source for source, target in edges if target in affected)
    return {
        "mode": "BLOCK_MAP", "reason": "DEPENDENCY_CLOSURE_SELECTED",
        "affected": sorted(affected), "trusted": True,
        "scan_fingerprint": report.get("scan", {}).get("scan_fingerprint", ""),
    }


def classify(paths: list[str], block_map_report: dict[str, Any] | None = None) -> CIPlan:
    changed = {_normal(path) for path in paths if path.strip()}
    impact = select_impact(paths, block_map_report)
    if impact["mode"] == "FAIL_CLOSED":
        return CIPlan(skip=False, core=True)
    affected = set(impact["affected"])
    if not changed or all(_can_skip_validation(path) for path in affected):
        return CIPlan(skip=True, core=False)

    # New or mixed paths remain conservative: run Core unless the complete
    # change set is documentation, Monitor UI, or the parked Browser Bridge.
    return CIPlan(skip=False, core=True)


def _scan_report(root: Path) -> dict[str, Any]:
    module_path = root / "src" / "bct" / "code_block_scan.py"
    spec = importlib.util.spec_from_file_location("bct_ci_code_block_scan", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("CODE_BLOCK_SCAN_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.scan(root, max_files=5000, max_blocks=10000)


def changed_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", base, head],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output")
    evidence = parser.add_mutually_exclusive_group()
    evidence.add_argument("--block-map", type=Path)
    evidence.add_argument("--scan-root", type=Path)
    args = parser.parse_args()

    paths = changed_paths(args.base, args.head)
    report = None
    try:
        if args.block_map:
            report = json.loads(args.block_map.read_text(encoding="utf-8-sig"))
        elif args.scan_root:
            report = _scan_report(args.scan_root.resolve())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        report = {"schema": "bct.code-block-scan.v1", "status": "PARTIAL",
                  "scan": {"complete": False}, "error": str(error)}
    impact = select_impact(paths, report)
    plan = classify(paths, report)
    value = {**asdict(plan), "changed": paths, "impact": impact}
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as stream:
            for key, enabled in asdict(plan).items():
                stream.write(f"{key}={str(enabled).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
