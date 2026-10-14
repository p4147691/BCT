from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, replace
from typing import Any

from bct.core.models import (ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
                             PreconditionError, UnknownEffectError, Work)


class VerificationFeature:
    """Bounded, fail-fast verification using existing feature contracts and claims."""

    capability = "verify"
    allowed = frozenset({"read", "test", "github_pr_status"})

    def __init__(self, features):
        self.features = features

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        steps = arguments.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise PreconditionError("VERIFY_STEPS_INVALID")
        prepared, resources, identifiers = [], set(), set()
        budget = 0.0
        for step in steps:
            if not isinstance(step, dict):
                raise PreconditionError("VERIFY_STEP_INVALID")
            identifier, capability = step.get("id"), step.get("capability")
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
                raise PreconditionError("VERIFY_STEP_ID_INVALID")
            if identifier in identifiers or capability not in self.allowed:
                raise PreconditionError("VERIFY_STEP_DUPLICATE_OR_UNSUPPORTED")
            if capability not in work.actions:
                raise PreconditionError("VERIFY_ACTION_OUTSIDE_USER_SCOPE")
            values = step.get("arguments")
            if not isinstance(values, dict):
                raise PreconditionError("VERIFY_ARGUMENTS_INVALID")
            if capability == "read" and values.get("operation", "file") != "batch":
                values = {"operation": "batch", "items": [{**values, "id": identifier}]}
            request = self.features[capability].prepare(work=work, arguments=values)
            cost = float(request.arguments.get("timeout_s", request.arguments.get("wait_seconds", 0)))
            if not math.isfinite(cost):
                raise PreconditionError("VERIFY_TIMEOUT_INVALID")
            budget += cost
            if budget > 600:
                raise PreconditionError("VERIFY_TIME_BUDGET_EXCEEDED")
            identifiers.add(identifier)
            resources.update(request.resources)
            prepared.append({"id": identifier, "request": asdict(request)})
        return FeatureRequest(self.capability, "verification", {"steps": prepared}, tuple(sorted(resources)))

    def execute_authorized(self, request: FeatureRequest, authorize) -> FeatureResult:
        started = time.monotonic()
        evidence = []
        for step in request.arguments["steps"]:
            child = FeatureRequest(**step["request"])
            child = replace(child, operation_id=request.operation_id)
            tick = time.monotonic()
            try:
                authorize(child.capability)
                result = self.features[child.capability].execute(child)
            except PreconditionError as exc:
                result = FeatureResult(Outcome.NOT_APPLIED, {"code": str(exc)})
            except ConfirmedFailure as exc:
                result = FeatureResult(Outcome.FAILED, {"code": str(exc)}, release_claims=exc.release_claims)
            except UnknownEffectError:
                result = FeatureResult(Outcome.UNKNOWN, {"code": "VERIFY_STEP_EFFECT_UNKNOWN"}, release_claims=False)
            except Exception as exc:
                result = FeatureResult(Outcome.UNKNOWN, {"code": "VERIFY_STEP_UNEXPECTED", "type": type(exc).__name__}, release_claims=False)
            evidence.append({"id": step["id"], "capability": child.capability,
                             "outcome": result.outcome.value, "evidence": result.evidence,
                             "elapsed_ms": round((time.monotonic() - tick) * 1000, 3)})
            passed = result.outcome is Outcome.APPLIED
            if child.capability == "test":
                passed = passed and result.evidence.get("status") == "PASS"
            if child.capability == "github_pr_status":
                passed = passed and result.evidence.get("checks_ready") is True
            if not passed:
                return FeatureResult(result.outcome if result.outcome is Outcome.UNKNOWN else Outcome.FAILED,
                                     {"status": "STOPPED", "steps": evidence, "stopped_at": step["id"]},
                                     release_claims=result.release_claims and result.outcome is not Outcome.UNKNOWN)
        return FeatureResult(Outcome.APPLIED, {"status": "PASS", "steps": evidence,
                             "elapsed_ms": round((time.monotonic() - started) * 1000, 3)})

    def execute(self, request: FeatureRequest) -> FeatureResult:
        raise RuntimeError("VERIFY_AUTHENTICATED_COORDINATOR_REQUIRED")
