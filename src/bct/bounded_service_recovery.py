"""Adapter for the two existing Monitor Supervisor recovery contracts.

Only requests an existing scheduled task. Never creates tasks, changes their
definitions, stops processes, configures security or uses a caller URL/command.
"""
from __future__ import annotations
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from bct.core.models import ConfirmedFailure, PreconditionError, UnknownEffectError

TASKS = {"core": "BCT Core Supervisor", "mcp_tunnel": "BCT Tunnel Supervisor"}


class BoundedServiceRecovery:
    def _probe(self, url):
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(url, timeout=1.5) as response:
                return response.status == 200, response.read(65536).decode("utf-8")
        except (OSError, ValueError):
            return False, ""

    def ready(self, target):
        if target not in TASKS:
            raise PreconditionError("SERVICE_RECOVERY_TARGET_NOT_ALLOWED")
        if target == "core":
            ok, text = self._probe("http://127.0.0.1:18790/health")
            try:
                value = json.loads(text)
                return ok and value.get("service") == "bct-core" and value.get("ready") is True
            except (ValueError, AttributeError):
                return False
        try:
            file = Path.home() / ".local/state/tunnel-client/health/act-control.url"
            url = urlsplit(file.read_text(encoding="utf-8").strip())
            if (url.scheme != "http" or url.hostname != "127.0.0.1"
                    or url.username or url.password or not url.port):
                return False
            base = "http://127.0.0.1:" + str(url.port)
        except (OSError, ValueError):
            return False
        health, body = self._probe(base + "/healthz")
        ready, text = self._probe(base + "/readyz")
        return health and body.strip() == "live" and ready and text.strip() == "ready"

    def _dispatch(self, task):
        executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/schtasks.exe"
        if not executable.is_file():
            raise PreconditionError("SERVICE_RECOVERY_SCHTASKS_MISSING")
        try:
            result = subprocess.run([str(executable), "/Run", "/TN", task],
                capture_output=True, timeout=10, shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise ConfirmedFailure("SERVICE_RECOVERY_DISPATCH_UNAVAILABLE",
                                   release_claims=True) from exc
        except subprocess.TimeoutExpired as exc:
            raise UnknownEffectError("SERVICE_RECOVERY_DISPATCH_UNKNOWN") from exc
        if result.returncode != 0:
            raise ConfirmedFailure("SERVICE_RECOVERY_TASK_REJECTED", release_claims=True)

    def recover(self, target):
        if target not in TASKS:
            raise PreconditionError("SERVICE_RECOVERY_TARGET_NOT_ALLOWED")
        if os.name != "nt":
            raise PreconditionError("SERVICE_RECOVERY_WINDOWS_REQUIRED")
        task = TASKS[target]
        if self.ready(target):
            return {"target": target, "task": task, "already_ready": True,
                    "ready": True, "task_dispatched": False}
        self._dispatch(task)
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            if self.ready(target):
                return {"target": target, "task": task, "already_ready": False,
                        "ready": True, "task_dispatched": True}
            time.sleep(0.3)
        raise UnknownEffectError("SERVICE_RECOVERY_ACCEPTED_READY_UNVERIFIED")
