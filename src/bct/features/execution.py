from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, UnknownEffectError, Work
from bct.integrations.native_process import list_processes, port_owners, process_fingerprint, process_matches, process_snapshot, redact_argv

from .common import resolve_in_work


_MAX_CAPTURE_BYTES = 1024 * 1024


def _bounded_text(value: bytes) -> tuple[str, bool]:
    clipped = len(value) > _MAX_CAPTURE_BYTES
    data = value[:_MAX_CAPTURE_BYTES]
    return data.decode("utf-8", errors="replace"), clipped


class SystemInspectFeature:
    capability = "system_inspect"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "").strip().casefold()
        if operation not in {"process_list", "process", "port"}:
            raise PreconditionError("SYSTEM_INSPECT_OPERATION_INVALID")
        normalized: dict[str, Any] = {"operation": operation}
        if operation == "process_list":
            normalized["query"] = str(arguments.get("query") or "")
            normalized["limit"] = max(1, min(int(arguments.get("limit") or 200), 1000))
        elif operation == "process":
            normalized["pid"] = int(arguments.get("pid") or 0)
            if normalized["pid"] <= 0:
                raise PreconditionError("PID_INVALID")
        else:
            normalized["port"] = int(arguments.get("port") or 0)
            if not 1 <= normalized["port"] <= 65535:
                raise PreconditionError("PORT_INVALID")
        target = f"system:{operation}:{normalized.get('pid', normalized.get('port', normalized.get('query', 'all')))}"
        return FeatureRequest(self.capability, target, normalized, (target.casefold(),))

    def execute(self, request: FeatureRequest) -> FeatureResult:
        operation = request.arguments["operation"]
        if operation == "process_list":
            rows = list_processes(query=request.arguments["query"], limit=request.arguments["limit"])
            output = {"processes": rows, "count": len(rows)}
        elif operation == "process":
            output = {"process": process_snapshot(request.arguments["pid"])}
        else:
            rows = port_owners(request.arguments["port"])
            output = {"port": request.arguments["port"], "owners": rows, "count": len(rows)}
        return FeatureResult(Outcome.APPLIED, {"operation": operation}, output=output)


class ExecuteFeature:
    capability = "execute"

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        kind = str(arguments.get("kind") or "argv").strip().casefold()
        if kind not in {"argv", "python", "powershell"}:
            raise PreconditionError("EXECUTION_KIND_INVALID")
        cwd = resolve_in_work(work, str(arguments.get("cwd") or ""), must_exist=True)
        if not cwd.is_dir():
            raise PreconditionError("EXECUTION_CWD_NOT_DIRECTORY")
        timeout_s = float(arguments.get("timeout_s") or 60.0)
        if not 0.1 <= timeout_s <= 3600.0:
            raise PreconditionError("EXECUTION_TIMEOUT_INVALID")

        argv: list[str]
        if kind == "argv":
            supplied = arguments.get("argv")
            if not isinstance(supplied, list) or not supplied or not all(isinstance(item, str) and item for item in supplied):
                raise PreconditionError("EXECUTION_ARGV_INVALID")
            argv = list(supplied)
        elif kind == "python":
            supplied = arguments.get("args") or []
            if not isinstance(supplied, list) or not all(isinstance(item, str) for item in supplied):
                raise PreconditionError("EXECUTION_ARGS_INVALID")
            module = str(arguments.get("module") or "").strip()
            script = str(arguments.get("script") or "").strip()
            if bool(module) == bool(script):
                raise PreconditionError("PYTHON_MODULE_OR_SCRIPT_REQUIRED")
            if script:
                script_path = resolve_in_work(work, script, must_exist=True)
                if not script_path.is_file():
                    raise PreconditionError("PYTHON_SCRIPT_NOT_FILE")
                argv = [sys.executable, str(script_path), *supplied]
            else:
                argv = [sys.executable, "-m", module, *supplied]
        else:
            supplied = arguments.get("args") or []
            if not isinstance(supplied, list) or not all(isinstance(item, str) for item in supplied):
                raise PreconditionError("EXECUTION_ARGS_INVALID")
            command = arguments.get("command")
            script = str(arguments.get("script") or "").strip()
            if bool(command) == bool(script):
                raise PreconditionError("POWERSHELL_COMMAND_OR_SCRIPT_REQUIRED")
            executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
            if not executable:
                raise PreconditionError("POWERSHELL_NOT_FOUND")
            prefix = [executable, "-NoLogo", "-NonInteractive", "-NoProfile"]
            if script:
                script_path = resolve_in_work(work, script, must_exist=True)
                if not script_path.is_file():
                    raise PreconditionError("POWERSHELL_SCRIPT_NOT_FILE")
                argv = [*prefix, "-File", str(script_path), *supplied]
            elif isinstance(command, str) and command.strip():
                argv = [*prefix, "-Command", command, *supplied]
            else:
                raise PreconditionError("POWERSHELL_COMMAND_INVALID")

        return FeatureRequest(
            self.capability,
            str(cwd),
            {"kind": kind, "cwd": str(cwd), "argv": argv, "timeout_s": timeout_s},
            ("execution:" + str(cwd).casefold(),),
            {"cwd": str(cwd)},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        argv = list(request.arguments["argv"])
        cwd = request.arguments["cwd"]
        timeout_s = float(request.arguments["timeout_s"])
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        started = time.time()
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            shell=False,
        )
        fingerprint = process_fingerprint(process.pid)
        try:
            stdout_raw, stderr_raw = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                stdout_raw, stderr_raw = process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired as exc:
                if process_matches(fingerprint):
                    raise UnknownEffectError("EXECUTION_TIMEOUT_PROCESS_STILL_RUNNING") from exc
                stdout_raw, stderr_raw = b"", b""
            stdout, stdout_truncated = _bounded_text(stdout_raw)
            stderr, stderr_truncated = _bounded_text(stderr_raw)
            return FeatureResult(
                Outcome.FAILED,
                {
                    "phase": "TIMEOUT", "pid": process.pid, "fingerprint": fingerprint,
                    "terminated": not process_matches(fingerprint), "duration_ms": int((time.time() - started) * 1000),
                },
                output={
                    "argv": redact_argv(argv), "returncode": process.returncode,
                    "stdout": stdout, "stderr": stderr,
                    "stdout_truncated": stdout_truncated, "stderr_truncated": stderr_truncated,
                },
            )
        stdout, stdout_truncated = _bounded_text(stdout_raw)
        stderr, stderr_truncated = _bounded_text(stderr_raw)
        outcome = Outcome.APPLIED if process.returncode == 0 else Outcome.FAILED
        return FeatureResult(
            outcome,
            {
                "phase": "EXITED", "pid": process.pid, "fingerprint": fingerprint,
                "returncode": process.returncode, "duration_ms": int((time.time() - started) * 1000),
            },
            output={
                "argv": redact_argv(argv), "returncode": process.returncode,
                "stdout": stdout, "stderr": stderr,
                "stdout_truncated": stdout_truncated, "stderr_truncated": stderr_truncated,
            },
        )
