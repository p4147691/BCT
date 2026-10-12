from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .service_runtime import atomic_json, current_process_identity, process_identity


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("PROCESS_SESSION_JOB_INVALID")
    return value


def _stop(process: subprocess.Popen[bytes]) -> tuple[bool, bool]:
    if process.poll() is not None:
        return True, False
    process.terminate()
    try:
        process.wait(timeout=5)
        return True, False
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
            return True, True
        except subprocess.TimeoutExpired:
            return False, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    arguments = parser.parse_args()
    job_path = Path(arguments.job).resolve(strict=True)
    job = _read(job_path)
    session_dir = Path(str(job["session_dir"])).resolve()
    state_path = session_dir / "session.json"
    command_dir = session_dir / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = session_dir / "stdout.bin"
    stderr_path = session_dir / "stderr.bin"
    worker = current_process_identity()
    process: subprocess.Popen[bytes] | None = None
    try:
        with stdout_path.open("ab", buffering=0) as stdout, stderr_path.open("ab", buffering=0) as stderr:
            process = subprocess.Popen(
                list(job["argv"]),
                cwd=str(job["cwd"]),
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            child = None
            deadline = time.monotonic() + 3.0
            while child is None and time.monotonic() < deadline:
                child = process_identity(process.pid)
                if child is None:
                    time.sleep(0.02)
            if child is None:
                raise RuntimeError("PROCESS_SESSION_CHILD_IDENTITY_UNAVAILABLE")
            state = {
                "schema_version": 1,
                "session_id": job["session_id"],
                "work_id": job["work_id"],
                "spec_sha256": job["spec_sha256"],
                "kind": job["kind"],
                "cwd": job["cwd"],
                "argv": job["redacted_argv"],
                "state": "RUNNING",
                "worker": worker.as_dict(),
                "process": child.as_dict(),
                "started_at": time.time(),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
            atomic_json(state_path, state)
            while True:
                returncode = process.poll()
                if returncode is not None:
                    atomic_json(state_path, {
                        **state,
                        "state": "EXITED",
                        "returncode": returncode,
                        "exited_at": time.time(),
                    })
                    return 0
                for command_path in sorted(command_dir.glob("*.command.json")):
                    processing = command_path.with_suffix(".processing")
                    try:
                        os.replace(command_path, processing)
                    except FileNotFoundError:
                        continue
                    command = _read(processing)
                    result_path = command_dir / f"{command['command_key']}.result.json"
                    action = str(command.get("action") or "")
                    if action == "input":
                        text = str(command.get("text") or "")
                        if bool(command.get("append_newline", True)):
                            text += "\n"
                        if process.stdin is None or process.poll() is not None:
                            result = {"applied": False, "code": "PROCESS_SESSION_NOT_RUNNING"}
                        else:
                            try:
                                process.stdin.write(text.encode("utf-8"))
                                process.stdin.flush()
                            except (BrokenPipeError, OSError):
                                result = {"applied": False, "code": "PROCESS_SESSION_INPUT_NOT_APPLIED"}
                            else:
                                result = {"applied": True, "bytes": len(text.encode("utf-8"))}
                    elif action == "stop":
                        stopped, forced = _stop(process)
                        result = {"applied": stopped, "forced": forced}
                        final_code = process.poll()
                        atomic_json(state_path, {
                            **state,
                            "state": "STOPPED" if stopped else "STOP_UNVERIFIED",
                            "returncode": final_code,
                            "forced": forced,
                            "stopped_at": time.time(),
                        })
                        atomic_json(result_path, {**result, "completed_at": time.time()})
                        return 0 if stopped else 2
                    else:
                        result = {"applied": False, "code": "PROCESS_SESSION_COMMAND_INVALID"}
                    atomic_json(result_path, {**result, "completed_at": time.time()})
                    processing.rename(command_dir / f"{command['command_key']}.done.json")
                time.sleep(0.05)
    except Exception as exc:
        if process is not None and process.poll() is None:
            process.terminate()
        atomic_json(state_path, {
            "schema_version": 1,
            "session_id": job.get("session_id"),
            "work_id": job.get("work_id"),
            "spec_sha256": job.get("spec_sha256"),
            "state": "FAILED",
            "worker": worker.as_dict(),
            "error_type": type(exc).__name__,
            "failed_at": time.time(),
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
