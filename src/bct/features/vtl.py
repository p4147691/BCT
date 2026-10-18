from __future__ import annotations

import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work

from .common import is_reparse_point, resolve_in_work, sha256_file


_REPOSITORY = "p4147691/VIRTUAL-TEST-LAB"
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_OUTPUT_CHARS = 65536


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise PreconditionError("VTL_JSON_TOO_LARGE:" + str(path))
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except PreconditionError:
        raise
    except Exception as exc:
        raise PreconditionError("VTL_JSON_INVALID:" + str(path)) from exc
    if not isinstance(value, dict):
        raise PreconditionError("VTL_JSON_OBJECT_REQUIRED:" + str(path))
    return value


def _bounded(value: str) -> tuple[str, bool]:
    return value[-_MAX_OUTPUT_CHARS:], len(value) > _MAX_OUTPUT_CHARS


def _decode_process_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not value:
        return ""

    # Machine-readable VTL results travel through UTF-8 JSON files. Captured
    # stdout/stderr are diagnostic only and may come from Windows PowerShell or
    # a native child using either the UTF-8 system locale or a legacy code page.
    # Decode losslessly when possible without making the host locale a runtime
    # prerequisite. UTF-32 must be checked before UTF-16 because their BOMs
    # share a prefix.
    bom_encodings = (
        (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    )
    for marker, encoding in bom_encodings:
        if value.startswith(marker):
            return value.decode(encoding, errors="replace")

    candidates = ["utf-8-sig"]
    if os.name == "nt":
        candidates.extend(("mbcs", "oem"))
    candidates.extend((locale.getpreferredencoding(False), "cp949"))
    attempted: set[str] = set()
    for encoding in candidates:
        normalized = encoding.casefold()
        if normalized in attempted:
            continue
        attempted.add(normalized)
        try:
            return value.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def _default_runner(argv: list[str], cwd: Path, timeout_s: float) -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    started = time.monotonic()
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=child_env,
            creationflags=creationflags,
        )
    except OSError as exc:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "not_started": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            process.kill()
        stdout, stderr = process.communicate(timeout=10)
    return {
        "returncode": process.returncode,
        "stdout": _decode_process_output(stdout),
        "stderr": _decode_process_output(stderr),
        "timed_out": timed_out,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


class VtlValidateFeature:
    capability = "vtl_validate"

    def __init__(
        self,
        policy_path: str | Path,
        *,
        data_root: str | Path | None = None,
        runner: Callable[[list[str], Path, float], dict[str, Any]] | None = None,
    ):
        data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
        section = data.get("vtl", {})
        if not isinstance(section, dict):
            raise ValueError("VTL_SECTION_INVALID")
        self.pointer_path = Path(
            str(section.get("current_pointer") or r"D:\TOOLS\VTL\current.json")
        ).resolve(strict=False)
        default_evidence = (
            Path(data_root).resolve(strict=False) / "vtl-evidence"
            if data_root is not None
            else Path(r"D:\BCT\data\vtl-evidence")
        )
        self.evidence_root = Path(
            str(section.get("evidence_root") or default_evidence)
        ).resolve(strict=False)
        if not self.pointer_path.is_absolute() or not self.evidence_root.is_absolute():
            raise ValueError("VTL_PATH_ABSOLUTE_REQUIRED")
        self._runner = runner or _default_runner

    def _runtime(self) -> dict[str, Any]:
        if not self.pointer_path.is_file() or is_reparse_point(self.pointer_path):
            raise PreconditionError("VTL_POINTER_UNAVAILABLE")
        pointer = _read_json(self.pointer_path)
        sha = str(pointer.get("source_sha") or "").lower()
        if (
            pointer.get("schema_version") != 1
            or pointer.get("source_repository") != _REPOSITORY
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
        ):
            raise PreconditionError("VTL_POINTER_IDENTITY_INVALID")
        try:
            release = Path(str(pointer.get("release_path") or "")).resolve(strict=True)
            expected_release_root = (self.pointer_path.parent / "releases").resolve(strict=True)
        except OSError as exc:
            raise PreconditionError("VTL_RELEASE_UNAVAILABLE") from exc
        if release.parent != expected_release_root or release.name.lower() != sha:
            raise PreconditionError("VTL_RELEASE_PATH_INVALID")
        if is_reparse_point(release):
            raise PreconditionError("VTL_RELEASE_REPARSE_FORBIDDEN")
        try:
            manifest_path = Path(str(pointer.get("manifest_path") or "")).resolve(strict=True)
        except OSError as exc:
            raise PreconditionError("VTL_MANIFEST_UNAVAILABLE") from exc
        if manifest_path != release / "release-manifest.json" or is_reparse_point(manifest_path):
            raise PreconditionError("VTL_MANIFEST_PATH_INVALID")
        manifest_sha = str(pointer.get("manifest_sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha) or sha256_file(manifest_path) != manifest_sha:
            raise PreconditionError("VTL_MANIFEST_HASH_MISMATCH")
        manifest = _read_json(manifest_path)
        files = manifest.get("files")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("source_repository") != _REPOSITORY
            or str(manifest.get("source_sha") or "").lower() != sha
            or not isinstance(files, dict)
            or not files
        ):
            raise PreconditionError("VTL_MANIFEST_IDENTITY_INVALID")
        required = {
            "vtl.ps1",
            "core/Invoke-VtlRun.ps1",
            "core/Test-VtlProfile.ps1",
            "drivers/browser-playwright/Invoke-VtlBrowserPlaywright.ps1",
        }
        if not required.issubset(files):
            raise PreconditionError("VTL_MANIFEST_ENTRY_MISSING")
        for relative, expected_hash in files.items():
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                raise PreconditionError("VTL_MANIFEST_FILE_INVALID")
            relative_path = Path(relative.replace("/", os.sep))
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise PreconditionError("VTL_MANIFEST_PATH_ESCAPE")
            target = (release / relative_path).resolve(strict=True)
            if not target.is_relative_to(release) or not target.is_file() or is_reparse_point(target):
                raise PreconditionError("VTL_RELEASE_FILE_INVALID:" + relative)
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) \
                    or sha256_file(target) != expected_hash.lower():
                raise PreconditionError("VTL_RELEASE_FILE_HASH_MISMATCH:" + relative)
        return {
            "sha": sha,
            "release": release,
            "manifest_sha256": manifest_sha,
            "file_count": len(files),
        }

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {"operation", "profile_path", "scenario_path", "mode", "timeout_s"}
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("VTL_VALIDATE_FIELD_INVALID:" + ",".join(sorted(unknown)))
        operation = str(arguments.get("operation") or "browser").strip().casefold()
        if operation not in {"browser", "profile"}:
            raise PreconditionError("VTL_VALIDATE_OPERATION_INVALID")
        scenario = resolve_in_work(work, str(arguments.get("scenario_path") or ""), must_exist=True)
        if not scenario.is_file() or scenario.suffix.casefold() != ".json":
            raise PreconditionError("VTL_SCENARIO_JSON_REQUIRED")
        _read_json(scenario)
        try:
            timeout_s = float(arguments.get("timeout_s", 300))
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("VTL_TIMEOUT_INVALID") from exc
        if not 5 <= timeout_s <= 3600:
            raise PreconditionError("VTL_TIMEOUT_INVALID")
        profile: Path | None = None
        mode = str(arguments.get("mode") or "Fast").strip().title()
        if operation == "browser":
            if arguments.get("profile_path"):
                raise PreconditionError("VTL_BROWSER_PROFILE_FORBIDDEN")
            if mode not in {"Fast", "Full"}:
                raise PreconditionError("VTL_MODE_INVALID")
        else:
            if arguments.get("mode") not in {None, "", "Fast", "fast"}:
                raise PreconditionError("VTL_PROFILE_MODE_UNSUPPORTED")
            mode = "Profile"
            profile = resolve_in_work(work, str(arguments.get("profile_path") or ""), must_exist=True)
            if not profile.is_file() or profile.suffix.casefold() != ".json":
                raise PreconditionError("VTL_PROFILE_JSON_REQUIRED")
            profile_value = _read_json(profile)
            source = resolve_in_work(work, str(profile_value.get("source_path") or ""), must_exist=True)
            if not source.is_dir():
                raise PreconditionError("VTL_PROFILE_SOURCE_DIRECTORY_REQUIRED")
        runtime = self._runtime()
        normalized = {
            "operation": operation,
            "scenario_path": str(scenario),
            "scenario_sha256": sha256_file(scenario),
            "profile_path": str(profile) if profile else "",
            "profile_sha256": sha256_file(profile) if profile else "",
            "mode": mode,
            "timeout_s": timeout_s,
            "vtl_sha": runtime["sha"],
            "vtl_manifest_sha256": runtime["manifest_sha256"],
            "vtl_release": str(runtime["release"]),
        }
        return FeatureRequest(
            self.capability,
            f"{operation}:{scenario}",
            normalized,
            (
                "vtl-runtime:" + str(runtime["release"]).casefold(),
                "vtl-scenario:" + str(scenario).casefold(),
            ),
            {
                "vtl_sha": runtime["sha"],
                "vtl_manifest_sha256": runtime["manifest_sha256"],
                "scenario_sha256": normalized["scenario_sha256"],
                "profile_sha256": normalized["profile_sha256"],
            },
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        runtime = self._runtime()
        if (
            runtime["sha"] != request.arguments["vtl_sha"]
            or runtime["manifest_sha256"] != request.arguments["vtl_manifest_sha256"]
            or str(runtime["release"]) != request.arguments["vtl_release"]
        ):
            raise PreconditionError("VTL_RUNTIME_CHANGED")
        scenario = Path(request.arguments["scenario_path"])
        profile_value = request.arguments["profile_path"]
        if sha256_file(scenario) != request.arguments["scenario_sha256"]:
            raise PreconditionError("VTL_SCENARIO_CHANGED")
        if profile_value and sha256_file(Path(profile_value)) != request.arguments["profile_sha256"]:
            raise PreconditionError("VTL_PROFILE_CHANGED")

        key = hashlib.sha256(request.operation_id.encode("utf-8")).hexdigest()
        run_root = self.evidence_root / key
        try:
            run_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise PreconditionError("VTL_EVIDENCE_ALREADY_EXISTS") from exc
        executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not executable:
            raise PreconditionError("POWERSHELL_NOT_FOUND")
        prefix = [executable, "-NoLogo", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass"]
        release = runtime["release"]
        if request.arguments["operation"] == "browser":
            result_path = run_root / "result.json"
            argv = [
                *prefix,
                "-File", str(release / "drivers" / "browser-playwright" / "Invoke-VtlBrowserPlaywright.ps1"),
                "-Scenario", str(scenario),
                "-Evidence", str(run_root),
                "-Mode", request.arguments["mode"],
            ]
        else:
            run_id = "bct-" + key[:24]
            result_path = run_root / run_id / "output" / "result.json"
            argv = [
                *prefix,
                "-File", str(release / "vtl.ps1"),
                "run",
                "-Profile", request.arguments["profile_path"],
                "-Scenario", str(scenario),
                "-EvidenceRoot", str(run_root),
                "-RunId", run_id,
                "-TimeoutSeconds", str(int(request.arguments["timeout_s"])),
            ]
        process = self._runner(argv, release, float(request.arguments["timeout_s"]) + 15)
        stdout, stdout_truncated = _bounded(str(process.get("stdout") or ""))
        stderr, stderr_truncated = _bounded(str(process.get("stderr") or ""))
        common_evidence = {
            "operation": request.arguments["operation"],
            "mode": request.arguments["mode"],
            "vtl_sha": runtime["sha"],
            "vtl_manifest_sha256": runtime["manifest_sha256"],
            "scenario_sha256": request.arguments["scenario_sha256"],
            "profile_sha256": request.arguments["profile_sha256"] or None,
            "evidence_root": str(run_root),
            "result_path": str(result_path),
            "returncode": process.get("returncode"),
            "duration_ms": int(process.get("duration_ms") or 0),
        }
        output = {
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
        if process.get("timed_out"):
            return FeatureResult(
                Outcome.APPLIED,
                {**common_evidence, "status": "TIMEOUT"},
                output=output,
            )
        if process.get("not_started"):
            return FeatureResult(
                Outcome.FAILED,
                {**common_evidence, "status": "INFRA_ERROR", "code": "VTL_PROCESS_NOT_STARTED"},
                output=output,
            )
        if not result_path.is_file():
            return FeatureResult(
                Outcome.FAILED,
                {**common_evidence, "status": "INFRA_ERROR", "code": "VTL_RESULT_MISSING"},
                output=output,
            )
        try:
            exact_result = result_path.resolve(strict=True)
            exact_run_root = run_root.resolve(strict=True)
        except OSError:
            exact_result = result_path
            exact_run_root = run_root
        if (
            not exact_result.is_relative_to(exact_run_root)
            or is_reparse_point(result_path)
        ):
            return FeatureResult(
                Outcome.FAILED,
                {**common_evidence, "status": "INFRA_ERROR", "code": "VTL_RESULT_PATH_INVALID"},
                output=output,
            )
        result = _read_json(result_path)
        status = str(result.get("status") or "").upper()
        if status not in {"PASS", "FAIL"}:
            return FeatureResult(
                Outcome.FAILED,
                {**common_evidence, "status": "INFRA_ERROR", "code": "VTL_RESULT_STATUS_INVALID"},
                output=output,
            )
        expected_code = 0 if status == "PASS" else 1
        if process.get("returncode") != expected_code:
            return FeatureResult(
                Outcome.FAILED,
                {**common_evidence, "status": "INFRA_ERROR", "code": "VTL_RESULT_EXIT_MISMATCH"},
                output=output,
            )
        actions = result.get("actions") if isinstance(result.get("actions"), list) else []
        result_summary = {
            key: result.get(key)
            for key in ("version", "status", "mode", "browser", "channel", "durationMs")
            if key in result
        }
        if actions:
            result_summary["action_count"] = len(actions)
            result_summary["failed_action_count"] = sum(
                1 for action in actions
                if isinstance(action, dict) and str(action.get("status") or "").upper() == "FAIL"
            )
        return FeatureResult(
            Outcome.APPLIED,
            {**common_evidence, "status": status},
            output={**output, "result_summary": result_summary},
        )
