"""Refresh the tracked RCC candidate inventory from the active unpacked extension.

This only updates the source release manifest.  It does not touch an installed
extension, Chrome, BCT services, immutable release artifacts, or receipts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.rcc.release.verify_release_candidate import inventory_digest


EXTENSION = ROOT / "modules" / "rcc" / "extension"
RELEASE = ROOT / "modules" / "rcc" / "release" / "rcc_v2_rc.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path, paths: list[str]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for relative in sorted(paths):
        path = root.joinpath(*relative.split("/"))
        if path.is_symlink():
            raise RuntimeError(f"RCC_SOURCE_LINK_FORBIDDEN:{path}")
        if not path.is_file():
            raise RuntimeError(f"RCC_SOURCE_PAYLOAD_MISSING:{relative}")
        records.append({
            "path": relative,
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return records


def main() -> int:
    release = json.loads(RELEASE.read_text(encoding="utf-8-sig"))
    baseline = json.loads(subprocess.check_output(
        ["git", "show", "HEAD:modules/rcc/release/rcc_v2_rc.json"],
        cwd=ROOT, text=True, encoding="utf-8",
    ))
    records = _inventory(
        EXTENSION,
        [row["path"] for row in baseline["candidateInventory"]["files"]],
    )
    release["candidateInventory"] = {
        "fileCount": len(records),
        "files": records,
        "aggregateSha256": inventory_digest(records),
    }
    release["candidate"] = "RCC_COMPOSER_REBIND_20261110"
    RELEASE.write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        "effect": "SOURCE_RELEASE_INVENTORY_REFRESHED",
        "fileCount": len(records),
        "aggregateSha256": release["candidateInventory"]["aggregateSha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
