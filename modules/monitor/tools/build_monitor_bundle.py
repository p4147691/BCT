from pathlib import Path
import json,re,hashlib,argparse
root=Path(__file__).resolve().parents[1]
partdir=root/"source-parts"; domaindir=root/"domains"
parts=json.loads((partdir/"manifest.json").read_text(encoding="utf-8"))["parts"]
domain_manifest=json.loads((domaindir/"manifest.json").read_text(encoding="utf-8"))["domains"]
fpat=re.compile(rb"^//@@FN_START:([A-Za-z_$][\w$]*)\n(.*?)\n//@@FN_END:\1\n",re.S|re.M)
functions={};owners={}
for info in domain_manifest:
    raw=(domaindir/info["file"]).read_bytes();pos=0;count=0
    for m in fpat.finditer(raw):
        if raw[pos:m.start()].strip():raise ValueError("INVALID_DOMAIN_FRAGMENT:"+info["file"])
        name=m.group(1).decode("ascii")
        if name in functions:raise ValueError("DUPLICATE:"+name)
        functions[name]=m.group(2);owners[name]=info["domain"];count+=1;pos=m.end()
    if raw[pos:].strip() or count!=info["functions"]:raise ValueError("DOMAIN_INTEGRITY:"+info["file"])
marker=re.compile(rb"/\*@@MONITOR_FUNCTION:([A-Za-z_$][\w$]*)@@\*/")
used=[]
def splice(match):
    name=match.group(1).decode("ascii")
    if name not in functions:raise ValueError("UNBOUND_FUNCTION:"+name)
    used.append(name)
    return functions[name]
output=b"".join(marker.sub(splice,(partdir/name).read_bytes()) for name in parts)
if len(used)!=len(set(used)) or len(used)!=len(functions):raise ValueError("MISSING_OR_DUPLICATE_FUNCTION")
runtime=root/"extension/monitor.js"
index=partdir/"SOURCE_FUNCTION_INDEX.md"
idx=["# Monitor function edit ownership","","Edit source in domains/*.js, ordered statements in source-parts/*.js.","Generated extension/monitor.js is not an edit target.",""]
for info in domain_manifest:
    idx+=["## "+info["domain"]+" ("+str(info["functions"])+" functions)",""]
    idx+=["- "+n for n in sorted(functions) if owners[n]==info["domain"]]
    idx+=[""]
index_text="\n".join(idx)
a=argparse.ArgumentParser();a.add_argument("--check",action="store_true");args=a.parse_args()
if args.check:
    if runtime.read_bytes()!=output:raise SystemExit("MONITOR_RUNTIME_OUT_OF_SYNC")
    if not index.is_file() or index.read_text(encoding="utf-8")!=index_text:raise SystemExit("DOMAIN_INDEX_OUT_OF_SYNC")
    print("DOMAIN_BUNDLE_PASS",len(functions),len(domain_manifest),"sha",hashlib.sha256(output).hexdigest())
else:
    runtime.write_bytes(output);index.write_text(index_text,encoding="utf-8",newline="")
    print("DOMAIN_BUNDLE_GENERATED",len(functions),len(domain_manifest),"sha",hashlib.sha256(output).hexdigest())
