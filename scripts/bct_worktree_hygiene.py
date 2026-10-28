"""Read-only inventory of local-main BCT Git worktrees.

This tool never removes worktrees, closes Work records, releases claims, or
modifies source/runtime. An eligible result is a review candidate, not an
automatic deletion authorization.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PROTECTED_NAME_PARTS = (
    "backup", "recovery", "recover", "handoff", "integration", "live",
    "source-base", "main", "node-sync", "monitor-minimized",
)


def _git(cwd: Path, *args: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, encoding="utf-8",
        errors="replace", shell=False, timeout=25, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    return completed.returncode, completed.stdout, completed.stderr


def _norm(path: str | Path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def _inside(value: str | Path, root: str | Path) -> bool:
    child, parent = _norm(value), _norm(root)
    return child == parent or child.startswith(parent + "\\")


def _git_required(cwd: Path, *args: str) -> str:
    code, output, error = _git(cwd, *args)
    if code:
        raise ValueError("GIT_AUDIT_FAILED:" + " ".join(args) + ":" + error[:180])
    return output.strip()


def _worktrees(porcelain: str) -> list[dict[str, Any]]:
    rows = []
    for block in porcelain.strip().split("\n\n"):
        record: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("worktree "):
                record["path"] = line[9:]
            elif line.startswith("HEAD "):
                record["head"] = line[5:]
            elif line.startswith("branch "):
                record["branch"] = line[7:].removeprefix("refs/heads/")
            elif line == "detached":
                record["detached"] = True
            elif line == "locked" or line.startswith("locked "):
                record["locked"] = True
            elif line == "prunable" or line.startswith("prunable "):
                record["prunable"] = True
        if record.get("path"):
            rows.append(record)
    return rows


def _ledger(path: Path | None) -> tuple[dict[str, Any], bool]:
    empty = {
        "work_authority_states": {},
        "operation_states": {},
        "work_roots": [],
        "unresolved_targets": [],
    }
    if path is None:
        return empty, False
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=4)
    except (OSError, sqlite3.Error):
        return empty, False
    try:
        works = db.execute("SELECT state, roots_json FROM works").fetchall()
        ops = db.execute(
            "SELECT state, outcome, target FROM operations"
        ).fetchall()
        work_roots = []
        for _, encoded in works:
            try:
                decoded = json.loads(encoded)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, list):
                work_roots.extend(_norm(root) for root in decoded if isinstance(root, str))
        unresolved = [
            _norm(target)
            for state, outcome, target in ops
            if state != "FINISHED" or outcome == "UNKNOWN"
        ]
        return {
            "work_authority_states": dict(Counter(state for state, _ in works)),
            "operation_states": {
                f"{state}/{outcome or 'NONE'}": count
                for (state, outcome), count in Counter(
                    (state, outcome) for state, outcome, _ in ops
                ).items()
            },
            "work_roots": work_roots,
            "unresolved_targets": unresolved,
        }, True
    except sqlite3.Error:
        return empty, False
    finally:
        db.close()


def _process_paths() -> tuple[list[str], bool]:
    try:
        import psutil
    except ImportError:
        return [], False
    paths = []
    try:
        for process in psutil.process_iter(["pid"]):
            try:
                cwd = process.cwd()
                if cwd:
                    paths.append(_norm(cwd))
                for argument in process.cmdline():
                    if re.match(r"^[A-Za-z]:[\\/]", argument):
                        paths.append(_norm(argument))
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
                continue
    except (psutil.Error, OSError):
        return paths, False
    return paths, True


def audit(
    repo: Path,
    worktrees_root: Path,
    database: Path | None = None,
    *,
    process_paths: list[str] | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    top = Path(_git_required(repo, "rev-parse", "--show-toplevel")).resolve()
    if top != repo:
        raise ValueError("AUDIT_REPO_MUST_BE_GIT_ROOT")
    if _git_required(repo, "branch", "--show-current") != "main":
        raise ValueError("AUDIT_REQUIRES_LOCAL_MAIN")
    head = _git_required(repo, "rev-parse", "HEAD")
    main_dirty = bool(_git_required(repo, "status", "--porcelain=v1", "-uall"))
    all_worktrees = _worktrees(_git_required(repo, "worktree", "list", "--porcelain"))
    merged = set(_git_required(repo, "branch", "--merged", "main",
                               "--format=%(refname:short)").splitlines())
    ledger, ledger_ready = _ledger(database)
    if process_paths is None:
        process_paths, process_ready = _process_paths()
    else:
        process_paths = [_norm(value) for value in process_paths]
        process_ready = True
    entries = []
    for worktree in all_worktrees:
        path = Path(worktree["path"])
        is_main = path.resolve() == repo
        merged_main = worktree.get("branch") in merged
        status = "UNAVAILABLE"
        ignored: int | None = None
        problems = []
        if not path.is_dir() or path.is_symlink():
            problems.append("NOT_REGULAR_DIRECTORY")
        elif worktree.get("locked") or worktree.get("prunable"):
            problems.append("LOCKED_OR_PRUNABLE")
        else:
            rc, output, _ = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
            if rc == 0:
                status = "DIRTY" if output.strip() else "CLEAN"
                if status == "CLEAN":
                    rc, output, _ = _git(path, "ls-files", "--others", "--ignored",
                                          "--exclude-standard", "-z")
                    if rc == 0:
                        ignored = len([item for item in output.split("\0") if item])
                    else:
                        problems.append("IGNORED_FILES_UNAVAILABLE")
            else:
                problems.append("GIT_STATUS_UNAVAILABLE")
        work_refs = sum(_inside(root, path) for root in ledger["work_roots"])
        unresolved = sum(_inside(target, path) for target in ledger["unresolved_targets"])
        processes = sum(_inside(value, path) for value in process_paths)
        protected = any(part in path.name.casefold() for part in PROTECTED_NAME_PARTS)
        if is_main:
            problems.append("AUTHORITATIVE_MAIN")
        if not merged_main:
            problems.append("UNMERGED_OR_DETACHED")
        if not _inside(path, worktrees_root):
            problems.append("OUTSIDE_MANAGED_WORKTREES_ROOT")
        if protected:
            problems.append("PROTECTED_NAME")
        if status != "CLEAN":
            problems.append("STATUS_NOT_CLEAN")
        if ignored is None or ignored:
            problems.append("IGNORED_FILES_OR_UNKNOWN")
        if work_refs:
            problems.append("BCT_WORK_REFERENCE")
        if unresolved:
            problems.append("NONTERMINAL_OR_UNKNOWN_OPERATION_REFERENCE")
        if processes:
            problems.append("ACTIVE_PROCESS_REFERENCE")
        if not ledger_ready:
            problems.append("WORK_LEDGER_UNAVAILABLE")
        if not process_ready:
            problems.append("PROCESS_INVENTORY_UNAVAILABLE")
        if main_dirty:
            problems.append("MAIN_DIRTY")
        entries.append({
            **worktree,
            "status": status,
            "merged_main": merged_main,
            "ignored_count": ignored,
            "work_ref_count": work_refs,
            "unresolved_operation_count": unresolved,
            "process_ref_count": processes,
            "review_candidate": not problems,
            "hold_reasons": problems,
        })
    return {
        "schema": 1,
        "mode": "READ_ONLY",
        "main": str(repo),
        "main_sha": head,
        "main_clean": not main_dirty,
        "worktree_count": len(entries),
        "states": dict(Counter(row["status"] for row in entries)),
        "review_candidate_count": sum(item["review_candidate"] for item in entries),
        "work_authority_states": ledger["work_authority_states"],
        "operation_states": ledger["operation_states"],
        "work_authority_is_not_execution_progress": True,
        "candidates_are_not_delete_authorization": True,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only BCT Worktree safety audit")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--worktrees-root", type=Path, required=True)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--include-items", action="store_true")
    args = parser.parse_args()
    try:
        result = audit(args.repo, args.worktrees_root, args.state_db)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"AUDIT_BLOCKED:{exc}\n")
    if not args.include_items:
        result.pop("entries")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
