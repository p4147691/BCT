from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.integrations.decision import DecisionClient


class DecisionModelFeature:
    capability = "decision_model"

    def __init__(self, policy_path: str | Path, client: DecisionClient | None = None):
        self.policy_path = Path(policy_path)
        self._client = client

    def _client_for_request(self) -> DecisionClient:
        if self._client is not None:
            return self._client
        data = tomllib.loads(self.policy_path.read_text(encoding="utf-8"))
        config = data.get("decision") or {}
        endpoint_file = str(config.get("endpoint_file") or "").strip()
        if not endpoint_file:
            raise PreconditionError("DECISION_ENDPOINT_NOT_CONFIGURED")
        return DecisionClient(endpoint_file, timeout_s=float(config.get("timeout_s") or 1.0))

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "status").strip().casefold()
        if operation not in {"status", "recommend"}:
            raise PreconditionError("DECISION_OPERATION_INVALID")
        normalized: dict[str, Any] = {"operation": operation}
        if operation == "recommend":
            structured_input = arguments.get("input")
            questions = arguments.get("questions")
            if not isinstance(structured_input, dict):
                raise PreconditionError("DECISION_INPUT_INVALID")
            if questions is not None and not isinstance(questions, dict):
                raise PreconditionError("DECISION_QUESTIONS_INVALID")
            normalized.update({"input": structured_input, "questions": questions})
        return FeatureRequest(
            self.capability, "decision:local", normalized, ("decision:local",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        client = self._client_for_request()
        try:
            if request.arguments["operation"] == "status":
                output = client.status()
            else:
                output = client.recommend(request.arguments["input"], request.arguments.get("questions"))
        except Exception as exc:
            return FeatureResult(
                Outcome.APPLIED,
                {"operation": request.arguments["operation"], "available": False, "error_type": type(exc).__name__},
                output={"available": False, "fallback": "deterministic", "error": str(exc)[:240]},
            )
        return FeatureResult(
            Outcome.APPLIED,
            {"operation": request.arguments["operation"], "available": True},
            output={"available": True, **output},
        )
