from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bct.features.deploy import DeploymentProfiles, _start_with_one_safe_retry, _validate_release
from bct.service_runtime import RuntimeServiceController, read_json


def ensure_service(*, runtime_root: Path, profile_name: str) -> dict[str, Any]:
    root = runtime_root.resolve()
    current = read_json(root / "current.json")
    if current is None:
        raise RuntimeError("BCT_CURRENT_RELEASE_MISSING")
    release_path = Path(str(current.get("release_path") or "")).resolve()
    expected = root / "releases" / str(current.get("source_head") or "")
    if release_path != expected.resolve():
        raise RuntimeError("BCT_CURRENT_RELEASE_PATH_MISMATCH")
    policy_path = release_path / "bct.toml"
    profile = DeploymentProfiles(policy_path).get(profile_name)
    if profile.runtime_root != root:
        raise RuntimeError("BCT_SUPERVISOR_RUNTIME_ROOT_MISMATCH")
    _validate_release(profile, current)
    controller = RuntimeServiceController(
        runtime_root=root,
        service_name=profile.service_name,
        port=profile.port,
    )
    state = controller.inspect()
    if state.get("state") == "RUNNING":
        if (
            state.get("release_sha") != current.get("source_head")
            or state.get("manifest_sha256") != current.get("manifest_sha256")
        ):
            raise RuntimeError("BCT_DIFFERENT_RELEASE_RUNNING")
        return {**state, "already_running": True}
    if state.get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
        raise RuntimeError("BCT_SERVICE_STATE_NOT_RECOVERABLE")
    return _start_with_one_safe_retry(controller, current)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=r"D:\BCT\runtime")
    parser.add_argument("--profile", default="bct_runtime_v1")
    args = parser.parse_args()
    result = ensure_service(runtime_root=Path(args.runtime_root), profile_name=args.profile)
    print(json.dumps({
        "state": result.get("state"),
        "pid": result.get("pid"),
        "release_sha": result.get("release_sha"),
        "already_running": bool(result.get("already_running")),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
