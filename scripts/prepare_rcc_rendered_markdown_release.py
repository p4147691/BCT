"""Prepare the immutable RCC 1.0.64 candidate and exact installed rollback.

This is source/candidate preparation only. It never changes the installed
extension, reloads Chrome, or starts BCT services.
"""
from __future__ import annotations

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
RELEASE_ROOT = Path(r"D:\BCT\data\RCC_RENDERED_MARKDOWN_IDENTITY_20261106")
CANDIDATE = RELEASE_ROOT / "candidate_1_0_64_exact"
ROLLBACK = RELEASE_ROOT / "rollback_installed_1_0_63"
IMMUTABLE_MANIFEST = RELEASE_ROOT / "release_manifest_rendered_markdown_identity_immutable.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(folder: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"PAYLOAD_LINK_FORBIDDEN:{path}")
        if path.is_file():
            relative = path.relative_to(folder).as_posix()
            rows.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path)})
    return rows


def copy_inventory(source: Path, target: Path, rows: list[dict[str, object]]) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for row in rows:
        relative = Path(str(row["path"]))
        source_file = source / relative
        target_file = target / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def main() -> int:
    if RELEASE_ROOT.exists():
        raise RuntimeError(f"RELEASE_ROOT_ALREADY_EXISTS:{RELEASE_ROOT}")
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8-sig"))
    candidate_rows = source["candidateInventory"]["files"]
    copy_inventory(SOURCE_EXTENSION, CANDIDATE, candidate_rows)
    installed_rows = inventory(INSTALLED_EXTENSION)
    copy_inventory(INSTALLED_EXTENSION, ROLLBACK, installed_rows)
    source["rollbackBaseline"] = {
        "fileCount": len(installed_rows),
        "files": installed_rows,
        "aggregateSha256": inventory_digest(installed_rows),
    }
    IMMUTABLE_MANIFEST.write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    result = verify(IMMUTABLE_MANIFEST, live_root=ROLLBACK, candidate_root=CANDIDATE)
    result["immutableManifest"] = str(IMMUTABLE_MANIFEST)
    result["immutableManifestSha256"] = sha256(IMMUTABLE_MANIFEST)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
