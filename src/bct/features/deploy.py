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
from bct.service_runtime import (
    RuntimeServiceController,
    RuntimeWriterLock,
    atomic_json,
    read_json,
)


_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_LOCAL_APP_DATA_PREFIX = "%LOCALAPPDATA%"


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


def _git_filtered_oid(root: Path, relative: str, data: bytes) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "hash-object", "--stdin", "--path", relative],
        input=data,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise PreconditionError("DEPLOYMENT_SOURCE_GIT_FILTER_FAILED:" + relative)
    return result.stdout.decode("ascii").strip()


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
    protected_activation_required: bool = False
    migration_source_profile: str | None = None


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

    def _path(self, value: str, *, allow_local_app_data: bool) -> Path:
        candidate_value = value
        if value.upper().startswith(_LOCAL_APP_DATA_PREFIX):
            if not allow_local_app_data:
                raise PreconditionError("DEPLOYMENT_PROFILE_PATH_VARIABLE_FORBIDDEN")
            suffix = value[len(_LOCAL_APP_DATA_PREFIX):].replace("/", "\\")
            if not suffix.startswith("\\"):
                raise PreconditionError("DEPLOYMENT_PROFILE_PATH_VARIABLE_INVALID")
            parts = tuple(part for part in suffix.split("\\") if part)
            if not parts or any(part in {".", ".."} or any(ch in part for ch in "*?[]:%") for part in parts):
                raise PreconditionError("DEPLOYMENT_PROFILE_PATH_VARIABLE_INVALID")
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            local_root = Path(local_app_data)
            if not local_app_data or not local_root.is_absolute():
                raise PreconditionError("DEPLOYMENT_LOCALAPPDATA_UNAVAILABLE")
            candidate = local_root.joinpath(*parts)
            try:
                candidate.resolve().relative_to(local_root.resolve())
            except ValueError as exc:
                raise PreconditionError("DEPLOYMENT_PROFILE_PATH_ESCAPE") from exc
            return candidate.resolve()
        if "%" in candidate_value:
            raise PreconditionError("DEPLOYMENT_PROFILE_PATH_VARIABLE_INVALID")
        candidate = Path(candidate_value)
        if not candidate.is_absolute():
            candidate = self.path.parent / candidate
        return candidate.resolve()

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
        source_root = self._path(source_value, allow_local_app_data=False)
        runtime_root = self._path(runtime_value, allow_local_app_data=True)
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
        protected_activation_required = value.get("protected_activation_required", False)
        if not isinstance(protected_activation_required, bool):
            raise PreconditionError("DEPLOYMENT_PROFILE_ACTIVATION_GATE_INVALID")
        migration_source_profile = value.get("migration_source_profile")
        if migration_source_profile is not None:
            if not isinstance(migration_source_profile, str) or not _NAME.fullmatch(migration_source_profile):
                raise PreconditionError("DEPLOYMENT_PROFILE_MIGRATION_SOURCE_INVALID")
        if protected_activation_required and not migration_source_profile:
            raise PreconditionError("DEPLOYMENT_PROFILE_MIGRATION_SOURCE_REQUIRED")
        return DeploymentProfile(
            name,
            source_root,
            runtime_root,
            service_name,
            port,
            files,
            protected_activation_required,
            migration_source_profile,
        )


def _validate_source_repository(profile: DeploymentProfile, expected_head: str) -> Path:
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
    policy = root / "bct.toml"
    resolved_policy = policy.resolve()
    tracked = _git(root, "ls-files", "--error-unmatch", "--", "bct.toml")
    if (
        not policy.is_file()
        or policy.is_symlink()
        or resolved_policy != policy.absolute()
        or tracked.returncode != 0
    ):
        raise PreconditionError("DEPLOYMENT_SOURCE_POLICY_INVALID")
    return policy


def _target_profile(profile: DeploymentProfile, expected_head: str) -> DeploymentProfile:
    policy = _validate_source_repository(profile, expected_head)
    target = DeploymentProfiles(policy).get(profile.name)
    invariant_values = (
        ("SOURCE_ROOT", target.source_root, profile.source_root),
        ("RUNTIME_ROOT", target.runtime_root, profile.runtime_root),
        ("SERVICE_NAME", target.service_name, profile.service_name),
        ("PORT", target.port, profile.port),
        ("ACTIVATION_GATE", target.protected_activation_required, profile.protected_activation_required),
        ("MIGRATION_SOURCE", target.migration_source_profile, profile.migration_source_profile),
    )
    for label, actual, expected in invariant_values:
        if actual != expected:
            raise PreconditionError("DEPLOYMENT_TARGET_PROFILE_" + label + "_MISMATCH")
    if "bct.toml" not in target.files:
        raise PreconditionError("DEPLOYMENT_TARGET_PROFILE_POLICY_FILE_REQUIRED")
    return target


def _validate_source(profile: DeploymentProfile, expected_head: str) -> dict[str, Any]:
    _validate_source_repository(profile, expected_head)
    root = profile.source_root
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
        working_bytes = path.read_bytes()
        committed = _git(root, "rev-parse", f"{expected_head}:{relative}")
        if (
            committed.returncode != 0
            or _git_filtered_oid(root, relative, working_bytes) != committed.stdout.strip()
        ):
            raise PreconditionError("DEPLOYMENT_SOURCE_GIT_BLOB_MISMATCH:" + relative)
        hashes[relative] = hashlib.sha256(working_bytes).hexdigest()
    payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "profile": profile.name,
        "source_root": str(root),
        "source_head": expected_head,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "files": hashes,
    }


def _validate_protected_activation(
    profiles: DeploymentProfiles,
    profile: DeploymentProfile,
    expected_head: str,
    *,
    acquire_lock: bool = True,
) -> RuntimeWriterLock | None:
    if not profile.protected_activation_required:
        return None
    source = profiles.get(str(profile.migration_source_profile))
    activation_path = profile.runtime_root.parent / "migration" / "activation.json"
    receipt = read_json(activation_path)
    exact = {
        "schema": "BCT_PROTECTED_ACTIVATION_V1",
        "state": "APPROVED",
        "source_profile": source.name,
        "target_profile": profile.name,
        "source_head": expected_head,
        "source_runtime": str(source.runtime_root),
        "target_runtime": str(profile.runtime_root),
        "source_supervisor_disabled": True,
        "cross_account_denial_verified": True,
        "rcc_canary_verified": True,
    }
    if receipt is None or any(receipt.get(key) != value for key, value in exact.items()):
        raise PreconditionError("PROTECTED_ACTIVATION_RECEIPT_INVALID")
    operation_id = str(receipt.get("operation_id") or "")
    acl_digest = str(receipt.get("acl_evidence_sha256") or "")
    migration = read_json(profile.runtime_root.parent / "migration" / f"{operation_id}.json")
    if (
        not _NAME.fullmatch(operation_id)
        or not _SHA256.fullmatch(acl_digest)
        or migration is None
        or migration.get("state") != "PUBLISHED"
        or migration.get("source_head") != expected_head
        or migration.get("source_runtime") != str(source.runtime_root)
    ):
        raise PreconditionError("PROTECTED_ACTIVATION_MIGRATION_INVALID")
    if not (source.runtime_root / "BCT_CORE_SUPERVISOR.STOP").is_file():
        raise PreconditionError("PROTECTED_SOURCE_SUPERVISOR_NOT_DISABLED")
    source_state = RuntimeServiceController(
        runtime_root=source.runtime_root,
        service_name=source.service_name,
        port=source.port,
    ).inspect()
    if source_state.get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
        raise PreconditionError("PROTECTED_SOURCE_CORE_NOT_QUIESCED")
    if not acquire_lock:
        return None
    lock = RuntimeWriterLock(source.runtime_root / "state" / "core-writer.lock")
    lock.acquire()
    return lock


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


def _start_with_one_safe_retry(
    controller: RuntimeServiceController,
    release: dict[str, Any],
) -> dict[str, Any]:
    try:
        return controller.start(release)
    except ConfirmedFailure:
        state = controller.inspect()
        if state.get("state") != "STOPPED_STALE_RECEIPT":
            raise
        time.sleep(1.0)
        return controller.start(release)


class DeployFeature:
    capability = "deploy"

    def __init__(self, profiles: DeploymentProfiles):
        self.profiles = profiles

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "apply").strip().lower()
        if operation not in {"apply", "reconcile"}:
            raise PreconditionError("DEPLOYMENT_OPERATION_INVALID")
        profile_name = str(arguments.get("profile") or "")
        profile = self.profiles.get(profile_name)
        expected_source_head = str(arguments.get("expected_source_head") or "").lower()
        expected_current = arguments.get("expected_current_source_head")
        restart = arguments.get("restart", operation == "apply")
        if not _SHA.fullmatch(expected_source_head):
            raise PreconditionError("DEPLOYMENT_SOURCE_SHA_INVALID")
        if expected_current is not None:
            expected_current = str(expected_current).lower()
            if not _SHA.fullmatch(expected_current):
                raise PreconditionError("DEPLOYMENT_CURRENT_SHA_INVALID")
        if not isinstance(restart, bool):
            raise PreconditionError("DEPLOYMENT_RESTART_INVALID")
        if operation == "reconcile":
            original_operation_id = str(
                arguments.get("original_operation_id") or ""
            ).strip()
            if not original_operation_id or len(original_operation_id) > 80:
                raise PreconditionError("DEPLOYMENT_RECONCILE_OPERATION_ID_INVALID")
            if restart:
                raise PreconditionError("DEPLOYMENT_RECONCILE_RESTART_FORBIDDEN")
            if expected_current != expected_source_head:
                raise PreconditionError("DEPLOYMENT_RECONCILE_EXACT_CURRENT_REQUIRED")
            receipt_path = (
                profile.runtime_root / "deployments" / (expected_source_head + ".json")
            )
            return FeatureRequest(
                self.capability,
                profile.name,
                {
                    "operation": "reconcile",
                    "original_operation_id": original_operation_id,
                    "profile": profile.name,
                    "expected_source_head": expected_source_head,
                    "expected_current_source_head": expected_current,
                    "restart": False,
                },
                (
                    "deployment-reconcile:"
                    + str(profile.runtime_root).casefold()
                    + ":"
                    + original_operation_id.casefold(),
                ),
                {
                    "expected_source_head": expected_source_head,
                    "expected_current_source_head": expected_current,
                    "reconciliation_receipt": str(receipt_path),
                },
            )
        return FeatureRequest(
            self.capability,
            profile.name,
            {"profile": profile.name, "expected_source_head": expected_source_head,
             "expected_current_source_head": expected_current, "restart": restart},
            (f"deployment:{str(profile.runtime_root).casefold()}", f"service:{profile.service_name.casefold()}"),
            {"expected_source_head": expected_source_head, "expected_current_source_head": expected_current},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments.get("operation") == "reconcile":
            return self._reconcile(request)
        trusted_profile = self.profiles.get(request.arguments["profile"])
        profile = _target_profile(trusted_profile, request.arguments["expected_source_head"])
        source_lock = _validate_protected_activation(
            self.profiles, profile, request.arguments["expected_source_head"]
        )
        try:
            return self._execute_apply(request, profile)
        finally:
            if source_lock is not None:
                source_lock.close()

    def _execute_apply(
        self, request: FeatureRequest, profile: DeploymentProfile
    ) -> FeatureResult:
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
                _validate_protected_activation(
                    self.profiles, profile, request.arguments["expected_source_head"],
                    acquire_lock=False,
                )
                service = _start_with_one_safe_retry(controller, current)
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
                _validate_protected_activation(
                    self.profiles, profile, request.arguments["expected_source_head"],
                    acquire_lock=False,
                )
                if service_before.get("state") == "RUNNING":
                    controller.stop()
                service = _start_with_one_safe_retry(controller, release)
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
                    restored = _start_with_one_safe_retry(controller, current)
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

    def _reconcile(self, request: FeatureRequest) -> FeatureResult:
        """Resolve one exact UNKNOWN deploy from verified immutable LIVE state."""
        profile = self.profiles.get(request.arguments["profile"])
        expected_head = request.arguments["expected_source_head"]
        current = _read_current(profile)
        if current is None or current.get("source_head") != expected_head:
            raise PreconditionError("DEPLOYMENT_RECONCILE_CURRENT_MISMATCH")
        if current.get("source_head") != request.arguments["expected_current_source_head"]:
            raise PreconditionError("DEPLOYMENT_RECONCILE_CURRENT_MISMATCH")
        _validate_release(profile, current, require_profile_files=True)
        receipt_path = Path(request.preconditions["reconciliation_receipt"])
        receipt = read_json(receipt_path)
        if (
            receipt is None
            or receipt.get("state") != "ROLLBACK_FAILED"
            or receipt.get("profile") != profile.name
            or receipt.get("source_head") != expected_head
            or receipt.get("manifest_sha256") != current.get("manifest_sha256")
        ):
            raise PreconditionError("DEPLOYMENT_RECONCILE_RECEIPT_MISMATCH")
        controller = RuntimeServiceController(
            runtime_root=profile.runtime_root,
            service_name=profile.service_name,
            port=profile.port,
        )
        service = controller.inspect()
        if (
            service.get("state") != "RUNNING"
            or service.get("release_sha") != expected_head
            or service.get("manifest_sha256") != current.get("manifest_sha256")
        ):
            raise PreconditionError("DEPLOYMENT_RECONCILE_SERVICE_MISMATCH")
        original_operation_id = request.arguments["original_operation_id"]
        return FeatureResult(
            Outcome.APPLIED,
            {
                "profile": profile.name,
                "source_head": expected_head,
                "manifest_sha256": current["manifest_sha256"],
                "service": service,
                "deployment_receipt": str(receipt_path),
                "reconciled_operation_id": original_operation_id,
                "live_state_verified": True,
            },
            reconciled_operation_ids=(original_operation_id,),
        )


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
