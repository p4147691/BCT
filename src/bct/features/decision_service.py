from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.decision_service import DecisionServiceController


class DecisionServiceFeature:
    capability = "decision_service"

    def __init__(self, policy_path: str | Path, controller: DecisionServiceController | None = None):
        self.policy_path = Path(policy_path)
        self._controller = controller

    def _controller_for_request(self) -> DecisionServiceController:
        if self._controller is not None:
            return self._controller
        data = tomllib.loads(self.policy_path.read_text(encoding="utf-8"))
        config = data.get("decision") or {}
        service = config.get("service") or {}
        paths = service.get("python_paths") or []
        if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
            raise PreconditionError("DECISION_PYTHONPATH_INVALID")
        return DecisionServiceController(
            state_root=Path(str(service.get("state_root") or r"D:\BCT\data")),
            endpoint_file=Path(str(config.get("endpoint_file") or r"D:\BCT\data\decision-endpoint.json")),
            model_path=Path(str(service.get("model_path") or "")),
            model_name=str(service.get("model_name") or ""),
            model_sha256=str(service.get("model_sha256") or ""),
            port=int(service.get("port") or 18771),
            python_path=str(service.get("python") or sys.executable),
            python_paths=paths,
            module=str(service.get("module") or "laya.serve"),
            readiness_timeout=float(service.get("readiness_timeout") or 45.0),
        )

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        action = str(arguments.get("action") or "status").strip().casefold()
        if action not in {"status", "start", "stop", "restart"}:
            raise PreconditionError("DECISION_SERVICE_ACTION_INVALID")
        return FeatureRequest(
            self.capability, "service:bct-decision", {"action": action},
            ("service:bct-decision",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        controller = self._controller_for_request()
        action = request.arguments["action"]
        if action == "status":
            output = controller.inspect()
        elif action == "start":
            output = controller.start()
        elif action == "stop":
            output = controller.stop()
        else:
            output = controller.restart()
        return FeatureResult(Outcome.APPLIED, {"action": action, "state": output.get("state")}, output=output)
