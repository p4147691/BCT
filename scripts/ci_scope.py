from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


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


def classify(paths: list[str]) -> CIPlan:
    changed = {_normal(path) for path in paths if path.strip()}
    if not changed or all(_can_skip_validation(path) for path in changed):
        return CIPlan(skip=True, core=False)

    # New or mixed paths remain conservative: run Core unless the complete
    # change set is documentation, Monitor UI, or the parked Browser Bridge.
    return CIPlan(skip=False, core=True)


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
    args = parser.parse_args()

    paths = changed_paths(args.base, args.head)
    plan = classify(paths)
    value = {**asdict(plan), "changed": paths}
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as stream:
            for key, enabled in asdict(plan).items():
                stream.write(f"{key}={str(enabled).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
