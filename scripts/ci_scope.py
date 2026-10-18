from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class CIPlan:
    docs_only: bool
    core: bool
    bridge: bool
    vtl: bool


_GLOBAL_CI_PATHS = {
    ".github/workflows/ci.yml",
    "pyproject.toml",
    "scripts/ci_scope.py",
    "scripts/ci_test_shard.py",
    "scripts/vtl_readonly_smoke.py",
    "tests/test_ci_acceleration.py",
}
_DESKTOP_PATHS = {
    "src/bct/features/desktop_session.py",
    "src/bct/integrations/desktop_session.py",
    "src/bct/mcp_server.py",
    "tests/test_desktop_session.py",
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


def classify(paths: list[str]) -> CIPlan:
    changed = {_normal(path) for path in paths if path.strip()}
    if not changed or all(_documentation(path) for path in changed):
        return CIPlan(docs_only=True, core=False, bridge=False, vtl=False)

    active = {path for path in changed if not _documentation(path)}
    global_change = bool(active & _GLOBAL_CI_PATHS)
    bridge_only = all(path.startswith("modules/browser-bridge/") for path in active)
    core = global_change or not bridge_only
    bridge = core or any(
        path.startswith("modules/browser-bridge/")
        or path.startswith("src/bct/")
        for path in active
    )
    vtl = global_change or bool(active & _DESKTOP_PATHS) or any(
        "desktop_session" in path or path.startswith("scripts/vtl_")
        for path in active
    )
    return CIPlan(docs_only=False, core=core, bridge=bridge, vtl=vtl)


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
