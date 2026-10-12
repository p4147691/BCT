from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psutil


_SENSITIVE_SWITCHES = {
    "--password", "--token", "--secret", "--authorization", "--api-key",
    "-password", "-token", "-secret", "-apikey",
}


def redact_argv(argv: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for raw in argv:
        value = str(raw)
        lower = value.casefold()
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            continue
        if lower in _SENSITIVE_SWITCHES:
            redacted.append(value)
            hide_next = True
            continue
        if any(lower.startswith(prefix + "=") for prefix in _SENSITIVE_SWITCHES):
            redacted.append(value.split("=", 1)[0] + "=<redacted>")
            continue
        redacted.append(value)
    return redacted


def process_fingerprint(pid: int) -> dict[str, Any]:
    process = psutil.Process(int(pid))
    return {
        "pid": process.pid,
        "parent_pid": process.ppid(),
        "created_at": process.create_time(),
        "executable": str(Path(process.exe()).resolve()),
        "name": process.name(),
    }


def process_matches(fingerprint: dict[str, Any]) -> bool:
    try:
        current = process_fingerprint(int(fingerprint["pid"]))
        return (
            abs(float(current["created_at"]) - float(fingerprint["created_at"])) < 0.001
            and os.path.normcase(current["executable"])
            == os.path.normcase(str(fingerprint["executable"]))
        )
    except (KeyError, TypeError, ValueError, psutil.Error, OSError):
        return False


def process_snapshot(pid: int) -> dict[str, Any]:
    process = psutil.Process(int(pid))
    result = process_fingerprint(pid)
    with process.oneshot():
        result.update({
            "status": process.status(),
            "username": process.username(),
            "cwd": _safe_call(process.cwd),
            "argv": redact_argv(_safe_call(process.cmdline) or []),
            "memory_rss": int(process.memory_info().rss),
        })
    return result


def list_processes(*, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "create_time", "cmdline"]):
        try:
            info = process.info
            argv = redact_argv([str(item) for item in (info.get("cmdline") or [])])
            searchable = " ".join([
                str(info.get("name") or ""), str(info.get("exe") or ""), *argv,
            ]).casefold()
            if needle and needle not in searchable:
                continue
            rows.append({
                "pid": int(info["pid"]),
                "parent_pid": int(info.get("ppid") or 0),
                "name": str(info.get("name") or ""),
                "executable": str(info.get("exe") or ""),
                "created_at": float(info.get("create_time") or 0.0),
                "argv": argv,
            })
        except (psutil.Error, OSError, ValueError):
            continue
        if len(rows) >= max(1, min(int(limit), 1000)):
            break
    return rows


def port_owners(port: int) -> list[dict[str, Any]]:
    wanted = int(port)
    if wanted < 1 or wanted > 65535:
        raise ValueError("PORT_OUT_OF_RANGE")
    pids: set[int] = set()
    for connection in psutil.net_connections(kind="inet"):
        if connection.laddr and int(connection.laddr.port) == wanted and connection.pid:
            pids.add(int(connection.pid))
    return [process_snapshot(pid) for pid in sorted(pids) if psutil.pid_exists(pid)]


def _safe_call(function):
    try:
        return function()
    except (psutil.Error, OSError):
        return None
