"""Read-only check for stale common/module instructions in a Git worktree."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

_COMMON = "AGENTS.md"
_EDITOR = ".cursor/rules/bct-delivery-flow.mdc"
_RETIRED = ".cursor/rules/bct-persistent-supervision.mdc"
_MODULES = ("modules/monitor/extension/AGENTS.md",)

def digest(path: Path):
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        return hashlib.sha256(raw).hexdigest()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()

def compare(canonical_root: Path, worktree: Path):
    canonical_root=canonical_root.resolve()
    worktree=worktree.resolve()
    rows=[]
    for rel in (_COMMON,_EDITOR,*_MODULES):
        expected=digest(canonical_root/rel)
        observed=digest(worktree/rel)
        status=("MATCH" if expected is not None and observed==expected
                else "MISSING_CANONICAL" if expected is None
                else "MISSING_WORKTREE" if observed is None
                else "STALE_INSTRUCTIONS")
        rows.append({"path":rel,"status":status,"canonical_sha256":expected,
                     "worktree_sha256":observed})
    retired=(worktree/_RETIRED).is_file()
    return {
        "schema":1,
        "canonical_root":str(canonical_root),
        "worktree":str(worktree),
        "common_policy":str(canonical_root/_COMMON),
        "results":rows,
        "retired_common_rule_present":retired,
        "stale":retired or any(x["status"]!="MATCH" for x in rows),
        "effect":"NONE_READ_ONLY",
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--worktree",type=Path,required=True)
    p.add_argument("--canonical-root",type=Path,default=Path(r"D:\BCT\source"))
    p.add_argument("--strict",action="store_true")
    a=p.parse_args()
    result=compare(a.canonical_root,a.worktree)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if a.strict and result["stale"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
