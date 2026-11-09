"""RCC unpacked-extension bounded install/rollback, invoked only by BCT deploy Work/Operation.

No Chrome/reload calls here. Caller must separately use existing
browser(reload-extension) fenced Operation and read back exact state.
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
EXACT_STAGE = Path(r"D:\BCT\data\RCC_PR362_58TO58_PREP_20261030\candidate_receipt_58")
EXACT_ROLLBACK = Path(r"D:\BCT\data\RCC_PR362_58TO58_PREP_20261030\rollback_installed_58")
EXACT_MANIFEST = Path(r"D:\BCT\data\RCC_PR362_58TO58_PREP_20261030\release_manifest_58to58_immutable.json")
PINNED_MANIFEST_PATH = EXACT_MANIFEST
PINNED_MANIFEST_SHA256 = "b35f64eccce91c1263cb85932c7c882bb181790ab2b3d406937e380e87b9f244"
EXACT_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-pr362")
PR388_STAGE = Path(r"D:\BCT\data\RCC_PR388_ORDER_20261031_V2\candidate_1_0_61")
PR388_ROLLBACK = Path(r"D:\BCT\data\RCC_PR388_ORDER_20261031_V2\rollback_installed_1_0_60")
PR388_MANIFEST = Path(r"D:\BCT\data\RCC_PR388_ORDER_20261031_V2\release_manifest_pr388_immutable.json")
PR388_MANIFEST_SHA256 = "f0be94c972debe77b784c3979d944a1a37887a1b63f074c00d1bf13e6190a629"
PR388_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-pr388")
RENAME_ACTIONS_STAGE = Path(r"D:\BCT\data\RCC_RENAME_CHAT_ACTIONS_20261031\candidate_1_0_61")
RENAME_ACTIONS_ROLLBACK = Path(r"D:\BCT\data\RCC_RENAME_CHAT_ACTIONS_20261031\rollback_installed_1_0_61")
RENAME_ACTIONS_MANIFEST = Path(r"D:\BCT\data\RCC_RENAME_CHAT_ACTIONS_20261031\release_manifest_rename_actions_immutable.json")
RENAME_ACTIONS_MANIFEST_SHA256 = "19659c2c2ceb53ff37b7d41c16d959d56af6460a31b66f6f9462ef33c89943cc"
RENAME_ACTIONS_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-rename-actions")
DELAYED_SOURCE_PROOF_ROOT = Path(r"D:\BCT\data\RCC_DELAYED_SOURCE_PROOF_20261031")
DELAYED_SOURCE_PROOF_STAGE = DELAYED_SOURCE_PROOF_ROOT / "candidate_1_0_61"
DELAYED_SOURCE_PROOF_ROLLBACK = DELAYED_SOURCE_PROOF_ROOT / "rollback_installed_1_0_61"
DELAYED_SOURCE_PROOF_MANIFEST = DELAYED_SOURCE_PROOF_ROOT / "release_manifest_delayed_source_proof_immutable.json"
DELAYED_SOURCE_PROOF_MANIFEST_SHA256 = "4ec1e98529f784d63f75d8f7f07ebb490ecc7afc71247680c2d0674f8386143b"
DELAYED_SOURCE_PROOF_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-delayed-source-proof")
DELAYED_SOURCE_PROOF_V2_ROOT = Path(r"D:\BCT\data\RCC_DELAYED_SOURCE_PROOF_V2_20261101")
DELAYED_SOURCE_PROOF_V2_STAGE = DELAYED_SOURCE_PROOF_V2_ROOT / "candidate_1_0_61"
DELAYED_SOURCE_PROOF_V2_ROLLBACK = DELAYED_SOURCE_PROOF_V2_ROOT / "rollback_installed_1_0_61"
DELAYED_SOURCE_PROOF_V2_MANIFEST = DELAYED_SOURCE_PROOF_V2_ROOT / "release_manifest_delayed_source_proof_v2_immutable.json"
DELAYED_SOURCE_PROOF_V2_MANIFEST_SHA256 = "c1bf097f51bb1e4d0ea164e95b5edccd3dff7f6b64fa7c2b18a552bb71c5c1d8"
DELAYED_SOURCE_PROOF_V2_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-delayed-source-proof-v2")
SEMANTIC_TURN_ROOT = Path(r"D:\BCT\data\RCC_SEMANTIC_TURN_20261104")
SEMANTIC_TURN_STAGE = SEMANTIC_TURN_ROOT / "candidate_1_0_63"
SEMANTIC_TURN_ROLLBACK = SEMANTIC_TURN_ROOT / "rollback_installed_1_0_63"
SEMANTIC_TURN_MANIFEST = SEMANTIC_TURN_ROOT / "release_manifest_semantic_turn_immutable.json"
SEMANTIC_TURN_MANIFEST_SHA256 = "56caa01e0e1ba700f39e51ae58b91836931a461c2710683a87fd2ab4550d6653"
SEMANTIC_TURN_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-semantic-turn")
SUBMIT_ACTIVATION_FENCE_ROOT = Path(r"D:\BCT\data\RCC_SUBMIT_ACTIVATION_FENCE_20261105")
SUBMIT_ACTIVATION_FENCE_STAGE = SUBMIT_ACTIVATION_FENCE_ROOT / "candidate_1_0_63"
SUBMIT_ACTIVATION_FENCE_ROLLBACK = SUBMIT_ACTIVATION_FENCE_ROOT / "rollback_installed_1_0_63"
SUBMIT_ACTIVATION_FENCE_MANIFEST = SUBMIT_ACTIVATION_FENCE_ROOT / "release_manifest_submit_activation_fence_immutable.json"
SUBMIT_ACTIVATION_FENCE_MANIFEST_SHA256 = "d969dc3789beb08bf32da57b5f06c9db65b8704a7a29bcb8e96446baadceb3ab"
SUBMIT_ACTIVATION_FENCE_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-submit-activation-fence")
RENDERED_PROMPT_PROVENANCE_ROOT = Path(r"D:\BCT\data\RCC_RENDERED_PROMPT_PROVENANCE_20261105")
RENDERED_PROMPT_PROVENANCE_STAGE = RENDERED_PROMPT_PROVENANCE_ROOT / "candidate_1_0_63_exact"
RENDERED_PROMPT_PROVENANCE_ROLLBACK = RENDERED_PROMPT_PROVENANCE_ROOT / "rollback_installed_1_0_63"
RENDERED_PROMPT_PROVENANCE_MANIFEST = RENDERED_PROMPT_PROVENANCE_ROOT / "release_manifest_rendered_prompt_provenance_immutable.json"
RENDERED_PROMPT_PROVENANCE_MANIFEST_SHA256 = "80f9fad12a74afb4f21243315ef65f74aa9b14618fb040229eff5be869ba4427"
RENDERED_PROMPT_PROVENANCE_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-rendered-prompt-provenance")
RENDERED_MARKDOWN_IDENTITY_ROOT = Path(r"D:\BCT\data\RCC_RENDERED_MARKDOWN_IDENTITY_20261106")
RENDERED_MARKDOWN_IDENTITY_STAGE = RENDERED_MARKDOWN_IDENTITY_ROOT / "candidate_1_0_64_exact"
RENDERED_MARKDOWN_IDENTITY_ROLLBACK = RENDERED_MARKDOWN_IDENTITY_ROOT / "rollback_installed_1_0_63"
RENDERED_MARKDOWN_IDENTITY_MANIFEST = RENDERED_MARKDOWN_IDENTITY_ROOT / "release_manifest_rendered_markdown_identity_immutable.json"
RENDERED_MARKDOWN_IDENTITY_MANIFEST_SHA256 = "218463c15870bba1f0608ef8db8f3ebbc5db494a84e72e63c4ea4c0e1ee1c7d8"
RENDERED_MARKDOWN_IDENTITY_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-rendered-markdown-identity")
RENAME_RESILIENCE_ROOT = Path(r"D:\BCT\data\RCC_PUBLIC_COMMANDS_20261108_R3")
RENAME_RESILIENCE_STAGE = RENAME_RESILIENCE_ROOT / "candidate_1_0_65_exact"
RENAME_RESILIENCE_ROLLBACK = RENAME_RESILIENCE_ROOT / "rollback_installed_1_0_64"
RENAME_RESILIENCE_MANIFEST = RENAME_RESILIENCE_ROOT / "release_manifest_rename_resilience_immutable.json"
RENAME_RESILIENCE_MANIFEST_SHA256 = "0900acea83f116831b0c52556a1b66d53a2f7bcd7962c50dba3ee6d62071177f"
RENAME_RESILIENCE_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-rename-resilience")
COMMAND_NAMESPACE_ROOT = Path(r"D:\BCT\data\RCC_COMMAND_NAMESPACE_20261108_R4")
COMMAND_NAMESPACE_STAGE = COMMAND_NAMESPACE_ROOT / "candidate_1_0_66_exact"
COMMAND_NAMESPACE_ROLLBACK = COMMAND_NAMESPACE_ROOT / "rollback_installed_1_0_65"
COMMAND_NAMESPACE_MANIFEST = COMMAND_NAMESPACE_ROOT / "release_manifest_command_namespace_immutable.json"
# Filled from the immutable release artifact before this route is merged.
COMMAND_NAMESPACE_MANIFEST_SHA256 = "a2dab10f4703bd8aca26943c359be598d263f2d37a787f998a6fcd3517579ce1"
COMMAND_NAMESPACE_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-command-namespace")
# Canonical wire vocabulary: preserve the exact 1.0.66 installed payload as
# rollback input and pin the immutable 1.0.67 candidate independently from
# earlier command-namespace receipts.
CANONICAL_WIRE_ROOT = Path(r"D:\BCT\data\RCC_CANONICAL_WIRE_20261108")
CANONICAL_WIRE_STAGE = CANONICAL_WIRE_ROOT / "candidate_1_0_67_exact"
CANONICAL_WIRE_ROLLBACK = CANONICAL_WIRE_ROOT / "rollback_installed_1_0_66"
CANONICAL_WIRE_MANIFEST = CANONICAL_WIRE_ROOT / "release_manifest_canonical_wire_immutable.json"
CANONICAL_WIRE_MANIFEST_SHA256 = "b49520dcef5061503e67f1b1e74742a7a914899b4621b64ae8e30b7b54326f58"
CANONICAL_WIRE_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-canonical-wire")
DOT_TITLE_RENAME_ROOT = Path(r"D:\BCT\data\RCC_DOT_TITLE_RENAME_HIDDEN_BUTTON_20261109")
DOT_TITLE_RENAME_STAGE = DOT_TITLE_RENAME_ROOT / "candidate_1_0_69_hidden_button_exact"
DOT_TITLE_RENAME_ROLLBACK = DOT_TITLE_RENAME_ROOT / "rollback_installed_1_0_69_row_target"
DOT_TITLE_RENAME_MANIFEST = DOT_TITLE_RENAME_ROOT / "release_manifest_dot_hidden_button_immutable.json"
DOT_TITLE_RENAME_MANIFEST_SHA256 = "c6aed9fb673a1be52febca57242e961259cf0fd37c7984f42fb43a851808acab"
DOT_TITLE_RENAME_JOURNAL = Path(r"D:\BCT\runtime\backups\rcc-guarded-install-dot-title-hidden-button")
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
          manifest_file: Path, journal: Path, candidate_version: str = "1.0.60",
          installed_version: str | None = None) -> dict:
    if not OP_ID.fullmatch(operation_id):
        raise PreconditionError("RCC_INSTALL_OPERATION_ID_INVALID")
    for item in (live, candidate, backup_source, manifest_file, journal):
        _no_links(item)
    if manifest_file == PINNED_MANIFEST_PATH and _sha(manifest_file.read_bytes()) != PINNED_MANIFEST_SHA256:
        raise PreconditionError("RCC_INSTALL_PINNED_RELEASE_MANIFEST_CHANGED")
    release = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    rollback = release["rollbackBaseline"]
    proposed = release["candidateInventory"]
    if rollback.get("fileCount") not in (57, 58) or proposed.get("fileCount") != 58:
        raise PreconditionError("RCC_INSTALL_57_58_OR_58_58_CONTRACT_INVALID")
    baseline_version = installed_version or ("1.0.59" if rollback["fileCount"] == 57 else "1.0.60")
    if _identity(live) != (EXTENSION_ID, baseline_version):
        raise PreconditionError("RCC_INSTALL_LIVE_IDENTITY_MISMATCH")
    if candidate_version not in {"1.0.60", "1.0.61", "1.0.63", "1.0.64", "1.0.65", "1.0.66", "1.0.67", "1.0.69"}:
        raise PreconditionError("RCC_INSTALL_CANDIDATE_VERSION_UNSUPPORTED")
    if _identity(candidate) != (EXTENSION_ID, candidate_version):
        raise PreconditionError("RCC_INSTALL_CANDIDATE_IDENTITY_MISMATCH")
    if _identity(backup_source) != (EXTENSION_ID, baseline_version):
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
        "installed_files": rollback["fileCount"], "candidate_files": proposed["fileCount"],
    }


def inspect(operation_id: str, *, live: Path | None = None,
            candidate: Path | None = None, backup_source: Path | None = None,
            manifest_file: Path | None = None, journal_root: Path | None = None,
            candidate_version: str = "1.0.60", installed_version: str | None = None) -> dict:
    """Pure read-only validation. No staging, backup, Chrome or user profile changes."""
    live = EXACT_INSTALLED if live is None else live
    candidate = EXACT_STAGE if candidate is None else candidate
    backup_source = EXACT_ROLLBACK if backup_source is None else backup_source
    manifest_file = EXACT_MANIFEST if manifest_file is None else manifest_file
    journal_root = EXACT_JOURNAL if journal_root is None else journal_root
    return _plan(operation_id, live=live, candidate=candidate,
                 backup_source=backup_source, manifest_file=manifest_file,
                 journal=journal_root / (operation_id + ".json"),
                 candidate_version=candidate_version, installed_version=installed_version)


def install(plan: dict, *, authorization: Any = None, live: Path | None = None,
            candidate: Path | None = None, backup_source: Path | None = None,
            manifest_file: Path | None = None, journal_root: Path | None = None,
            candidate_version: str = "1.0.60", installed_version: str | None = None) -> dict:
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
                       journal_root=journal_root, candidate_version=candidate_version,
                       installed_version=installed_version):
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


def verify_installed(operation_id: str, install_operation_id: str, *,
                     live: Path | None = None, manifest_file: Path | None = None,
                     journal_root: Path | None = None,
                     candidate_version: str = "1.0.60") -> dict:
    """Read-only proof that LIVE is the exact installed candidate.

    This deliberately does not call ``inspect`` because pre-install inspection
    expects LIVE to equal the rollback baseline.  The original immutable
    install receipt binds this check to one approved candidate transition.
    """
    live = EXACT_INSTALLED if live is None else live
    manifest_file = EXACT_MANIFEST if manifest_file is None else manifest_file
    journal_root = EXACT_JOURNAL if journal_root is None else journal_root
    if not OP_ID.fullmatch(operation_id) or not OP_ID.fullmatch(install_operation_id):
        raise PreconditionError("RCC_INSTALL_OPERATION_ID_INVALID")
    _no_links(live)
    _no_links(manifest_file)
    _no_links(journal_root)
    journal = journal_root / (install_operation_id + ".json")
    if not journal.is_file():
        raise PreconditionError("RCC_INSTALL_ORIGINAL_RECEIPT_NOT_FOUND")
    record = json.loads(journal.read_text(encoding="utf-8"))
    if record.get("operation_id") != install_operation_id:
        raise PreconditionError("RCC_INSTALL_ORIGINAL_RECEIPT_MISMATCH")
    if record.get("state") != "INSTALLED_AWAITING_RELOAD":
        raise PreconditionError("RCC_INSTALL_POSTCHECK_STATE_INVALID")
    if record.get("live") != str(live):
        raise PreconditionError("RCC_INSTALL_POSTCHECK_TARGET_MISMATCH")
    release_raw = manifest_file.read_bytes()
    if _sha(release_raw) != record.get("manifest_sha256"):
        raise PreconditionError("RCC_INSTALL_POSTCHECK_MANIFEST_CHANGED")
    release = json.loads(release_raw.decode("utf-8-sig"))
    candidate = release["candidateInventory"]
    if record.get("candidate_aggregate") != candidate.get("aggregateSha256"):
        raise PreconditionError("RCC_INSTALL_POSTCHECK_CANDIDATE_CHANGED")
    _exact(live, candidate)
    if _identity(live) != (EXTENSION_ID, candidate_version):
        raise PreconditionError("RCC_INSTALL_POSTCHECK_IDENTITY_MISMATCH")
    return {
        "state": "INSTALLED_CANDIDATE_VERIFIED",
        "read_only": True,
        "install_operation_id": install_operation_id,
        "extension_id": EXTENSION_ID,
        "candidate_files": candidate["fileCount"],
        "candidate_aggregate": candidate["aggregateSha256"],
        "reload_performed": False,
    }


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
