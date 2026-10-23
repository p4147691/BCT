"""Discoverable, bounded Chrome extension management on an existing CDP session.

The executable contains the only permitted DOM operations. There is no
arbitrary JavaScript or DevTools command passthrough. BCT Work/Operation
ownership and exact source SHA are required for every mutation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
    PreconditionError, Work,
)


class BrowserExtensionManageFeature:
    capability = "browser_extension_manage"
    _READ_ONLY = {"inventory": "list_extensions", "pages": "list_pages"}
    _SCRIPTS = frozenset({"list", "read", "create", "update", "remove"})
    _EXTENSION_ID = "dhdgffkkebhmkfjojejmpbldmpobfkfo"

    def __init__(self, manager, *, policy_path=None, data_root=None):
        self.manager = manager
        self.policy_path = Path(policy_path) if policy_path else None
        self.data_root = Path(data_root) if data_root else (
            self.policy_path.parent if self.policy_path else None
        )
        self.script = Path(__file__).resolve().parents[3] / "scripts" / "browser_extension_manage.cjs"

    def _settings(self):
        if self.policy_path is None:
            return None
        try:
            data = tomllib.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PreconditionError("EXTENSION_MANAGER_POLICY_UNREADABLE") from exc
        opts = data.get("browser_extension_manage", {})
        if not isinstance(opts, dict) or not isinstance(opts.get("enabled", False), bool):
            raise PreconditionError("EXTENSION_MANAGER_POLICY_INVALID")
        if not opts.get("enabled", False):
            return None
        for key in ("profile_root", "puppeteer_module", "node_executable"):
            value = opts.get(key)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise PreconditionError("EXTENSION_MANAGER_PATH_REQUIRED:" + key)
        return opts

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if not isinstance(arguments, dict):
            raise PreconditionError("BROWSER_EXTENSION_ARGUMENTS_INVALID")
        operation = arguments.get("operation")
        if operation in self._READ_ONLY and set(arguments) == {"operation"}:
            return FeatureRequest(
                self.capability, "cdp:authorized-existing-chrome",
                {"operation": operation}, ("cdp:authorized-existing-chrome",),
            )
        if operation not in self._SCRIPTS:
            raise PreconditionError("BROWSER_EXTENSION_OPERATION_NOT_SUPPORTED")
        settings = self._settings()
        if settings is None:
            raise PreconditionError("EXTENSION_MANAGER_NOT_ENABLED")
        if arguments.get("extension_id") != self._EXTENSION_ID:
            raise PreconditionError("EXTENSION_MANAGER_ID_NOT_ALLOWED")
        allowed = {"operation", "extension_id", "script_uuid", "expected_sha256",
                   "source", "expected_count", "confirm_remove"}
        if set(arguments) - allowed:
            raise PreconditionError("EXTENSION_MANAGER_UNKNOWN_ARGUMENTS")
        if operation == "list" and set(arguments) != {"operation", "extension_id"}:
            raise PreconditionError("EXTENSION_MANAGER_LIST_ARGUMENTS_INVALID")
        if operation == "read" and set(arguments) != {"operation", "extension_id", "script_uuid"}:
            raise PreconditionError("EXTENSION_MANAGER_READ_ARGUMENTS_INVALID")
        if operation == "create":
            if (set(arguments) != {"operation", "extension_id", "source", "expected_count"}
                    or not isinstance(arguments["expected_count"], int)
                    or isinstance(arguments["expected_count"], bool)
                    or arguments["expected_count"] < 0):
                raise PreconditionError("EXTENSION_MANAGER_CREATE_ARGUMENTS_INVALID")
        if operation in {"update", "remove"}:
            required = {"operation", "extension_id", "script_uuid", "expected_sha256"}
            if operation == "update":
                required.add("source")
            else:
                required.add("confirm_remove")
            if set(arguments) != required or (operation == "remove" and arguments["confirm_remove"] is not True):
                raise PreconditionError("EXTENSION_MANAGER_WRITE_ARGUMENTS_INVALID")
        if operation in {"read", "update", "remove"}:
            identifier = arguments.get("script_uuid")
            import re
            if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", identifier):
                raise PreconditionError("EXTENSION_MANAGER_UUID_INVALID")
        if operation in {"update", "remove"}:
            if (not isinstance(arguments["expected_sha256"], str)
                    or not __import__("re").fullmatch(r"[0-9a-f]{64}", arguments["expected_sha256"])):
                raise PreconditionError("EXTENSION_MANAGER_SOURCE_SHA_REQUIRED")
        if operation in {"create", "update"}:
            src = arguments.get("source")
            if not isinstance(src, str) or not src.startswith("// ==UserScript==") or not 75 <= len(src) <= 200000:
                raise PreconditionError("EXTENSION_MANAGER_SOURCE_INVALID")
        return FeatureRequest(
            self.capability,
            "chrome-extension:" + self._EXTENSION_ID,
            dict(arguments),
            ("cdp:authorized-existing-chrome", "chrome-extension:" + self._EXTENSION_ID),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        operation = request.arguments["operation"]
        if operation in self._READ_ONLY:
            try:
                response = self.manager.request("tools/call", {
                    "name": self._READ_ONLY[operation], "arguments": {},
                })
            except (OSError, ValueError, RuntimeError, PermissionError) as exc:
                raise ConfirmedFailure(
                    "BROWSER_EXTENSION_READ_FAILED:" + str(exc), release_claims=True
                ) from exc
            if response.get("isError"):
                raise ConfirmedFailure("BROWSER_EXTENSION_MCP_REPORTED_ERROR", release_claims=True)
            return FeatureResult(
                Outcome.APPLIED,
                {"operation": operation, "connection_generation": self.manager.generation},
                output={"result": response},
            )
        settings = self._settings()
        if settings is None:
            raise ConfirmedFailure("EXTENSION_MANAGER_NOT_ENABLED", release_claims=True)
        if not self.script.is_file():
            raise ConfirmedFailure("EXTENSION_MANAGER_ADAPTER_MISSING", release_claims=True)
        if not Path(settings["node_executable"]).is_file() or not Path(settings["puppeteer_module"]).is_dir():
            raise ConfirmedFailure("EXTENSION_MANAGER_DEPENDENCY_MISSING", release_claims=True)
        if not Path(settings["profile_root"]).is_dir():
            raise ConfirmedFailure("EXTENSION_MANAGER_PROFILE_NOT_FOUND", release_claims=True)
        payload = {
            **request.arguments,
            "profile_root": settings["profile_root"],
            "puppeteer_module": settings["puppeteer_module"],
            "backup_root": str(self.data_root / "browser_extension_backups"),
        }
        try:
            completed = subprocess.run(
                [settings["node_executable"], str(self.script)],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=90, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            # A write may have been submitted. BCT must persist UNKNOWN; never replay.
            raise RuntimeError("BROWSER_EXTENSION_RESULT_UNCERTAIN") from exc
        try:
            result = json.loads(completed.stdout.strip())
        except (ValueError, TypeError) as exc:
            raise RuntimeError("BROWSER_EXTENSION_RESULT_UNPARSEABLE") from exc
        if result.get("status") != "PASS":
            if result.get("effect_started"):
                raise RuntimeError("BROWSER_EXTENSION_EFFECT_UNCERTAIN:" + str(result.get("code"))[:160])
            raise ConfirmedFailure("BROWSER_EXTENSION_NO_EFFECT:" + str(result.get("code"))[:160],
                                   release_claims=True)
        clean = {key: value for key, value in result.items() if key != "source"}
        return FeatureResult(
            Outcome.APPLIED,
            {"operation": operation, "script_uuid": result.get("script_uuid"),
             "verified": result.get("verified", operation == "list")},
            output={"result": result},
        )
