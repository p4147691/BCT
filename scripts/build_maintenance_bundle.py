"""Build a separate immutable maintenance directory; never install into LIVE."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil


LAUNCHER = '''"""Verify the frozen maintenance payload before importing it."""
import hashlib, json, sys
from pathlib import Path
root = Path(__file__).resolve().parent
manifest = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
for name, expected in manifest["files"].items():
    path = root / name
    if path.is_symlink() or path.resolve() != path.absolute() or not path.is_file():
        raise SystemExit("MAINTENANCE_BUNDLE_PATH_INVALID")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("MAINTENANCE_BUNDLE_HASH_MISMATCH:" + name)
sys.path.insert(0, str(root / "src"))
from bct_maintenance.cli import main
raise SystemExit(main())
'''


def build(destination):
    source = Path(__file__).resolve().parents[1]
    destination = destination.absolute()
    # Build outputs are deliberately restricted to this checkout's artifacts.
    allowed = source / "artifacts"
    destination.resolve().relative_to(allowed.resolve())
    if destination.exists() or destination.is_symlink():
        raise ValueError("BUNDLE_DESTINATION_ALREADY_EXISTS")
    destination.mkdir(parents=True)
    payload = destination / "src" / "bct_maintenance"
    payload.mkdir(parents=True)
    for path in sorted((source / "src" / "bct_maintenance").glob("*.py")):
        shutil.copyfile(path, payload / path.name)
    (destination / "run.py").write_text(LAUNCHER, encoding="utf-8")
    files = {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(destination.rglob("*.py"))}
    (destination / "bundle.json").write_text(json.dumps({"schema": 1, "files": files}, indent=2), encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    print(build(parser.parse_args().output))
