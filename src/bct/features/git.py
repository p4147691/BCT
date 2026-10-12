from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from bct.core.models import ConfirmedFailure, FeatureRequest, FeatureResult, Outcome, PreconditionError, Work

from .common import relative_git_path, resolve_in_work, sha256_file


def _git(root: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", shell=False, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _repo_root(path: Path) -> Path:
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise PreconditionError("NOT_A_GIT_REPOSITORY")
    root = Path(result.stdout.strip()).resolve()
    if root != path.resolve():
        raise PreconditionError("GIT_TARGET_MUST_BE_REPOSITORY_ROOT")
    return root


def _dirty_paths(root: Path) -> set[str]:
    result = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise PreconditionError("GIT_STATUS_FAILED")
    dirty: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        value = line[3:]
        if status[0] in "RC" or status[1] in "RC" or " -> " in value:
            raise PreconditionError("GIT_RENAME_COPY_NOT_SUPPORTED_IN_FIRST_SLICE")
        dirty.add(value.replace("\\", "/").strip('"'))
    return dirty


class GitCommitFeature:
    capability = "git_commit"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        root = _repo_root(resolve_in_work(work, str(arguments.get("path") or ""), must_exist=True))
        paths = arguments.get("paths")
        expected_head = str(arguments.get("expected_head") or "").lower()
        message = str(arguments.get("message") or "").strip()
        new_files = arguments.get("new_files", [])
        if not isinstance(paths, list) or not paths or len(paths) > 64:
            raise PreconditionError("GIT_PATHS_INVALID")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_head):
            raise PreconditionError("GIT_EXPECTED_HEAD_INVALID")
        if not message or len(message) > 240 or "\n" in message or "\r" in message:
            raise PreconditionError("GIT_MESSAGE_INVALID")
        normalized: list[str] = []
        for value in paths:
            if (not isinstance(value, str) or not value or value.startswith(("/", "-"))
                    or ":" in value or any(ord(character) < 32 for character in value)):
                raise PreconditionError("GIT_PATH_INVALID")
            candidate = resolve_in_work(work, str(root / value), must_exist=False)
            rel = relative_git_path(root, candidate)
            if rel in normalized:
                raise PreconditionError("GIT_PATH_DUPLICATE")
            normalized.append(rel)
        proofs: dict[str, str] = {}
        if not isinstance(new_files, list):
            raise PreconditionError("GIT_NEW_FILE_PROOFS_INVALID")
        for proof in new_files:
            if not isinstance(proof, dict) or set(proof) != {"path", "sha256"}:
                raise PreconditionError("GIT_NEW_FILE_PROOF_INVALID")
            rel = str(proof["path"]).replace("\\", "/")
            digest = str(proof["sha256"]).lower()
            if rel in proofs or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise PreconditionError("GIT_NEW_FILE_PROOF_INVALID")
            proofs[rel] = digest
        return FeatureRequest(
            self.capability, str(root), {"paths": normalized, "expected_head": expected_head,
                                        "message": message, "new_files": proofs},
            ("git-index:" + str(root).casefold(), *tuple("file:" + str(root / item).casefold() for item in normalized)),
            {"expected_head": expected_head},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        root = Path(request.target)
        paths: list[str] = request.arguments["paths"]
        proofs: dict[str, str] = dict(request.arguments["new_files"])
        head = _git(root, "rev-parse", "HEAD")
        if head.returncode != 0 or head.stdout.strip().lower() != request.preconditions["expected_head"]:
            raise PreconditionError("GIT_HEAD_MISMATCH")
        dirty = _dirty_paths(root)
        if {item.casefold() for item in dirty} != {item.casefold() for item in paths}:
            raise PreconditionError("GIT_DIRTY_SET_MISMATCH")
        new_paths: list[str] = []
        for rel in paths:
            tracked = _git(root, "ls-files", "--error-unmatch", "--", ":(literal)" + rel)
            path = root / rel
            if tracked.returncode == 0:
                if rel in proofs:
                    raise PreconditionError("TRACKED_PATH_HAS_NEW_FILE_PROOF:" + rel)
                continue
            expected = proofs.pop(rel, None)
            if expected is None:
                raise PreconditionError("NEW_FILE_PROOF_REQUIRED:" + rel)
            if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
                raise PreconditionError("NEW_FILE_PROOF_MISMATCH:" + rel)
            ignored = _git(root, "check-ignore", "--quiet", "--", rel)
            if ignored.returncode == 0:
                raise PreconditionError("NEW_FILE_IGNORED:" + rel)
            if ignored.returncode != 1:
                raise PreconditionError("GIT_IGNORE_CHECK_FAILED:" + rel)
            new_paths.append(rel)
        if proofs:
            raise PreconditionError("UNUSED_NEW_FILE_PROOF")
        pathspecs = [":(literal)" + item for item in paths]
        if new_paths:
            intent = _git(root, "add", "--intent-to-add", "--", *[":(literal)" + item for item in new_paths])
            if intent.returncode != 0:
                raise ConfirmedFailure("GIT_INTENT_TO_ADD_FAILED", release_claims=True)
        changed = _git(root, "diff", "--name-only", "HEAD", "--", *pathspecs)
        if changed.returncode != 0 or {line.casefold() for line in changed.stdout.splitlines() if line} != {item.casefold() for item in paths}:
            if new_paths:
                _git(root, "reset", "--mixed", "HEAD", "--", *[":(literal)" + item for item in new_paths])
            raise PreconditionError("GIT_PATHS_NOT_ALL_CHANGED")
        committed = _git(root, "commit", "--only", "-m", request.arguments["message"], "--", *pathspecs)
        if committed.returncode != 0:
            if new_paths:
                _git(root, "reset", "--mixed", "HEAD", "--", *[":(literal)" + item for item in new_paths])
            raise ConfirmedFailure("GIT_COMMIT_FAILED:" + (committed.stderr or committed.stdout)[-500:])
        after = _git(root, "rev-parse", "HEAD")
        if after.returncode != 0 or after.stdout.strip().lower() == request.preconditions["expected_head"]:
            raise ConfirmedFailure("GIT_COMMIT_POST_HEAD_INVALID")
        new_head = after.stdout.strip().lower()
        scope = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", new_head)
        committed_paths = [line.replace("\\", "/") for line in scope.stdout.splitlines() if line]
        if scope.returncode != 0 or {item.casefold() for item in committed_paths} != {item.casefold() for item in paths}:
            raise ConfirmedFailure("GIT_COMMIT_SCOPE_MISMATCH")
        return FeatureResult(Outcome.APPLIED, {
            "root": str(root), "head_before": request.preconditions["expected_head"],
            "head_after": new_head, "files": committed_paths,
        })
