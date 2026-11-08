"""Prepare the immutable RCC 1.0.67 canonical-wire candidate.

This is a preparation step only.  It never touches the installed extension,
Chrome, Core, existing Work, Operation, Claim, or delivery receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.rcc.release.verify_release_candidate import inventory_digest, verify


SOURCE_MANIFEST = ROOT / "modules" / "rcc" / "release" / "rcc_v2_rc.json"
SOURCE_EXTENSION = ROOT / "modules" / "rcc" / "extension"
INSTALLED_EXTENSION = Path(r"D:\ChromeExtensions\RCC\extension")
DEFAULT_RELEASE_ROOT = Path(r"D:\BCT\data\RCC_CANONICAL_WIRE_20261108")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(folder: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"PAYLOAD_LINK_FORBIDDEN:{path}")
        if path.is_file():
            rows.append({"path": path.relative_to(folder).as_posix(),
                         "size": path.stat().st_size, "sha256": _sha256(path)})
    return rows


def _copy_inventory(source: Path, target: Path, rows: list[dict[str, object]]) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for row in rows:
        relative = Path(str(row["path"]))
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
        if _sha256(destination) != row["sha256"]:
            raise RuntimeError(f"COPY_VERIFICATION_FAILED:{relative.as_posix()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one immutable RCC 1.0.67 candidate.")
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    args = parser.parse_args()
    release_root = args.release_root.resolve()
    candidate = release_root / "candidate_1_0_67_exact"
    rollback = release_root / "rollback_installed_1_0_66"
    immutable_manifest = release_root / "release_manifest_canonical_wire_immutable.json"
    if release_root.exists():
        raise RuntimeError(f"RELEASE_ROOT_ALREADY_EXISTS:{release_root}")
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8-sig"))
    _copy_inventory(SOURCE_EXTENSION, candidate, source["candidateInventory"]["files"])
    installed_rows = _inventory(INSTALLED_EXTENSION)
    installed_manifest = json.loads((INSTALLED_EXTENSION / "manifest.json").read_text(encoding="utf-8-sig"))
    if installed_manifest.get("version") != "1.0.66":
        raise RuntimeError("INSTALLED_VERSION_NOT_1_0_66")
    source["rollbackBaseline"] = {
        "fileCount": len(installed_rows), "files": installed_rows,
        "aggregateSha256": inventory_digest(installed_rows),
    }
    _copy_inventory(INSTALLED_EXTENSION, rollback, installed_rows)
    immutable_manifest.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
    result = verify(immutable_manifest, live_root=rollback, candidate_root=candidate)
    result["immutableManifest"] = str(immutable_manifest)
    result["immutableManifestSha256"] = _sha256(immutable_manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
