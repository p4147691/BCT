"""Authorized Explorer-folder orchestration under one durable BCT operation."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
    PreconditionError, UnknownEffectError, Work,
)
from bct.integrations.desktop_session import (
    DesktopSessionClient, DesktopSessionEffectUnknown,
    DesktopSessionRequestFailed, DesktopSessionUnavailable,
)
from bct.integrations.explorer_folder_open import (
    ExplorerFolderError, normalize_folder_path, select_exact_explorer,
)


class DesktopExplorerFolderOpenFeature:
    capability = "desktop_explorer_folder_open"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if set(arguments) - {"folder_path", "foreground"}:
            raise PreconditionError("EXPLORER_OPEN_FIELDS_INVALID")
        try:
            path = normalize_folder_path(arguments.get("folder_path"))
        except ExplorerFolderError as exc:
            raise PreconditionError(str(exc)) from exc
        foreground = arguments.get("foreground", True)
        if not isinstance(foreground, bool):
            raise PreconditionError("EXPLORER_OPEN_FOREGROUND_INVALID")
        return FeatureRequest(
            self.capability, "open:explorer:" + path.casefold(),
            {"folder_path": path, "foreground": foreground, "owner_id": work.work_id},
            ("desktop-control:interactive-session",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        path = request.arguments["folder_path"]
        owner = request.arguments["owner_id"]
        rid = request.operation_id
        lease_id = None
        active_error = None

        def observe(suffix: str):
            raw = self.client.explorer_windows(
                request_id=rid + ":" + suffix, include_minimized=True,
                title_query="", folder_path=path, limit=256,
            )
            windows = raw["windows"]
            if windows.get("shellAvailable") is not True:
                raise ConfirmedFailure("EXPLORER_SHELL_UNAVAILABLE", release_claims=True)
            if windows.get("folderPath", "").casefold() != path.casefold():
                raise UnknownEffectError("EXPLORER_SHELL_FOLDER_MISMATCH")
            items = [item for item in windows["items"] if
                     str(item.get("processName", "")).casefold() == "explorer"
                     and str(item.get("className", "")).casefold() in
                     ("cabinetwclass", "explorewclass")]
            # Exact path is guaranteed by the Explorer Shell query on the agent.
            return select_exact_explorer(path, {
                "windows": windows,
                "applicationWindows": {
                    "application": "explorer", "folderPath": path, "items": items,
                    "count": len(items), "truncated": windows["truncated"],
                },
            })

        def observe_bounded_after_launch(suffix: str):
            # Shell registration can lag explorer.exe handoff even on a healthy
            # Windows desktop. Never re-run the launch effect: reconcile its
            # exact folder window with bounded read-only Shell observations.
            for number, delay in enumerate((0.0, 0.35, 0.55, 0.85)):
                if delay:
                    time.sleep(delay)
                decision = observe(f"{suffix}-{number}")
                if decision.action == "reuse":
                    return decision
            return decision

        def control(command, suffix, arguments=None):
            return self.client.control(
                request_id=rid + ":" + suffix, command=command,
                arguments=arguments or {},
            )

        try:
            decision = observe("before")
            if decision.action == "open":
                acquired = control("lease_acquire", "session-lease", {
                    "ownerId": owner, "ttlSeconds": 60, "targetType": "session",
                    "hwnd": "",
                })
                lease_id = acquired["control"]["lease"]["leaseId"]
                try:
                    self.client.launch(
                        request_id=rid + ":launch", owner_id=owner,
                        lease_id=lease_id, executable=r"C:\Windows\explorer.exe",
                        arguments=[path], working_directory=r"C:\Windows",
                        window_timeout_ms=5000,
                    )
                except DesktopSessionRequestFailed:
                    # Explorer may delegate creation to an existing PID. Verify
                    # exact Shell folder path; never retry the launch effect.
                    decision = observe_bounded_after_launch("after-launch-failure")
                    if decision.action != "reuse":
                        raise
                # UNKNOWN is deliberately not reclassified as successful.
                decision = observe_bounded_after_launch("after-launch")
                if decision.action != "reuse":
                    raise ConfirmedFailure("EXPLORER_WINDOW_NOT_CONFIRMED", release_claims=True)
                control("lease_release", "session-release", {
                    "ownerId": owner, "leaseId": lease_id,
                })
                lease_id = None
            if request.arguments["foreground"]:
                acquired = control("lease_acquire", "window-lease", {
                    "ownerId": owner, "ttlSeconds": 30, "targetType": "window",
                    "hwnd": decision.hwnd,
                })
                lease_id = acquired["control"]["lease"]["leaseId"]
                target = acquired["control"]["lease"].get("target", {})
                observed = observe("before-activate")
                if observed.action != "reuse" or observed.hwnd != decision.hwnd:
                    raise UnknownEffectError("EXPLORER_WINDOW_CHANGED")
                identity = next((item for item in self.client.explorer_windows(
                    request_id=rid + ":identity", include_minimized=True,
                    title_query="", folder_path=path, limit=256,
                )["windows"]["items"] if str(item.get("hwnd")) == decision.hwnd), None)
                if not isinstance(identity, dict) or any(
                    target.get(key) != identity.get(key) for key in (
                        "pid", "processStartTimeUtc", "sessionId", "virtualDesktopId",
                    )
                ):
                    raise UnknownEffectError("EXPLORER_WINDOW_FINGERPRINT_MISMATCH")
                if identity.get("minimized") is True:
                    self.client.manage(
                        request_id=rid + ":restore", owner_id=owner,
                        lease_id=lease_id, operation="restore",
                        x=None, y=None, width=None, height=None,
                    )
                self.client.activate(request_id=rid + ":activate",
                                     owner_id=owner, lease_id=lease_id)
            return FeatureResult(Outcome.APPLIED, {
                "folder_path": path, "hwnd": decision.hwnd,
                "verified": True, "foreground_requested": request.arguments["foreground"],
            }, output={"folder_path": path, "hwnd": decision.hwnd})
        except (DesktopSessionEffectUnknown, DesktopSessionUnavailable) as exc:
            active_error = UnknownEffectError(str(exc))
            raise active_error from exc
        except DesktopSessionRequestFailed as exc:
            active_error = ConfirmedFailure(str(exc), release_claims=True)
            raise active_error from exc
        except ExplorerFolderError as exc:
            active_error = ConfirmedFailure(str(exc), release_claims=True)
            raise active_error from exc
        finally:
            if lease_id is not None:
                try:
                    control("lease_release", "final-release", {
                        "ownerId": owner, "leaseId": lease_id,
                    })
                except (DesktopSessionEffectUnknown, DesktopSessionRequestFailed,
                        DesktopSessionUnavailable) as exc:
                    # Never hide an unresolved Lease: force UNKNOWN.
                    raise UnknownEffectError("EXPLORER_LEASE_RELEASE_UNVERIFIED") from exc
