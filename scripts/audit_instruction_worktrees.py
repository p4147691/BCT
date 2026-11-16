from __future__ import annotations

"""Read-only instruction assessment for registered BCT worktrees.

This deliberately reports unproven policy exceptions as HOLD and never
interprets a matching Work name or ACTIVE Work as an ownership receipt.
"""
import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

FILES = ("AGENTS.md", ".cursor/rules/bct-delivery-flow.mdc",
         ".cursor/rules/bct-persistent-supervision.mdc",
         "modules/monitor/extension/AGENTS.md")
OLD_MAIN = "a synchronized working copy, not a second authority"
OLD_LANE = "Reversible local-display lane"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def classify(current: dict[str, str | None], canonical: dict[str, str | None],
             agents: str, cursor: str) -> tuple[str, list[str]]:
    evidence = []
    if OLD_MAIN in agents:
        evidence.append("LOCAL_MAIN_AUTHORITY_CONTRADICTION")
    if OLD_LANE in cursor:
        evidence.append("MONITOR_FAST_LANE_EXCEPTION_UNVERIFIED")
    if current[FILES[2]] is not None:
        evidence.append("RETIRED_CURSOR_RULE_PRESENT")
    if any(current[k] is None for k in (FILES[0], FILES[1], FILES[3])):
        return "MISSING", evidence
    if all(current[k] == canonical[k] for k in FILES):
        return "MATCH", evidence
    if "LOCAL_MAIN_AUTHORITY_CONTRADICTION" in evidence:
        return "STALE_CONFLICT", evidence
    if "MONITOR_FAST_LANE_EXCEPTION_UNVERIFIED" in evidence:
        return "EXCEPTION_UNVERIFIED_HOLD", evidence
    return "COMPATIBILITY_UNVERIFIED", evidence


def assess(repo: Path) -> dict:
    repo = repo.resolve()
    result = subprocess.run(["git", "-C", str(repo), "worktree", "list",
                             "--porcelain"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=True)
    canonical = {k: digest(repo / k) for k in FILES}
    entries = []
    for block in result.stdout.replace("\r\n", "\n").strip().split("\n\n"):
        meta = {}
        for line in block.splitlines():
            if line.startswith("worktree "):
                meta["path"] = line[9:]
            elif line.startswith("HEAD "):
                meta["head"] = line[5:]
            elif line.startswith("branch "):
                meta["branch"] = line[7:]
            elif line == "detached":
                meta["branch"] = "DETACHED"
        if not meta.get("path"):
            continue
        path = Path(meta["path"])
        hashes = {k: digest(path / k) for k in FILES}
        agents = (path / FILES[0]).read_text(encoding="utf-8", errors="replace") if hashes[FILES[0]] else ""
        cursor = (path / FILES[1]).read_text(encoding="utf-8", errors="replace") if hashes[FILES[1]] else ""
        status, evidence = classify(hashes, canonical, agents, cursor)
        entries.append({**meta, "sha256": hashes, "instruction": status,
                        "evidence": evidence, "protection": "HOLD",
                        "ownership": "UNVERIFIED_BY_INSTRUCTION_AUDIT"})
    return {"schema": 1, "mode": "READ_ONLY",
            "total": len(entries),
            "counts": dict(Counter(x["instruction"] for x in entries)),
            "entries": entries, "cleanup_authorized": False,
            "merge_authorized": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(assess(args.repo), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()