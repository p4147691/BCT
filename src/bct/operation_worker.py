from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from . import BCT
from .core.models import OperationState, Outcome, Principal
from .service_runtime import atomic_json, current_process_identity


def _claim(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        identity = current_process_identity()
        os.write(descriptor, (json.dumps({
            **identity.as_dict(), "claimed_at": time.time(),
        }, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or int(value.get("schema_version") or 0) != 1:
        raise ValueError("BACKGROUND_JOB_INVALID")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    arguments = parser.parse_args()
    job_path = Path(arguments.job).resolve(strict=True)
    job = _load(job_path)
    result_path = Path(str(job["result_path"])).resolve()
    not_before = float(job.get("not_before") or 0.0)
    if not_before > time.time():
        time.sleep(not_before - time.time())

    bct = BCT(state_path=job["state_path"], policy_path=job["policy_path"])
    identity = current_process_identity()
    if not bct.store.acquire_background_executor(
        operation_id=str(job["operation_id"]), pid=identity.pid,
        fingerprint=identity.fingerprint,
    ):
        return 2
    _claim(Path(str(job["claim_path"])).resolve())
    principal_value = job["principal"]
    principal = Principal(
        str(principal_value["principal_id"]),
        str(principal_value["auth_source"]),
        frozenset(str(item) for item in principal_value["capabilities"]),
    )
    try:
        result = bct.operations.resume(
            principal=principal,
            work_id=str(job["work_id"]),
            operation_id=str(job["operation_id"]),
            capability=str(job["capability"]),
            arguments=dict(job["arguments"]),
            approval_ref=job.get("approval_ref"),
        )
    except Exception as exc:
        current = bct.store.get_operation_for(
            operation_id=str(job["operation_id"]),
            work_id=str(job["work_id"]),
            principal_id=principal.principal_id,
        )
        if current.state is OperationState.RUNNING:
            result = bct.store.finish_operation(
                operation_id=str(job["operation_id"]),
                outcome=Outcome.UNKNOWN,
                evidence={"phase": "BACKGROUND_WORKER", "type": type(exc).__name__},
                error=str(exc),
                release_claims=False,
            )
        else:
            result = current
    atomic_json(result_path, {
        "schema_version": 1,
        "completed_at": time.time(),
        "result": result.as_dict(),
    })
    return 0 if result.outcome is Outcome.APPLIED else 1


if __name__ == "__main__":
    raise SystemExit(main())
