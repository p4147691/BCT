"""Build-only packaging of the existing BCT Browser Bridge with ComfyUI read assets."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import json

def build(destination: Path, root: Path) -> Path:
    source=root/"modules/browser-bridge/extension"
    assets=root/"modules/browser-bridge/comfy-canvas"
    if destination.resolve() in (source.resolve(),assets.resolve()):
        raise ValueError("COMFY_BUILD_DESTINATION_PROTECTED")
    if destination.exists():
        raise FileExistsError("COMFY_BUILD_DESTINATION_EXISTS")
    shutil.copytree(source,destination)
    target=destination/"comfy-canvas"
    target.mkdir()
    for name in ("comfy-main.js","comfy-isolated.js","comfy-transport.js"):
        shutil.copy2(assets/name,target/name)
    manifest=json.loads((destination/"manifest.json").read_text(encoding="utf-8"))
    # Keep the existing prototype manifest unchanged in the source tree.
    # Grant fixed-origin access only to this explicitly built candidate.
    manifest["host_permissions"]=["http://127.0.0.1:8188/*"]
    manifest["content_scripts"]=[
        {"matches":["http://127.0.0.1:8188/*"],
         "js":["comfy-canvas/comfy-main.js"],"run_at":"document_idle","world":"MAIN"},
        {"matches":["http://127.0.0.1:8188/*"],
         "js":["comfy-canvas/comfy-isolated.js"],"run_at":"document_idle","world":"ISOLATED"},
    ]
    (destination/"manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for item in manifest["content_scripts"]:
        for name in item["js"]:
            if not (destination/name).is_file():
                raise RuntimeError("COMFY_CONTENT_SCRIPT_MISSING")
    if manifest.get("permissions") != ["nativeMessaging"]:
        raise RuntimeError("COMFY_PERMISSIONS_UNEXPECTED")
    return destination

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--dest",type=Path,required=True)
    args=parser.parse_args()
    print(build(args.dest,Path(__file__).resolve().parents[1]))
