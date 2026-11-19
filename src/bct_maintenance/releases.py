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
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ConfirmedFailure, PreconditionError, UnknownEffectError
from .service_runtime import RuntimeServiceController, RuntimeWriterLock, atomic_json, read_json


_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_LOCAL_APP_DATA_PREFIX = "%LOCALAPPDATA%"
_RUNTIME_RECOVERY_SCRIPTS = (
    "modules/mcp/ops/run_bct_core_supervisor.ps1",
    "modules/mcp/ops/run_bct_tunnel_supervisor.ps1",
    "modules/mcp/ops/invoke_bct_tunnel_cutover.ps1",
)


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
    cutover_successor_profile: str | None = None


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
        cutover_successor_profile = value.get("cutover_successor_profile")
        if cutover_successor_profile is not None:
            if not isinstance(cutover_successor_profile, str) or not _NAME.fullmatch(
                cutover_successor_profile
            ):
                raise PreconditionError("DEPLOYMENT_PROFILE_CUTOVER_SUCCESSOR_INVALID")
        return DeploymentProfile(
            name,
            source_root,
            runtime_root,
            service_name,
            port,
            files,
            protected_activation_required,
            migration_source_profile,
            cutover_successor_profile,
        )

    def for_runtime_root(self, runtime_root: Path) -> DeploymentProfile:
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        values = data.get("deployment", {}).get("profiles", {})
        if not isinstance(values, dict):
            raise PreconditionError("DEPLOYMENT_PROFILE_NOT_FOUND_FOR_RUNTIME")
        matches: list[DeploymentProfile] = []
        for name in values:
            profile = self.get(str(name))
            if profile.runtime_root == runtime_root.resolve():
                matches.append(profile)
        if len(matches) != 1:
            raise PreconditionError("DEPLOYMENT_PROFILE_NOT_FOUND_FOR_RUNTIME")
        return matches[0]


def _validate_source_repository(
    profile: DeploymentProfile, expected_head: str, source_worktree: Path | None = None,
) -> Path:
    canonical = profile.source_root
    root = source_worktree.resolve() if source_worktree is not None else canonical
    top = _git(root, "rev-parse", "--show-toplevel")
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        raise PreconditionError("DEPLOYMENT_SOURCE_NOT_REPOSITORY_ROOT")
    if head.returncode != 0 or head.stdout.strip().lower() != expected_head:
        raise PreconditionError("DEPLOYMENT_SOURCE_HEAD_MISMATCH")
    if source_worktree is None and (branch.returncode != 0 or branch.stdout.strip() != "main"):
        raise PreconditionError("DEPLOYMENT_SOURCE_MAIN_REQUIRED")
    if source_worktree is not None:
        main = _git(canonical, "rev-parse", "--verify", "refs/heads/main")
        canonical_top = _git(canonical, "rev-parse", "--show-toplevel")
        canonical_git = _git(canonical, "rev-parse", "--path-format=absolute", "--git-common-dir")
        source_git = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if (canonical_top.returncode != 0 or Path(canonical_top.stdout.strip()).resolve() != canonical
                or canonical_git.returncode != 0 or source_git.returncode != 0
                or Path(canonical_git.stdout.strip()).resolve() != Path(source_git.stdout.strip()).resolve()
                or root == canonical):
            raise PreconditionError("DEPLOYMENT_SOURCE_WORKTREE_REPOSITORY_MISMATCH")
        if main.returncode != 0 or main.stdout.strip().lower() != expected_head:
            raise PreconditionError("DEPLOYMENT_CANONICAL_MAIN_HEAD_MISMATCH")
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
    committed = _git(root, "rev-parse", f"{expected_head}:bct.toml")
    if committed.returncode != 0 or _git_filtered_oid(root, "bct.toml", policy.read_bytes()) != committed.stdout.strip():
        raise PreconditionError("DEPLOYMENT_SOURCE_GIT_BLOB_MISMATCH:bct.toml")
    return policy


def _target_profile(
    profile: DeploymentProfile, expected_head: str, source_worktree: Path | None = None,
) -> DeploymentProfile:
    policy = _validate_source_repository(profile, expected_head, source_worktree)
    target = DeploymentProfiles(policy).get(profile.name)
    invariant_values = (
        ("SOURCE_ROOT", target.source_root, profile.source_root),
        ("RUNTIME_ROOT", target.runtime_root, profile.runtime_root),
        ("SERVICE_NAME", target.service_name, profile.service_name),
        ("PORT", target.port, profile.port),
        ("ACTIVATION_GATE", target.protected_activation_required, profile.protected_activation_required),
        ("MIGRATION_SOURCE", target.migration_source_profile, profile.migration_source_profile),
        ("CUTOVER_SUCCESSOR", target.cutover_successor_profile, profile.cutover_successor_profile),
    )
    for label, actual, expected in invariant_values:
        if actual != expected:
            raise PreconditionError("DEPLOYMENT_TARGET_PROFILE_" + label + "_MISMATCH")
    if "bct.toml" not in target.files:
        raise PreconditionError("DEPLOYMENT_TARGET_PROFILE_POLICY_FILE_REQUIRED")
    return target


def _cutover_authority(
    profiles: DeploymentProfiles, profile: DeploymentProfile
) -> tuple[str, DeploymentProfile, DeploymentProfile, Path] | None:
    """Return this profile's role and the single durable cutover authority."""
    successor_name = getattr(profile, "cutover_successor_profile", None)
    source_name = getattr(profile, "migration_source_profile", None)
    if successor_name is not None:
        source = profile
        target = profiles.get(successor_name)
        role = "source"
    elif source_name is not None:
        source = profiles.get(source_name)
        target = profile
        role = "target"
    else:
        return None
    return role, source, target, target.runtime_root.parent / "migration" / "cutover.json"


def _cutover_authority_path(
    profiles: DeploymentProfiles, profile: DeploymentProfile
) -> Path | None:
    authority = _cutover_authority(profiles, profile)
    return authority[3] if authority is not None else None


def _validate_profile_start_allowed(
    profiles: DeploymentProfiles, profile: DeploymentProfile
) -> None:
    """Fail closed after a protected successor has become the durable authority."""
    authority = _cutover_authority(profiles, profile)
    if authority is None:
        return
    role, source, target, marker_path = authority
    if not marker_path.exists():
        if role == "target":
            raise PreconditionError("PROTECTED_TARGET_CUTOVER_AUTHORITY_MISSING")
        return
    marker = read_json(marker_path)
    exact = {
        "schema": "BCT_PROTECTED_CUTOVER_V1",
        "source_profile": source.name,
        "target_profile": target.name,
        "source_runtime": str(source.runtime_root),
        "target_runtime": str(target.runtime_root),
    }
    if marker is None or any(marker.get(key) != value for key, value in exact.items()):
        raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_INVALID")
    state = marker.get("state")
    if state in {"ACTIVATING", "ACTIVATED"}:
        if (
            not _NAME.fullmatch(str(marker.get("operation_id") or ""))
            or not _SHA.fullmatch(str(marker.get("source_head") or ""))
        ):
            raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_INVALID")
        if role == "source":
            raise PreconditionError("PROTECTED_SOURCE_PROFILE_RETIRED")
        return
    if state != "ROLLED_BACK" or marker.get("rollback_approved") is not True or not _NAME.fullmatch(
        str(marker.get("rollback_operation_id") or "")
    ):
        raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_INVALID")
    if role == "target":
        raise PreconditionError("PROTECTED_TARGET_PROFILE_RETIRED")


def write_protected_cutover_rollback(
    *,
    profiles: DeploymentProfiles,
    source_profile_name: str,
    operation_id: str,
    target_references_restored: bool,
) -> dict[str, Any]:
    """Record a quiesced, separately approved rollback; starts no service."""
    if not _NAME.fullmatch(operation_id) or target_references_restored is not True:
        raise PreconditionError("PROTECTED_CUTOVER_ROLLBACK_EVIDENCE_INVALID")
    source = profiles.get(source_profile_name)
    marker_path = _cutover_authority_path(profiles, source)
    if marker_path is None:
        raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_MISSING")
    marker = read_json(marker_path)
    successor = profiles.get(str(source.cutover_successor_profile))
    if (
        marker is None
        or marker.get("schema") != "BCT_PROTECTED_CUTOVER_V1"
        or marker.get("state") not in {"ACTIVATING", "ACTIVATED"}
        or marker.get("source_profile") != source.name
        or marker.get("target_profile") != successor.name
        or marker.get("source_runtime") != str(source.runtime_root)
        or marker.get("target_runtime") != str(successor.runtime_root)
    ):
        raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_INVALID")
    locks = (
        RuntimeWriterLock(source.runtime_root / "state" / "core-writer.lock"),
        RuntimeWriterLock(successor.runtime_root / "state" / "core-writer.lock"),
    )
    acquired: list[RuntimeWriterLock] = []
    try:
        for item in locks:
            item.acquire()
            acquired.append(item)
        for profile in (source, successor):
            state = RuntimeServiceController(
                runtime_root=profile.runtime_root,
                service_name=profile.service_name,
                port=profile.port,
            ).inspect()
            if state.get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
                raise PreconditionError("PROTECTED_CUTOVER_ROLLBACK_CORE_NOT_QUIESCED")
        rolled_back = {
            **marker,
            "state": "ROLLED_BACK",
            "rollback_operation_id": operation_id,
            "rollback_approved": True,
            "target_references_restored": True,
        }
        atomic_json(marker_path, rolled_back)
        return rolled_back
    finally:
        for item in reversed(acquired):
            item.close()


def _begin_protected_cutover(
    profiles: DeploymentProfiles,
    profile: DeploymentProfile,
    expected_head: str,
) -> dict[str, Any] | None:
    if not profile.protected_activation_required:
        return None
    source = profiles.get(str(profile.migration_source_profile))
    activation = read_json(profile.runtime_root.parent / "migration" / "activation.json")
    if activation is None:
        raise PreconditionError("PROTECTED_ACTIVATION_RECEIPT_INVALID")
    marker = {
        "schema": "BCT_PROTECTED_CUTOVER_V1",
        "state": "ACTIVATING",
        "operation_id": activation.get("operation_id"),
        "source_profile": source.name,
        "target_profile": profile.name,
        "source_runtime": str(source.runtime_root),
        "target_runtime": str(profile.runtime_root),
        "source_head": expected_head,
    }
    marker_path = profile.runtime_root.parent / "migration" / "cutover.json"
    existing = read_json(marker_path)
    if existing is not None:
        stable_keys = (
            "schema", "operation_id", "source_profile", "target_profile",
            "source_runtime", "target_runtime",
        )
        if any(existing.get(key) != marker.get(key) for key in stable_keys):
            raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
        if existing.get("state") not in {"ACTIVATING", "ACTIVATED"}:
            raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
        if (
            not _SHA.fullmatch(str(existing.get("source_head") or ""))
            or (
                existing.get("state") == "ACTIVATING"
                and existing.get("source_head") != expected_head
            )
        ):
            raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
        return existing
    atomic_json(marker_path, marker)
    return marker


def _record_protected_cutover(
    profiles: DeploymentProfiles,
    profile: DeploymentProfile,
    expected_head: str,
    service: dict[str, Any],
) -> None:
    """Complete an authority transfer that was durably begun before target start."""
    if not profile.protected_activation_required:
        return
    marker_path = profile.runtime_root.parent / "migration" / "cutover.json"
    existing = read_json(marker_path)
    source = profiles.get(str(profile.migration_source_profile))
    activation = read_json(profile.runtime_root.parent / "migration" / "activation.json")
    exact = {
        "schema": "BCT_PROTECTED_CUTOVER_V1",
        "operation_id": activation.get("operation_id") if activation is not None else None,
        "source_profile": source.name,
        "target_profile": profile.name,
        "source_runtime": str(source.runtime_root),
        "target_runtime": str(profile.runtime_root),
    }
    if (
        existing is None
        or existing.get("state") not in {"ACTIVATING", "ACTIVATED"}
        or any(existing.get(key) != value for key, value in exact.items())
        or not _SHA.fullmatch(str(existing.get("source_head") or ""))
    ):
        raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_INVALID")
    if existing.get("state") == "ACTIVATED":
        return
    if existing.get("source_head") != expected_head:
        raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
    completed = {
        **existing,
        "state": "ACTIVATED",
        "service_generation": service.get("generation"),
        "service_instance_id": service.get("instance_id"),
    }
    atomic_json(marker_path, completed)


def _validate_source(
    profile: DeploymentProfile, expected_head: str, source_worktree: Path | None = None,
) -> dict[str, Any]:
    root = _validate_source_repository(profile, expected_head, source_worktree).parent
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


def _validate_protected_deploy_gate(
    profiles: DeploymentProfiles,
    profile: DeploymentProfile,
    expected_head: str,
    *,
    acquire_lock: bool,
) -> RuntimeWriterLock | None:
    """Separate first cutover/recovery evidence from later target upgrades.

    The migration source writer lock is also the durable cutover-authority
    lock.  Holding it for an activated target upgrade prevents an approved
    rollback from changing authority between this gate and target health.
    """
    if not profile.protected_activation_required:
        return None
    marker_path = profile.runtime_root.parent / "migration" / "cutover.json"
    if marker_path.exists():
        marker = read_json(marker_path)
        _validate_profile_start_allowed(profiles, profile)
        if marker is None:
            raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_INVALID")
        if marker.get("state") == "ACTIVATED":
            if not acquire_lock:
                return None
            source = profiles.get(str(profile.migration_source_profile))
            lock = RuntimeWriterLock(source.runtime_root / "state" / "core-writer.lock")
            lock.acquire()
            try:
                # Rollback may have won immediately before lock acquisition.
                # Re-read the durable authority while exclusion is held.
                _validate_profile_start_allowed(profiles, profile)
                current = read_json(marker_path)
                if current is None or current.get("state") != "ACTIVATED":
                    raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
            except Exception:
                lock.close()
                raise
            return lock
        if marker.get("state") != "ACTIVATING" or marker.get("source_head") != expected_head:
            raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
    lock = _validate_protected_activation(
        profiles, profile, expected_head, acquire_lock=acquire_lock
    )
    if marker_path.exists() and lock is not None:
        try:
            # An approved rollback can race the pre-lock ACTIVATING read.
            _validate_profile_start_allowed(profiles, profile)
            current = read_json(marker_path)
            if (
                current is None
                or current.get("state") != "ACTIVATING"
                or current.get("source_head") != expected_head
            ):
                raise PreconditionError("PROTECTED_CUTOVER_AUTHORITY_CONFLICT")
        except Exception:
            lock.close()
            raise
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


def _validate_historic_release(profile: DeploymentProfile, release: dict[str, Any]) -> None:
    """Validate a retained rollback release against its own immutable policy."""
    _validate_release(profile, release, require_profile_files=False)
    release_root = Path(str(release["release_path"])).resolve()
    try:
        historic = DeploymentProfiles(release_root / "bct.toml").get(profile.name)
    except (OSError, ValueError, KeyError) as exc:
        raise PreconditionError("DEPLOYMENT_HISTORIC_PROFILE_INVALID") from exc
    if (
        historic.runtime_root != profile.runtime_root
        or historic.service_name != profile.service_name
        or historic.port != profile.port
    ):
        raise PreconditionError("DEPLOYMENT_HISTORIC_PROFILE_TARGET_MISMATCH")
    manifest = read_json(release_root / "manifest.json")
    if not isinstance(manifest, dict) or set(manifest.get("files") or {}) != set(historic.files):
        raise PreconditionError("DEPLOYMENT_HISTORIC_PROFILE_FILE_SET_MISMATCH")


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
            source = Path(manifest["source_root"]) / Path(relative)
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


def _publish_runtime_recovery_scripts(
    profile: DeploymentProfile, release: dict[str, Any]
) -> None:
    """Atomically refresh the bounded sign-in supervisor entrypoints.

    Task Scheduler intentionally invokes stable paths below ``runtime/ops``.
    The scripts themselves are versioned and hash-verified inside the immutable
    release, so publish only those exact release bytes after activation.
    """
    if profile.name != "bct_runtime_v1":
        return
    release_root = Path(str(release["release_path"])).resolve()
    # current.json is deliberately a small activation pointer and does not
    # duplicate the immutable release's file map.  Re-publication after a Core
    # upgrade must therefore load that map from the already validated release
    # manifest instead of assuming the caller still has the staging object.
    manifest = read_json(release_root / "manifest.json")
    if (
        manifest is None
        or manifest.get("source_head") != release.get("source_head")
        or manifest.get("manifest_sha256") != release.get("manifest_sha256")
        or manifest.get("release_path") != str(release_root)
    ):
        raise PreconditionError("DEPLOYMENT_RELEASE_MANIFEST_INVALID")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise PreconditionError("DEPLOYMENT_RELEASE_MANIFEST_INVALID")
    ops_root = profile.runtime_root / "ops"
    ops_root.mkdir(parents=True, exist_ok=True)
    for relative in _RUNTIME_RECOVERY_SCRIPTS:
        expected = files.get(relative)
        source = release_root / Path(relative)
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise PreconditionError("DEPLOYMENT_RECOVERY_SCRIPT_MANIFEST_INVALID:" + relative)
        if not source.is_file() or source.is_symlink() or _sha256(source) != expected:
            raise PreconditionError("DEPLOYMENT_RECOVERY_SCRIPT_INVALID:" + relative)
        destination = ops_root / Path(relative).name
        temporary = ops_root / (destination.name + ".tmp-" + uuid.uuid4().hex)
        try:
            shutil.copyfile(source, temporary)
            if _sha256(temporary) != expected:
                raise ConfirmedFailure("DEPLOYMENT_RECOVERY_SCRIPT_COPY_HASH_MISMATCH:" + relative, release_claims=True)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()


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
