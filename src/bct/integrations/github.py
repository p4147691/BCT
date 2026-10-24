from __future__ import annotations

import json
import subprocess
import re
from typing import Any, Protocol


class GitHubClient(Protocol):
    def get_ref_sha(self, repository: str, branch: str) -> str: ...

    def list_pull_requests(self, repository: str, *, head: str, base: str) -> list[dict[str, Any]]: ...

    def create_pull_request(
        self, repository: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]: ...

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]: ...

    def get_check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]: ...

    def merge_pull_request(
        self, repository: str, number: int, *, sha: str, method: str
    ) -> dict[str, Any]: ...


class GhCliClient:
    """Small GitHub adapter that delegates credential handling to the official gh CLI."""

    def __init__(self, *, executable: str = "gh", timeout: float = 30):
        self.executable = executable
        self.timeout = timeout

    def _api(self, endpoint: str, *arguments: str, method: str = "GET") -> Any:
        command = [self.executable, "api", endpoint, "--method", method]
        command.extend(arguments)
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=self.timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.returncode != 0:
            detail = (process.stderr or process.stdout).strip()[-1000:]
            raise RuntimeError("GITHUB_API_FAILED:" + detail)
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GITHUB_API_INVALID_JSON") from exc

    def get_ref_sha(self, repository: str, branch: str) -> str:
        value = self._api(f"repos/{repository}/git/ref/heads/{branch}")
        return str(value["object"]["sha"]).lower()

    def get_workflow_run(self, repository: str, run_id: int) -> dict[str, Any]:
        """Read one Actions run; validate path components before invoking gh."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("GITHUB_REPOSITORY_INVALID")
        if not isinstance(run_id, int) or run_id < 1:
            raise ValueError("GITHUB_RUN_ID_INVALID")
        value = self._api(f"repos/{repository}/actions/runs/{run_id}")
        if not isinstance(value, dict):
            raise RuntimeError("GITHUB_WORKFLOW_RUN_INVALID")
        return value

    def get_workflow_jobs(self, repository: str, run_id: int) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not isinstance(run_id, int) or run_id < 1:
            raise ValueError("GITHUB_WORKFLOW_RUN_PATH_INVALID")
        value = self._api(f"repos/{repository}/actions/runs/{run_id}/jobs", "-f", "per_page=100")
        jobs = value.get("jobs") if isinstance(value, dict) else None
        if not isinstance(jobs, list) or len(jobs) > 100:
            raise RuntimeError("GITHUB_WORKFLOW_JOBS_INVALID")
        return [job for job in jobs if isinstance(job, dict)]

    def list_pull_requests(self, repository: str, *, head: str, base: str) -> list[dict[str, Any]]:
        owner = repository.split("/", 1)[0]
        value = self._api(
            f"repos/{repository}/pulls",
            "-f", "state=all",
            "-f", f"head={owner}:{head}",
            "-f", f"base={base}",
            "-f", "per_page=100",
        )
        if not isinstance(value, list):
            raise RuntimeError("GITHUB_PULL_LIST_INVALID")
        return value

    def create_pull_request(
        self, repository: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        return self._api(
            f"repos/{repository}/pulls",
            "-f", f"head={head}",
            "-f", f"base={base}",
            "-f", f"title={title}",
            "-f", f"body={body}",
            method="POST",
        )

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        return self._api(f"repos/{repository}/pulls/{number}")

    def get_check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]:
        value = self._api(
            f"repos/{repository}/commits/{sha}/check-runs",
            "-H", "Accept: application/vnd.github+json",
            "-f", "per_page=100", "--paginate", "--slurp",
        )
        if not isinstance(value, list) or not value:
            raise RuntimeError("GITHUB_CHECK_RUNS_INVALID")
        runs: list[dict[str, Any]] = []
        expected_total: int | None = None
        for page in value:
            if not isinstance(page, dict) or not isinstance(page.get("check_runs"), list):
                raise RuntimeError("GITHUB_CHECK_RUNS_INVALID")
            count = page.get("total_count")
            if not isinstance(count, int) or count < 0:
                raise RuntimeError("GITHUB_CHECK_RUNS_INVALID")
            if expected_total is None:
                expected_total = count
            elif count != expected_total:
                raise RuntimeError("GITHUB_CHECK_RUNS_CHANGED_DURING_PAGINATION")
            for run in page["check_runs"]:
                if not isinstance(run, dict):
                    raise RuntimeError("GITHUB_CHECK_RUNS_INVALID")
                runs.append(run)
        if len({run.get("id") for run in runs}) != len(runs):
            raise RuntimeError("GITHUB_CHECK_RUNS_DUPLICATE")
        if len(runs) != expected_total:
            raise RuntimeError("GITHUB_CHECK_RUNS_INCOMPLETE")
        return runs

    def merge_pull_request(
        self, repository: str, number: int, *, sha: str, method: str
    ) -> dict[str, Any]:
        return self._api(
            f"repos/{repository}/pulls/{number}/merge",
            "-f", f"sha={sha}",
            "-f", f"merge_method={method}",
            method="PUT",
        )
