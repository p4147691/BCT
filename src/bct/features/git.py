from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from bct.core.models import (
    ConfirmedFailure,
    FeatureRequest,
    FeatureResult,
    Outcome,
    PreconditionError,
    UnknownEffectError,
    Work,
)

from .common import relative_git_path, resolve_in_work, sha256_file
from .git_authority import require_local_main
from bct.instruction_preflight import find_branch_worktree, inspect_worktree


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

    def __init__(self, policy_path: str | Path | None = None):
        self.policy_path = policy_path

    def _prepare_local_main_merge(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if set(arguments) != {"operation", "path", "branch", "expected_head", "expected_feature_head", "message"}:
            raise PreconditionError("LOCAL_MAIN_MERGE_ARGUMENTS_INVALID")
        root = _repo_root(resolve_in_work(work, arguments["path"], must_exist=True))
        authority = require_local_main(self.policy_path, root)
        branch = str(arguments["branch"])
        if (branch == "main" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", branch)
                or ".." in branch or branch.endswith(("/", ".", ".lock"))
                or _git(root, "check-ref-format", "--branch", branch).returncode != 0):
            raise PreconditionError("LOCAL_MAIN_FEATURE_BRANCH_INVALID")
        before = str(arguments["expected_head"]).lower()
        feature_head = str(arguments["expected_feature_head"]).lower()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", before):
            raise PreconditionError("LOCAL_MAIN_EXPECTED_HEAD_INVALID")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", feature_head):
            raise PreconditionError("LOCAL_MAIN_FEATURE_SHA_INVALID")
        message = str(arguments["message"])
        if not message or len(message) > 240 or any(ch in message for ch in "\n\r"):
            raise PreconditionError("LOCAL_MAIN_MESSAGE_INVALID")
        return FeatureRequest(
            self.capability, str(root),
            {"operation": "merge_local_main", "branch": branch,
             "expected_head": before, "expected_feature_head": feature_head, "message": message},
            ("git-index:" + str(root).casefold(), "git-worktree:" + str(root).casefold(),
             "github-base:" + authority.repository.casefold()),
            {"expected_head": before, "expected_feature_head": feature_head},
        )

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = arguments.get("operation", "commit")
        if operation == "merge_local_main":
            return self._prepare_local_main_merge(work=work, arguments=arguments)
        if operation != "commit":
            raise PreconditionError("GIT_OPERATION_INVALID")
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

    def _execute_local_main_merge(self, request: FeatureRequest) -> FeatureResult:
        root = Path(request.target)
        require_local_main(self.policy_path, root)
        before = request.preconditions["expected_head"]
        feature_head = request.preconditions["expected_feature_head"]
        branch = request.arguments["branch"]
        head = _git(root, "rev-parse", "HEAD")
        current_branch = _git(root, "branch", "--show-current")
        if head.returncode != 0 or head.stdout.strip().lower() != before:
            raise PreconditionError("LOCAL_MAIN_HEAD_MISMATCH")
        if current_branch.returncode != 0 or current_branch.stdout.strip() != "main":
            raise PreconditionError("LOCAL_MAIN_BRANCH_REQUIRED")
        if _dirty_paths(root):
            raise PreconditionError("LOCAL_MAIN_WORKTREE_DIRTY")
        feature = _git(root, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
        if feature.returncode != 0 or feature.stdout.strip().lower() != feature_head:
            raise PreconditionError("LOCAL_MAIN_FEATURE_HEAD_MISMATCH")
        already = _git(root, "merge-base", "--is-ancestor", feature_head, before)
        if already.returncode == 0:
            raise PreconditionError("LOCAL_MAIN_FEATURE_ALREADY_CONTAINED")
        if already.returncode != 1:
            raise PreconditionError("LOCAL_MAIN_ANCESTRY_UNVERIFIED")
        # Check the *attached* candidate that owns this exact branch before
        # any shared-main effect. Do not copy instructions into historical trees.
        # The canonical script remains the only content comparator.
        if (root / "AGENTS.md").is_file():
            if not (root / "scripts" / "check_instruction_authority.py").is_file():
                raise PreconditionError("LOCAL_MAIN_INSTRUCTION_CHECKER_UNAVAILABLE")
            candidate = find_branch_worktree(root, branch)
            if candidate is None:
                raise PreconditionError("LOCAL_MAIN_INSTRUCTION_WORKTREE_UNAVAILABLE")
            candidate_head = _git(candidate, "rev-parse", "HEAD")
            if (candidate_head.returncode != 0
                    or candidate_head.stdout.strip().lower() != feature_head):
                raise PreconditionError("LOCAL_MAIN_INSTRUCTION_CANDIDATE_SHA_MISMATCH")
            if _dirty_paths(candidate):
                raise PreconditionError("LOCAL_MAIN_INSTRUCTION_CANDIDATE_DIRTY")
            inspection = inspect_worktree(root, candidate)
            if inspection["status"] != "MATCH":
                raise PreconditionError(
                    "LOCAL_MAIN_INSTRUCTION_REVIEW_REQUIRED:" + inspection["status"]
                )
        # Preflight detects ordinary content conflicts before changing main/worktree.
        preview = _git(root, "merge-tree", "--write-tree", before, feature_head)
        if preview.returncode != 0:
            raise PreconditionError("LOCAL_MAIN_MERGE_CONFLICT_OR_UNAVAILABLE")
        tree_sha = preview.stdout.splitlines()[0].strip().lower() if preview.stdout else ""
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree_sha):
            raise PreconditionError("LOCAL_MAIN_PREVIEW_TREE_INVALID")
        # Re-fence both refs immediately before the effect.
        if (_git(root, "rev-parse", "HEAD").stdout.strip().lower() != before
                or _git(root, "rev-parse", f"refs/heads/{branch}").stdout.strip().lower() != feature_head
                or _dirty_paths(root)):
            raise PreconditionError("LOCAL_MAIN_REFS_CHANGED")
        try:
            merged = _git(root, "merge", "--no-ff", "--no-edit",
                          "-m", request.arguments["message"], feature_head)
        except (OSError, subprocess.TimeoutExpired):
            merged = None
        if merged is None or merged.returncode != 0:
            try:
                current = _git(root, "rev-parse", "HEAD")
                clean = not _dirty_paths(root)
                state = _git(root, "rev-parse", "--verify", "-q", "MERGE_HEAD")
            except Exception as exc:
                raise UnknownEffectError("LOCAL_MAIN_MERGE_POSTSTATE_UNAVAILABLE") from exc
            if (merged is not None and current.returncode == 0
                    and current.stdout.strip().lower() == before and clean and state.returncode != 0):
                raise ConfirmedFailure("LOCAL_MAIN_MERGE_NOT_APPLIED", release_claims=True)
            raise UnknownEffectError("LOCAL_MAIN_MERGE_EFFECT_UNKNOWN")
        after = _git(root, "rev-parse", "HEAD")
        parents = _git(root, "rev-list", "--parents", "-n", "1", "HEAD")
        actual_tree = _git(root, "rev-parse", "HEAD^{tree}")
        tokens = parents.stdout.strip().lower().split() if parents.returncode == 0 else []
        if (after.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", after.stdout.strip().lower())
                or tokens != [after.stdout.strip().lower(), before, feature_head]
                or actual_tree.returncode != 0 or actual_tree.stdout.strip().lower() != tree_sha
                or _dirty_paths(root)):
            raise UnknownEffectError("LOCAL_MAIN_MERGE_POSTSTATE_UNVERIFIED")
        return FeatureResult(Outcome.APPLIED, {
            "operation": "merge_local_main", "root": str(root),
            "head_before": before, "feature_head": feature_head,
            "head_after": after.stdout.strip().lower(), "tree_sha": tree_sha,
            "remote_ci_required": False,
        })

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments.get("operation") == "merge_local_main":
            return self._execute_local_main_merge(request)
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
            try:
                after_failure = _git(root, "rev-parse", "HEAD")
                dirty_after_failure = _dirty_paths(root)
            except Exception as exc:
                raise UnknownEffectError("GIT_COMMIT_FAILURE_STATE_UNAVAILABLE") from exc
            if (
                after_failure.returncode == 0
                and after_failure.stdout.strip().lower() == request.preconditions["expected_head"]
                and {item.casefold() for item in dirty_after_failure}
                == {item.casefold() for item in paths}
            ):
                raise ConfirmedFailure(
                    "GIT_COMMIT_NOT_APPLIED:" + (committed.stderr or committed.stdout)[-500:],
                    release_claims=True,
                )
            raise UnknownEffectError("GIT_COMMIT_FAILURE_STATE_UNEXPECTED")
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
