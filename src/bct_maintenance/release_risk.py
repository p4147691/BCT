"""Classify exact committed changes and verify the independent CI gate."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

from .errors import PreconditionError
from .releases import _git, _SHA

MCP = "src/bct/mcp_server.py"
LIBRARY = "src/bct/data/component-library.json"
MEDIUM_MODULES = {"src/bct/status_views.py", "src/bct/project_plan.py"}
TEXT_ONLY_USAGE = {"desktop_explore", "desktop_session_status", "desktop_window_list", "system_inspect"}
EXPECTED_JOBS = {"scope", "preflight", *(f"core ({n})" for n in range(12))}


def git_output(root, *args):
    result = _git(root, *args)
    if result.returncode:
        raise PreconditionError("RELEASE_GIT_EVIDENCE_UNAVAILABLE")
    return result.stdout


def _usage_only(old, new):
    def shape(source):
        tree = ast.parse(source)
        matches = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "_CAPABILITY_USAGE"
                           for target in node.targets)]
        if len(matches) != 1 or not isinstance(matches[0].value, ast.Dict):
            return None
        node = matches[0]
        # Limit automatic changes to help text whose output is not a browser
        # routing contract. Keep keys, position and the rest of the AST exact.
        for i, key in enumerate(node.value.keys):
            if (isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in TEXT_ONLY_USAGE
                    and isinstance(node.value.values[i], ast.Constant)
                    and isinstance(node.value.values[i].value, str)):
                node.value.values[i] = ast.Constant(value="")
        return ast.dump(tree)

    left, right = shape(old), shape(new)
    return left is not None and left == right


def _catalogue_hash_refresh(old, new, dependency_text):
    before, after = json.loads(old), json.loads(new)
    expected = dict(before["source_hashes"])
    for path, contents in dependency_text.items():
        if path in expected:
            expected[path] = hashlib.sha256(contents.encode("utf-8")).hexdigest()
    before["source_hashes"] = expected
    before["source_fingerprint"] = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    return before == after


def _same_execution_boundary(old, new):
    # These modules only project or prepare data. A new integration, dynamic
    # invocation, module-level effect, or altered public signature needs review.
    def shape(source):
        tree = ast.parse(source)
        top_level = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                top_level.append(ast.dump(ast.FunctionDef(
                    name=node.name, args=node.args, body=[], decorator_list=node.decorator_list,
                    returns=node.returns, type_params=node.type_params,
                )))
            else:
                top_level.append(ast.dump(node))
        guarded = (ast.Import, ast.ImportFrom, ast.With, ast.AsyncWith, ast.AsyncFunctionDef,
                   ast.Await, ast.ClassDef, ast.Global, ast.Nonlocal)
        dependencies = {ast.dump(node) for node in ast.walk(tree) if isinstance(node, guarded)}
        calls = {ast.dump(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        return top_level, dependencies, calls

    before, after = shape(old), shape(new)
    return before[0] == after[0] and after[1] <= before[1] and after[2] <= before[2]


def release_risk(root, baseline, candidate):
    if not all(_SHA.fullmatch(value) for value in (baseline, candidate)) or baseline == candidate:
        raise PreconditionError("RELEASE_SHA_INVALID")
    git_output(root, "merge-base", "--is-ancestor", baseline, candidate)
    raw = git_output(root, "diff", "--raw", "--no-ext-diff", "--no-renames", "-z", baseline, candidate, "--")
    fields = raw.rstrip("\0").split("\0") if raw else []
    changed = dict(zip(fields[1::2], fields[::2], strict=True))
    reasons = {}
    dependencies = {}
    for path, record in sorted(changed.items()):
        before_mode, after_mode, _, _, status = record.removeprefix(":").split()
        if path == LIBRARY:
            continue
        if path == MCP and (before_mode, after_mode, status) == ("100644", "100644", "M"):
            try:
                old = git_output(root, "show", f"{baseline}:{path}")
                new = git_output(root, "show", f"{candidate}:{path}")
                if _usage_only(old, new):
                    reasons[path] = "LOW"
                    dependencies[path] = new
                    continue
            except (ValueError, SyntaxError):
                pass
        if path.startswith("docs/") and path.endswith(".md") and status in {"A", "M", "D"}:
            # The chain manual is loaded as operational instructions.
            if not path.startswith(("docs/CHAIN_", "docs/INDEPENDENT_MAINTENANCE", "docs/DEPLOYMENT")) and before_mode in {"100644", "000000"} and after_mode in {"100644", "000000"}:
                reasons[path] = "LOW"
                if status != "D":
                    dependencies[path] = git_output(root, "show", f"{candidate}:{path}")
                continue
        reasons[path] = "HIGH"
        if path in MEDIUM_MODULES and (before_mode, after_mode, status) == ("100644", "100644", "M"):
            old = git_output(root, "show", f"{baseline}:{path}")
            new = git_output(root, "show", f"{candidate}:{path}")
            try:
                if _same_execution_boundary(old, new):
                    reasons[path] = "MEDIUM"
                    dependencies[path] = new
            except SyntaxError:
                pass
    if LIBRARY in changed:
        reasons[LIBRARY] = "HIGH"
        if changed[LIBRARY].startswith(":100644 100644 ") and changed[LIBRARY].endswith(" M") and dependencies:
            try:
                if _catalogue_hash_refresh(git_output(root, "show", f"{baseline}:{LIBRARY}"),
                                           git_output(root, "show", f"{candidate}:{LIBRARY}"), dependencies):
                    reasons[LIBRARY] = "LOW"
            except (KeyError, TypeError, ValueError):
                pass
    level = max(reasons.values(), key=("LOW", "MEDIUM", "HIGH").index) if reasons else "HIGH"
    return {"level": level, "paths": reasons}


def verify_ci(policy_path: Path, sha: str, run_id: int):
    policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))
    repo = policy.get("git_authority", {}).get("repository", "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or type(run_id) is not int or run_id < 1:
        raise PreconditionError("RELEASE_CI_IDENTITY_INVALID")

    def api(suffix):
        try:
            result = subprocess.run(["gh", "api", f"repos/{repo}/actions/{suffix}"], capture_output=True,
                                    encoding="utf-8", timeout=20, check=True)
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise PreconditionError("RELEASE_CI_UNAVAILABLE") from exc

    run = api(f"runs/{run_id}")
    attempt = run.get("run_attempt")
    if (run.get("id") != run_id or run.get("path") != ".github/workflows/ci.yml"
            or run.get("head_sha") != sha or run.get("status") != "completed"
            or run.get("conclusion") != "success" or type(attempt) is not int or attempt < 1
            or (run.get("head_repository") or {}).get("full_name", "").casefold() != repo.casefold()):
        raise PreconditionError("RELEASE_EXACT_CI_NOT_VERIFIED")
    jobs = api(f"runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
    rows = jobs.get("jobs", [])
    if (jobs.get("total_count") != len(EXPECTED_JOBS) or len(rows) != len(EXPECTED_JOBS)
            or {job.get("name") for job in rows} != EXPECTED_JOBS
            or any(job.get("head_sha") != sha or job.get("status") != "completed"
                   or job.get("conclusion") != "success" for job in rows)):
        raise PreconditionError("RELEASE_REQUIRED_CI_JOBS_NOT_VERIFIED")
    return {"repository": repo, "run_id": run_id, "attempt": attempt, "head_sha": sha,
            "jobs": sorted(EXPECTED_JOBS)}
