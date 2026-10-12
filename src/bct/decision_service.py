from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import psutil

from bct.core.models import ConfirmedFailure, PreconditionError, UnknownEffectError
from bct.service_runtime import ProcessIdentity, atomic_json, process_identity, read_json


_LIVE_DECISION_CHILDREN: dict[int, subprocess.Popen[bytes]] = {}


class DecisionServiceController:
    def __init__(
        self,
        *,
        state_root: Path,
        endpoint_file: Path,
        model_path: Path,
        model_name: str,
        model_sha256: str,
        port: int,
        python_path: str | Path = sys.executable,
        python_paths: list[str] | None = None,
        module: str = "laya.serve",
        readiness_timeout: float = 45.0,
    ):
        self.state_root = state_root.resolve()
        self.endpoint_file = endpoint_file.resolve()
        self.service_file = self.state_root / "decision-service.json"
        self.log_file = self.state_root / "logs" / "decision-service.log"
        self.model_path = model_path.resolve()
        self.model_name = str(model_name)
        self.model_sha256 = str(model_sha256).upper()
        self.port = int(port)
        self.python_path = str(Path(python_path).resolve())
        self.python_paths = [str(Path(path).resolve()) for path in (python_paths or [])]
        self.module = str(module)
        self.readiness_timeout = max(1.0, float(readiness_timeout))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _health(self, timeout: float = 1.0) -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=timeout) as response:
                value = json.load(response)
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            return None

    @staticmethod
    def _identity(record: dict[str, Any] | None) -> ProcessIdentity | None:
        if not isinstance(record, dict):
            return None
        value = record.get("process")
        if not isinstance(value, dict):
            return None
        try:
            return ProcessIdentity(
                int(value["pid"]), str(value["executable"]), str(value["creation_marker"]),
                str(value["fingerprint"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def inspect(self) -> dict[str, Any]:
        receipt = read_json(self.service_file)
        health = self._health()
        if receipt is None:
            return {
                "state": "UNOWNED_RUNNING" if health else "STOPPED",
                "owned": False,
                "health": health,
                "base_url": self.base_url,
            }
        if str(receipt.get("state") or "").upper() == "STOPPED" and health is None:
            return {
                "state": "STOPPED", "owned": True, "ready": False, "health": None,
                "generation": int(receipt.get("generation") or 0), "base_url": self.base_url,
                "model_name": self.model_name, "model_path": str(self.model_path),
                "previous_process": receipt.get("previous_process"),
            }
        expected = self._identity(receipt)
        current = process_identity(expected.pid) if expected else None
        exact = bool(current and expected and current.fingerprint == expected.fingerprint)
        ready = bool(
            health
            and str(health.get("status") or "").casefold() in {"ok", "ready"}
            and self.model_name in list(health.get("loaded") or [self.model_name])
        )
        return {
            "state": "RUNNING" if exact and ready else ("OWNERSHIP_STALE" if not exact else "UNHEALTHY"),
            "owned": exact,
            "ready": ready,
            "process": expected.as_dict() if expected else None,
            "health": health,
            "generation": int(receipt.get("generation") or 0),
            "base_url": self.base_url,
            "model_name": self.model_name,
            "model_path": str(self.model_path),
        }

    def _preconditions(self) -> None:
        if not Path(self.python_path).is_file():
            raise PreconditionError("DECISION_PYTHON_MISSING")
        if not self.model_path.is_dir():
            raise PreconditionError("DECISION_MODEL_MISSING")
        weights = self.model_path / "model.safetensors"
        if not weights.is_file():
            raise PreconditionError("DECISION_MODEL_WEIGHTS_MISSING")
        import hashlib
        digest = hashlib.sha256()
        with weights.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest().upper() != self.model_sha256:
            raise PreconditionError("DECISION_MODEL_SHA_MISMATCH")
        for path in self.python_paths:
            if not Path(path).is_dir():
                raise PreconditionError("DECISION_PYTHONPATH_MISSING:" + path)

    def start(self) -> dict[str, Any]:
        current = self.inspect()
        if current["state"] == "RUNNING":
            return {**current, "duplicate": True}
        if current["state"] != "STOPPED":
            raise PreconditionError("DECISION_SERVICE_NOT_SAFE_TO_START:" + current["state"])
        self._preconditions()
        prior = read_json(self.service_file) or {}
        generation = int(prior.get("generation") or 0) + 1
        environment = dict(os.environ)
        environment.update({
            "LAYA_DEFAULT_MODEL": self.model_name,
            "LAYA_DEVICE": "cuda",
            "LAYA_EXTRA_MODELS": json.dumps({self.model_name: str(self.model_path)}),
            "LAYA_HOST": "127.0.0.1",
            "LAYA_LOG_LEVEL": "warning",
            "LAYA_MAX_LOADED": "1",
            "LAYA_MODELS": self.model_name,
            "LAYA_PORT": str(self.port),
            "PYTHONPATH": os.pathsep.join(self.python_paths),
        })
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with self.log_file.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                [self.python_path, "-m", self.module],
                cwd=str(self.state_root),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=environment,
                creationflags=creationflags,
            )
        identity = process_identity(process.pid)
        if identity is None:
            process.terminate()
            raise ConfirmedFailure("DECISION_PROCESS_IDENTITY_UNAVAILABLE", release_claims=True)
        _LIVE_DECISION_CHILDREN[process.pid] = process
        deadline = time.monotonic() + self.readiness_timeout
        health: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ConfirmedFailure(f"DECISION_PROCESS_EXITED:{process.returncode}", release_claims=True)
            health = self._health()
            if health and str(health.get("status") or "").casefold() in {"ok", "ready"}:
                loaded = list(health.get("loaded") or [])
                if not loaded or self.model_name in loaded:
                    break
            time.sleep(0.25)
        else:
            self._terminate_exact(identity)
            raise ConfirmedFailure("DECISION_READINESS_TIMEOUT", release_claims=True)
        receipt = {
            "service": "bct-decision",
            "owner": "BCT",
            "generation": generation,
            "process": identity.as_dict(),
            "base_url": self.base_url,
            "model_name": self.model_name,
            "model": str(self.model_path),
            "model_sha256": self.model_sha256,
            "started_at": time.time(),
            "health": health,
        }
        atomic_json(self.service_file, receipt)
        atomic_json(self.endpoint_file, {
            "service": "decision", "owner": "BCT", "base_url": self.base_url,
            "runtime": "laya", "model": str(self.model_path), "model_name": self.model_name,
            "model_sha256": self.model_sha256, "mode": "recommend_shadow",
            "generation": generation, "process": identity.as_dict(), "warmed_up": True,
        })
        return {**self.inspect(), "duplicate": False}

    @staticmethod
    def _terminate_exact(expected: ProcessIdentity, timeout: float = 10.0) -> bool:
        current = process_identity(expected.pid)
        if current is None:
            return True
        if current.fingerprint != expected.fingerprint:
            raise PreconditionError("DECISION_PROCESS_FINGERPRINT_MISMATCH")
        try:
            process = psutil.Process(expected.pid)
            process.terminate()
            process.wait(timeout=max(0.1, timeout))
        except psutil.TimeoutExpired:
            current = process_identity(expected.pid)
            if current is None:
                return True
            if current.fingerprint != expected.fingerprint:
                raise UnknownEffectError("DECISION_PROCESS_CHANGED_DURING_STOP")
            process.kill()
            try:
                process.wait(timeout=5.0)
            except psutil.TimeoutExpired as exc:
                raise UnknownEffectError("DECISION_PROCESS_STOP_UNVERIFIED") from exc
        except psutil.NoSuchProcess:
            return True
        return process_identity(expected.pid) is None

    def stop(self) -> dict[str, Any]:
        receipt = read_json(self.service_file)
        expected = self._identity(receipt)
        if receipt is None or expected is None:
            current = self.inspect()
            if current["state"] == "STOPPED":
                return {**current, "duplicate": True}
            raise PreconditionError("DECISION_SERVICE_NOT_BCT_OWNED")
        current = process_identity(expected.pid)
        if current is None:
            return {**self.inspect(), "duplicate": True}
        if current.fingerprint != expected.fingerprint:
            raise PreconditionError("DECISION_PROCESS_FINGERPRINT_MISMATCH")
        if not self._terminate_exact(expected):
            raise UnknownEffectError("DECISION_STOP_UNVERIFIED")
        stopped = {
            **receipt,
            "state": "STOPPED",
            "stopped_at": time.time(),
            "previous_process": receipt.get("process"),
        }
        stopped.pop("process", None)
        atomic_json(self.service_file, stopped)
        endpoint = read_json(self.endpoint_file)
        if endpoint and endpoint.get("owner") == "BCT" and int(endpoint.get("generation") or 0) == int(receipt.get("generation") or 0):
            atomic_json(self.endpoint_file, {**endpoint, "ready": False, "stopped_at": time.time()})
        return {"state": "STOPPED", "owned": True, "previous_process": expected.as_dict(), "duplicate": False}

    def restart(self) -> dict[str, Any]:
        before = self.inspect()
        stopped = self.stop() if before["state"] != "STOPPED" else before
        started = self.start()
        return {"state": started["state"], "pre": before, "stop": stopped, "post": started}
