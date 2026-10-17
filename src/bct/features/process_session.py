from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome, PreconditionError,
    UnknownEffectError, Work,
)
from bct.features.execution import resolve_execution
from bct.integrations.native_process import redact_argv
from bct.service_runtime import atomic_json, process_identity


_SESSION_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}")
_SESSION_WORKERS: dict[int, subprocess.Popen[bytes]] = {}


def _sha(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise PreconditionError("PROCESS_SESSION_RECEIPT_INVALID")
    return value


class ProcessSessionFeature:
    capability = "process_session"

    def __init__(self, policy_path: str | Path, *, data_root: str | Path | None = None):
        data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
        execution = data.get("execution") or {}
        sessions = execution.get("sessions") or {}
        configured = sessions.get("state_root") or r"D:\BCT\data\process-sessions"
        self.state_root = (
            Path(data_root).resolve() / "process-sessions"
            if data_root is not None
            else Path(str(configured)).resolve()
        )

    def _session_dir(self, session_id: str) -> Path:
        return self.state_root / session_id

    def _owned_receipt(self, work: Work, session_id: str) -> tuple[Path, dict[str, Any]]:
        directory = self._session_dir(session_id)
        receipt = _read(directory / "session.json")
        if receipt is None:
            raise PreconditionError("PROCESS_SESSION_NOT_FOUND")
        if receipt.get("session_id") != session_id or receipt.get("work_id") != work.work_id:
            raise PreconditionError("PROCESS_SESSION_NOT_OWNED")
        return directory, receipt

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "").strip().casefold()
        if operation not in {"start", "status", "output", "input", "stop"}:
            raise PreconditionError("PROCESS_SESSION_OPERATION_INVALID")
        session_id = str(arguments.get("session_id") or "").strip()
        if not _SESSION_ID.fullmatch(session_id):
            raise PreconditionError("PROCESS_SESSION_ID_INVALID")
        normalized: dict[str, Any] = {"operation": operation, "session_id": session_id, "work_id": work.work_id}
        preconditions: dict[str, Any] = {}
        if operation == "start":
            resolved = resolve_execution(work, arguments)
            specification = {**resolved, "work_id": work.work_id, "session_id": session_id}
            normalized.update(resolved)
            normalized["spec_sha256"] = _sha(specification)
            preconditions["spec_sha256"] = normalized["spec_sha256"]
        else:
            _, receipt = self._owned_receipt(work, session_id)
            preconditions["spec_sha256"] = str(receipt.get("spec_sha256") or "")
            if operation == "output":
                for name in ("stdout_offset", "stderr_offset"):
                    value = int(arguments.get(name) or 0)
                    if value < 0:
                        raise PreconditionError("PROCESS_SESSION_OFFSET_INVALID")
                    normalized[name] = value
                normalized["limit"] = max(1, min(int(arguments.get("limit") or 262144), 1048576))
            elif operation == "input":
                text = arguments.get("text")
                if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 65536:
                    raise PreconditionError("PROCESS_SESSION_INPUT_INVALID")
                normalized["text"] = text
                normalized["append_newline"] = bool(arguments.get("append_newline", True))
        return FeatureRequest(
            self.capability,
            session_id,
            normalized,
            ("process-session:" + session_id.casefold(),),
            preconditions,
        )

    @staticmethod
    def _identity_ok(receipt: dict[str, Any], key: str) -> bool:
        value = receipt.get(key)
        if not isinstance(value, dict):
            return False
        try:
            actual = process_identity(int(value["pid"]))
        except (KeyError, TypeError, ValueError):
            return False
        return actual is not None and actual.as_dict() == value

    def _status(self, directory: Path, receipt: dict[str, Any]) -> dict[str, Any]:
        current = _read(directory / "session.json") or receipt
        state = str(current.get("state") or "UNKNOWN")
        worker_alive = self._identity_ok(current, "worker")
        process_alive = self._identity_ok(current, "process")
        worker_value = current.get("worker")
        worker_pid = int(worker_value.get("pid") or 0) if isinstance(worker_value, dict) else 0
        if worker_pid and not worker_alive:
            handle = _SESSION_WORKERS.pop(worker_pid, None)
            if handle is not None:
                try:
                    handle.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
        if state == "RUNNING" and not (worker_alive and process_alive):
            state = "STALE_UNVERIFIED" if worker_alive or process_alive else "EXIT_PENDING_RECEIPT"
        return {**current, "state": state, "worker_alive": worker_alive, "process_alive": process_alive}

    def _start(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        directory = self._session_dir(values["session_id"])
        state_path = directory / "session.json"
        existing = _read(state_path)
        if existing is not None:
            if existing.get("work_id") != values["work_id"] or existing.get("spec_sha256") != values["spec_sha256"]:
                raise PreconditionError("PROCESS_SESSION_ID_ALREADY_USED")
            status = self._status(directory, existing)
            if status["state"] == "RUNNING" and status["worker_alive"] and status["process_alive"]:
                return FeatureResult(Outcome.APPLIED, {"already_running": True, "session": status})
            raise PreconditionError("PROCESS_SESSION_ID_TERMINAL")
        directory.mkdir(parents=True, exist_ok=False)
        job = {
            "schema_version": 1,
            "session_id": values["session_id"],
            "work_id": values["work_id"],
            "spec_sha256": values["spec_sha256"],
            "kind": values["kind"],
            "cwd": values["cwd"],
            "argv": values["argv"],
            "redacted_argv": redact_argv(values["argv"]),
            "session_dir": str(directory),
        }
        job_path = directory / "launch.json"
        atomic_json(job_path, job)
        environment = dict(os.environ)
        source_root = Path(__file__).resolve().parents[2]
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = str(source_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        with (directory / "worker.stdout.log").open("ab") as stdout, (directory / "worker.stderr.log").open("ab") as stderr:
            worker = subprocess.Popen(
                [sys.executable, "-m", "bct.process_session_worker", "--job", str(job_path)],
                cwd=values["cwd"], env=environment, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, shell=False,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
            )
        _SESSION_WORKERS[worker.pid] = worker
        deadline = time.monotonic() + 10
        receipt = None
        while time.monotonic() < deadline:
            receipt = _read(state_path)
            if receipt is not None:
                break
            if worker.poll() is not None:
                break
            time.sleep(0.05)
        if receipt is None or receipt.get("state") != "RUNNING":
            if worker.poll() is None:
                worker.terminate()
            raise ConfirmedFailure("PROCESS_SESSION_START_NOT_APPLIED", release_claims=True)
        status = self._status(directory, receipt)
        if not status["worker_alive"] or not status["process_alive"]:
            raise UnknownEffectError("PROCESS_SESSION_START_UNVERIFIED")
        return FeatureResult(Outcome.APPLIED, {"already_running": False, "session": status})

    @staticmethod
    def _read_output(path: Path, offset: int, limit: int) -> tuple[str, int, bool]:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return "", offset, False
        start = min(offset, size)
        with path.open("rb") as handle:
            handle.seek(start)
            raw = handle.read(limit)
        return raw.decode("utf-8", errors="replace"), start + len(raw), start + len(raw) < size

    def _command(self, request: FeatureRequest, directory: Path, action: str) -> dict[str, Any]:
        key = hashlib.sha256(request.operation_id.encode("utf-8")).hexdigest()
        command_dir = directory / "commands"
        command_dir.mkdir(parents=True, exist_ok=True)
        result_path = command_dir / f"{key}.result.json"
        existing = _read(result_path)
        if existing is not None:
            return existing
        command = {
            "command_key": key,
            "operation_id": request.operation_id,
            "action": action,
        }
        if action == "input":
            command.update({
                "text": request.arguments["text"],
                "append_newline": request.arguments["append_newline"],
            })
        atomic_json(command_dir / f"{key}.command.json", command)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = _read(result_path)
            if result is not None:
                return result
            time.sleep(0.05)
        raise UnknownEffectError("PROCESS_SESSION_COMMAND_RESULT_UNAVAILABLE")

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        operation = values["operation"]
        if operation == "start":
            return self._start(request)
        directory = self._session_dir(values["session_id"])
        receipt = _read(directory / "session.json")
        if receipt is None or receipt.get("work_id") != values["work_id"]:
            raise PreconditionError("PROCESS_SESSION_NOT_OWNED")
        if operation == "status":
            status = self._status(directory, receipt)
            return FeatureResult(Outcome.APPLIED, {"operation": operation, "state": status["state"]}, output={"session": status})
        if operation == "output":
            stdout, stdout_offset, stdout_more = self._read_output(
                directory / "stdout.bin", values["stdout_offset"], values["limit"],
            )
            stderr, stderr_offset, stderr_more = self._read_output(
                directory / "stderr.bin", values["stderr_offset"], values["limit"],
            )
            return FeatureResult(Outcome.APPLIED, {"operation": operation}, output={
                "stdout": stdout, "stderr": stderr,
                "stdout_offset": stdout_offset, "stderr_offset": stderr_offset,
                "stdout_more": stdout_more, "stderr_more": stderr_more,
                "session": self._status(directory, receipt),
            })
        if operation == "input":
            if self._status(directory, receipt)["state"] != "RUNNING":
                raise PreconditionError("PROCESS_SESSION_NOT_RUNNING")
            result = self._command(request, directory, "input")
            if result.get("applied") is not True:
                raise ConfirmedFailure(str(result.get("code") or "PROCESS_SESSION_INPUT_NOT_APPLIED"), release_claims=True)
            return FeatureResult(Outcome.APPLIED, {"operation": operation, **result})
        status = self._status(directory, receipt)
        if status["state"] in {"STOPPED", "EXITED"}:
            return FeatureResult(Outcome.APPLIED, {"operation": operation, "already_stopped": True, "session": status})
        if status["state"] != "RUNNING":
            raise UnknownEffectError("PROCESS_SESSION_STOP_STATE_UNVERIFIED")
        result = self._command(request, directory, "stop")
        final = self._status(directory, receipt)
        if result.get("applied") is not True or final["process_alive"]:
            raise UnknownEffectError("PROCESS_SESSION_STOP_UNVERIFIED")
        worker_value = final.get("worker")
        worker_pid = int(worker_value.get("pid") or 0) if isinstance(worker_value, dict) else 0
        handle = _SESSION_WORKERS.pop(worker_pid, None)
        if handle is not None:
            try:
                handle.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        final = self._status(directory, final)
        return FeatureResult(Outcome.APPLIED, {"operation": operation, "already_stopped": False, "session": final})
