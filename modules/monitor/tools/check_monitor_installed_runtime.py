"""Validate only the files that belong to an installed Monitor runtime.

The full source structure checker intentionally depends on source-parts, native
sources, design documents, and repository tests.  Those are not runtime files
and must not be copied into the Chrome extension installation merely to make a
reload gate pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_asset(root: Path, value: str) -> Path | None:
    value = value.split("?", 1)[0].split("#", 1)[0]
    if not value or "://" in value or value.startswith(("data:", "chrome-extension:")):
        return None
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"asset escapes extension root: {value}")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate installed Monitor runtime")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    runtime = Path(args.root).resolve()
    ext = runtime / "extension"
    tools = runtime / "tools"
    errors: list[dict[str, object]] = []
    facts: dict[str, object] = {}

    required = [
        ext / "manifest.json", ext / "desktop.html", ext / "monitor.js",
        ext / "monitor.css", ext / "MONITOR_JS_INDEX.md",
        tools / "Request-MonitorDeploymentCheck.ps1",
        tools / "check_monitor_installed_runtime.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        errors.append({"kind": "installed_runtime_missing_required", "paths": missing})

    manifest: dict[str, object] = {}
    if (ext / "manifest.json").is_file():
        try:
            manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8-sig"))
            if manifest.get("name") != "BCT Window Monitor" or not manifest.get("version") or not manifest.get("key"):
                errors.append({"kind": "installed_manifest_identity_invalid"})
            facts["manifest_version"] = manifest.get("version")
        except (OSError, ValueError) as exc:
            errors.append({"kind": "installed_manifest_unreadable", "detail": str(exc)[:160]})

    index = ext / "MONITOR_JS_INDEX.md"
    monitor = ext / "monitor.js"
    if index.is_file() and monitor.is_file():
        match = re.search(r"^- sha256: `([0-9a-f]{64})`$", index.read_text(encoding="utf-8"), re.MULTILINE)
        observed = sha256(monitor)
        facts["monitor_js_sha256"] = observed
        if not match or match.group(1) != observed:
            errors.append({"kind": "installed_monitor_bundle_hash_mismatch"})

    assets: set[Path] = set()
    html = ext / "desktop.html"
    if html.is_file():
        text = html.read_text(encoding="utf-8", errors="replace")
        for value in re.findall(r"<(?:script|link)\b[^>]*?(?:src|href)=[\"']([^\"']+)", text, re.IGNORECASE):
            try:
                asset = local_asset(ext, value)
            except ValueError as exc:
                errors.append({"kind": "installed_asset_path_invalid", "detail": str(exc)})
                continue
            if asset is not None:
                assets.add(asset)
                if not asset.is_file():
                    errors.append({"kind": "installed_asset_missing", "path": str(asset)})
        layout_pos = text.find('src="monitor-ui-layout.js"')
        monitor_pos = text.find('src="monitor.js"')
        if layout_pos < 0 or monitor_pos < 0 or layout_pos > monitor_pos:
            errors.append({"kind": "installed_script_order_invalid"})

    worker = manifest.get("background", {}) if isinstance(manifest, dict) else {}
    if isinstance(worker, dict) and isinstance(worker.get("service_worker"), str):
        assets.add(ext / str(worker["service_worker"]))
    node = shutil.which("node")
    if node:
        for asset in sorted(assets):
            if asset.suffix.lower() != ".js" or not asset.is_file():
                continue
            result = subprocess.run(
                [node, "--check", str(asset)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            if result.returncode:
                errors.append({"kind": "installed_javascript_syntax", "path": str(asset)})
    else:
        errors.append({"kind": "installed_node_unavailable"})

    facts["referenced_asset_count"] = len(assets)
    print(json.dumps({"ok": not errors, "errors": errors, "facts": facts}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
