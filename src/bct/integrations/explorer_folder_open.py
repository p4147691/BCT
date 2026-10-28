"""Pure, fail-closed Explorer folder-open decision logic.

Execution remains with the authorized, work-scoped Desktop Control capabilities.
No direct OS launch, focus, lease or privilege effects are performed here.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ExplorerFolderError(ValueError):
    """The requested path or window evidence cannot be trusted."""


@dataclass(frozen=True)
class ExplorerDecision:
    action: str
    folder_path: str
    hwnd: str | None = None


def normalize_folder_path(folder_path: str) -> str:
    if not isinstance(folder_path, str) or not folder_path or "\x00" in folder_path or len(folder_path) > 1024:
        raise ExplorerFolderError("EXPLORER_FOLDER_PATH_INVALID")
    folder = Path(folder_path)
    if not folder.is_absolute():
        raise ExplorerFolderError("EXPLORER_FOLDER_PATH_INVALID")
    try:
        resolved = folder.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExplorerFolderError("EXPLORER_FOLDER_NOT_FOUND") from exc
    if not resolved.is_dir():
        raise ExplorerFolderError("EXPLORER_FOLDER_NOT_DIRECTORY")
    return str(resolved)


def select_exact_explorer(folder_path: str, inventory: dict[str, Any]) -> ExplorerDecision:
    """Pick one *Shell-proven* exact Explorer window; never trust title or PID.

    'open' means existing-window reuse is unavailable and the caller may request
    a separately authorized explorer.exe launch. Post-launch must call this
    function again; launched PID alone is never success evidence.
    """
    windows = inventory.get("windows")
    app = inventory.get("applicationWindows")
    if not isinstance(windows, dict) or not isinstance(app, dict):
        raise ExplorerFolderError("EXPLORER_INVENTORY_INVALID")
    if windows.get("truncated") or app.get("truncated") or windows.get("inspectionAvailable") is False:
        raise ExplorerFolderError("EXPLORER_INVENTORY_INCOMPLETE")
    if app.get("application") != "explorer" or str(app.get("folderPath", "")).casefold() != folder_path.casefold():
        raise ExplorerFolderError("EXPLORER_INVENTORY_FOLDER_MISMATCH")
    items = app.get("items")
    if not isinstance(items, list) or app.get("count") != len(items):
        raise ExplorerFolderError("EXPLORER_INVENTORY_INVALID")
    if len(items) > 1:
        raise ExplorerFolderError("EXPLORER_FOLDER_AMBIGUOUS")
    if not items:
        return ExplorerDecision("open", folder_path)
    window = items[0]
    if (not isinstance(window, dict) or window.get("className", "").casefold() not in
        ("cabinetwclass", "explorewclass") or str(window.get("processName", "")).casefold() != "explorer"
        or not str(window.get("hwnd", "")).isdigit()):
        raise ExplorerFolderError("EXPLORER_WINDOW_IDENTITY_INVALID")
    return ExplorerDecision("reuse", folder_path, str(window["hwnd"]))



def open_explorer_folder(folder_path: str, invoke, *, foreground: bool = True) -> dict[str, Any]:
    """Coordinate existing work-authorized desktop capabilities, not raw OS effects.

    invoke(capability, arguments) must enforce the BCT Work/Operation boundary
    and return the existing capability output. UNKNOWN effects must propagate,
    never be retried. Lease release is attempted even if activation fails.
    """
    path = normalize_folder_path(folder_path)
    def observe():
        return select_exact_explorer(path, invoke("desktop_application_target", {
            "operation": "list", "application": "explorer",
            "folder_path": path, "include_minimized": True}))
    decision = observe()
    if decision.action == "open":
        acquired = invoke("desktop_control_lease", {
            "operation": "acquire", "target_type": "session"})
        lease = acquired["control"]["lease"]["leaseId"]
        try:
            # Generic launch may report failure because Explorer handed off
            # its new window to a different PID. Never retry that effect.
            try:
                invoke("desktop_program_launch", {
                    "lease_id": lease, "executable": r"C:\Windows\explorer.exe",
                    "working_directory": r"C:\Windows",
                    "arguments": [path]})
            except Exception as exc:
                # UNKNOWN and authorization failures must not be reclassified as
                # success based on a later unrelated Explorer window.
                from bct.core.models import UnknownEffectError, AuthorizationError
                if isinstance(exc, (UnknownEffectError, AuthorizationError)):
                    raise
                decision = observe()
                if decision.action != "reuse":
                    raise
        finally:
            invoke("desktop_control_lease", {"operation": "release", "lease_id": lease})
        decision = observe()
        if decision.action != "reuse":
            raise ExplorerFolderError("EXPLORER_WINDOW_NOT_CONFIRMED")
    if not foreground:
        return {"folder_path": path, "hwnd": decision.hwnd, "verified": True}
    bound = invoke("desktop_application_target", {
        "operation": "bind", "application": "explorer",
        "folder_path": path, "include_minimized": True})
    lease = bound["control"]["lease"]["leaseId"]
    try:
        if str(bound["applicationTarget"]["window"]["hwnd"]) != decision.hwnd:
            raise ExplorerFolderError("EXPLORER_WINDOW_CHANGED")
        if bound["applicationTarget"]["window"].get("isMinimized") is True:
            invoke("desktop_window_manage", {"lease_id": lease, "operation": "restore"})
        invoke("desktop_window_activate", {"lease_id": lease})
        return {"folder_path": path, "hwnd": decision.hwnd, "verified": True, "foreground": True}
    finally:
        invoke("desktop_control_lease", {"operation": "release", "lease_id": lease})
