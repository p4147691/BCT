from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import re
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bct.core.models import PreconditionError
from bct.service_runtime import atomic_json, read_json


_REPARSE_POINT = 0x400
_BROAD_SIDS = frozenset({
    "S-1-1-0",       # Everyone
    "S-1-5-7",       # Anonymous
    "S-1-5-11",      # Authenticated Users
    "S-1-5-32-545",  # BUILTIN\\Users
})
_WRITE_RIGHTS = frozenset({
    "WRITE", "MODIFY", "DELETE", "DELETECHILD", "DELETESUBDIRECTORIESANDFILES",
    "WRITEPERMISSIONS", "WRITEDAC", "TAKEOWNERSHIP", "WRITEOWNER", "FULLCONTROL",
    "WRITEDATA", "CREATEFILES", "CREATEDIRECTORIES", "APPENDDATA", "WRITEATTRIBUTES",
    "WRITEEXTENDEDATTRIBUTES",
})
_OPERATION_ID = re.compile(r"[A-Za-z0-9_.-]{1,160}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & _REPARSE_POINT)


def _safe_child(root: Path, child: Path) -> Path:
    resolved_root = root.resolve()
    resolved = child.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PreconditionError("PROTECTED_PATH_ESCAPE:" + str(child)) from exc
    return resolved


@dataclass(frozen=True)
class OperatingPathLayout:
    root: Path
    runtime: Path
    data: Path
    rcc_native: Path
    rcc_extension: Path

    @classmethod
    def from_local_app_data(cls, local_app_data: str | Path | None = None) -> "OperatingPathLayout":
        raw = str(local_app_data or os.environ.get("LOCALAPPDATA", ""))
        base = Path(raw)
        if not raw or not base.is_absolute():
            raise PreconditionError("PROTECTED_LOCALAPPDATA_UNAVAILABLE")
        root = (base / "BCT").resolve()
        if root == base.resolve() or _is_reparse(base):
            raise PreconditionError("PROTECTED_LOCALAPPDATA_INVALID")
        return cls(
            root=root,
            runtime=root / "runtime",
            data=root / "data",
            rcc_native=root / "rcc" / "native",
            rcc_extension=root / "rcc" / "extension",
        )


@dataclass(frozen=True)
class AclEvidence:
    path: str
    owner_sid: str
    inheritance_protected: bool
    reparse_point: bool
    rules: tuple[tuple[str, str, bool], ...]


def validate_acl_evidence(
    evidence: Iterable[AclEvidence],
    *,
    protected_root: Path,
    boundary_root: Path,
    current_user_sid: str,
) -> None:
    """Validate already-collected Windows ACL evidence without changing an ACL.

    Each rule is (SID, normalized right, allow). The operating procedure must
    collect the protected root and every existing ancestor through LOCALAPPDATA.
    """
    records = tuple(evidence)
    if not records:
        raise PreconditionError("PROTECTED_ACL_EVIDENCE_MISSING")
    canonical_root = protected_root.resolve()
    canonical_boundary = boundary_root.resolve()
    if canonical_boundary != canonical_root.parent:
        raise PreconditionError("PROTECTED_ACL_BOUNDARY_INVALID")
    allowed_owners = {current_user_sid, "S-1-5-18", "S-1-5-32-544"}
    saw_root = False
    saw_boundary = False
    for record in records:
        path = Path(record.path).resolve()
        if path == canonical_root:
            saw_root = True
            if not record.inheritance_protected:
                raise PreconditionError("PROTECTED_ACL_ROOT_INHERITANCE_ENABLED")
        elif path == canonical_boundary:
            saw_boundary = True
        elif canonical_root not in path.parents and path not in canonical_root.parents:
            raise PreconditionError("PROTECTED_ACL_UNRELATED_PATH")
        if record.reparse_point:
            raise PreconditionError("PROTECTED_ACL_REPARSE_POINT:" + str(path))
        if record.owner_sid not in allowed_owners:
            raise PreconditionError("PROTECTED_ACL_OWNER_INVALID:" + str(path))
        for sid, right, allow in record.rules:
            normalized = {
                part.strip().upper().replace("_", "").replace(" ", "")
                for part in str(right).replace(",", "|").split("|")
            }
            if allow and sid in _BROAD_SIDS and normalized.intersection(_WRITE_RIGHTS):
                raise PreconditionError("PROTECTED_ACL_BROAD_WRITE:" + str(path))
    if not saw_root:
        raise PreconditionError("PROTECTED_ACL_ROOT_EVIDENCE_MISSING")
    if not saw_boundary:
        raise PreconditionError("PROTECTED_ACL_BOUNDARY_EVIDENCE_MISSING")


def collect_windows_acl_evidence(paths: Iterable[Path]) -> tuple[AclEvidence, ...]:
    """Collect owner/ACE/reparse evidence with Windows PowerShell; never changes ACLs."""
    if os.name != "nt":
        raise PreconditionError("PROTECTED_ACL_WINDOWS_REQUIRED")
    records: list[AclEvidence] = []
    script = (
        "$p=$args[0];$a=Get-Acl -LiteralPath $p -ErrorAction Stop;"
        "$o=([Security.Principal.NTAccount]$a.Owner).Translate([Security.Principal.SecurityIdentifier]).Value;"
        "$r=@($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|%{"
        "@{sid=$_.IdentityReference.Value;right=$_.FileSystemRights.ToString();allow=($_.AccessControlType -eq 'Allow')}});"
        "$x=((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0;"
        "@{path=[IO.Path]::GetFullPath($p);owner_sid=$o;inheritance_protected=$a.AreAccessRulesProtected;"
        "reparse_point=$x;rules=$r}|ConvertTo-Json -Depth 6 -Compress"
    )
    for path in paths:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise PreconditionError("PROTECTED_ACL_COLLECTION_FAILED:" + str(path))
        try:
            value = json.loads(result.stdout)
            rules_value = value["rules"]
            if isinstance(rules_value, dict):
                rules_value = [rules_value]
            rules = tuple(
                (str(rule["sid"]), str(rule["right"]), bool(rule["allow"]))
                for rule in rules_value
            )
            records.append(AclEvidence(
                path=str(value["path"]),
                owner_sid=str(value["owner_sid"]),
                inheritance_protected=bool(value["inheritance_protected"]),
                reparse_point=bool(value["reparse_point"]),
                rules=rules,
            ))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PreconditionError("PROTECTED_ACL_EVIDENCE_INVALID:" + str(path)) from exc
    return tuple(records)


def sqlite_online_backup(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file() or _is_reparse(source):
        raise PreconditionError("PROTECTED_SQLITE_SOURCE_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise PreconditionError("PROTECTED_SQLITE_DESTINATION_EXISTS")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as source_db:
        with closing(sqlite3.connect(destination)) as target_db:
            source_db.backup(target_db)
            check = target_db.execute("PRAGMA quick_check").fetchall()
            if check != [("ok",)]:
                raise PreconditionError("PROTECTED_SQLITE_QUICK_CHECK_FAILED")
            page_count = int(target_db.execute("PRAGMA page_count").fetchone()[0])
            target_db.commit()
    return {
        "path": str(destination.resolve()),
        "sha256": _sha256(destination),
        "page_count": page_count,
        "quick_check": "ok",
    }


def _copy_tree_exact(source: Path, destination: Path) -> dict[str, str]:
    if not source.exists():
        return {}
    if not source.is_dir() or _is_reparse(source):
        raise PreconditionError("PROTECTED_COPY_SOURCE_INVALID:" + str(source))
    hashes: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        if _is_reparse(path):
            raise PreconditionError("PROTECTED_COPY_REPARSE_POINT:" + str(path))
        relative = path.relative_to(source)
        target = _safe_child(destination, destination / relative)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            raise PreconditionError("PROTECTED_COPY_SOURCE_INVALID:" + str(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        source_hash = _sha256(path)
        if _sha256(target) != source_hash:
            raise PreconditionError("PROTECTED_COPY_HASH_MISMATCH:" + str(relative))
        hashes[relative.as_posix()] = source_hash
    return hashes


def _copy_active_release(source_runtime: Path, target_runtime: Path, current: dict[str, Any]) -> dict[str, Any]:
    source_head = str(current.get("source_head") or "")
    manifest_hash = str(current.get("manifest_sha256") or "")
    source_release = Path(str(current.get("release_path") or "")).resolve()
    if source_release != (source_runtime / "releases" / source_head).resolve():
        raise PreconditionError("PROTECTED_CURRENT_RELEASE_PATH_MISMATCH")
    manifest = read_json(source_release / "manifest.json")
    if manifest is None or manifest.get("source_head") != source_head or manifest.get("manifest_sha256") != manifest_hash:
        raise PreconditionError("PROTECTED_RELEASE_MANIFEST_MISMATCH")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PreconditionError("PROTECTED_RELEASE_FILES_INVALID")
    target_release = target_runtime / "releases" / source_head
    if target_release.exists():
        raise PreconditionError("PROTECTED_TARGET_RELEASE_EXISTS")
    for relative, digest in files.items():
        source_file = _safe_child(source_release, source_release / str(relative))
        target_file = _safe_child(target_release, target_release / str(relative))
        if not source_file.is_file() or _is_reparse(source_file) or _sha256(source_file) != digest:
            raise PreconditionError("PROTECTED_RELEASE_FILE_INVALID:" + str(relative))
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target_file)
        if _sha256(target_file) != digest:
            raise PreconditionError("PROTECTED_RELEASE_COPY_MISMATCH:" + str(relative))
    shutil.copyfile(source_release / "manifest.json", target_release / "manifest.json")
    target_current = {**current, "release_path": str(target_release.resolve())}
    atomic_json(target_runtime / "current.json", target_current)
    return target_current


def prepare_core_migration(
    *,
    source_runtime: Path,
    source_data: Path,
    target: OperatingPathLayout,
    operation_id: str,
    expected_source_head: str,
    source_service_state: str,
    target_service_state: str,
    acl_evidence: Iterable[AclEvidence],
    current_user_sid: str,
) -> dict[str, Any]:
    """Stage a quiesced Core migration; never starts either Core or retires old secrets."""
    if source_service_state not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
        raise PreconditionError("PROTECTED_SOURCE_CORE_NOT_QUIESCED")
    if target_service_state not in {"MISSING", "STOPPED", "STOPPED_STALE_RECEIPT"}:
        raise PreconditionError("PROTECTED_TARGET_CORE_NOT_QUIESCED")
    if not _OPERATION_ID.fullmatch(operation_id):
        raise PreconditionError("PROTECTED_OPERATION_ID_INVALID")
    source_runtime = source_runtime.resolve()
    source_data = source_data.resolve()
    if not target.root.is_dir() or _is_reparse(target.root) or _is_reparse(target.root.parent):
        raise PreconditionError("PROTECTED_TARGET_ROOT_INVALID")
    validate_acl_evidence(
        acl_evidence,
        protected_root=target.root,
        boundary_root=target.root.parent,
        current_user_sid=current_user_sid,
    )
    if target.runtime.exists() or target.data.exists():
        raise PreconditionError("PROTECTED_TARGET_MUST_BE_NEW")
    if source_runtime == target.runtime.resolve() or source_data == target.data.resolve():
        raise PreconditionError("PROTECTED_SOURCE_TARGET_COLLISION")
    current = read_json(source_runtime / "current.json")
    if current is None or current.get("source_head") != expected_source_head:
        raise PreconditionError("PROTECTED_CURRENT_HEAD_MISMATCH")
    target.runtime.mkdir(parents=True)
    target.data.mkdir(parents=True)
    target_current = _copy_active_release(source_runtime, target.runtime, current)
    token_hashes: dict[str, str] = {}
    for name in ("control.token", "mcp.token"):
        source = source_runtime / name
        if not source.is_file() or _is_reparse(source):
            raise PreconditionError("PROTECTED_TOKEN_INVALID:" + name)
        destination = target.runtime / name
        shutil.copyfile(source, destination)
        if _sha256(source) != _sha256(destination):
            raise PreconditionError("PROTECTED_TOKEN_COPY_MISMATCH:" + name)
        token_hashes[name] = _sha256(destination)
    database = sqlite_online_backup(
        source_runtime / "state" / "state.sqlite",
        target.runtime / "state" / "state.sqlite",
    )
    receipt_hashes: dict[str, dict[str, str]] = {}
    for name in ("deployments", "background-operations", "logs"):
        receipt_hashes[name] = _copy_tree_exact(source_runtime / name, target.runtime / name)
    data_hashes = _copy_tree_exact(source_data, target.data)
    old_service = read_json(source_runtime / "service.json")
    if old_service is not None:
        atomic_json(target.runtime / "migration" / "legacy-service.json", old_service)
    receipt = {
        "schema": "BCT_PROTECTED_OPERATING_PATHS_V1",
        "operation_id": operation_id,
        "source_runtime": str(source_runtime),
        "target_root": str(target.root),
        "source_head": expected_source_head,
        "manifest_sha256": target_current.get("manifest_sha256"),
        "database": database,
        "token_sha256": token_hashes,
        "receipt_tree_sha256": receipt_hashes,
        "data_tree_sha256": data_hashes,
        "source_core_quiesced": True,
        "target_core_started": False,
        "legacy_sensitive_copies_retired": False,
        "activation_allowed": False,
    }
    atomic_json(target.runtime / "migration" / f"{operation_id}.json", receipt)
    return receipt


def extension_id_from_key(encoded_key: str) -> str:
    try:
        public_key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, TypeError) as exc:
        raise PreconditionError("PROTECTED_RCC_MANIFEST_KEY_INVALID") from exc
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[int(character, 16)] for character in hashlib.sha256(public_key).hexdigest()[:32])


def validate_rcc_relocation(
    *,
    extension_manifest: Path,
    native_manifest: Path,
    expected_extension_id: str,
    target_host_executable: Path,
) -> dict[str, Any]:
    try:
        extension = json.loads(extension_manifest.read_text(encoding="utf-8-sig"))
        native = json.loads(native_manifest.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreconditionError("PROTECTED_RCC_MANIFEST_INVALID") from exc
    actual_id = extension_id_from_key(str(extension.get("key") or ""))
    origin = f"chrome-extension://{actual_id}/"
    if actual_id != expected_extension_id or native.get("allowed_origins") != [origin]:
        raise PreconditionError("PROTECTED_RCC_IDENTITY_MISMATCH")
    if native.get("name") != "com.ai_workspace_relay.host":
        raise PreconditionError("PROTECTED_RCC_HOST_NAME_MISMATCH")
    target = target_host_executable.resolve()
    if target.name.casefold() != "relaynativehostv2.exe":
        raise PreconditionError("PROTECTED_RCC_HOST_TARGET_INVALID")
    return {
        "extension_id": actual_id,
        "allowed_origin": origin,
        "extension_manifest_sha256": _sha256(extension_manifest),
        "native_manifest_sha256": _sha256(native_manifest),
        "target_host_executable": str(target),
        "chrome_path_switch_required": True,
        "existing_tabs_must_be_preserved": True,
    }


def prepare_rcc_migration(
    *,
    source_extension: Path,
    source_host_executable: Path,
    source_native_manifest: Path,
    target: OperatingPathLayout,
    expected_extension_id: str,
    acl_evidence: Iterable[AclEvidence],
    current_user_sid: str,
) -> dict[str, Any]:
    """Stage protected RCC assets without changing Chrome or HKCU registration."""
    validate_acl_evidence(
        acl_evidence,
        protected_root=target.root,
        boundary_root=target.root.parent,
        current_user_sid=current_user_sid,
    )
    if target.rcc_native.exists() or target.rcc_extension.exists():
        raise PreconditionError("PROTECTED_RCC_TARGET_EXISTS")
    source_identity = validate_rcc_relocation(
        extension_manifest=source_extension / "manifest.json",
        native_manifest=source_native_manifest,
        expected_extension_id=expected_extension_id,
        target_host_executable=target.rcc_native / "RelayNativeHostV2.exe",
    )
    extension_hashes = _copy_tree_exact(source_extension, target.rcc_extension)
    if not source_host_executable.is_file() or _is_reparse(source_host_executable):
        raise PreconditionError("PROTECTED_RCC_HOST_SOURCE_INVALID")
    target.rcc_native.mkdir(parents=True)
    target_host = target.rcc_native / "RelayNativeHostV2.exe"
    shutil.copyfile(source_host_executable, target_host)
    if _sha256(source_host_executable) != _sha256(target_host):
        raise PreconditionError("PROTECTED_RCC_HOST_COPY_MISMATCH")
    native = json.loads(source_native_manifest.read_text(encoding="utf-8-sig"))
    native["path"] = str(target_host.resolve())
    target_manifest = target.rcc_native / source_native_manifest.name
    atomic_json(target_manifest, native)
    target_identity = validate_rcc_relocation(
        extension_manifest=target.rcc_extension / "manifest.json",
        native_manifest=target_manifest,
        expected_extension_id=expected_extension_id,
        target_host_executable=target_host,
    )
    return {
        **target_identity,
        "source_extension_manifest_sha256": source_identity["extension_manifest_sha256"],
        "extension_files": extension_hashes,
        "host_sha256": _sha256(target_host),
        "native_manifest": str(target_manifest.resolve()),
        "registry_changed": False,
        "chrome_changed": False,
        "activation_allowed": False,
    }
