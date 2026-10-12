from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work

from .common import resolve_in_work


class TestFeature:
    capability = "test"
    _kinds = {"py_compile", "unittest"}

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        cwd = resolve_in_work(work, str(arguments.get("cwd") or ""), must_exist=True)
        if not cwd.is_dir():
            raise PreconditionError("TEST_CWD_NOT_DIRECTORY")
        kind = str(arguments.get("kind") or "")
        targets = arguments.get("targets")
        timeout = float(arguments.get("timeout_s", 60))
        if kind not in self._kinds:
            raise PreconditionError("TEST_KIND_NOT_ALLOWED")
        if not isinstance(targets, list) or not targets or len(targets) > 64:
            raise PreconditionError("TEST_TARGETS_INVALID")
        if timeout <= 0 or timeout > 600:
            raise PreconditionError("TEST_TIMEOUT_INVALID")
        normalized: list[str] = []
        for target in targets:
            if not isinstance(target, str) or not target or target.startswith("-"):
                raise PreconditionError("TEST_TARGET_INVALID")
            if kind == "py_compile":
                path = resolve_in_work(work, str(cwd / target), must_exist=True)
                if path.suffix.lower() != ".py":
                    raise PreconditionError("PY_COMPILE_REQUIRES_PY_FILES")
                normalized.append(str(path))
            else:
                if any(separator in target for separator in ("/", "\\")) or not all(
                    part.isidentifier() for part in target.split(".")
                ):
                    raise PreconditionError("BAD_TEST_MODULE")
                normalized.append(target)
        return FeatureRequest(
            self.capability, str(cwd), {"kind": kind, "targets": normalized, "timeout_s": timeout},
            ("test:" + str(cwd).casefold(),),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        kind = request.arguments["kind"]
        targets = request.arguments["targets"]
        argv = [sys.executable, "-m", "py_compile", *targets] if kind == "py_compile" else [
            sys.executable, "-m", "unittest", "-q", *targets
        ]
        with tempfile.TemporaryDirectory(prefix="bct-pycache-") as cache:
            environment = os.environ.copy()
            environment["PYTHONPYCACHEPREFIX"] = cache
            src = Path(request.target) / "src"
            if src.is_dir():
                environment["PYTHONPATH"] = str(src) + os.pathsep + environment.get("PYTHONPATH", "")
            started = time.perf_counter()
            try:
                process = subprocess.run(
                    argv, cwd=request.target, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=request.arguments["timeout_s"], shell=False, env=environment,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                status = "PASS" if process.returncode == 0 else "FAIL"
                return FeatureResult(Outcome.APPLIED, {
                    "kind": kind, "status": status, "returncode": process.returncode,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "stdout_chars": len(process.stdout), "stderr_chars": len(process.stderr),
                }, output={"stdout": process.stdout[-65536:], "stderr": process.stderr[-65536:]})
            except subprocess.TimeoutExpired as exc:
                stdout = str(exc.stdout or "")
                stderr = str(exc.stderr or "")
                return FeatureResult(Outcome.APPLIED, {
                    "kind": kind, "status": "TIMEOUT", "returncode": None,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "stdout_chars": len(stdout), "stderr_chars": len(stderr),
                }, output={"stdout": stdout[-65536:], "stderr": stderr[-65536:]})
