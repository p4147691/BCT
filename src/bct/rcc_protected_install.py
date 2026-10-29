"""RCC unpacked-extension bounded install/rollback, invoked only by BCT deploy Work/Operation.

No Chrome/reload calls here. Caller must separately use existing
relay_browser(reload-extension) fenced Operation and read back exact state.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
from typing import Any

from bct.core.models import PreconditionError, UnknownEffectError

EXACT_INSTALLED = Path(r"D:\ChromeExtensions\RCC\extension")
EXACT_STAGE = Path(r"D:\BCT\runtime\rehearsals\rcc-pr356-candidate58-20261029-a")
EXACT_ROLLBACK = Path(r"D:\BCT\runtime\backups\rcc-pr356-live57-20261029-a")
EXACT_MANIFEST = Path(r"D:\BCT\data\RCC_PR356_GUARDED_INSTALL_20261030\release_manifest_immutable.json")
PINNED_MANIFEST_PATH = EXACT_MANIFEST
PINNED_MANIFEST_SHA256 = "c7c1f7f982fcc5669763af737315e3183293e8cfc39ec447d8c18addfc5b620e"
EXACT_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install")
EXTENSION_ID = "ocbidbaplechjjdacmokhnfbdmgjkphf"
OP_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inventory(folder: Path) -> list[dict]:
    if not folder.is_dir() or folder.is_symlink():
        raise PreconditionError("RCC_INSTALL_ROOT_MISSING_OR_LINK")
    result = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or _reparse(path):
            raise PreconditionError("RCC_INSTALL_PAYLOAD_LINK_FORBIDDEN")
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        raw = path.read_bytes()
        result.append({"path": relative, "size": len(raw), "sha256": _sha(raw)})
    return sorted(result, key=lambda item: item["path"])


def _reparse(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        return path.is_symlink()
    except OSError as exc:
        raise PreconditionError("RCC_INSTALL_PATH_UNOBSERVABLE") from exc
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _no_links(path: Path) -> None:
    for node in (path, *path.parents):
        if node.exists() and (node.is_symlink() or _reparse(node)):
            raise PreconditionError("RCC_INSTALL_REPARSE_FORBIDDEN")


def _aggregate(rows: list[dict]) -> str:
    data = "".join(
        f"{r['path']}\0{r['size']}\0{r['sha256']}\n"
        for r in sorted(rows, key=lambda item: item["path"])
    )
    return _sha(data.encode("utf-8"))


def _exact(folder: Path, inventory: dict) -> None:
    actual = _inventory(folder)
    if (len(actual) != inventory.get("fileCount")
            or actual != sorted(inventory.get("files", []), key=lambda x: x["path"])
            or _aggregate(actual) != inventory.get("aggregateSha256")):
        raise PreconditionError("RCC_INSTALL_PAYLOAD_DIGEST_MISMATCH")


def _identity(folder: Path) -> tuple[str, str]:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))
        pub = __import__("base64").b64decode(manifest["key"], validate=True)
        alphabet = "abcdefghijklmnop"
        extension_id = "".join(alphabet[n] for byte in hashlib.sha256(pub).digest()[:16]
                               for n in (byte >> 4, byte & 15))
        return extension_id, str(manifest.get("version") or "")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PreconditionError("RCC_INSTALL_IDENTITY_UNVERIFIABLE") from exc


def _write_once(path: Path, value: dict) -> None:
    """Create-only fsynced journal: never overwrite an ambiguous effect record."""
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise PreconditionError("RCC_INSTALL_OPERATION_ALREADY_RECORDED") from exc


def _advance(path: Path, expected: str, next_state: str, extra: dict | None = None) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("state") != expected:
        raise PreconditionError("RCC_INSTALL_JOURNAL_STATE_CHANGED")
    record.update(extra or {})
    record["state"] = next_state
    record["updated_at"] = time.time()
    tmp = path.with_name(path.name + ".update")
    with tmp.open("xb") as out:
        out.write((json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    return record


def _copy_exact(source: Path, target: Path, manifest: dict) -> None:
    if target.exists():
        raise PreconditionError("RCC_INSTALL_STAGING_EXISTS")
    target.mkdir(parents=False)
    for row in manifest["files"]:
        src = source.joinpath(*row["path"].split("/"))
        dst = target.joinpath(*row["path"].split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if _sha(dst.read_bytes()) != row["sha256"]:
            raise PreconditionError("RCC_INSTALL_STAGING_COPY_MISMATCH")
    _exact(target, manifest)


def _plan(operation_id: str, *, live: Path, candidate: Path, backup_source: Path,
          manifest_file: Path, journal: Path) -> dict:
    if not OP_ID.fullmatch(operation_id):
        raise PreconditionError("RCC_INSTALL_OPERATION_ID_INVALID")
    for item in (live, candidate, backup_source, manifest_file, journal):
        _no_links(item)
    if manifest_file == PINNED_MANIFEST_PATH and _sha(manifest_file.read_bytes()) != PINNED_MANIFEST_SHA256:
        raise PreconditionError("RCC_INSTALL_PINNED_RELEASE_MANIFEST_CHANGED")
    release = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    rollback = release["rollbackBaseline"]
    proposed = release["candidateInventory"]
    if rollback.get("fileCount") != 57 or proposed.get("fileCount") != 58:
        raise PreconditionError("RCC_INSTALL_57_58_CONTRACT_INVALID")
    if _identity(live) != (EXTENSION_ID, "1.0.59"):
        raise PreconditionError("RCC_INSTALL_LIVE_IDENTITY_MISMATCH")
    if _identity(candidate) != (EXTENSION_ID, "1.0.60"):
        raise PreconditionError("RCC_INSTALL_CANDIDATE_IDENTITY_MISMATCH")
    if _identity(backup_source) != (EXTENSION_ID, "1.0.59"):
        raise PreconditionError("RCC_INSTALL_ROLLBACK_IDENTITY_MISMATCH")
    _exact(live, rollback)
    _exact(backup_source, rollback)
    _exact(candidate, proposed)
    if live.parent.stat().st_dev != candidate.stat().st_dev:
        raise PreconditionError("RCC_INSTALL_NOT_SAME_VOLUME")
    return {
        "operation_id": operation_id,
        "live": str(live), "candidate": str(candidate),
        "rollback_source": str(backup_source), "journal": str(journal),
        "installed_aggregate": rollback["aggregateSha256"],
        "candidate_aggregate": proposed["aggregateSha256"],
        "manifest_sha256": _sha(manifest_file.read_bytes()),
        "extension_id": EXTENSION_ID,
        "installed_files": 57, "candidate_files": 58,
    }


def inspect(operation_id: str, *, live: Path | None = None,
            candidate: Path | None = None, backup_source: Path | None = None,
            manifest_file: Path | None = None, journal_root: Path | None = None) -> dict:
    """Pure read-only validation. No staging, backup, Chrome or user profile changes."""
    live = EXACT_INSTALLED if live is None else live
    candidate = EXACT_STAGE if candidate is None else candidate
    backup_source = EXACT_ROLLBACK if backup_source is None else backup_source
    manifest_file = EXACT_MANIFEST if manifest_file is None else manifest_file
    journal_root = EXACT_JOURNAL if journal_root is None else journal_root
    return _plan(operation_id, live=live, candidate=candidate,
                 backup_source=backup_source, manifest_file=manifest_file,
                 journal=journal_root / (operation_id + ".json"))


def install(plan: dict, *, authorization: Any = None, live: Path | None = None,
            candidate: Path | None = None, backup_source: Path | None = None,
            manifest_file: Path | None = None, journal_root: Path | None = None) -> dict:
    """Used only after an externally verified BCT deploy Work/Operation gate.

    An untrusted CLI string is not approval. Production dispatcher must provide
    a verified, exact BCT authorization object after its approval/claim check.
    """
    live = EXACT_INSTALLED if live is None else live
    candidate = EXACT_STAGE if candidate is None else candidate
    backup_source = EXACT_ROLLBACK if backup_source is None else backup_source
    manifest_file = EXACT_MANIFEST if manifest_file is None else manifest_file
    journal_root = EXACT_JOURNAL if journal_root is None else journal_root
    if authorization is None or authorization(plan) is not True:
        raise PreconditionError("RCC_INSTALL_VERIFIED_BCT_AUTHORIZATION_REQUIRED")
    if plan != inspect(plan["operation_id"], live=live, candidate=candidate,
                       backup_source=backup_source, manifest_file=manifest_file,
                       journal_root=journal_root):
        raise PreconditionError("RCC_INSTALL_PLAN_CHANGED")
    journal = journal_root / (plan["operation_id"] + ".json")
    if journal.exists():
        raise PreconditionError("RCC_INSTALL_DUPLICATE_OPERATION")
    if journal_root.exists() and any(journal_root.glob("*.json")):
        raise PreconditionError("RCC_INSTALL_PREVIOUS_STATE_REQUIRES_RECONCILIATION")
    stage = live.parent / (".rcc-stage-" + plan["operation_id"])
    previous = live.parent / (".rcc-previous-" + plan["operation_id"])
    backup_dir = journal_root / ("backup-" + plan["operation_id"])
    for path in (stage, previous, backup_dir):
        _no_links(path)
        if path.exists():
            raise PreconditionError("RCC_INSTALL_PREVIOUS_TEMP_PRESENT")
    release = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    # The journal root is created by the approved install effect, never by inspect.
    journal_root.mkdir(parents=True, exist_ok=True)
    _copy_exact(candidate, stage, release["candidateInventory"])
    _copy_exact(live, backup_dir, release["rollbackBaseline"])
    _write_once(journal, {**plan, "state": "PREPARED",
                          "stage": str(stage), "previous": str(previous),
                          "backup_dir": str(backup_dir), "created_at": time.time()})
    # Windows directory renames are individually atomic, but two renames are
    # not one crash-atomic transaction. An interrupted transition remains
    # visibly UNCERTAIN and must be reconciled, never automatically retried.
    try:
        os.rename(live, previous)
        _advance(journal, "PREPARED", "ORIGINAL_QUARANTINED")
        os.rename(stage, live)
        _advance(journal, "ORIGINAL_QUARANTINED", "INSTALLED_AWAITING_RELOAD")
        _exact(live, release["candidateInventory"])
    except Exception as exc:
        # Journal and original backup remain. Do not silently infer success
        # or call Chrome reload; supervisor inspects exact on-disk state.
        raise UnknownEffectError("RCC_INSTALL_OUTCOME_REQUIRES_RECONCILIATION") from exc
    return {"state": "INSTALLED_AWAITING_RELOAD", "journal": str(journal),
            "extension_id": EXTENSION_ID, "reload_performed": False}


def rollback(operation_id: str, *, authorization: Any = None,
             live: Path | None = None, manifest_file: Path | None = None,
             journal_root: Path | None = None) -> dict:
    """Rollback only exact known install operation, no implicit Chrome reload."""
    live = EXACT_INSTALLED if live is None else live
    manifest_file = EXACT_MANIFEST if manifest_file is None else manifest_file
    journal_root = EXACT_JOURNAL if journal_root is None else journal_root
    journal = journal_root / (operation_id + ".json")
    if not journal.is_file():
        raise PreconditionError("RCC_INSTALL_ORIGINAL_RECEIPT_NOT_FOUND")
    record = json.loads(journal.read_text(encoding="utf-8"))
    if authorization is None or authorization(record) is not True:
        raise PreconditionError("RCC_INSTALL_VERIFIED_BCT_AUTHORIZATION_REQUIRED")
    if record.get("state") != "INSTALLED_AWAITING_RELOAD":
        raise PreconditionError("RCC_INSTALL_ROLLBACK_STATE_INVALID")
    if record.get("live") != str(live):
        raise PreconditionError("RCC_INSTALL_ROLLBACK_TARGET_MISMATCH")
    original = Path(record["previous"])
    if original != live.parent / (".rcc-previous-" + operation_id):
        raise PreconditionError("RCC_INSTALL_ROLLBACK_SOURCE_PATH_INVALID")
    failed = live.parent / (".rcc-rejected-" + operation_id)
    _no_links(original)
    _no_links(failed)
    if failed.exists():
        raise PreconditionError("RCC_INSTALL_ROLLBACK_QUARANTINE_EXISTS")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    if _sha(manifest_file.read_bytes()) != record["manifest_sha256"]:
        raise PreconditionError("RCC_INSTALL_ROLLBACK_MANIFEST_CHANGED")
    _exact(live, manifest["candidateInventory"])
    _exact(original, manifest["rollbackBaseline"])
    try:
        os.rename(live, failed)
        _advance(journal, "INSTALLED_AWAITING_RELOAD", "ROLLBACK_ORIGINAL_SWAPPING")
        os.rename(original, live)
        _advance(journal, "ROLLBACK_ORIGINAL_SWAPPING", "ROLLBACK_AWAITING_RELOAD")
        _exact(live, manifest["rollbackBaseline"])
    except Exception as exc:
        raise UnknownEffectError("RCC_INSTALL_ROLLBACK_OUTCOME_REQUIRES_RECONCILIATION") from exc
    return {"state": "ROLLBACK_AWAITING_RELOAD", "journal": str(journal),
            "extension_id": EXTENSION_ID, "reload_performed": False}
