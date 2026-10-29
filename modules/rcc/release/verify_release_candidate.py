from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = Path(__file__).with_name("rcc_v2_rc.json")


class VerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise VerificationError(f"unsafe relative path: {value}")
    return path.as_posix()


def inventory_digest(files: list[dict[str, Any]]) -> str:
    normalized = "".join(
        f"{item['path']}\0{int(item['size'])}\0{item['sha256']}\n"
        for item in sorted(files, key=lambda value: value["path"])
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _verify_inventory(root: Path, inventory: dict[str, Any], *, exact: bool) -> None:
    files = inventory.get("files")
    if not isinstance(files, list) or not files:
        raise VerificationError("inventory files are required")
    seen: set[str] = set()
    for item in files:
        relative = _safe_relative(str(item.get("path", "")))
        if relative in seen:
            raise VerificationError(f"duplicate inventory path: {relative}")
        seen.add(relative)
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file():
            raise VerificationError(f"missing payload file: {relative}")
        size = target.stat().st_size
        digest = _sha256(target)
        if size != int(item.get("size", -1)) or digest != item.get("sha256"):
            raise VerificationError(f"payload mismatch: {relative}")
    if int(inventory.get("fileCount", -1)) != len(files):
        raise VerificationError("inventory fileCount mismatch")
    if inventory_digest(files) != inventory.get("aggregateSha256"):
        raise VerificationError("inventory aggregate mismatch")
    if exact:
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*") if path.is_file()
        }
        if actual != seen:
            missing = sorted(seen - actual)
            extra = sorted(actual - seen)
            raise VerificationError(f"exact inventory mismatch missing={missing} extra={extra}")


def _extension_id(public_key_text: str) -> str:
    public_key = base64.b64decode(public_key_text, validate=True)
    alphabet = "abcdefghijklmnop"
    return "".join(
        alphabet[nibble]
        for byte in hashlib.sha256(public_key).digest()[:16]
        for nibble in (byte >> 4, byte & 0x0F)
    )


def _set_values(source: str, name: str) -> list[str]:
    match = re.search(rf"const\s+{re.escape(name)}\s*=\s*new Set\(\[(.*?)\]\);", source, re.S)
    if not match:
        raise VerificationError(f"missing policy set: {name}")
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def _message_branches(source: str) -> list[str]:
    return sorted(set(re.findall(r"message\.type\s*===\s*['\"]([^'\"]+)['\"]", source)))


def _verify_contracts(
    repo_root: Path, candidate: dict[str, Any], extension_root: Path | None = None
) -> None:
    extension = extension_root or repo_root / candidate["sourceRoot"]
    chrome_manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8-sig"))
    contracts = candidate["contracts"]

    if _extension_id(chrome_manifest["key"]) != contracts["extensionId"]:
        raise VerificationError("extension identity mismatch")
    if chrome_manifest.get("permissions") != contracts["chromeApi"]["permissions"]:
        raise VerificationError("Chrome permission contract mismatch")
    if chrome_manifest.get("host_permissions") != contracts["chromeApi"]["hostPermissions"]:
        raise VerificationError("Chrome host permission contract mismatch")

    loader = (extension / "background_loader.js").read_text(encoding="utf-8")
    background_graph = re.findall(r"importScripts\(['\"]([^'\"]+)['\"]\);", loader)
    if background_graph != candidate["activeLoaderGraph"]["background"]:
        raise VerificationError("background loader graph mismatch")
    content_graph = chrome_manifest["content_scripts"][0]["js"]
    if content_graph != candidate["activeLoaderGraph"]["content"]:
        raise VerificationError("content loader graph mismatch")

    active = set(background_graph + content_graph)
    if active.intersection(candidate["optionalBrowserPayload"]):
        raise VerificationError("optional Browser Adapter became active")
    if active.intersection(candidate["excludedLegacyPayload"]):
        raise VerificationError("retired legacy payload became active")
    for relative in candidate["dependencyRules"]["domainWithoutChromeApi"]:
        if "chrome." in (extension / relative).read_text(encoding="utf-8"):
            raise VerificationError(f"domain directly uses Chrome API: {relative}")

    policy = (extension / "legacy" / "command_policy.js").read_text(encoding="utf-8")
    matrix = contracts["messageMatrix"]
    policy_sets = {
        "nativeNewRelay": _set_values(policy, "NEW_RELAY_COMMANDS"),
        "nativeConversation": _set_values(policy, "CONVERSATION_COMMANDS"),
        "nativeAtomicChat": _set_values(policy, "ATOMIC_CHAT_COMMANDS"),
        "nativeOrchestration": _set_values(policy, "ORCHESTRATION_COMMANDS"),
        "nativeNodeLabel": _set_values(policy, "NODE_LABEL_COMMANDS"),
        "nativeReadOnly": _set_values(policy, "READ_ONLY_COMMANDS"),
        "nativeMaintenance": _set_values(policy, "MAINTENANCE_COMMANDS"),
        "nativeBlockedLegacy": _set_values(policy, "LEGACY_MUTATION_COMMANDS"),
        "runtimeReadOnly": _set_values(policy, "READ_ONLY_MESSAGES"),
        "runtimeOrchestration": _set_values(policy, "ORCHESTRATION_MESSAGES"),
        "runtimeBlockedLegacy": _set_values(policy, "LEGACY_MUTATION_MESSAGES"),
    }
    for name, actual in policy_sets.items():
        if actual != matrix[name]:
            raise VerificationError(f"message policy mismatch: {name}")
    content_source = (extension / "content" / "content_router.js").read_text(encoding="utf-8")
    if _message_branches(content_source) != sorted(matrix["contentAccepted"]):
        raise VerificationError("content message matrix mismatch")
    popup_source = (extension / "popup.js").read_text(encoding="utf-8")
    popup_types = sorted(set(re.findall(r"type:\s*['\"]([^'\"]+)['\"]", popup_source)))
    if popup_types != sorted(matrix["popupAccepted"]):
        raise VerificationError("popup message matrix mismatch")

    storage = contracts["storage"]
    combined = "\n".join(
        (extension / relative).read_text(encoding="utf-8")
        for relative in background_graph + content_graph
    )
    for area in ("chromeLocal", "chromeSession", "pageSession"):
        for key in storage[area]:
            if key not in combined:
                raise VerificationError(f"storage key missing from active payload: {key}")

    native_manifest = json.loads(
        (repo_root / "modules/rcc/native-host/com.ai_workspace_relay.host.v2.json")
        .read_text(encoding="utf-8-sig")
    )
    wire = contracts["wire"]
    if native_manifest["name"] != wire["nativeHostName"]:
        raise VerificationError("Native Host name mismatch")
    if native_manifest["allowed_origins"] != [wire["allowedOrigin"]]:
        raise VerificationError("Native Host allowed origin mismatch")
    for message_type in wire["nativeInbound"] + wire["nativeOutbound"]:
        if message_type not in combined:
            raise VerificationError(f"native wire message missing: {message_type}")
    if sorted(wire["content"]) != sorted(matrix["contentAccepted"]):
        raise VerificationError("content wire matrix mismatch")
    if sorted(wire["runtime"]) != sorted(
        matrix["runtimeReadOnly"] + matrix["runtimeOrchestration"]
    ):
        raise VerificationError("runtime wire matrix mismatch")
    content_chrome_source = "\n".join(
        (extension / relative).read_text(encoding="utf-8")
        for relative in candidate["activeLoaderGraph"]["content"]
    )
    for forbidden in ("chrome.tabs", "chrome.scripting", "connectNative", "sendNativeMessage"):
        if forbidden in content_chrome_source:
            raise VerificationError(f"Content Script crossed Chrome API boundary: {forbidden}")
    if "lifecycle.runtimeSenderKind(sender)" not in (
        extension / "domain/runtime_message_service.js"
    ).read_text(encoding="utf-8"):
        raise VerificationError("runtime sender validation is not active")
    if "RCC_CONTENT_SENDER_REJECTED" not in content_source:
        raise VerificationError("content sender validation is not active")


def verify(
    manifest_path: Path = DEFAULT_MANIFEST,
    live_root: Path | None = None,
    candidate_root: Path | None = None,
) -> dict[str, Any]:
    candidate = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if candidate.get("schemaVersion") != 1 or candidate.get("kind") != "RCC_REBUILD_V2_RC":
        raise VerificationError("unsupported RCC release candidate manifest")
    source_root = ROOT / candidate["sourceRoot"]
    _verify_inventory(source_root, candidate["candidateInventory"], exact=False)
    _verify_contracts(ROOT, candidate)
    if candidate_root is not None:
        _verify_inventory(candidate_root, candidate["candidateInventory"], exact=True)
        _verify_contracts(ROOT, candidate, extension_root=candidate_root)

    rollback = candidate["rollbackBaseline"]
    if inventory_digest(rollback["files"]) != rollback["aggregateSha256"]:
        raise VerificationError("rollback inventory aggregate mismatch")
    if int(rollback["fileCount"]) != len(rollback["files"]):
        raise VerificationError("rollback fileCount mismatch")
    for item in rollback["files"]:
        _safe_relative(item["path"])
    if live_root is not None:
        _verify_inventory(live_root, rollback, exact=True)

    rollback_plan = ROOT / candidate["rollbackPlan"]
    if not rollback_plan.is_file() or _sha256(rollback_plan) != candidate["rollbackPlanSha256"]:
        raise VerificationError("rollback plan hash mismatch")
    return {
        "ok": True,
        "candidate": candidate["candidate"],
        "candidateFileCount": candidate["candidateInventory"]["fileCount"],
        "candidateAggregateSha256": candidate["candidateInventory"]["aggregateSha256"],
        "rollbackFileCount": rollback["fileCount"],
        "rollbackAggregateSha256": rollback["aggregateSha256"],
        "liveBaselineVerified": live_root is not None,
        "stagedCandidateVerified": candidate_root is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the source-only RCC V2 release candidate")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--live-root", type=Path)
    parser.add_argument("--candidate-root", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            args.manifest.resolve(),
            args.live_root.resolve() if args.live_root else None,
            args.candidate_root.resolve() if args.candidate_root else None,
        )
    except (OSError, ValueError, KeyError, VerificationError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
