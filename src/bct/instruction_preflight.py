"""Bounded, read-only checks against the current canonical BCT instruction file.

This adapter intentionally calls scripts/check_instruction_authority.py, rather
than implementing a second independent instruction comparison.  An outdated
Worktree is observed, never rewritten.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def inspect_worktree(canonical_root: str | Path, worktree: str | Path) -> dict[str, Any]:
    """Return MATCH / STALE_INSTRUCTIONS / UNKNOWN, without modifying files."""
    canonical = Path(canonical_root).resolve()
    candidate = Path(worktree).resolve()
    base = {"canonical_root": str(canonical), "worktree": str(candidate)}
    checker = canonical / "scripts" / "check_instruction_authority.py"
    if not checker.is_file() or not candidate.is_dir():
        return {**base, "status": "UNKNOWN", "reason": "CHECKER_OR_WORKTREE_UNAVAILABLE"}
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(checker), "--canonical-root", str(canonical),
             "--worktree", str(candidate), "--strict"],
            cwd=str(canonical), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, shell=False,
        )
        if completed.returncode not in (0, 2):
            return {**base, "status": "UNKNOWN",
                    "reason": "INSTRUCTION_CHECK_EXECUTION_FAILED"}
        data = json.loads(completed.stdout)
        if (not isinstance(data, dict) or data.get("effect") != "NONE_READ_ONLY"
                or not isinstance(data.get("results"), list)
                or data.get("stale") is not (completed.returncode == 2)):
            return {**base, "status": "UNKNOWN",
                    "reason": "INSTRUCTION_CHECK_RESULT_INVALID"}
        return {**base,
                "status": "STALE_INSTRUCTIONS" if data["stale"] else "MATCH",
                "results": data["results"],
                "retired_common_rule_present": bool(data.get("retired_common_rule_present"))}
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {**base, "status": "UNKNOWN", "reason": "INSTRUCTION_CHECK_UNAVAILABLE"}


def inspect_work_roots(canonical_root: str | Path, roots: list[str] | tuple[str, ...],
                       *, max_roots: int = 12) -> list[dict[str, Any]]:
    """Advisory on actual linked worktrees only; Work creation stays non-blocking."""
    canonical = Path(canonical_root).resolve()
    result = []
    if len(roots) > max_roots:
        return [{"status": "UNKNOWN", "reason": "WORK_ROOTS_LIMIT_EXCEEDED"}]
    for raw in roots:
        path = Path(raw).resolve()
        if (path == canonical or not path.is_relative_to(canonical.parent)
                or not (path / ".git").is_file()):
            continue
        result.append(inspect_worktree(canonical, path))
    return result


def find_branch_worktree(repository_root: str | Path, branch: str) -> Path | None:
    """Resolve an exact local branch to its attached worktree, if any."""
    root = Path(repository_root).resolve()
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    target = "refs/heads/" + branch
    path: str | None = None
    for line in [*completed.stdout.splitlines(), ""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == "branch " + target and path:
            return Path(path).resolve()
        elif not line:
            path = None
    return None


def inspect_feature_branch(canonical_root: str | Path, branch: str) -> dict[str, Any]:
    """Shared integration-request / guarded-merge preflight for exact branch."""
    candidate = find_branch_worktree(canonical_root, branch)
    if candidate is None:
        return {"status": "UNKNOWN", "reason": "FEATURE_WORKTREE_NOT_ATTACHED",
                "feature_branch": branch}
    result = inspect_worktree(canonical_root, candidate)
    result["feature_branch"] = branch
    return result
