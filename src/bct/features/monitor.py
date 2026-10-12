from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class MonitorFeature:
    capability = "monitor"

    def __init__(self, policy_path: str | Path):
        self.policy_path = Path(policy_path)

    def _config(self) -> tuple[Path, Path]:
        data = tomllib.loads(self.policy_path.read_text(encoding="utf-8"))
        config = data.get("monitor") or {}
        source_value = str(config.get("source_root") or "components/monitor")
        live_value = str(config.get("live_root") or "").strip()
        source = Path(source_value)
        if not source.is_absolute():
            source = self.policy_path.parent / source
        if not live_value:
            raise PreconditionError("MONITOR_LIVE_ROOT_NOT_CONFIGURED")
        live = Path(live_value)
        return source.resolve(), live.resolve()

    @staticmethod
    def _owned_files(source: Path) -> list[str]:
        manifest = source / "BASELINE_SHA256.txt"
        if not manifest.is_file():
            raise PreconditionError("MONITOR_BASELINE_MANIFEST_MISSING")
        result: list[str] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise PreconditionError("MONITOR_BASELINE_MANIFEST_INVALID")
            normalized = Path(parts[1])
            if normalized.is_absolute() or ".." in normalized.parts:
                raise PreconditionError("MONITOR_BASELINE_PATH_INVALID")
            result.append(parts[1])
        return sorted(set(result))

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "status").strip().casefold()
        if operation not in {"status", "validate"}:
            raise PreconditionError("MONITOR_OPERATION_INVALID")
        source, live = self._config()
        if not source.is_dir() or not live.is_dir():
            raise PreconditionError("MONITOR_ROOT_MISSING")
        return FeatureRequest(
            self.capability, str(live),
            {"operation": operation, "source": str(source), "live": str(live)},
            ("monitor:" + str(live).casefold(),),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        source = Path(request.arguments["source"])
        live = Path(request.arguments["live"])
        files = self._owned_files(source)
        if request.arguments["operation"] == "validate":
            return self._validate(source, files)
        missing_source: list[str] = []
        missing_live: list[str] = []
        mismatches: list[dict[str, str]] = []
        for relative in files:
            source_path = source / Path(relative)
            live_path = live / Path(relative)
            if not source_path.is_file():
                missing_source.append(relative)
                continue
            if not live_path.is_file():
                missing_live.append(relative)
                continue
            source_sha = _sha256(source_path)
            live_sha = _sha256(live_path)
            if source_sha != live_sha:
                mismatches.append({"path": relative, "source_sha256": source_sha, "live_sha256": live_sha})
        exact = not missing_source and not missing_live and not mismatches
        return FeatureResult(
            Outcome.APPLIED,
            {"operation": "status", "owned_files": len(files), "source_live_exact": exact},
            output={
                "source_root": str(source), "live_root": str(live), "owned_files": len(files),
                "source_live_exact": exact, "missing_source": missing_source,
                "missing_live": missing_live, "mismatches": mismatches,
            },
        )

    @staticmethod
    def _validate(source: Path, files: list[str]) -> FeatureResult:
        errors: list[dict[str, Any]] = []
        checked = 0
        node = shutil.which("node.exe") or shutil.which("node")
        for relative in files:
            path = source / Path(relative)
            if not path.is_file():
                errors.append({"path": relative, "error": "MISSING"})
                continue
            suffix = path.suffix.casefold()
            if suffix == ".json":
                checked += 1
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception as exc:
                    errors.append({"path": relative, "error": type(exc).__name__})
            elif suffix == ".py":
                checked += 1
                try:
                    compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
                except Exception as exc:
                    errors.append({"path": relative, "error": type(exc).__name__})
            elif suffix == ".js":
                checked += 1
                if not node:
                    errors.append({"path": relative, "error": "NODE_NOT_FOUND"})
                    continue
                result = subprocess.run(
                    [node, "--check", str(path)], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30,
                )
                if result.returncode != 0:
                    errors.append({"path": relative, "error": (result.stderr or result.stdout)[-500:]})
        outcome = Outcome.APPLIED if not errors else Outcome.FAILED
        return FeatureResult(
            outcome,
            {"operation": "validate", "checked": checked, "errors": len(errors)},
            output={"valid": not errors, "checked": checked, "errors": errors},
        )
