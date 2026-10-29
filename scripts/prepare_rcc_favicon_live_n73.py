"""Read-only installed RCC capture + isolated integration release-manifest assembly.

Never writes the installed extension, Chrome profile, running service or shared main.
The installed copy is an exact offline rollback snapshot, not an instruction to deploy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXTRAS = {
    "browser/tab_group_adapter.js",
    "browser/tab_group_contract.js",
    "domain/tab_group_service.js",
}
TEN_OLD_MISMATCHES = {
    "background_loader.js",
    "boot/platform_context.js",
    "browser/tab_move_contract.js",
    "content/content_router.js",
    "content/conversation_dom.js",
    "domain/endpoint_service.js",
    "domain/readonly_diagnostics.js",
    "legacy/command_policy.js",
    "manifest.json",
    "platform/browser_gateway.js",
}
NEW_CANDIDATE_ONLY = {"domain/node_favicon_notify_service.js"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(root: Path) -> dict[str, dict]:
    return {
        file.relative_to(root).as_posix(): {
            "path": file.relative_to(root).as_posix(),
            "size": len(file.read_bytes()),
            "sha256": digest(file.read_bytes()),
        }
        for file in sorted(root.rglob("*"))
        if file.is_file()
    }


def inventory_aggregate(records: dict[str, dict]) -> str:
    rows = "".join(
        f"{row['path']}\0{row['size']}\0{row['sha256']}\n"
        for _, row in sorted(records.items())
    )
    return digest(rows.encode("utf-8"))


def manifest_value(records: dict[str, dict]) -> dict:
    return {
        "fileCount": len(records),
        "files": list(row for _, row in sorted(records.items())),
        "aggregateSha256": inventory_aggregate(records),
    }


def copy_and_verify(source: Path, target: Path, expected: dict[str, dict]) -> None:
    if target.exists():
        raise RuntimeError("SNAPSHOT_DESTINATION_MUST_BE_NEW:" + str(target))
    for name, expected_item in expected.items():
        src = source.joinpath(*name.split("/"))
        dst = target.joinpath(*name.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if digest(dst.read_bytes()) != expected_item["sha256"]:
            raise RuntimeError("COPY_VERIFICATION_FAILED:" + name)
    if inventory(target) != expected:
        raise RuntimeError("SNAPSHOT_EXACT_FILE_LIST_MISMATCH")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    args = parser.parse_args()
    installed = args.installed_root.resolve(strict=True)
    snapshot = args.snapshot_root.resolve()
    source = ROOT / "modules" / "rcc" / "extension"
    manifest_path = ROOT / "modules" / "rcc" / "release" / "rcc_v2_rc.json"
    if snapshot.exists():
        raise RuntimeError("SNAPSHOT_ROOT_ALREADY_EXISTS")
    if str(installed).lower() != r"d:\chromeextensions\rcc\extension":
        raise RuntimeError("INSTALLED_ROOT_NOT_EXPECTED")

    # Use the exact 'ours' index stage: PR351 merge has one intentionally
    # unresolved release JSON, but all JS modules are already auto-merged.
    # Pin the previous source manifest to the exact supervisor-accepted main.
    # Do not depend on an unresolved Git merge index in a future rerun.
    source_main = "aaa3982e0b57c8d789189f5499215a4c77884d3e"
    original_text = subprocess.check_output(
        ["git", "show", source_main + ":modules/rcc/release/rcc_v2_rc.json"],
        cwd=ROOT, text=True, encoding="utf-8",
    )
    original = json.loads(original_text)
    historical = {
        row["path"]: row for row in original["rollbackBaseline"]["files"]
    }
    live = inventory(installed)
    if len(live) != 57:
        raise RuntimeError(f"INSTALLED_COUNT_UNEXPECTED:{len(live)}")
    if set(live) - set(historical) != EXTRAS:
        raise RuntimeError("INSTALLED_THREE_EXTRAS_CHANGED")
    differences = {
        name for name in historical.keys() & live.keys()
        if historical[name]["sha256"] != live[name]["sha256"]
    }
    if differences != TEN_OLD_MISMATCHES:
        raise RuntimeError("INSTALLED_TEN_MISMATCHES_CHANGED:" + repr(sorted(differences)))
    if set(historical) - set(live):
        raise RuntimeError("HISTORICAL_FILES_MISSING")
    release_paths = {row["path"] for row in original["candidateInventory"]["files"]}
    if set(live) - release_paths:
        raise RuntimeError("INSTALLED_FILE_NOT_COVERED_BY_CANDIDATE")
    if release_paths - set(live) != NEW_CANDIDATE_ONLY:
        raise RuntimeError("CANDIDATE_NEW_MODULES_UNEXPECTED")

    candidate = {
        name: {
            "path": name,
            "size": len((source / name).read_bytes()),
            "sha256": digest((source / name).read_bytes()),
        }
        for name in sorted(release_paths)
    }
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("version") != "1.0.60":
        raise RuntimeError("SOURCE_MANIFEST_VERSION_CHANGED")
    if json.loads((installed / "manifest.json").read_text(encoding="utf-8")).get("version") != "1.0.59":
        raise RuntimeError("INSTALLED_MANIFEST_VERSION_CHANGED")
    router = (source / "content/content_router.js").read_text(encoding="utf-8")
    if ("relay:nodeLabelNotify" not in router or "renameDiagnostic" not in router):
        raise RuntimeError("BOTH_PR351_AND_PR354_CONTENT_CONTRACTS_REQUIRED")
    if "NODE_LABEL_COMMANDS" not in (source / "legacy/command_policy.js").read_text(encoding="utf-8"):
        raise RuntimeError("NODE_LABEL_ALLOWLIST_LOST")
    if "renameDiagnostic" not in (source / "domain/conversation_rename_service.js").read_text(encoding="utf-8"):
        raise RuntimeError("PR351_DIAGNOSTICS_LOST")

    candidate_loader = re.findall(
        r"importScripts\(['\"]([^'\"]+)['\"]\);",
        (source / "background_loader.js").read_text(encoding="utf-8"),
    )
    if "domain/node_favicon_notify_service.js" not in candidate_loader:
        raise RuntimeError("NODE_FAVICON_LOADER_MISSING")

    original["candidateInventory"] = manifest_value(candidate)
    original["rollbackBaseline"] = manifest_value(live)
    original["activeLoaderGraph"]["background"] = candidate_loader
    original["activeLoaderGraph"]["content"] = source_manifest["content_scripts"][0]["js"]
    plan_path = ROOT / original["rollbackPlan"]
    with plan_path.open("a", encoding="utf-8", newline="\n") as plan:
        plan.write(
            "\n## 2026-10-29 N73 exact installed 1.0.59 baseline\n"
            "The former 54-file reference was **not** an exact copy of the "
            "installed 57-file RCC payload. N73 preserved the installed payload "
            "as an offline, byte-identical 57-file snapshot. No live installation "
            "or Chrome reload was performed.\n\n"
            "Preflight: verify candidate 58-file staging and 57-file rollback "
            "snapshot with verify_release_candidate.py --candidate-root and "
            "--live-root. Never use the previous 54-file rollback reference "
            "as proof of the installed 1.0.59 state.\n\n"
            "Supervisor only: record the accepted installed extension ID, "
            "profile and same-ID loader; back up the then-current installed "
            "payload again before applying a replacement. Promote the exact "
            "staged candidate atomically through the protected BCT deploy gate, "
            "not a manual partial overwrite. On failed acceptance, restore the "
            "exact 57-file snapshot only when its SHA and installation "
            "provenance still match the live target. Preserve all Core, RCC, "
            "Chrome, Work, Operation, Claim and UNKNOWN records. "
            "Never restart/reload for this preparation phase.\n"
        )
    original["rollbackPlanSha256"] = digest(plan_path.read_bytes())

    # Freeze rollback/provenance before updating the tracked manifest.
    snapshot.mkdir(parents=True, exist_ok=False)
    (snapshot / "previous_manifest.json").write_text(
        json.dumps(json.loads(original_text), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rollback_dir = snapshot / "rollback_installed_1_0_59"
    copy_and_verify(installed, rollback_dir, live)
    stage_dir = snapshot / "candidate_source_1_0_60"
    copy_and_verify(source, stage_dir, candidate)
    report = {
        "schema": 1,
        "installed_version": "1.0.59",
        "source_candidate_version": "1.0.60",
        "installed_file_count": len(live),
        "candidate_file_count": len(candidate),
        "installed_extra_from_old_rollback": sorted(EXTRAS),
        "installed_mismatch_from_old_rollback": sorted(TEN_OLD_MISMATCHES),
        "candidate_only_from_installed": sorted(NEW_CANDIDATE_ONLY),
        "installed_sha256_aggregate": inventory_aggregate(live),
        "candidate_sha256_aggregate": inventory_aggregate(candidate),
        "actual_install_modified": False,
        "chrome_reloaded": False,
        "pr351_diagnostics_and_pr354_favicon_both_present": True,
    }
    (snapshot / "comparison_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps(original, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        **report,
        "snapshot_root": str(snapshot),
        "rollback_dir": str(rollback_dir),
        "candidate_dir": str(stage_dir),
        "manifest": str(manifest_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
