from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
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
from bct.integrations.github import GitHubClient

from .common import resolve_in_work


_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")


def _git(root: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=timeout,
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


def _validate_repository(value: Any) -> str:
    repository = str(value or "")
    if not _REPOSITORY.fullmatch(repository) or repository.startswith((".", "-")):
        raise PreconditionError("GITHUB_REPOSITORY_INVALID")
    return repository


def _validate_branch(value: Any) -> str:
    branch = str(value or "")
    if (
        not branch
        or len(branch) > 200
        or branch.startswith(("-", ".", "/"))
        or branch.endswith((".", "/", ".lock"))
        or ".." in branch
        or "@{" in branch
        or any(character in branch for character in " ~^:?*[\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in branch)
    ):
        raise PreconditionError("GIT_BRANCH_INVALID")
    return branch


def _validate_sha(value: Any, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    sha = str(value or "").lower()
    if not _SHA.fullmatch(sha):
        raise PreconditionError("GIT_SHA_INVALID")
    return sha


def _remote_matches(repository: str, url: str) -> bool:
    normalized = url.strip().removesuffix("/").removesuffix(".git").lower()
    expected = repository.lower()
    return normalized in {
        f"https://github.com/{expected}",
        f"ssh://git@github.com/{expected}",
        f"git@github.com:{expected}",
    }


def _remote_sha(root: Path, remote: str, branch: str) -> str | None:
    result = _git(root, "ls-remote", "--refs", remote, f"refs/heads/{branch}")
    if result.returncode != 0:
        raise RuntimeError("GIT_REMOTE_READ_FAILED:" + (result.stderr or result.stdout).strip()[-500:])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) != 1:
        raise RuntimeError("GIT_REMOTE_REF_AMBIGUOUS")
    sha = lines[0].split()[0].lower()
    if not _SHA.fullmatch(sha):
        raise RuntimeError("GIT_REMOTE_SHA_INVALID")
    return sha


def _ensure_clean(root: Path) -> None:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise PreconditionError("GIT_STATUS_FAILED")
    if status.stdout.strip():
        raise PreconditionError("GIT_WORKTREE_NOT_CLEAN")


def _pr_evidence(pull: dict[str, Any], *, already_present: bool = False) -> dict[str, Any]:
    return {
        "number": int(pull["number"]),
        "url": str(pull.get("html_url") or ""),
        "state": str(pull.get("state") or ""),
        "base": str(pull["base"]["ref"]),
        "head": str(pull["head"]["ref"]),
        "head_sha": str(pull["head"]["sha"]).lower(),
        "already_present": already_present,
    }


def _pull_matches(
    pull: dict[str, Any], *, marker: str, head: str, base: str, head_sha: str
) -> bool:
    return (
        marker in str(pull.get("body") or "")
        and str(pull.get("head", {}).get("ref") or "") == head
        and str(pull.get("head", {}).get("sha") or "").lower() == head_sha
        and str(pull.get("base", {}).get("ref") or "") == base
    )


class GitHubPushFeature:
    capability = "github_push"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        root = _repo_root(resolve_in_work(work, str(arguments.get("path") or ""), must_exist=True))
        repository = _validate_repository(arguments.get("repository"))
        branch = _validate_branch(arguments.get("branch"))
        expected_head = _validate_sha(arguments.get("expected_head"))
        expected_remote_sha = _validate_sha(arguments.get("expected_remote_sha"), optional=True)
        remote = str(arguments.get("remote") or "origin")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote) or remote.startswith("-"):
            raise PreconditionError("GIT_REMOTE_INVALID")
        return FeatureRequest(
            self.capability,
            f"{repository}:{branch}",
            {
                "root": str(root),
                "repository": repository,
                "branch": branch,
                "remote": remote,
                "expected_head": expected_head,
                "expected_remote_sha": expected_remote_sha,
            },
            (f"github-ref:{repository.casefold()}:{branch.casefold()}",),
            {"expected_head": expected_head, "expected_remote_sha": expected_remote_sha},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        root = Path(values["root"])
        branch = values["branch"]
        remote = values["remote"]
        expected_head = values["expected_head"]
        current = _git(root, "rev-parse", "HEAD")
        current_branch = _git(root, "branch", "--show-current")
        remote_url = _git(root, "remote", "get-url", remote)
        if current.returncode != 0 or current.stdout.strip().lower() != expected_head:
            raise PreconditionError("GIT_HEAD_MISMATCH")
        if current_branch.returncode != 0 or current_branch.stdout.strip() != branch:
            raise PreconditionError("GIT_BRANCH_MISMATCH")
        if remote_url.returncode != 0 or not _remote_matches(values["repository"], remote_url.stdout):
            raise PreconditionError("GITHUB_REMOTE_MISMATCH")
        _ensure_clean(root)
        before = _remote_sha(root, remote, branch)
        if before == expected_head:
            return FeatureResult(Outcome.APPLIED, {
                "repository": values["repository"], "branch": branch,
                "local_sha": expected_head, "remote_sha": expected_head,
                "already_current": True,
            })
        if before != values["expected_remote_sha"]:
            raise PreconditionError("GIT_REMOTE_SHA_MISMATCH")
        if before is not None:
            fetch = _git(root, "fetch", "--no-tags", remote, f"refs/heads/{branch}")
            if fetch.returncode != 0:
                raise PreconditionError("GIT_REMOTE_FETCH_FAILED")
            fetched = _git(root, "rev-parse", "FETCH_HEAD")
            ancestor = _git(root, "merge-base", "--is-ancestor", before, expected_head)
            if fetched.returncode != 0 or fetched.stdout.strip().lower() != before or ancestor.returncode != 0:
                raise PreconditionError("GIT_PUSH_NOT_FAST_FORWARD")
        try:
            pushed = _git(root, "push", "--porcelain", remote, f"{expected_head}:refs/heads/{branch}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            pushed = None
            failure = type(exc).__name__
        else:
            failure = (pushed.stderr or pushed.stdout).strip()[-500:] if pushed.returncode else ""
        try:
            after = _remote_sha(root, remote, branch)
        except Exception as exc:
            raise UnknownEffectError("GIT_PUSH_POST_STATE_UNAVAILABLE") from exc
        if after == expected_head:
            return FeatureResult(Outcome.APPLIED, {
                "repository": values["repository"], "branch": branch,
                "local_sha": expected_head, "remote_sha": after,
                "already_current": False,
            })
        if after == before:
            raise ConfirmedFailure("GIT_PUSH_NOT_APPLIED:" + failure, release_claims=True)
        raise UnknownEffectError("GIT_PUSH_REMOTE_STATE_UNEXPECTED")


class GitHubPullRequestFeature:
    capability = "github_pr_create"

    def __init__(self, client: GitHubClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        repository = _validate_repository(arguments.get("repository"))
        head = _validate_branch(arguments.get("head"))
        base = _validate_branch(arguments.get("base") or "main")
        head_sha = _validate_sha(arguments.get("head_sha"))
        title = str(arguments.get("title") or "").strip()
        body = str(arguments.get("body") or "")
        if not title or len(title) > 256 or "\n" in title or "\r" in title:
            raise PreconditionError("GITHUB_PR_TITLE_INVALID")
        if len(body) > 60000:
            raise PreconditionError("GITHUB_PR_BODY_INVALID")
        marker_digest = hashlib.sha256(json.dumps({
            "work_id": work.work_id,
            "repository": repository,
            "head": head,
            "base": base,
            "head_sha": head_sha,
            "title": title,
            "body": body,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        marker = f"<!-- bct-request:{marker_digest} -->"
        return FeatureRequest(
            self.capability,
            f"{repository}:{head}->{base}",
            {
                "repository": repository, "head": head, "base": base,
                "head_sha": head_sha, "title": title,
                "body": body.rstrip() + "\n\n" + marker,
                "marker": marker,
            },
            (f"github-pr-head:{repository.casefold()}:{head.casefold()}",),
            {"head_sha": head_sha},
        )

    def _find(self, request: FeatureRequest) -> dict[str, Any] | None:
        values = request.arguments
        pulls = self.client.list_pull_requests(
            values["repository"], head=values["head"], base=values["base"]
        )
        exact = [pull for pull in pulls if _pull_matches(
            pull, marker=values["marker"], head=values["head"],
            base=values["base"], head_sha=values["head_sha"],
        )]
        if len(exact) > 1:
            raise UnknownEffectError("GITHUB_PR_DUPLICATE_EXACT_MATCHES")
        if exact:
            return exact[0]
        if any(str(pull.get("state")) == "open" for pull in pulls):
            raise PreconditionError("GITHUB_PR_HEAD_ALREADY_IN_USE")
        return None

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        remote_sha = self.client.get_ref_sha(values["repository"], values["head"])
        if remote_sha != values["head_sha"]:
            raise PreconditionError("GITHUB_HEAD_SHA_MISMATCH")
        existing = self._find(request)
        if existing is not None:
            return FeatureResult(Outcome.APPLIED, _pr_evidence(existing, already_present=True))
        try:
            pull = self.client.create_pull_request(
                values["repository"], head=values["head"], base=values["base"],
                title=values["title"], body=values["body"],
            )
        except Exception as exc:
            try:
                recovered = self._find(request)
            except PreconditionError:
                recovered = None
            except Exception as inspect_exc:
                raise UnknownEffectError("GITHUB_PR_POST_STATE_UNAVAILABLE") from inspect_exc
            if recovered is not None:
                return FeatureResult(Outcome.APPLIED, _pr_evidence(recovered, already_present=False))
            raise UnknownEffectError("GITHUB_PR_CREATE_UNVERIFIED") from exc
        if not _pull_matches(
            pull, marker=values["marker"], head=values["head"],
            base=values["base"], head_sha=values["head_sha"],
        ):
            raise UnknownEffectError("GITHUB_PR_CREATE_RESPONSE_MISMATCH")
        return FeatureResult(Outcome.APPLIED, _pr_evidence(pull, already_present=False))


def _check_evidence(runs: list[dict[str, Any]], required: list[str]) -> tuple[bool, list[dict[str, str]]]:
    by_name = {}
    for run in runs:
        name = str(run.get("name") or "")
        if name not in by_name or int(run.get("id", 0)) > int(by_name[name].get("id", 0)):
            by_name[name] = run
    evidence: list[dict[str, str]] = []
    ready = True
    for name in required:
        run = by_name.get(name)
        status = str(run.get("status") or "MISSING") if run else "MISSING"
        conclusion = str(run.get("conclusion") or "") if run else ""
        if status != "completed" or conclusion != "success":
            ready = False
        evidence.append({"name": name, "status": status, "conclusion": conclusion})
    return ready, evidence


class GitHubPullRequestStatusFeature:
    capability = "github_pr_status"

    def __init__(self, client: GitHubClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        repository = _validate_repository(arguments.get("repository"))
        try:
            number = int(arguments.get("number"))
        except (TypeError, ValueError) as exc:
            raise PreconditionError("GITHUB_PR_NUMBER_INVALID") from exc
        if number < 1:
            raise PreconditionError("GITHUB_PR_NUMBER_INVALID")
        expected_head = _validate_sha(arguments.get("expected_head"))
        required = arguments.get("required_checks", [])
        if not isinstance(required, list) or not required or len(required) > 32:
            raise PreconditionError("GITHUB_REQUIRED_CHECKS_INVALID")
        if not all(isinstance(item, str) and item and len(item) <= 200 for item in required):
            raise PreconditionError("GITHUB_REQUIRED_CHECKS_INVALID")
        if len(set(required)) != len(required):
            raise PreconditionError("GITHUB_REQUIRED_CHECKS_DUPLICATE")
        wait = float(arguments.get("wait_seconds", 0))
        if not math.isfinite(wait) or not 0 <= wait <= 300:
            raise PreconditionError("GITHUB_WAIT_INVALID")
        return FeatureRequest(
            self.capability, f"{repository}#{number}",
            {"repository": repository, "number": number,
             "expected_head": expected_head, "required_checks": required,
             **({"wait_seconds": wait} if wait else {})},
            (f"github-pr:{repository.casefold()}:{number}",),
            {"expected_head": expected_head},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        started = time.monotonic()
        deadline = started + values.get("wait_seconds", 0)
        polls = 0
        while True:
            result = self._snapshot(request)
            polls += 1
            evidence = result.evidence
            failed = any(check["status"] == "completed" and check["conclusion"] != "success"
                         for check in evidence["checks"])
            done = evidence["checks_ready"] or failed or evidence["state"] != "open"
            if done or time.monotonic() >= deadline:
                return FeatureResult(Outcome.APPLIED, {**evidence, "poll_count": polls,
                    "wait_status": "READY" if evidence["checks_ready"] else (
                        "FAILED" if failed else "CLOSED" if evidence["state"] != "open" else "PENDING"),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3)})
            time.sleep(min(5.0, max(0, deadline - time.monotonic())))

    def _snapshot(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        pull = self.client.get_pull_request(values["repository"], values["number"])
        head_sha = str(pull.get("head", {}).get("sha") or "").lower()
        if head_sha != values["expected_head"]:
            raise PreconditionError("GITHUB_PR_HEAD_MISMATCH")
        ready, checks = _check_evidence(
            self.client.get_check_runs(values["repository"], head_sha),
            values["required_checks"],
        )
        after = self.client.get_pull_request(values["repository"], values["number"])
        if str(after.get("head", {}).get("sha") or "").lower() != head_sha:
            raise PreconditionError("GITHUB_PR_HEAD_MISMATCH")
        return FeatureResult(Outcome.APPLIED, {
            **_pr_evidence(after), "checks": checks, "checks_ready": ready,
            "merged": bool(after.get("merged")),
        })


class GitHubPullRequestMergeFeature:
    capability = "github_pr_merge"

    def __init__(self, client: GitHubClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        status = GitHubPullRequestStatusFeature(self.client).prepare(work=work, arguments=arguments)
        method = str(arguments.get("method") or "squash")
        if method not in {"merge", "squash", "rebase"}:
            raise PreconditionError("GITHUB_MERGE_METHOD_INVALID")
        merged_arguments = dict(status.arguments)
        merged_arguments["method"] = method
        return FeatureRequest(
            self.capability, status.target, merged_arguments,
            (status.resources[0], f"github-base:{merged_arguments['repository'].casefold()}"),
            status.preconditions,
        )

    def _inspect(self, request: FeatureRequest) -> tuple[dict[str, Any], bool, list[dict[str, str]]]:
        values = request.arguments
        pull = self.client.get_pull_request(values["repository"], values["number"])
        head_sha = str(pull.get("head", {}).get("sha") or "").lower()
        if head_sha != values["expected_head"]:
            raise PreconditionError("GITHUB_PR_HEAD_MISMATCH")
        ready, checks = _check_evidence(
            self.client.get_check_runs(values["repository"], head_sha),
            values["required_checks"],
        )
        return pull, ready, checks

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        pull, ready, checks = self._inspect(request)
        if bool(pull.get("merged")):
            return FeatureResult(Outcome.APPLIED, {
                **_pr_evidence(pull, already_present=True), "checks": checks,
                "merge_commit_sha": str(pull.get("merge_commit_sha") or "").lower(),
                "already_merged": True,
            })
        if str(pull.get("state") or "") != "open":
            raise PreconditionError("GITHUB_PR_NOT_OPEN")
        if not ready:
            raise PreconditionError("GITHUB_REQUIRED_CHECK_NOT_SUCCESS")
        try:
            result = self.client.merge_pull_request(
                values["repository"], values["number"],
                sha=values["expected_head"], method=values["method"],
            )
        except Exception as exc:
            try:
                after, _, after_checks = self._inspect(request)
            except Exception as inspect_exc:
                raise UnknownEffectError("GITHUB_MERGE_POST_STATE_UNAVAILABLE") from inspect_exc
            if bool(after.get("merged")):
                return FeatureResult(Outcome.APPLIED, {
                    **_pr_evidence(after), "checks": after_checks,
                    "merge_commit_sha": str(after.get("merge_commit_sha") or "").lower(),
                    "already_merged": False,
                })
            if str(after.get("state") or "") == "open":
                raise ConfirmedFailure("GITHUB_MERGE_NOT_APPLIED", release_claims=True) from exc
            raise UnknownEffectError("GITHUB_MERGE_STATE_UNEXPECTED") from exc
        if not bool(result.get("merged")):
            raise ConfirmedFailure(
                "GITHUB_MERGE_NOT_APPLIED:" + str(result.get("message") or ""),
                release_claims=True,
            )
        merge_sha = str(result.get("sha") or "").lower()
        if not _SHA.fullmatch(merge_sha):
            raise UnknownEffectError("GITHUB_MERGE_SHA_INVALID")
        try:
            after, _, after_checks = self._inspect(request)
        except Exception as exc:
            raise UnknownEffectError("GITHUB_MERGE_POST_STATE_UNAVAILABLE") from exc
        if not bool(after.get("merged")):
            raise UnknownEffectError("GITHUB_MERGE_POST_STATE_UNVERIFIED")
        recorded_merge_sha = str(after.get("merge_commit_sha") or "").lower()
        if recorded_merge_sha != merge_sha:
            raise UnknownEffectError("GITHUB_MERGE_POST_SHA_MISMATCH")
        return FeatureResult(Outcome.APPLIED, {
            **_pr_evidence(after), "checks": after_checks,
            "merge_commit_sha": recorded_merge_sha, "already_merged": False,
        })


class GitHubSyncMainFeature:
    capability = "github_sync_main"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        root = _repo_root(resolve_in_work(work, str(arguments.get("path") or ""), must_exist=True))
        repository = _validate_repository(arguments.get("repository"))
        expected_local_head = _validate_sha(arguments.get("expected_local_head"))
        verified_main_sha = _validate_sha(arguments.get("verified_main_sha"))
        remote = str(arguments.get("remote") or "origin")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote) or remote.startswith("-"):
            raise PreconditionError("GIT_REMOTE_INVALID")
        return FeatureRequest(
            self.capability, str(root),
            {"root": str(root), "repository": repository, "remote": remote,
             "expected_local_head": expected_local_head, "verified_main_sha": verified_main_sha},
            ("git-worktree:" + str(root).casefold(),),
            {"expected_local_head": expected_local_head, "verified_main_sha": verified_main_sha},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        root = Path(values["root"])
        remote = values["remote"]
        current = _git(root, "rev-parse", "HEAD")
        branch = _git(root, "branch", "--show-current")
        remote_url = _git(root, "remote", "get-url", remote)
        if current.returncode != 0 or current.stdout.strip().lower() != values["expected_local_head"]:
            raise PreconditionError("GIT_HEAD_MISMATCH")
        if branch.returncode != 0 or branch.stdout.strip() != "main":
            raise PreconditionError("GIT_MAIN_BRANCH_REQUIRED")
        if remote_url.returncode != 0 or not _remote_matches(values["repository"], remote_url.stdout):
            raise PreconditionError("GITHUB_REMOTE_MISMATCH")
        _ensure_clean(root)
        remote_sha = _remote_sha(root, remote, "main")
        if remote_sha != values["verified_main_sha"]:
            raise PreconditionError("GITHUB_VERIFIED_MAIN_MISMATCH")
        if values["expected_local_head"] == values["verified_main_sha"]:
            return FeatureResult(Outcome.APPLIED, {
                "repository": values["repository"], "head_before": values["expected_local_head"],
                "head_after": values["verified_main_sha"], "already_current": True,
            })
        fetched = _git(root, "fetch", "--no-tags", remote, "refs/heads/main")
        fetch_head = _git(root, "rev-parse", "FETCH_HEAD")
        if fetched.returncode != 0 or fetch_head.returncode != 0:
            raise ConfirmedFailure("GIT_MAIN_FETCH_FAILED", release_claims=True)
        if fetch_head.stdout.strip().lower() != values["verified_main_sha"]:
            raise PreconditionError("GITHUB_FETCHED_MAIN_MISMATCH")
        merged = _git(root, "merge", "--ff-only", values["verified_main_sha"])
        after = _git(root, "rev-parse", "HEAD")
        after_sha = after.stdout.strip().lower() if after.returncode == 0 else ""
        if after_sha == values["verified_main_sha"]:
            return FeatureResult(Outcome.APPLIED, {
                "repository": values["repository"], "head_before": values["expected_local_head"],
                "head_after": after_sha, "already_current": False,
            })
        if after_sha == values["expected_local_head"]:
            raise ConfirmedFailure(
                "GIT_MAIN_FAST_FORWARD_FAILED:" + (merged.stderr or merged.stdout).strip()[-500:],
                release_claims=True,
            )
        raise UnknownEffectError("GIT_MAIN_SYNC_STATE_UNEXPECTED")
