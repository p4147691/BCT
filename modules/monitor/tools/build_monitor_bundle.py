from pathlib import Path
import json,hashlib,argparse,re
root=Path(__file__).resolve().parents[1]
folder=root/"source-parts"
manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
output=b"".join((folder/name).read_bytes() for name in manifest["parts"])
target=root/"extension"/"monitor.js"
index_path=root/"source-parts"/"SOURCE_FUNCTION_INDEX.md"
index_lines=["# Monitor editable source function index","","Edit the listed source part, then rebuild the generated extension/monitor.js.",""]
for name in manifest["parts"]:
    text=(folder/name).read_text(encoding="utf-8")
    matches=re.findall(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",text,re.M)
    index_lines.append("## "+name+" ("+str(len(matches))+" declared functions)")
    index_lines.append("")
    for f in matches: index_lines.append("- "+f)
    index_lines.append("")
index_content="\n".join(index_lines)

a=argparse.ArgumentParser();a.add_argument("--check",action="store_true");mode=a.parse_args()
if mode.check:
 if target.read_bytes()!=output:raise SystemExit("OUT_OF_SYNC: edit source-parts then rebuild")
 if not index_path.exists() or index_path.read_text(encoding="utf-8")!=index_content:
  raise SystemExit("SOURCE_FUNCTION_INDEX_OUT_OF_SYNC")
 print("MONITOR_BUNDLE_SYNC_PASS",len(output),hashlib.sha256(output).hexdigest())
else:
 target.write_bytes(output)
 index_path.write_text(index_content,encoding="utf-8",newline="")
 print("MONITOR_BUNDLE_GENERATED",len(output),hashlib.sha256(output).hexdigest())
