from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .core.models import OperationResult, OperationState, Outcome, Principal
from .service_runtime import atomic_json, process_identity, read_json


BACKGROUND_CAPABILITIES = frozenset({
    "deploy", "service_control", "verify", "github_pr_status", "orchestrate",
})

_ORCHESTRATION_RESTARTABLE = frozenset({
    "dispatch", "worker-replace", "chain-run", "chain-resume", "reconcile",
    "recover-not-dispatched", "recover-node-sync",
})


class BackgroundWorkerNotStarted(RuntimeError):
    """The OS rejected process creation, proving that no worker effect began."""


def _runtime_root(bct: Any) -> Path:
    state_path = Path(bct.store.path).resolve()
    if state_path.name != "state.sqlite" or state_path.parent.name != "state":
        raise ValueError("BACKGROUND_RUNTIME_STATE_PATH_INVALID")
    return state_path.parent.parent


def _worker_command_environment(bct: Any, job_path: Path) -> tuple[list[str], dict[str, str]]:
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1]
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(source_root) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    return [sys.executable, "-m", "bct.operation_worker", "--job", str(job_path)], environment


def _execution_job(bct: Any, stored_job: dict[str, Any]) -> dict[str, Any]:
    """Bind immutable intent to the current exact release and current policy."""
    return {
        **stored_job,
        "policy_path": str(bct.policy.path.resolve()),
        "state_path": str(Path(bct.store.path).resolve()),
    }


def _spawn_worker(bct: Any, *, job_path: Path, operation_id: str,
                  capability: str, job_sha256: str) -> dict[str, Any]:
    process: subprocess.Popen[bytes] | None = None
    try:
        runtime_root = _runtime_root(bct)
        logs = runtime_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        command, environment = _worker_command_environment(bct, job_path)
        with (logs / "background.stdout.log").open("ab") as stdout, (
            logs / "background.stderr.log"
        ).open("ab") as stderr:
            process = subprocess.Popen(
                command,
                cwd=str(bct.policy.path.parent),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                ),
            )
    except Exception as exc:
        if process is None:
            raise BackgroundWorkerNotStarted(str(exc)) from exc
        raise
    identity = None
    deadline = time.monotonic() + 2.0
    while identity is None and time.monotonic() < deadline:
        identity = process_identity(process.pid)
        if identity is None:
            time.sleep(0.02)
    if identity is None:
        raise RuntimeError("BACKGROUND_WORKER_IDENTITY_UNAVAILABLE")
    key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    launch = {
        "schema_version": 1,
        "operation_id": operation_id,
        "capability": capability,
        "job_sha256": job_sha256,
        "worker": identity.as_dict(),
        "launched_at": time.time(),
    }
    atomic_json(runtime_root / "background-operations" / f"{key}.launch.json", launch)
    return launch


def recover_orphaned_orchestration_operations(bct: Any) -> list[dict[str, Any]]:
    """Restart exact durable orchestration jobs whose proven worker is gone.

    This runs on Core startup.  It never invents a new operation or request and
    never removes an unproven live claim.  Old claim files are renamed as audit
    evidence only after the recorded process fingerprint is proven absent.
    """
    runtime_root = _runtime_root(bct)
    jobs = runtime_root / "background-operations"
    jobs.mkdir(parents=True, exist_ok=True)
    durable_operation_ids: set[str] = set()
    for stored_job in bct.store.running_background_jobs(capability="orchestrate"):
        arguments = stored_job.get("arguments")
        if not isinstance(arguments, dict) or str(arguments.get("operation")) \
                not in _ORCHESTRATION_RESTARTABLE:
            continue
        key = hashlib.sha256(
            str(stored_job["operation_id"]).encode("utf-8")
        ).hexdigest()
        durable_operation_ids.add(str(stored_job["operation_id"]))
        job_path = jobs / f"{key}.job.json"
        # Recovery always re-enters the current exact release and current policy.
        # OperationCoordinator revalidates policy/ownership before every effect.
        execution_job = _execution_job(bct, stored_job)
        try:
            current_file = read_json(job_path)
        except Exception:
            current_file = None
        if current_file != execution_job:
            atomic_json(job_path, execution_job)
    recovered: list[dict[str, Any]] = []
    for job_path in sorted(jobs.glob("*.job.json")):
        try:
            job = read_json(job_path)
            if job is None or job.get("capability") != "orchestrate":
                continue
            if str(job.get("operation_id") or "") not in durable_operation_ids:
                continue
            arguments = job.get("arguments")
            if not isinstance(arguments, dict) or str(arguments.get("operation")) \
                    not in _ORCHESTRATION_RESTARTABLE:
                continue
            principal_value = job.get("principal")
            if not isinstance(principal_value, dict):
                continue
            current = bct.store.get_operation_for(
                operation_id=str(job["operation_id"]),
                work_id=str(job["work_id"]),
                principal_id=str(principal_value["principal_id"]),
            )
            if current.state is not OperationState.RUNNING:
                continue
            executor = bct.store.background_executor(str(job["operation_id"]))
            if executor is not None:
                executor_live = process_identity(int(executor["pid"]))
                if (
                    executor_live is not None
                    and executor_live.fingerprint == str(executor["fingerprint"])
                ):
                    recovered.append({
                        "operation_id": str(job["operation_id"]),
                        "status": "WORKER_STILL_RUNNING",
                    })
                    continue
                if not bct.store.clear_background_executor(
                    operation_id=str(job["operation_id"]),
                    fingerprint=str(executor["fingerprint"]),
                ):
                    recovered.append({
                        "operation_id": str(job["operation_id"]),
                        "status": "RECOVERY_LEASE_CHANGED",
                    })
                    continue
            key = hashlib.sha256(str(job["operation_id"]).encode("utf-8")).hexdigest()
            launch_path = jobs / f"{key}.launch.json"
            launch = read_json(launch_path)
            worker = launch.get("worker") if isinstance(launch, dict) else None
            if isinstance(worker, dict):
                live = process_identity(int(worker.get("pid") or 0))
                if live is not None and live.fingerprint == str(worker.get("fingerprint") or ""):
                    recovered.append({
                        "operation_id": str(job["operation_id"]),
                        "status": "WORKER_STILL_RUNNING",
                    })
                    continue
            claim_path = Path(str(job["claim_path"])).resolve()
            if claim_path.exists():
                try:
                    claim = read_json(claim_path)
                except Exception:
                    claim = None
                if isinstance(claim, dict):
                    claim_live = process_identity(int(claim.get("pid") or 0))
                    claim_fingerprint = str(claim.get("fingerprint") or "")
                    if (
                        claim_live is not None and claim_fingerprint
                        and claim_live.fingerprint == claim_fingerprint
                    ):
                        recovered.append({
                            "operation_id": str(job["operation_id"]),
                            "status": "WORKER_STILL_RUNNING",
                        })
                        continue
                stale_path = claim_path.with_name(
                    claim_path.name + ".stale." + str(time.time_ns())
                )
                os.replace(claim_path, stale_path)
            job_sha256 = hashlib.sha256(job_path.read_bytes()).hexdigest()
            _spawn_worker(
                bct, job_path=job_path,
                operation_id=str(job["operation_id"]),
                capability="orchestrate", job_sha256=job_sha256,
            )
            recovered.append({
                "operation_id": str(job["operation_id"]),
                "status": "RESTARTED_EXACT_JOB",
            })
        except Exception as exc:
            recovered.append({
                "job": job_path.name, "status": "RECOVERY_SKIPPED",
                "reason": type(exc).__name__,
            })
    return recovered


def launch_background_operation(
    bct: Any,
    *,
    principal: Principal,
    work_id: str,
    operation_id: str,
    capability: str,
    arguments: dict[str, Any],
    approval_ref: str | None,
) -> OperationResult:
    if capability not in BACKGROUND_CAPABILITIES:
        raise ValueError("BACKGROUND_CAPABILITY_INVALID")
    runtime_root = _runtime_root(bct)
    jobs = runtime_root / "background-operations"
    jobs.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    job_path = jobs / f"{key}.job.json"
    result_path = jobs / f"{key}.result.json"
    claim_path = jobs / f"{key}.claim"
    job_spec = {
        "schema_version": 1,
        "_not_before_delay": (
            1.0 if capability in {"deploy", "service_control"} else 0.0
        ),
        "state_path": str(Path(bct.store.path).resolve()),
        "policy_path": str(bct.policy.path.resolve()),
        "principal": {
            "principal_id": principal.principal_id,
            "auth_source": principal.auth_source,
            "capabilities": sorted(principal.capabilities),
        },
        "work_id": work_id,
        "operation_id": operation_id,
        "capability": capability,
        "arguments": arguments,
        "approval_ref": approval_ref,
        "claim_path": str(claim_path),
        "result_path": str(result_path),
    }
    created, current = bct.operations.begin(
        principal=principal,
        work_id=work_id,
        operation_id=operation_id,
        capability=capability,
        arguments=arguments,
        approval_ref=approval_ref,
        background_job=job_spec,
    )
    if not created and current.state is OperationState.FINISHED:
        return current
    job = bct.store.background_job(operation_id)
    if job is None:
        raise RuntimeError("BACKGROUND_JOB_NOT_DURABLE")
    atomic_json(job_path, _execution_job(bct, job))
    if not created:
        if capability == "orchestrate" and str(arguments.get("operation")) \
                in _ORCHESTRATION_RESTARTABLE:
            recover_orphaned_orchestration_operations(bct)
        return replace(bct.store.get_operation_for(
            operation_id=operation_id, work_id=work_id,
            principal_id=principal.principal_id,
        ), duplicate=True)
    try:
        _spawn_worker(
            bct, job_path=job_path, operation_id=operation_id,
            capability=capability,
            job_sha256=hashlib.sha256(job_path.read_bytes()).hexdigest(),
        )
        return current
    except BackgroundWorkerNotStarted as exc:
        return bct.store.finish_operation(
            operation_id=operation_id,
            outcome=Outcome.NOT_APPLIED,
            evidence={"phase": "DISPATCH", "code": type(exc.__cause__).__name__},
            error=str(exc), release_claims=True,
        )
    except Exception as exc:
        # The spawn boundary itself is ambiguous once Popen is attempted.  Preserve
        # RUNNING and its claims; exact startup recovery will inspect the fingerprint.
        return bct.store.get_operation_for(
            operation_id=operation_id, work_id=work_id,
            principal_id=principal.principal_id,
        )
