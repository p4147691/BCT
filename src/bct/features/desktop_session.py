from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome, PreconditionError,
    UnknownEffectError, Work,
)
from bct.integrations.desktop_session import (
    DesktopSessionClient, DesktopSessionEffectUnknown, DesktopSessionRequestFailed,
    DesktopSessionUnavailable,
)


def desktop_session_client(policy_path: str | Path, *, data_root: str | Path | None) -> DesktopSessionClient:
    policy_path = Path(policy_path)
    data = tomllib.loads(policy_path.read_text(encoding="utf-8"))
    config = data.get("desktop_session") or {}
    if not isinstance(config, dict):
        raise ValueError("DESKTOP_SESSION_SECTION_INVALID")
    fallback_data = Path(data_root).resolve() if data_root is not None else policy_path.parent / ".desktop-session-data"
    state_root = Path(str(config.get("state_root") or policy_path.parent / ".desktop-session-state"))
    evidence_root = Path(str(config.get("evidence_root") or fallback_data / "desktop-session" / "evidence"))
    if not state_root.is_absolute():
        state_root = policy_path.parent / state_root
    if not evidence_root.is_absolute():
        evidence_root = policy_path.parent / evidence_root
    return DesktopSessionClient(
        endpoint_path=state_root.resolve() / "endpoint.json",
        evidence_root=evidence_root.resolve(),
    )


def _session_evidence(result: dict[str, Any]) -> dict[str, Any]:
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    return {
        "operation": result.get("command"),
        "instance_id": result.get("instanceId"),
        "session": session,
        "monitors": result.get("monitors") if isinstance(result.get("monitors"), list) else [],
    }


class DesktopSessionStatusFeature:
    capability = "desktop_session_status"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if arguments:
            raise PreconditionError("DESKTOP_SESSION_STATUS_ARGUMENTS_INVALID")
        return FeatureRequest(
            self.capability, "interactive-session", {}, ("desktop-session:observe",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.status(request_id=request.operation_id)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            # Status is read-only: transport loss cannot leave an external mutation.
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        evidence = _session_evidence(result)
        return FeatureResult(Outcome.APPLIED, evidence, output=result)


class DesktopCaptureFeature:
    capability = "desktop_capture"

    def __init__(self, client: DesktopSessionClient):
        self.client = client

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {"target_type", "monitor_index", "hwnd", "max_width", "max_height"}
        unknown = set(arguments) - allowed
        if unknown:
            raise PreconditionError("DESKTOP_CAPTURE_FIELD_INVALID:" + ",".join(sorted(unknown)))
        target_type = str(arguments.get("target_type") or "virtual_screen").strip().casefold()
        if target_type not in {"virtual_screen", "monitor", "window"}:
            raise PreconditionError("DESKTOP_CAPTURE_TARGET_INVALID")
        monitor_index = arguments.get("monitor_index")
        hwnd = str(arguments.get("hwnd") or "").strip()
        if target_type == "monitor":
            try:
                monitor_index = int(monitor_index)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PreconditionError("DESKTOP_CAPTURE_MONITOR_INVALID") from exc
            if not 0 <= monitor_index <= 31:
                raise PreconditionError("DESKTOP_CAPTURE_MONITOR_INVALID")
        else:
            monitor_index = None
        if target_type == "window" and not re.fullmatch(r"[1-9][0-9]{0,18}", hwnd):
            raise PreconditionError("DESKTOP_CAPTURE_HWND_INVALID")
        if target_type != "window":
            hwnd = ""
        try:
            max_width = int(arguments.get("max_width") or 1600)
            max_height = int(arguments.get("max_height") or 1200)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreconditionError("DESKTOP_CAPTURE_SIZE_INVALID") from exc
        if not 320 <= max_width <= 3840 or not 200 <= max_height <= 2160:
            raise PreconditionError("DESKTOP_CAPTURE_SIZE_INVALID")
        normalized = {
            "target_type": target_type, "monitor_index": monitor_index,
            "hwnd": hwnd, "max_width": max_width, "max_height": max_height,
        }
        if target_type == "window":
            target_suffix = hwnd
        elif target_type == "monitor":
            target_suffix = str(monitor_index)
        else:
            target_suffix = "all"
        target = target_type + ":" + target_suffix
        return FeatureRequest(
            self.capability, target, normalized,
            ("desktop-session:observe", "desktop-capture:" + target.casefold()),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = self.client.capture(request_id=request.operation_id, **request.arguments)
        except DesktopSessionUnavailable as exc:
            raise PreconditionError(str(exc)) from exc
        except DesktopSessionEffectUnknown as exc:
            raise UnknownEffectError(str(exc)) from exc
        except DesktopSessionRequestFailed as exc:
            raise ConfirmedFailure(str(exc), release_claims=True) from exc
        capture = result["capture"]
        evidence = {
            **_session_evidence(result),
            "capture": capture,
        }
        return FeatureResult(Outcome.APPLIED, evidence, output=result)
