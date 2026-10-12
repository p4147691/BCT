from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .core.models import OperationResult, Outcome, Principal
from .service_runtime import atomic_json, process_identity


BACKGROUND_CAPABILITIES = frozenset({"deploy", "service_control"})


def _runtime_root(bct: Any) -> Path:
    state_path = Path(bct.store.path).resolve()
    if state_path.name != "state.sqlite" or state_path.parent.name != "state":
        raise ValueError("BACKGROUND_RUNTIME_STATE_PATH_INVALID")
    return state_path.parent.parent


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
    created, current = bct.operations.begin(
        principal=principal,
        work_id=work_id,
        operation_id=operation_id,
        capability=capability,
        arguments=arguments,
        approval_ref=approval_ref,
    )
    if not created:
        return current

    runtime_root = _runtime_root(bct)
    jobs = runtime_root / "background-operations"
    logs = runtime_root / "logs"
    jobs.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    job_path = jobs / f"{key}.job.json"
    result_path = jobs / f"{key}.result.json"
    claim_path = jobs / f"{key}.claim"
    job = {
        "schema_version": 1,
        "created_at": time.time(),
        "not_before": time.time() + 1.0,
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
    atomic_json(job_path, job)
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1]
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(source_root) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    command = [sys.executable, "-m", "bct.operation_worker", "--job", str(job_path)]
    process: subprocess.Popen[bytes] | None = None
    try:
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
        identity = None
        deadline = time.monotonic() + 2.0
        while identity is None and time.monotonic() < deadline:
            identity = process_identity(process.pid)
            if identity is None:
                time.sleep(0.02)
        if identity is None:
            raise RuntimeError("BACKGROUND_WORKER_IDENTITY_UNAVAILABLE")
        atomic_json(jobs / f"{key}.launch.json", {
            "schema_version": 1,
            "operation_id": operation_id,
            "capability": capability,
            "job_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
            "worker": identity.as_dict(),
            "launched_at": time.time(),
        })
        return current
    except Exception as exc:
        if process is not None and process.poll() is None:
            process.terminate()
        return bct.store.finish_operation(
            operation_id=operation_id,
            outcome=Outcome.NOT_APPLIED,
            evidence={"phase": "DISPATCH", "code": type(exc).__name__},
            error=str(exc),
            release_claims=True,
        )
