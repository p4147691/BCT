from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if os.name == "nt":
    from ctypes import wintypes

from bct.core.models import ConfirmedFailure, PreconditionError, UnknownEffectError


_LIVE_CHILDREN: dict[int, subprocess.Popen[bytes]] = {}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(value, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise PreconditionError("RUNTIME_RECEIPT_INVALID:" + str(path)) from exc
    if not isinstance(value, dict):
        raise PreconditionError("RUNTIME_RECEIPT_INVALID:" + str(path))
    return value


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    executable: str
    creation_marker: str
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "executable": self.executable,
            "creation_marker": self.creation_marker,
            "fingerprint": self.fingerprint,
        }


def _fingerprint(pid: int, executable: str, creation_marker: str) -> ProcessIdentity:
    canonical = str(Path(executable).resolve())
    digest = hashlib.sha256(
        f"{pid}|{canonical.casefold()}|{creation_marker}".encode("utf-8")
    ).hexdigest()
    return ProcessIdentity(pid, canonical, creation_marker, digest)


def process_identity(pid: int) -> ProcessIdentity | None:
    if pid < 1:
        return None
    if os.name == "nt":
        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            creation_value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return _fingerprint(pid, buffer.value, str(creation_value))
        finally:
            kernel32.CloseHandle(handle)
    proc = Path("/proc") / str(pid)
    try:
        executable = os.readlink(proc / "exe")
        fields = (proc / "stat").read_text(encoding="utf-8").split()
        creation_marker = fields[21]
    except (FileNotFoundError, PermissionError, IndexError, OSError):
        return None
    return _fingerprint(pid, executable, creation_marker)


def current_process_identity() -> ProcessIdentity:
    identity = process_identity(os.getpid())
    if identity is None:
        raise RuntimeError("CURRENT_PROCESS_IDENTITY_UNAVAILABLE")
    return identity


class RuntimeServiceController:
    def __init__(self, *, runtime_root: Path, service_name: str, port: int, readiness_timeout: float = 15):
        self.runtime_root = runtime_root.resolve()
        self.service_name = service_name
        self.port = port
        self.readiness_timeout = readiness_timeout
        self.service_path = self.runtime_root / "service.json"
        self.secret_path = self.runtime_root / "control.token"
        self.mcp_secret_path = self.runtime_root / "mcp.token"

    def _secret_at(self, path: Path) -> str:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        try:
            value = path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            value = secrets.token_hex(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(path, flags, 0o600)
            try:
                os.write(descriptor, (value + "\n").encode("ascii"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise PreconditionError("SERVICE_CONTROL_TOKEN_INVALID")
        return value

    def _secret(self) -> str:
        return self._secret_at(self.secret_path)

    def mcp_secret(self) -> str:
        return self._secret_at(self.mcp_secret_path)

    def _health(self) -> dict[str, Any] | None:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                payload = response.read(65536)
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PreconditionError("SERVICE_HEALTH_INVALID")
        if not isinstance(value, dict):
            raise PreconditionError("SERVICE_HEALTH_INVALID")
        return value

    @staticmethod
    def _receipt_identity(receipt: dict[str, Any]) -> ProcessIdentity | None:
        try:
            return ProcessIdentity(
                int(receipt["pid"]),
                str(receipt["executable"]),
                str(receipt["creation_marker"]),
                str(receipt["fingerprint"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _validate_running(self, receipt: dict[str, Any], health: dict[str, Any]) -> ProcessIdentity:
        expected = self._receipt_identity(receipt)
        if expected is None:
            raise PreconditionError("SERVICE_OWNERSHIP_RECEIPT_INCOMPLETE")
        actual = process_identity(expected.pid)
        if actual is None:
            raise PreconditionError("SERVICE_PROCESS_NOT_RUNNING")
        if actual != expected:
            raise PreconditionError("SERVICE_PROCESS_FINGERPRINT_MISMATCH")
        exact = {
            "service": self.service_name,
            "pid": expected.pid,
            "fingerprint": expected.fingerprint,
            "executable": expected.executable,
            "creation_marker": expected.creation_marker,
            "release_sha": str(receipt.get("release_sha") or ""),
            "manifest_sha256": str(receipt.get("manifest_sha256") or ""),
            "generation": int(receipt.get("generation") or 0),
            "instance_id": str(receipt.get("instance_id") or ""),
            "ready": True,
        }
        health_contract = int(receipt.get("health_contract") or 1)
        if health_contract >= 2:
            exact.update({
                "health_contract": health_contract,
                "mcp_ready": True,
                "mcp_endpoint": f"http://127.0.0.1:{self.port}/mcp",
            })
        for key, value in exact.items():
            if health.get(key) != value:
                raise PreconditionError("SERVICE_HEALTH_OWNERSHIP_MISMATCH:" + key)
        return actual

    def inspect(self) -> dict[str, Any]:
        receipt = read_json(self.service_path)
        health = self._health()
        if receipt is None:
            if health is not None:
                raise PreconditionError("SERVICE_ENDPOINT_NOT_OWNED")
            return {"service": self.service_name, "state": "STOPPED", "port": self.port}
        if health is None:
            identity = self._receipt_identity(receipt)
            actual = process_identity(identity.pid) if identity else None
            if actual is None:
                return {
                    "service": self.service_name,
                    "state": "STOPPED_STALE_RECEIPT",
                    "port": self.port,
                    "release_sha": receipt.get("release_sha"),
                    "generation": receipt.get("generation", 0),
                }
            if identity != actual:
                raise PreconditionError("SERVICE_PROCESS_FINGERPRINT_MISMATCH")
            raise PreconditionError("SERVICE_PROCESS_RUNNING_WITHOUT_HEALTH")
        self._validate_running(receipt, health)
        return {**receipt, "state": "RUNNING", "health": health}

    def _write_service(self, value: dict[str, Any]) -> None:
        atomic_json(self.service_path, value)

    def _wait_for_exit(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process_identity(pid) is None:
                return True
            time.sleep(0.1)
        return process_identity(pid) is None

    def stop(self) -> dict[str, Any]:
        state = self.inspect()
        if state["state"] != "RUNNING":
            return {**state, "already_stopped": True}
        receipt = read_json(self.service_path)
        assert receipt is not None
        health = state["health"]
        self._validate_running(receipt, health)
        token = self._secret()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/shutdown",
            data=b"{}",
            headers={"X-BCT-Control-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                response.read(4096)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UnknownEffectError("SERVICE_SHUTDOWN_RESPONSE_UNAVAILABLE") from exc
        pid = int(receipt["pid"])
        if not self._wait_for_exit(pid, 10):
            raise UnknownEffectError("SERVICE_SHUTDOWN_UNVERIFIED")
        child = _LIVE_CHILDREN.pop(pid, None)
        if child is not None:
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired as exc:
                raise UnknownEffectError("SERVICE_CHILD_HANDLE_NOT_REAPED") from exc
        if self._health() is not None:
            raise UnknownEffectError("SERVICE_ENDPOINT_REMAINS_AFTER_STOP")
        stopped = {
            **receipt,
            "state": "STOPPED",
            "stopped_at": time.time(),
            "pre_pid": pid,
            "pre_fingerprint": receipt["fingerprint"],
        }
        self._write_service(stopped)
        return {**stopped, "already_stopped": False}

    def start(self, release: dict[str, Any]) -> dict[str, Any]:
        state = self.inspect()
        if state["state"] == "RUNNING":
            if (
                state.get("release_sha") == release["source_head"]
                and state.get("manifest_sha256") == release["manifest_sha256"]
            ):
                return {**state, "already_running": True}
            raise PreconditionError("SERVICE_DIFFERENT_RELEASE_RUNNING")
        if state["state"] not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
            raise PreconditionError("SERVICE_STATE_NOT_STARTABLE")
        previous = read_json(self.service_path) or {}
        generation = int(previous.get("generation") or 0) + 1
        instance_id = secrets.token_hex(16)
        starting = {
            "service": self.service_name,
            "state": "STARTING",
            "release_sha": release["source_head"],
            "manifest_sha256": release["manifest_sha256"],
            "generation": generation,
            "instance_id": instance_id,
            "health_contract": 2,
            "port": self.port,
            "launch_intent_at": time.time(),
        }
        self._write_service(starting)
        token = self._secret()
        release_root = Path(release["release_path"]).resolve()
        source_path = release_root / "src"
        server_module = source_path / "bct" / "runtime_server.py"
        if not server_module.is_file() or server_module.is_symlink():
            self._write_service({**starting, "state": "FAILED_NOT_APPLIED", "failed_at": time.time()})
            raise ConfirmedFailure("SERVICE_RUNTIME_MODULE_MISSING", release_claims=True)
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(source_path)
        environment["BCT_CONTROL_TOKEN"] = token
        environment["BCT_MCP_TOKEN"] = self.mcp_secret()
        command = [
            sys.executable,
            "-m",
            "bct.runtime_server",
            "--runtime-root", str(self.runtime_root),
            "--service-name", self.service_name,
            "--release-sha", release["source_head"],
            "--manifest-sha256", release["manifest_sha256"],
            "--generation", str(generation),
            "--instance-id", instance_id,
            "--port", str(self.port),
        ]
        logs = self.runtime_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[bytes] | None = None
        try:
            with (logs / "service.stdout.log").open("ab") as stdout, (logs / "service.stderr.log").open("ab") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=str(release_root),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            _LIVE_CHILDREN[process.pid] = process
            identity = None
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and identity is None:
                identity = process_identity(process.pid)
                if identity is None:
                    time.sleep(0.05)
            if identity is None:
                raise RuntimeError("SERVICE_PROCESS_IDENTITY_UNAVAILABLE")
            process_started = {
                **starting,
                **identity.as_dict(),
                "state": "PROCESS_STARTED",
                "process_started_at": time.time(),
            }
            self._write_service(process_started)
            deadline = time.monotonic() + self.readiness_timeout
            health = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                health = self._health()
                if health is not None:
                    try:
                        self._validate_running(process_started, health)
                    except PreconditionError:
                        health = None
                    else:
                        break
                time.sleep(0.1)
            if health is None:
                raise RuntimeError("SERVICE_READINESS_TIMEOUT")
            stability_deadline = time.monotonic() + 0.5
            while time.monotonic() < stability_deadline:
                if process.poll() is not None:
                    health = None
                    break
                candidate = self._health()
                if candidate is None:
                    health = None
                    break
                try:
                    self._validate_running(process_started, candidate)
                except PreconditionError:
                    health = None
                    break
                health = candidate
                time.sleep(0.1)
            if health is None:
                raise RuntimeError("SERVICE_READINESS_NOT_STABLE")
            running = {
                **process_started,
                "state": "RUNNING",
                "ready_at": time.time(),
                "verified_at": time.time(),
                "health": {"status": health.get("status"), "ready": health.get("ready")},
            }
            self._write_service(running)
            return {**running, "already_running": False}
        except Exception as exc:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired as terminate_exc:
                    self._write_service({**starting, "state": "FAILED_UNVERIFIED", "failed_at": time.time()})
                    raise UnknownEffectError("SERVICE_FAILED_PROCESS_REMAINS") from terminate_exc
            if process is not None:
                process.wait(timeout=1)
                _LIVE_CHILDREN.pop(process.pid, None)
            if process is not None and process_identity(process.pid) is not None:
                self._write_service({**starting, "state": "FAILED_UNVERIFIED", "failed_at": time.time()})
                raise UnknownEffectError("SERVICE_FAILED_PROCESS_STATE_UNKNOWN") from exc
            self._write_service({**starting, "state": "FAILED_NOT_APPLIED", "failed_at": time.time()})
            raise ConfirmedFailure("SERVICE_START_NOT_APPLIED:" + str(exc), release_claims=True) from exc

    def restart(self, release: dict[str, Any]) -> dict[str, Any]:
        state = self.inspect()
        if state["state"] != "RUNNING":
            raise PreconditionError("SERVICE_NOT_RUNNING")
        pre_pid = int(state["pid"])
        pre_fingerprint = str(state["fingerprint"])
        self.stop()
        try:
            started = self.start(release)
        except ConfirmedFailure as exc:
            raise UnknownEffectError("SERVICE_RESTART_FAILED_AFTER_CONFIRMED_STOP") from exc
        if int(started["pid"]) == pre_pid or started["fingerprint"] == pre_fingerprint:
            raise UnknownEffectError("SERVICE_RESTART_IDENTITY_NOT_CHANGED")
        return {**started, "pre_pid": pre_pid, "pre_fingerprint": pre_fingerprint}
