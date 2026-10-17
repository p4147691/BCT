from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import re
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bct.core.models import PreconditionError
from bct.service_runtime import (
    RuntimeServiceController,
    RuntimeWriterLock,
    atomic_json,
    read_json,
)


_REPARSE_POINT = 0x400
_SYSTEM_SIDS = frozenset({"S-1-5-18", "S-1-5-32-544"})
_WRITE_MASK = (
    0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000
    | 0x10000000 | 0x40000000  # GENERIC_ALL / GENERIC_WRITE
)
_OPERATION_ID = re.compile(r"[A-Za-z0-9_.-]{1,160}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *arguments: str, binary: bool = False) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
        errors=None if binary else "replace",
        shell=False,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _validate_trusted_source(root: Path, expected_head: str) -> Path:
    root = root.resolve()
    top = _git(root, "rev-parse", "--show-toplevel")
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    if (
        top.returncode or Path(top.stdout.strip()).resolve() != root
        or head.returncode or head.stdout.strip().casefold() != expected_head.casefold()
        or branch.returncode or branch.stdout.strip() != "main"
    ):
        raise PreconditionError("PROTECTED_TRUSTED_SOURCE_INVALID")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode or status.stdout.strip():
        raise PreconditionError("PROTECTED_TRUSTED_SOURCE_DIRTY")
    return root


def _git_blob(root: Path, head: str, relative: str) -> bytes:
    result = _git(root, "show", f"{head}:{relative}", binary=True)
    if result.returncode:
        raise PreconditionError("PROTECTED_TRUSTED_BLOB_MISSING:" + relative)
    return bytes(result.stdout)


def _git_blob_oid(root: Path, head: str, relative: str) -> str:
    result = _git(root, "rev-parse", f"{head}:{relative}")
    if result.returncode:
        raise PreconditionError("PROTECTED_TRUSTED_BLOB_MISSING:" + relative)
    return result.stdout.strip()


def _git_filtered_oid(root: Path, relative: str, data: bytes) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "hash-object", "--stdin", "--path", relative],
        input=data, capture_output=True, text=False, shell=False, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise PreconditionError("PROTECTED_TRUSTED_GIT_FILTER_FAILED:" + relative)
    return result.stdout.decode("ascii").strip()


def _copy_git_tree(root: Path, head: str, prefix: str, destination: Path) -> dict[str, str]:
    listing = _git(root, "ls-tree", "-r", "--name-only", head, "--", prefix)
    if listing.returncode:
        raise PreconditionError("PROTECTED_TRUSTED_TREE_MISSING:" + prefix)
    names = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    if not names:
        raise PreconditionError("PROTECTED_TRUSTED_TREE_EMPTY:" + prefix)
    hashes: dict[str, str] = {}
    prefix_path = Path(prefix)
    for name in names:
        relative = Path(name).relative_to(prefix_path)
        target = _safe_child(destination, destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = _git_blob(root, head, name)
        target.write_bytes(content)
        hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
    return hashes


def _logical_database_snapshot(path: Path) -> dict[str, Any]:
    names = (
        "operations",
        "resource_claims",
        "events",
        "orchestration_mailbox",
        "orchestration_manager_wakes",
        "orchestration_consumption_receipts",
        "orchestration_consumption_decisions",
        "orchestration_dispatch_outbox",
        "orchestration_reconciliations",
    )
    result: dict[str, Any] = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as database:
        for name in names:
            exists = database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            if not exists:
                continue
            columns = [str(row[1]) for row in database.execute(f"PRAGMA table_info({name})")]
            rows = database.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
            serializable = [
                [base64.b64encode(value).decode("ascii") if isinstance(value, bytes) else value for value in row]
                for row in rows
            ]
            payload = json.dumps(
                {"columns": columns, "rows": serializable},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}
    return result


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


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


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
        lexical_base = _lexical_absolute(base)
        root = lexical_base / "BCT"
        if root == lexical_base or _is_reparse(lexical_base) or _is_reparse(root):
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
    rules: tuple[tuple[str, int, bool, str], ...]


def validate_acl_evidence(
    evidence: Iterable[AclEvidence],
    *,
    protected_root: Path,
    boundary_root: Path,
    current_user_sid: str,
) -> None:
    """Validate already-collected Windows ACL evidence without changing an ACL.

    Each rule is (SID, raw access mask, allow, display rights). The procedure must
    collect the protected root and every existing ancestor through LOCALAPPDATA.
    """
    records = tuple(evidence)
    if not records:
        raise PreconditionError("PROTECTED_ACL_EVIDENCE_MISSING")
    canonical_root = protected_root.resolve()
    canonical_boundary = boundary_root.resolve()
    if canonical_boundary != canonical_root.parent:
        raise PreconditionError("PROTECTED_ACL_BOUNDARY_INVALID")
    allowed_owners = {current_user_sid, *_SYSTEM_SIDS}
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
        for sid, mask, allow, _display in record.rules:
            if not isinstance(mask, int) or mask < 0:
                raise PreconditionError("PROTECTED_ACL_MASK_INVALID:" + str(path))
            if not allow or sid in allowed_owners:
                continue
            if path == canonical_root and mask:
                raise PreconditionError("PROTECTED_ACL_FOREIGN_ACCESS:" + str(path))
            if mask & _WRITE_MASK:
                raise PreconditionError("PROTECTED_ACL_FOREIGN_WRITE:" + str(path))
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
        "@{sid=$_.IdentityReference.Value;mask=[int64]$_.FileSystemRights;right=$_.FileSystemRights.ToString();allow=($_.AccessControlType -eq 'Allow')}});"
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
                (str(rule["sid"]), int(rule["mask"]), bool(rule["allow"]), str(rule["right"]))
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
    source_invariants = _logical_database_snapshot(source)
    target_invariants = _logical_database_snapshot(destination)
    if source_invariants != target_invariants:
        raise PreconditionError("PROTECTED_SQLITE_INVARIANT_MISMATCH")
    return {
        "path": str(destination.resolve()),
        "sha256": _sha256(destination),
        "page_count": page_count,
        "quick_check": "ok",
        "logical_invariants": target_invariants,
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


def _copy_active_release(
    source_runtime: Path,
    target_runtime: Path,
    current: dict[str, Any],
    *,
    trusted_source_root: Path,
) -> dict[str, Any]:
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
    calculated = hashlib.sha256(json.dumps(
        files, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if calculated != manifest_hash:
        raise PreconditionError("PROTECTED_RELEASE_MANIFEST_HASH_MISMATCH")
    target_release = target_runtime / "releases" / source_head
    if target_release.exists():
        raise PreconditionError("PROTECTED_TARGET_RELEASE_EXISTS")
    for relative, digest in files.items():
        source_file = _safe_child(source_release, source_release / str(relative))
        target_file = _safe_child(target_release, target_release / str(relative))
        source_bytes = source_file.read_bytes() if source_file.is_file() else b""
        if (
            not source_file.is_file()
            or _is_reparse(source_file)
            or hashlib.sha256(source_bytes).hexdigest() != digest
            or _git_filtered_oid(trusted_source_root, str(relative), source_bytes)
                != _git_blob_oid(trusted_source_root, source_head, str(relative))
        ):
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
    trusted_source_root: Path,
    target: OperatingPathLayout,
    operation_id: str,
    expected_source_head: str,
    service_name: str,
    service_port: int,
    acl_evidence: Iterable[AclEvidence],
    current_user_sid: str,
) -> dict[str, Any]:
    """Crash-safely stage a quiesced Core migration without activating it."""
    if not _OPERATION_ID.fullmatch(operation_id):
        raise PreconditionError("PROTECTED_OPERATION_ID_INVALID")
    source_runtime = source_runtime.resolve()
    source_data = source_data.resolve()
    trusted_source_root = _validate_trusted_source(trusted_source_root, expected_source_head)
    if not target.root.is_dir() or _is_reparse(target.root) or _is_reparse(target.root.parent):
        raise PreconditionError("PROTECTED_TARGET_ROOT_INVALID")
    validate_acl_evidence(
        acl_evidence,
        protected_root=target.root,
        boundary_root=target.root.parent,
        current_user_sid=current_user_sid,
    )
    if source_runtime == target.runtime.resolve() or source_data == target.data.resolve():
        raise PreconditionError("PROTECTED_SOURCE_TARGET_COLLISION")
    if not (source_runtime / "BCT_CORE_SUPERVISOR.STOP").is_file():
        raise PreconditionError("PROTECTED_SOURCE_SUPERVISOR_NOT_DISABLED")
    controller = RuntimeServiceController(
        runtime_root=source_runtime,
        service_name=service_name,
        port=service_port,
    )
    state = controller.inspect()
    if state.get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
        raise PreconditionError("PROTECTED_SOURCE_CORE_NOT_QUIESCED")
    target_receipt = read_json(target.runtime / "service.json")
    if target_receipt is not None:
        raise PreconditionError("PROTECTED_TARGET_CORE_NOT_QUIESCED")
    receipt_dir = target.root / "migration"
    receipt_path = receipt_dir / f"{operation_id}.json"
    existing = read_json(receipt_path)
    if existing is not None and existing.get("state") == "PUBLISHED":
        exact = {
            "source_head": expected_source_head,
            "source_runtime": str(source_runtime),
            "source_data": str(source_data),
            "target_root": str(target.root),
        }
        if any(existing.get(key) != value for key, value in exact.items()):
            raise PreconditionError("PROTECTED_OPERATION_CONFLICT")
        return existing
    if target.runtime.exists() or target.data.exists():
        raise PreconditionError("PROTECTED_PARTIAL_TARGET_REQUIRES_ROLLBACK")
    staging_root = target.root / "staging" / operation_id
    if staging_root.exists():
        if existing is None or existing.get("state") not in {"PREPARING", "FAILED"}:
            raise PreconditionError("PROTECTED_STAGING_OWNERSHIP_UNKNOWN")
        quarantine = target.root / "quarantine" / f"{operation_id}-{time.time_ns()}"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_root, quarantine)
    stage_runtime = staging_root / "runtime"
    stage_data = staging_root / "data"
    stage_runtime.mkdir(parents=True)
    stage_data.mkdir(parents=True)
    base_receipt = {
        "schema": "BCT_PROTECTED_OPERATING_PATHS_V2",
        "state": "PREPARING",
        "operation_id": operation_id,
        "source_runtime": str(source_runtime),
        "source_data": str(source_data),
        "target_root": str(target.root),
        "source_head": expected_source_head,
        "staging_root": str(staging_root),
        "activation_allowed": False,
    }
    atomic_json(receipt_path, base_receipt)
    writer_lock = RuntimeWriterLock(source_runtime / "state" / "core-writer.lock")
    lock_acquired = False
    try:
        current = read_json(source_runtime / "current.json")
        if current is None or current.get("source_head") != expected_source_head:
            raise PreconditionError("PROTECTED_CURRENT_HEAD_MISMATCH")
        writer_lock.acquire()
        lock_acquired = True
        if controller.inspect().get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
            raise PreconditionError("PROTECTED_SOURCE_CORE_RESTARTED")
        target_current = _copy_active_release(
            source_runtime, stage_runtime, current,
            trusted_source_root=trusted_source_root,
        )
        token_hashes: dict[str, str] = {}
        for name in ("control.token", "mcp.token"):
            source = source_runtime / name
            if not source.is_file() or _is_reparse(source):
                raise PreconditionError("PROTECTED_TOKEN_INVALID:" + name)
            destination = stage_runtime / name
            shutil.copyfile(source, destination)
            if _sha256(source) != _sha256(destination):
                raise PreconditionError("PROTECTED_TOKEN_COPY_MISMATCH:" + name)
            token_hashes[name] = _sha256(destination)
        database = sqlite_online_backup(
            source_runtime / "state" / "state.sqlite",
            stage_runtime / "state" / "state.sqlite",
        )
        receipt_hashes = {
            name: _copy_tree_exact(source_runtime / name, stage_runtime / name)
            for name in ("deployments", "background-operations", "logs")
        }
        data_hashes = _copy_tree_exact(source_data, stage_data)
        release_root = Path(str(target_current["release_path"]))
        ops_hashes = _copy_tree_exact(release_root / "modules" / "mcp" / "ops", stage_runtime / "ops")
        if not ops_hashes:
            raise PreconditionError("PROTECTED_SUPERVISOR_OPS_MISSING")
        final_release = target.runtime / "releases" / expected_source_head
        target_current = {**target_current, "release_path": str(final_release.resolve())}
        atomic_json(stage_runtime / "current.json", target_current)
        old_service = read_json(source_runtime / "service.json")
        if old_service is not None:
            atomic_json(stage_runtime / "migration" / "legacy-service.json", old_service)
        prepared = {
            **base_receipt,
            "state": "PREPARED",
            "manifest_sha256": target_current.get("manifest_sha256"),
            "database": database,
            "token_sha256": token_hashes,
            "receipt_tree_sha256": receipt_hashes,
            "data_tree_sha256": data_hashes,
            "ops_tree_sha256": ops_hashes,
            "source_core_quiesced": True,
            "target_core_started": False,
            "legacy_sensitive_copies_retired": False,
        }
        atomic_json(receipt_path, prepared)
        if controller.inspect().get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
            raise PreconditionError("PROTECTED_SOURCE_CORE_RESTARTED")
        os.replace(stage_runtime, target.runtime)
        os.replace(stage_data, target.data)
        published = {**prepared, "state": "PUBLISHED", "published_at": time.time()}
        atomic_json(receipt_path, published)
        return published
    except Exception as exc:
        failed = {
            **base_receipt,
            "state": "FAILED",
            "error": type(exc).__name__ + ":" + str(exc),
            "target_runtime_exists": target.runtime.exists(),
            "target_data_exists": target.data.exists(),
        }
        atomic_json(receipt_path, failed)
        raise
    finally:
        if lock_acquired:
            writer_lock.close()


def write_activation_receipt(
    *,
    target: OperatingPathLayout,
    operation_id: str,
    source_profile: str,
    target_profile: str,
    expected_source_head: str,
    source_runtime: Path,
    acl_evidence_sha256: str,
    cross_account_denial_verified: bool,
    rcc_canary_verified: bool,
    source_supervisor_disabled: bool,
) -> dict[str, Any]:
    """Record separately approved operating evidence; performs no activation."""
    migration = read_json(target.root / "migration" / f"{operation_id}.json")
    if migration is None or migration.get("state") != "PUBLISHED":
        raise PreconditionError("PROTECTED_MIGRATION_NOT_PUBLISHED")
    booleans = (
        cross_account_denial_verified,
        rcc_canary_verified,
        source_supervisor_disabled,
    )
    if any(value is not True for value in booleans) or not re.fullmatch(r"[0-9a-f]{64}", acl_evidence_sha256):
        raise PreconditionError("PROTECTED_ACTIVATION_EVIDENCE_INVALID")
    receipt = {
        "schema": "BCT_PROTECTED_ACTIVATION_V1",
        "state": "APPROVED",
        "operation_id": operation_id,
        "source_profile": source_profile,
        "target_profile": target_profile,
        "source_head": expected_source_head,
        "source_runtime": str(source_runtime.resolve()),
        "target_runtime": str(target.runtime.resolve()),
        "acl_evidence_sha256": acl_evidence_sha256,
        "cross_account_denial_verified": True,
        "rcc_canary_verified": True,
        "source_supervisor_disabled": True,
    }
    atomic_json(target.root / "migration" / "activation.json", receipt)
    return receipt


def quarantine_failed_migration(
    *, target: OperatingPathLayout, operation_id: str, component: str = "core"
) -> dict[str, Any]:
    """Recoverably move only receipt-owned partial targets; never deletes them."""
    prefix = "rcc-" if component == "rcc" else ""
    receipt_path = target.root / "migration" / f"{prefix}{operation_id}.json"
    receipt = read_json(receipt_path)
    if receipt is None or receipt.get("state") != "FAILED":
        raise PreconditionError("PROTECTED_FAILED_RECEIPT_REQUIRED")
    quarantine = target.root / "quarantine" / f"rollback-{prefix}{operation_id}-{time.time_ns()}"
    quarantine.mkdir(parents=True, exist_ok=False)
    candidates = (
        ((target.root / "rcc"), "rcc"),
        ((target.root / "staging" / operation_id / "rcc"), "staging-rcc"),
    ) if component == "rcc" else (
        (target.runtime, "runtime"),
        (target.data, "data"),
        (target.root / "staging" / operation_id, "staging"),
    )
    moved: dict[str, str] = {}
    for source, name in candidates:
        if source.exists():
            destination = quarantine / name
            os.replace(source, destination)
            moved[name] = str(destination)
    rolled_back = {**receipt, "state": "QUARANTINED", "quarantine": moved}
    atomic_json(receipt_path, rolled_back)
    return rolled_back


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


def build_rcc_host_from_trusted_source(
    *,
    target: OperatingPathLayout,
    trusted_source_root: Path,
    expected_source_head: str,
    operation_id: str,
    acl_evidence: Iterable[AclEvidence],
    current_user_sid: str,
) -> dict[str, Any]:
    """Build the Host from the exact Git blob into the protected boundary."""
    root = _validate_trusted_source(trusted_source_root, expected_source_head)
    if not _OPERATION_ID.fullmatch(operation_id):
        raise PreconditionError("PROTECTED_RCC_HOST_BUILD_EVIDENCE_INVALID")
    validate_acl_evidence(
        acl_evidence,
        protected_root=target.root,
        boundary_root=target.root.parent,
        current_user_sid=current_user_sid,
    )
    source_relative = "modules/rcc/native-host/RelayNativeHostV2.cs"
    source_blob = _git_blob(root, expected_source_head, source_relative)
    source_oid = _git_blob_oid(root, expected_source_head, source_relative)
    tree = _git(root, "rev-parse", f"{expected_source_head}:modules/rcc/native-host")
    if tree.returncode or not re.fullmatch(r"[0-9a-f]{40}", tree.stdout.strip()):
        raise PreconditionError("PROTECTED_RCC_HOST_SOURCE_TREE_INVALID")
    path = target.root / "migration" / f"rcc-host-build-{operation_id}.json"
    existing = read_json(path)
    if existing is not None and existing.get("state") == "PUBLISHED":
        artifact = Path(str(existing.get("artifact_path") or ""))
        exact = {
            "source_head": expected_source_head,
            "source_tree_oid": tree.stdout.strip(),
            "source_blob_oid": source_oid,
        }
        if (
            any(existing.get(key) != value for key, value in exact.items())
            or not artifact.is_file()
            or _is_reparse(artifact)
            or _sha256(artifact) != existing.get("artifact_sha256")
        ):
            raise PreconditionError("PROTECTED_RCC_HOST_BUILD_RECEIPT_CONFLICT")
        return existing
    staging = target.root / "staging" / operation_id / "rcc-host-build"
    prior_artifacts = target.root / "builds" / "rcc" / operation_id
    if staging.exists() or prior_artifacts.exists():
        if existing is None or existing.get("state") not in {"PREPARING", "FAILED"}:
            raise PreconditionError("PROTECTED_RCC_HOST_BUILD_STAGING_EXISTS")
        quarantine = target.root / "quarantine" / f"rcc-host-build-{operation_id}-{time.time_ns()}"
        quarantine.mkdir(parents=True, exist_ok=False)
        if staging.exists():
            os.replace(staging, quarantine / "staging")
        if prior_artifacts.exists():
            os.replace(prior_artifacts, quarantine / "artifacts")
        atomic_json(quarantine / "receipt.json", existing)
    staging.mkdir(parents=True)
    source_path = staging / "RelayNativeHostV2.cs"
    output_path = staging / "RelayNativeHostV2.exe"
    source_path.write_bytes(source_blob)
    compiler_candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    )
    compiler = next((item for item in compiler_candidates if item.is_file()), None)
    if compiler is None or _is_reparse(compiler):
        raise PreconditionError("PROTECTED_RCC_HOST_COMPILER_UNAVAILABLE")
    preparing = {
        "schema": "BCT_RCC_HOST_BUILD_RECEIPT_V2",
        "state": "PREPARING",
        "operation_id": operation_id,
        "source_head": expected_source_head,
        "source_tree_oid": tree.stdout.strip(),
        "source_blob_oid": source_oid,
        "compiler_path": str(compiler.resolve()),
        "compiler_sha256": _sha256(compiler),
    }
    atomic_json(path, preparing)
    try:
        result = subprocess.run(
            [str(compiler), "/nologo", "/target:exe", f"/out:{output_path}", str(source_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode or not output_path.is_file():
            raise PreconditionError("PROTECTED_RCC_HOST_BUILD_FAILED")
        artifact_sha256 = _sha256(output_path)
        artifact = (
            target.root / "builds" / "rcc" / operation_id
            / expected_source_head / artifact_sha256 / output_path.name
        )
        artifact.parent.mkdir(parents=True, exist_ok=False)
        os.replace(output_path, artifact)
        published = {
            **preparing,
            "state": "PUBLISHED",
            "artifact_path": str(artifact.resolve()),
            "artifact_sha256": artifact_sha256,
        }
        atomic_json(path, published)
        return published
    except Exception as exc:
        atomic_json(path, {
            **preparing,
            "state": "FAILED",
            "error": type(exc).__name__ + ":" + str(exc),
        })
        raise


def _validate_rcc_host_build_receipt(
    *,
    target: OperatingPathLayout,
    trusted_source_root: Path,
    expected_source_head: str,
    source_host_executable: Path,
    host_build_operation_id: str,
) -> tuple[dict[str, Any], str]:
    path = target.root / "migration" / f"rcc-host-build-{host_build_operation_id}.json"
    if not path.is_file() or _is_reparse(path):
        raise PreconditionError("PROTECTED_RCC_HOST_BUILD_RECEIPT_REQUIRED")
    receipt_bytes = path.read_bytes()
    receipt = read_json(path)
    tree = _git(trusted_source_root, "rev-parse", f"{expected_source_head}:modules/rcc/native-host")
    source_blob = _git_blob_oid(
        trusted_source_root, expected_source_head,
        "modules/rcc/native-host/RelayNativeHostV2.cs",
    )
    compiler = Path(str(receipt.get("compiler_path") if receipt else ""))
    artifact = source_host_executable.resolve()
    try:
        artifact.relative_to((target.root / "builds" / "rcc" / host_build_operation_id).resolve())
    except ValueError as exc:
        raise PreconditionError("PROTECTED_RCC_HOST_BUILD_ARTIFACT_ESCAPE") from exc
    exact = {
        "schema": "BCT_RCC_HOST_BUILD_RECEIPT_V2",
        "state": "PUBLISHED",
        "source_head": expected_source_head,
        "source_tree_oid": tree.stdout.strip() if tree.returncode == 0 else "",
        "source_blob_oid": source_blob,
        "artifact_path": str(artifact),
        "artifact_sha256": _sha256(source_host_executable),
        "operation_id": host_build_operation_id,
    }
    if receipt is None or any(receipt.get(key) != value for key, value in exact.items()):
        raise PreconditionError("PROTECTED_RCC_HOST_BUILD_RECEIPT_MISMATCH")
    if not _OPERATION_ID.fullmatch(host_build_operation_id):
        raise PreconditionError("PROTECTED_RCC_HOST_BUILD_RECEIPT_MISMATCH")
    if not compiler.is_file() or _is_reparse(compiler) or _sha256(compiler) != receipt.get("compiler_sha256"):
        raise PreconditionError("PROTECTED_RCC_HOST_BUILD_COMPILER_MISMATCH")
    return receipt, hashlib.sha256(receipt_bytes).hexdigest()


def prepare_rcc_migration(
    *,
    source_extension: Path,
    source_host_executable: Path,
    source_native_manifest: Path,
    trusted_source_root: Path,
    expected_source_head: str,
    host_build_operation_id: str,
    operation_id: str,
    target: OperatingPathLayout,
    expected_extension_id: str,
    acl_evidence: Iterable[AclEvidence],
    current_user_sid: str,
) -> dict[str, Any]:
    """Stage protected RCC assets without changing Chrome or HKCU registration."""
    if not _OPERATION_ID.fullmatch(operation_id):
        raise PreconditionError("PROTECTED_OPERATION_ID_INVALID")
    trusted_source_root = _validate_trusted_source(trusted_source_root, expected_source_head)
    validate_acl_evidence(
        acl_evidence,
        protected_root=target.root,
        boundary_root=target.root.parent,
        current_user_sid=current_user_sid,
    )
    source_identity = validate_rcc_relocation(
        extension_manifest=source_extension / "manifest.json",
        native_manifest=source_native_manifest,
        expected_extension_id=expected_extension_id,
        target_host_executable=target.rcc_native / "RelayNativeHostV2.exe",
    )
    if not source_host_executable.is_file() or _is_reparse(source_host_executable):
        raise PreconditionError("PROTECTED_RCC_HOST_SOURCE_INVALID")
    build_receipt, build_receipt_sha256 = _validate_rcc_host_build_receipt(
        target=target,
        trusted_source_root=trusted_source_root,
        expected_source_head=expected_source_head,
        source_host_executable=source_host_executable,
        host_build_operation_id=host_build_operation_id,
    )
    expected_host_sha256 = str(build_receipt["artifact_sha256"])
    live_manifest = (source_extension / "manifest.json").read_bytes()
    manifest_relative = "modules/rcc/extension/manifest.json"
    if _git_filtered_oid(trusted_source_root, manifest_relative, live_manifest) != _git_blob_oid(
        trusted_source_root, expected_source_head, manifest_relative
    ):
        raise PreconditionError("PROTECTED_RCC_LIVE_MANIFEST_NOT_TRUSTED")
    receipt_path = target.root / "migration" / f"rcc-{operation_id}.json"
    staging = target.root / "staging" / operation_id / "rcc"
    existing = read_json(receipt_path)
    if existing is not None and existing.get("state") == "PUBLISHED":
        exact = {
            "source_head": expected_source_head,
            "extension_id": expected_extension_id,
            "host_sha256": expected_host_sha256,
            "host_build_receipt_sha256": build_receipt_sha256,
            "target_root": str(target.root),
        }
        if any(existing.get(key) != value for key, value in exact.items()):
            raise PreconditionError("PROTECTED_RCC_OPERATION_CONFLICT")
        return existing
    if target.rcc_native.exists() or target.rcc_extension.exists():
        raise PreconditionError("PROTECTED_RCC_TARGET_EXISTS")
    if staging.exists():
        if existing is None or existing.get("state") not in {"PREPARING", "FAILED"}:
            raise PreconditionError("PROTECTED_RCC_STAGING_OWNERSHIP_UNKNOWN")
        quarantine = target.root / "quarantine" / f"rcc-{operation_id}-{time.time_ns()}"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, quarantine)
    stage_native = staging / "native"
    stage_extension = staging / "extension"
    stage_native.mkdir(parents=True)
    preparing = {
        "schema": "BCT_PROTECTED_RCC_PATHS_V2",
        "state": "PREPARING",
        "operation_id": operation_id,
        "source_head": expected_source_head,
        "target_root": str(target.root),
        "extension_id": expected_extension_id,
        "host_sha256": expected_host_sha256,
        "host_build_receipt_sha256": build_receipt_sha256,
        "activation_allowed": False,
        "registry_changed": False,
        "chrome_changed": False,
    }
    atomic_json(receipt_path, preparing)
    try:
        extension_hashes = _copy_git_tree(
            trusted_source_root, expected_source_head, "modules/rcc/extension", stage_extension
        )
        target_host = stage_native / "RelayNativeHostV2.exe"
        shutil.copyfile(source_host_executable, target_host)
        if _sha256(target_host) != expected_host_sha256:
            raise PreconditionError("PROTECTED_RCC_HOST_COPY_MISMATCH")
        native = json.loads(source_native_manifest.read_text(encoding="utf-8-sig"))
        final_host = target.rcc_native / "RelayNativeHostV2.exe"
        native["path"] = str(final_host.resolve())
        target_manifest = stage_native / source_native_manifest.name
        atomic_json(target_manifest, native)
        target_identity = validate_rcc_relocation(
            extension_manifest=stage_extension / "manifest.json",
            native_manifest=target_manifest,
            expected_extension_id=expected_extension_id,
            target_host_executable=final_host,
        )
        prepared = {
            **preparing,
            **target_identity,
            "state": "PREPARED",
            "source_extension_manifest_sha256": source_identity["extension_manifest_sha256"],
            "extension_files": extension_hashes,
            "host_sha256": _sha256(target_host),
            "native_manifest": str((target.rcc_native / source_native_manifest.name).resolve()),
        }
        atomic_json(receipt_path, prepared)
        target_rcc = target.root / "rcc"
        if target_rcc.exists():
            raise PreconditionError("PROTECTED_RCC_TARGET_EXISTS")
        os.replace(staging, target_rcc)
        published = {**prepared, "state": "PUBLISHED", "published_at": time.time()}
        atomic_json(receipt_path, published)
        return published
    except Exception as exc:
        atomic_json(receipt_path, {
            **preparing,
            "state": "FAILED",
            "error": type(exc).__name__ + ":" + str(exc),
            "target_rcc_exists": (target.root / "rcc").exists(),
        })
        raise
