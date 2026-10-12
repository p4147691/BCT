from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from bct.core.models import (
    ConfirmedFailure,
    FeatureRequest,
    FeatureResult,
    Outcome,
    PreconditionError,
    UnknownEffectError,
    Work,
)
from bct.service_runtime import RuntimeServiceController, atomic_json, read_json


_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9_.-]+")


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DeploymentProfile:
    name: str
    source_root: Path
    runtime_root: Path
    service_name: str
    port: int
    files: tuple[str, ...]


class DeploymentProfiles:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    @staticmethod
    def _file(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("DEPLOYMENT_FILE_INVALID")
        normalized = value.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if (
            pure.is_absolute()
            or normalized.startswith(("/", "-"))
            or any(part in {"", ".", ".."} for part in pure.parts)
            or any(character in normalized for character in "*?[]")
            or ":" in normalized
        ):
            raise ValueError("DEPLOYMENT_FILE_INVALID:" + value)
        return normalized

    def get(self, name: str) -> DeploymentProfile:
        if not _NAME.fullmatch(name):
            raise PreconditionError("DEPLOYMENT_PROFILE_INVALID")
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        profiles = data.get("deployment", {}).get("profiles", {})
        value = profiles.get(name) if isinstance(profiles, dict) else None
        if not isinstance(value, dict):
            raise PreconditionError("DEPLOYMENT_PROFILE_NOT_FOUND:" + name)
        source_value = value.get("source_root")
        runtime_value = value.get("runtime_root")
        files_value = value.get("files")
        if not isinstance(source_value, str) or not isinstance(runtime_value, str):
            raise PreconditionError("DEPLOYMENT_PROFILE_PATH_INVALID")
        source_root = Path(source_value)
        if not source_root.is_absolute():
            source_root = self.path.parent / source_root
        runtime_root = Path(runtime_value)
        if not runtime_root.is_absolute():
            runtime_root = self.path.parent / runtime_root
        if not isinstance(files_value, list) or not files_value:
            raise PreconditionError("DEPLOYMENT_PROFILE_FILES_INVALID")
        try:
            files = tuple(self._file(item) for item in files_value)
        except ValueError as exc:
            raise PreconditionError(str(exc)) from exc
        if len(files) != len(set(item.casefold() for item in files)):
            raise PreconditionError("DEPLOYMENT_PROFILE_FILES_DUPLICATE")
        service_name = str(value.get("service_name") or "")
        port = value.get("port")
        if not _NAME.fullmatch(service_name) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise PreconditionError("DEPLOYMENT_PROFILE_SERVICE_INVALID")
        return DeploymentProfile(
            name,
            source_root.resolve(),
            runtime_root.resolve(),
            service_name,
            port,
            files,
        )


def _validate_source(profile: DeploymentProfile, expected_head: str) -> dict[str, Any]:
    root = profile.source_root
    top = _git(root, "rev-parse", "--show-toplevel")
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        raise PreconditionError("DEPLOYMENT_SOURCE_NOT_REPOSITORY_ROOT")
    if head.returncode != 0 or head.stdout.strip().lower() != expected_head:
        raise PreconditionError("DEPLOYMENT_SOURCE_HEAD_MISMATCH")
    if branch.returncode != 0 or branch.stdout.strip() != "main":
        raise PreconditionError("DEPLOYMENT_SOURCE_MAIN_REQUIRED")
    if status.returncode != 0 or status.stdout.strip():
        raise PreconditionError("DEPLOYMENT_SOURCE_NOT_CLEAN")
    hashes: dict[str, str] = {}
    for relative in profile.files:
        path = root / Path(relative)
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise PreconditionError("DEPLOYMENT_SOURCE_ESCAPE:" + relative) from exc
        if not path.is_file() or path.is_symlink() or resolved != path.absolute():
            raise PreconditionError("DEPLOYMENT_SOURCE_FILE_INVALID:" + relative)
        hashes[relative] = _sha256(path)
    payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "profile": profile.name,
        "source_root": str(root),
        "source_head": expected_head,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "files": hashes,
    }


def _validate_release(
    profile: DeploymentProfile,
    release: dict[str, Any],
    *,
    require_profile_files: bool = False,
) -> None:
    release_root = Path(str(release.get("release_path") or "")).resolve()
    expected_root = profile.runtime_root / "releases" / str(release.get("source_head") or "")
    if release_root != expected_root.resolve():
        raise PreconditionError("DEPLOYMENT_RELEASE_PATH_MISMATCH")
    manifest = read_json(release_root / "manifest.json")
    if (
        manifest is None
        or manifest.get("manifest_sha256") != release.get("manifest_sha256")
        or manifest.get("source_head") != release.get("source_head")
    ):
        raise PreconditionError("DEPLOYMENT_RELEASE_MANIFEST_MISMATCH")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PreconditionError("DEPLOYMENT_RELEASE_FILE_SET_MISMATCH")
    try:
        manifest_files = tuple(DeploymentProfiles._file(relative) for relative in files)
    except ValueError as exc:
        raise PreconditionError("DEPLOYMENT_RELEASE_FILE_SET_INVALID") from exc
    if len(manifest_files) != len(set(relative.casefold() for relative in manifest_files)):
        raise PreconditionError("DEPLOYMENT_RELEASE_FILE_SET_DUPLICATE")
    if require_profile_files and set(files) != set(profile.files):
        raise PreconditionError("DEPLOYMENT_RELEASE_FILE_SET_MISMATCH")
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != release.get("manifest_sha256"):
        raise PreconditionError("DEPLOYMENT_RELEASE_MANIFEST_HASH_MISMATCH")
    for relative, digest in files.items():
        path = release_root / Path(relative)
        resolved = path.resolve()
        try:
            resolved.relative_to(release_root)
        except ValueError as exc:
            raise PreconditionError("DEPLOYMENT_RELEASE_FILE_ESCAPE:" + relative) from exc
        if (
            not path.is_file()
            or path.is_symlink()
            or resolved != path.absolute()
            or not _SHA256.fullmatch(str(digest))
        ):
            raise PreconditionError("DEPLOYMENT_RELEASE_FILE_INVALID:" + relative)
        if _sha256(path) != digest:
            raise PreconditionError("DEPLOYMENT_RELEASE_FILE_HASH_MISMATCH:" + relative)


def _stage_release(profile: DeploymentProfile, manifest: dict[str, Any]) -> dict[str, Any]:
    runtime_root = profile.runtime_root
    runtime_root.mkdir(parents=True, exist_ok=True)
    if runtime_root.resolve() != profile.runtime_root:
        raise PreconditionError("DEPLOYMENT_RUNTIME_ROOT_MISMATCH")
    releases = runtime_root / "releases"
    staging_root = runtime_root / "staging"
    releases.mkdir(exist_ok=True)
    staging_root.mkdir(exist_ok=True)
    release_root = releases / manifest["source_head"]
    release = {**manifest, "release_path": str(release_root.resolve())}
    if release_root.exists():
        _validate_release(profile, release, require_profile_files=True)
        return release
    staging = Path(tempfile.mkdtemp(prefix=manifest["source_head"] + "-", dir=staging_root))
    try:
        if staging.resolve().parent != staging_root.resolve():
            raise PreconditionError("DEPLOYMENT_STAGING_ESCAPE")
        for relative, digest in manifest["files"].items():
            source = profile.source_root / Path(relative)
            destination = staging / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if _sha256(destination) != digest:
                raise ConfirmedFailure("DEPLOYMENT_COPY_HASH_MISMATCH:" + relative, release_claims=True)
        atomic_json(staging / "manifest.json", release)
        os.replace(staging, release_root)
    finally:
        if staging.exists() and staging.resolve().parent == staging_root.resolve():
            shutil.rmtree(staging)
    _validate_release(profile, release, require_profile_files=True)
    return release


def _current_path(profile: DeploymentProfile) -> Path:
    return profile.runtime_root / "current.json"


def _write_current(profile: DeploymentProfile, release: dict[str, Any] | None) -> None:
    path = _current_path(profile)
    if release is None:
        if path.exists():
            path.unlink()
        return
    atomic_json(path, {
        "profile": profile.name,
        "source_head": release["source_head"],
        "manifest_sha256": release["manifest_sha256"],
        "release_path": release["release_path"],
        "activated_at": time.time(),
    })


def _read_current(profile: DeploymentProfile) -> dict[str, Any] | None:
    value = read_json(_current_path(profile))
    if value is not None:
        _validate_release(profile, value)
    return value


class DeployFeature:
    capability = "deploy"

    def __init__(self, profiles: DeploymentProfiles):
        self.profiles = profiles

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        profile_name = str(arguments.get("profile") or "")
        profile = self.profiles.get(profile_name)
        expected_source_head = str(arguments.get("expected_source_head") or "").lower()
        expected_current = arguments.get("expected_current_source_head")
        restart = arguments.get("restart", True)
        if not _SHA.fullmatch(expected_source_head):
            raise PreconditionError("DEPLOYMENT_SOURCE_SHA_INVALID")
        if expected_current is not None:
            expected_current = str(expected_current).lower()
            if not _SHA.fullmatch(expected_current):
                raise PreconditionError("DEPLOYMENT_CURRENT_SHA_INVALID")
        if not isinstance(restart, bool):
            raise PreconditionError("DEPLOYMENT_RESTART_INVALID")
        return FeatureRequest(
            self.capability,
            profile.name,
            {"profile": profile.name, "expected_source_head": expected_source_head,
             "expected_current_source_head": expected_current, "restart": restart},
            (f"deployment:{str(profile.runtime_root).casefold()}", f"service:{profile.service_name.casefold()}"),
            {"expected_source_head": expected_source_head, "expected_current_source_head": expected_current},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        profile = self.profiles.get(request.arguments["profile"])
        manifest = _validate_source(profile, request.arguments["expected_source_head"])
        current = _read_current(profile)
        current_head = current.get("source_head") if current else None
        if current_head != request.arguments["expected_current_source_head"]:
            raise PreconditionError("DEPLOYMENT_CURRENT_SHA_MISMATCH")
        controller = RuntimeServiceController(
            runtime_root=profile.runtime_root,
            service_name=profile.service_name,
            port=profile.port,
        )
        service_before = controller.inspect()
        if current_head == manifest["source_head"]:
            _validate_release(profile, current, require_profile_files=True)
            if request.arguments["restart"]:
                if service_before.get("state") == "RUNNING" and service_before.get("release_sha") == current_head:
                    return FeatureResult(Outcome.APPLIED, {
                        "profile": profile.name, "source_head": current_head,
                        "manifest_sha256": manifest["manifest_sha256"],
                        "service": service_before, "already_current": True,
                    })
                service = controller.start(current)
            else:
                service = service_before
            return FeatureResult(Outcome.APPLIED, {
                "profile": profile.name, "source_head": current_head,
                "manifest_sha256": manifest["manifest_sha256"],
                "service": service, "already_current": True,
            })
        release = _stage_release(profile, manifest)
        receipt_path = profile.runtime_root / "deployments" / (manifest["source_head"] + ".json")
        receipt = {
            "profile": profile.name,
            "state": "PREPARED",
            "source_head": manifest["source_head"],
            "manifest_sha256": manifest["manifest_sha256"],
            "previous_source_head": current_head,
            "previous_current": current,
            "release_path": release["release_path"],
            "prepared_at": time.time(),
        }
        atomic_json(receipt_path, receipt)
        activated = False
        try:
            _write_current(profile, release)
            activated = True
            current_after = _read_current(profile)
            if current_after is None or current_after.get("source_head") != manifest["source_head"]:
                raise RuntimeError("DEPLOYMENT_CURRENT_POST_STATE_INVALID")
            if request.arguments["restart"]:
                if service_before.get("state") == "RUNNING":
                    controller.stop()
                service = controller.start(release)
            else:
                service = controller.inspect()
            completed = {
                **receipt,
                "state": "COMPLETED",
                "completed_at": time.time(),
                "service": service,
            }
            atomic_json(receipt_path, completed)
            return FeatureResult(Outcome.APPLIED, {
                "profile": profile.name,
                "source_head": manifest["source_head"],
                "manifest_sha256": manifest["manifest_sha256"],
                "release_path": release["release_path"],
                "previous_source_head": current_head,
                "service": service,
                "deployment_receipt": str(receipt_path),
                "already_current": False,
            })
        except Exception as exc:
            if not activated:
                raise
            try:
                target_state = controller.inspect()
                if target_state.get("state") == "RUNNING" and target_state.get("release_sha") == manifest["source_head"]:
                    controller.stop()
                _write_current(profile, current)
                if request.arguments["restart"] and service_before.get("state") == "RUNNING":
                    assert current is not None
                    restored = controller.start(current)
                    if restored.get("release_sha") != current_head:
                        raise RuntimeError("DEPLOYMENT_ROLLBACK_SERVICE_MISMATCH")
                current_rollback = _read_current(profile)
                if (current_rollback.get("source_head") if current_rollback else None) != current_head:
                    raise RuntimeError("DEPLOYMENT_ROLLBACK_POINTER_MISMATCH")
                atomic_json(receipt_path, {
                    **receipt,
                    "state": "ROLLED_BACK",
                    "failed_at": time.time(),
                    "failure": type(exc).__name__ + ":" + str(exc),
                    "rollback_verified": True,
                })
            except Exception as rollback_exc:
                atomic_json(receipt_path, {
                    **receipt,
                    "state": "ROLLBACK_FAILED",
                    "failed_at": time.time(),
                    "failure": type(exc).__name__ + ":" + str(exc),
                    "rollback_failure": type(rollback_exc).__name__ + ":" + str(rollback_exc),
                })
                raise UnknownEffectError("DEPLOYMENT_ROLLBACK_UNVERIFIED:" + str(receipt_path)) from rollback_exc
            raise ConfirmedFailure("DEPLOYMENT_ROLLED_BACK:" + str(receipt_path), release_claims=True) from exc


class ServiceControlFeature:
    capability = "service_control"

    def __init__(self, profiles: DeploymentProfiles):
        self.profiles = profiles

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        profile_name = str(arguments.get("profile") or "")
        profile = self.profiles.get(profile_name)
        action = str(arguments.get("action") or "")
        expected_release = str(arguments.get("expected_release_sha") or "").lower()
        if action not in {"status", "start", "restart", "stop"}:
            raise PreconditionError("SERVICE_ACTION_INVALID")
        if not _SHA.fullmatch(expected_release):
            raise PreconditionError("SERVICE_RELEASE_SHA_INVALID")
        return FeatureRequest(
            self.capability,
            profile.service_name,
            {"profile": profile.name, "action": action, "expected_release_sha": expected_release},
            (f"service:{profile.service_name.casefold()}",),
            {"expected_release_sha": expected_release},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        profile = self.profiles.get(request.arguments["profile"])
        current = _read_current(profile)
        if current is None or current.get("source_head") != request.arguments["expected_release_sha"]:
            raise PreconditionError("SERVICE_CURRENT_RELEASE_MISMATCH")
        controller = RuntimeServiceController(
            runtime_root=profile.runtime_root,
            service_name=profile.service_name,
            port=profile.port,
        )
        action = request.arguments["action"]
        if action == "status":
            result = controller.inspect()
        elif action == "start":
            result = controller.start(current)
        elif action == "restart":
            result = controller.restart(current)
        else:
            result = controller.stop()
        return FeatureResult(Outcome.APPLIED, {
            "profile": profile.name,
            "action": action,
            "release_sha": current["source_head"],
            "service": result,
        })
