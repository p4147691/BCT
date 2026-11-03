"""Public, allowlisted actions for BCT-owned Chrome extensions.

This feature deliberately exposes neither extension IDs nor URLs, JavaScript,
DevTools methods, function names, or arbitrary command arguments.  It is a
small router over two existing, independently fenced reload contracts:

* Monitor: installed-identity check plus the bounded deployment observation
  tool, which verifies structure, reload ACK, manifest version and telemetry.
* RCC: the existing exact-instance BrowserFeature maintenance operation.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from bct.core.models import (
    ConfirmedFailure,
    FeatureRequest,
    FeatureResult,
    Outcome,
    PreconditionError,
    UnknownEffectError,
    Work,
)
from bct.operating_paths import extension_id_from_key


class OwnedExtensionActionFeature:
    """Invoke one fixed action on one BCT-owned extension target."""

    capability = "owned_extension_action"
    _MONITOR_ID = "kaigandfpieiogfbfaemoimenmipedck"
    _MONITOR_RESULT = re.compile(
        r"MONITOR_DEPLOYMENT_OBSERVED version=([^\s]+) token=([a-f0-9]{32}) runtime=verified"
    )

    def __init__(self, browser_feature, *, policy_path: str | Path):
        self.browser = browser_feature
        self.policy_path = Path(policy_path)
        self.monitor_dispatch_adapter = (
            Path(__file__).resolve().parents[3]
            / "scripts" / "owned_extension_monitor_reload.cjs"
        )

    def _monitor_root(self) -> Path:
        try:
            policy = tomllib.loads(self.policy_path.read_text(encoding="utf-8"))
            value = policy.get("monitor", {}).get("live_root")
        except (OSError, ValueError, AttributeError) as exc:
            raise PreconditionError("OWNED_EXTENSION_MONITOR_POLICY_INVALID") from exc
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise PreconditionError("OWNED_EXTENSION_MONITOR_ROOT_REQUIRED")
        return Path(value)

    def _verify_monitor_identity(self, root: Path) -> dict[str, str]:
        manifest_path = root / "extension" / "manifest.json"
        tool_path = root / "tools" / "Request-MonitorDeploymentCheck.ps1"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            extension_id = extension_id_from_key(str(manifest.get("key") or ""))
        except (OSError, ValueError, TypeError, PreconditionError) as exc:
            raise PreconditionError("OWNED_EXTENSION_MONITOR_IDENTITY_UNREADABLE") from exc
        if (
            extension_id != self._MONITOR_ID
            or manifest.get("name") != "BCT Window Monitor"
            or not tool_path.is_file()
        ):
            raise PreconditionError("OWNED_EXTENSION_MONITOR_IDENTITY_MISMATCH")
        return {
            "extension_id": extension_id,
            "version": str(manifest.get("version") or ""),
            "tool_path": str(tool_path),
        }

    def _chrome_connection_settings(self) -> dict[str, str]:
        try:
            section = tomllib.loads(
                self.policy_path.read_text(encoding="utf-8")
            ).get("browser_extension_manage", {})
        except (OSError, ValueError, AttributeError) as exc:
            raise PreconditionError("OWNED_EXTENSION_CHROME_POLICY_INVALID") from exc
        if not isinstance(section, dict) or section.get("enabled") is not True:
            raise PreconditionError("OWNED_EXTENSION_CHROME_CONNECTION_DISABLED")
        values = {}
        for key in ("profile_root", "puppeteer_module", "node_executable"):
            value = section.get(key)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise PreconditionError("OWNED_EXTENSION_CHROME_PATH_REQUIRED:" + key)
            values[key] = value
        return values

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if not isinstance(arguments, dict):
            raise PreconditionError("OWNED_EXTENSION_ARGUMENTS_INVALID")
        target = str(arguments.get("target") or "").strip().lower()
        action = str(arguments.get("action") or "").strip().lower()
        if action != "reload" or target not in {"monitor", "rcc"}:
            raise PreconditionError("OWNED_EXTENSION_ACTION_NOT_ALLOWED")
        expected = {"target", "action"} if target == "monitor" else {
            "target", "action", "instance_id"
        }
        if set(arguments) != expected:
            raise PreconditionError("OWNED_EXTENSION_ARGUMENTS_NOT_ALLOWED")

        if target == "monitor":
            identity = self._verify_monitor_identity(self._monitor_root())
            self._chrome_connection_settings()
            return FeatureRequest(
                self.capability,
                "chrome-extension:" + identity["extension_id"],
                {"target": target, "action": action, "version": identity["version"]},
                ("chrome-extension:" + identity["extension_id"],),
                {"mutating": True, "owned_extension": True},
            )

        internal = self.browser.prepare(work=work, arguments={
            "command": "reload-extension",
            "instance_id": arguments.get("instance_id"),
            "timeout_s": 10.0,
        })
        return FeatureRequest(
            self.capability,
            internal.target,
            {
                "target": target,
                "action": action,
                "instance_id": internal.arguments["instance_id"],
                "rcc_request": {
                    "target": internal.target,
                    "arguments": internal.arguments,
                    "resources": list(internal.resources),
                    "preconditions": internal.preconditions,
                },
            },
            internal.resources,
            {"mutating": True, "owned_extension": True},
        )

    def _reload_monitor(self, request: FeatureRequest) -> FeatureResult:
        identity = self._verify_monitor_identity(self._monitor_root())
        settings = self._chrome_connection_settings()
        if identity["version"] != request.arguments["version"]:
            raise ConfirmedFailure(
                "OWNED_EXTENSION_MONITOR_VERSION_CHANGED", release_claims=True
            )
        observation_command = [
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", identity["tool_path"],
            "-TimeoutSeconds", "25",
        ]
        token_path = self._monitor_root() / "extension" / ".reload-token"
        old_token = token_path.read_text(encoding="utf-8-sig").strip() if token_path.is_file() else ""
        try:
            observation = subprocess.Popen(
                observation_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ConfirmedFailure(
                "OWNED_EXTENSION_MONITOR_TOOL_UNAVAILABLE", release_claims=True
            ) from exc

        # The observation tool publishes the token only after its structure
        # gate passes.  Once the token changes, a future Monitor focus could
        # cause the effect even if this process loses its response, so every
        # subsequent uncertainty must remain UNKNOWN and must not be retried.
        published = False
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and observation.poll() is None:
            try:
                published = token_path.read_text(encoding="utf-8-sig").strip() != old_token
            except OSError:
                published = False
            if published:
                break
            time.sleep(0.1)
        if not published:
            stdout, stderr = observation.communicate(timeout=3)
            combined = (stdout + "\n" + stderr).strip()
            raise ConfirmedFailure(
                "OWNED_EXTENSION_MONITOR_OBSERVATION_NOT_PUBLISHED:" + combined[:120],
                release_claims=True,
            )

        if not self.monitor_dispatch_adapter.is_file():
            raise UnknownEffectError("OWNED_EXTENSION_MONITOR_DISPATCH_ADAPTER_MISSING")
        payload = json.dumps({
            "profile_root": settings["profile_root"],
            "puppeteer_module": settings["puppeteer_module"],
        })
        try:
            dispatch = subprocess.run(
                [settings["node_executable"], str(self.monitor_dispatch_adapter)],
                input=payload, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=15, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            dispatch_result = json.loads(dispatch.stdout.strip())
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            dispatch_result = {"status": "UNKNOWN"}
        # The adapter may lose its CDP context because the requested reload
        # destroys that page.  Do not infer success or failure from that local
        # response.  The exact token ACK + fresh runtime telemetry below are
        # the sole terminal proof.
        try:
            stdout, stderr = observation.communicate(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise UnknownEffectError("OWNED_EXTENSION_MONITOR_RELOAD_RESULT_UNKNOWN") from exc
        combined = (stdout + "\n" + stderr).strip()
        match = self._MONITOR_RESULT.search(combined)
        if observation.returncode == 0 and match and match.group(1) == identity["version"]:
            return FeatureResult(
                Outcome.APPLIED,
                {
                    "target": "monitor", "action": "reload",
                    "extension_id": identity["extension_id"],
                    "manifest_version": identity["version"],
                    "reload_ack": True, "runtime_telemetry_verified": True,
                    "dispatch_observation": str(dispatch_result.get("status") or "UNKNOWN"),
                },
                output={"target": "monitor", "action": "reload", "status": "APPLIED"},
            )
        raise UnknownEffectError("OWNED_EXTENSION_MONITOR_RELOAD_ACK_UNKNOWN")

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments["target"] == "monitor":
            return self._reload_monitor(request)
        stored = request.arguments["rcc_request"]
        internal = FeatureRequest(
            "browser",
            stored["target"],
            stored["arguments"],
            tuple(stored["resources"]),
            stored["preconditions"],
            request.operation_id,
        )
        result = self.browser.execute(internal)
        return replace(
            result,
            evidence={
                "target": "rcc", "action": "reload",
                "instance_id": request.arguments["instance_id"],
                "rcc": result.evidence,
            },
            output={
                "target": "rcc", "action": "reload",
                "status": result.outcome.value, "rcc": result.output,
            },
        )
