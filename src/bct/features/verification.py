from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import asdict, replace
from typing import Any

from bct.core.models import (ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
                             PreconditionError, UnknownEffectError, Work)
from bct.core.store import Store


class VerificationFeature:
    """Bounded, fail-fast verification using existing feature contracts and claims."""

    capability = "verify"
    allowed = frozenset({"read", "test", "github_pr_status"})

    recipes = frozenset({"local-python-validation", "pr-readiness"})

    def __init__(self, features, store: Store):
        self.features = features
        self.store = store

    @staticmethod
    def _local_python_validation(inputs: dict[str, Any]) -> list[dict[str, Any]]:
        allowed = {"paths", "cwd", "kind", "targets", "timeout_s"}
        if set(inputs) - allowed:
            raise PreconditionError("RECIPE_INPUT_UNKNOWN")
        paths = inputs.get("paths")
        if not isinstance(paths, list) or not 1 <= len(paths) <= 20 or not all(
            isinstance(path, str) and path for path in paths
        ):
            raise PreconditionError("RECIPE_PATHS_INVALID")
        return [
            {
                "id": "sources",
                "capability": "read",
                "arguments": {
                    "operation": "batch",
                    "items": [
                        {"id": f"source-{index:02d}", "path": path}
                        for index, path in enumerate(paths, 1)
                    ],
                },
            },
            {
                "id": "tests",
                "capability": "test",
                "arguments": {
                    "cwd": inputs.get("cwd"),
                    "kind": inputs.get("kind"),
                    "targets": inputs.get("targets"),
                    "timeout_s": inputs.get("timeout_s", 60),
                },
            },
        ]

    @staticmethod
    def _pr_readiness(inputs: dict[str, Any]) -> list[dict[str, Any]]:
        allowed = {"repository", "number", "expected_head", "required_checks", "wait_seconds"}
        if set(inputs) - allowed:
            raise PreconditionError("RECIPE_INPUT_UNKNOWN")
        return [{
            "id": "required-checks",
            "capability": "github_pr_status",
            "arguments": {
                "repository": inputs.get("repository"),
                "number": inputs.get("number"),
                "expected_head": inputs.get("expected_head"),
                "required_checks": inputs.get("required_checks"),
                "wait_seconds": inputs.get("wait_seconds", 0),
            },
        }]

    def _resolve_plan(self, arguments: dict[str, Any]) -> tuple[list[Any], dict[str, Any] | None]:
        recipe_id = arguments.get("recipe_id")
        if recipe_id is None:
            if set(arguments) != {"steps"}:
                raise PreconditionError("VERIFY_ARGUMENTS_INVALID")
            return arguments.get("steps"), None
        if set(arguments) != {"recipe_id", "recipe_version", "inputs"}:
            raise PreconditionError("RECIPE_ARGUMENTS_INVALID")
        if not isinstance(recipe_id, str) or recipe_id not in self.recipes:
            raise PreconditionError("RECIPE_ID_UNKNOWN")
        version = arguments.get("recipe_version")
        if type(version) is not int or version != 1:
            raise PreconditionError("RECIPE_VERSION_UNSUPPORTED")
        inputs = arguments.get("inputs")
        if not isinstance(inputs, dict):
            raise PreconditionError("RECIPE_INPUTS_INVALID")
        builders = {
            "local-python-validation": self._local_python_validation,
            "pr-readiness": self._pr_readiness,
        }
        return builders[recipe_id](inputs), {"id": recipe_id, "version": version}

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        steps, recipe = self._resolve_plan(arguments)
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
        normalized: dict[str, Any] = {"steps": prepared}
        target = "verification"
        if recipe is not None:
            plan_digest = hashlib.sha256(json.dumps(
                {"recipe": recipe, "steps": prepared},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            recipe = {**recipe, "plan_digest": plan_digest}
            normalized["recipe"] = recipe
            target = f"recipe:{recipe['id']}@{recipe['version']}"
        return FeatureRequest(self.capability, target, normalized, tuple(sorted(resources)))

    def execute_authorized(self, request: FeatureRequest, authorize) -> FeatureResult:
        started = time.monotonic()
        evidence = []
        descriptors = []
        for ordinal, step in enumerate(request.arguments["steps"]):
            encoded = json.dumps(step["request"], sort_keys=True, separators=(",", ":")).encode("utf-8")
            descriptors.append({
                "step_id": step["id"], "ordinal": ordinal,
                "capability": step["request"]["capability"],
                "request_digest": hashlib.sha256(encoded).hexdigest(),
            })
        self.store.initialize_operation_steps(
            operation_id=request.operation_id, steps=descriptors,
        )
        for ordinal, step in enumerate(request.arguments["steps"]):
            child = FeatureRequest(**step["request"])
            child = replace(child, operation_id=request.operation_id)
            tick = time.monotonic()
            self.store.start_operation_step(
                operation_id=request.operation_id, step_id=step["id"],
            )
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
                # These bounded verification children are read/test/status
                # observations. A generic implementation error is a failed
                # check, not proof of an uncertain external mutation.
                result = FeatureResult(
                    Outcome.FAILED,
                    {
                        "code": "VERIFY_STEP_CONTRACT_FAILURE",
                        "type": type(exc).__name__,
                        "unknown_requires_explicit_signal": True,
                    },
                    release_claims=True,
                )
            evidence.append({"id": step["id"], "capability": child.capability,
                             "outcome": result.outcome.value, "evidence": result.evidence,
                             "elapsed_ms": round((time.monotonic() - tick) * 1000, 3)})
            passed = result.outcome is Outcome.APPLIED
            if child.capability == "test":
                passed = passed and result.evidence.get("status") == "PASS"
            if child.capability == "github_pr_status":
                passed = passed and result.evidence.get("checks_ready") is True
            journal_outcome = result.outcome
            if result.outcome is Outcome.APPLIED and not passed:
                journal_outcome = Outcome.FAILED
            self.store.finish_operation_step(
                operation_id=request.operation_id, step_id=step["id"],
                outcome=journal_outcome, evidence=result.evidence,
            )
            if not passed:
                self.store.skip_pending_operation_steps(
                    operation_id=request.operation_id, after_ordinal=ordinal,
                    reason="PRIOR_STEP_NOT_APPLIED:" + step["id"],
                )
                stopped = {"status": "STOPPED", "steps": evidence, "stopped_at": step["id"]}
                if "recipe" in request.arguments:
                    stopped["recipe"] = request.arguments["recipe"]
                return FeatureResult(result.outcome if result.outcome is Outcome.UNKNOWN else Outcome.FAILED,
                                     stopped,
                                     release_claims=result.release_claims and result.outcome is not Outcome.UNKNOWN)
        completed = {"status": "PASS", "steps": evidence,
                     "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}
        if "recipe" in request.arguments:
            completed["recipe"] = request.arguments["recipe"]
        return FeatureResult(Outcome.APPLIED, completed)

    def execute(self, request: FeatureRequest) -> FeatureResult:
        raise RuntimeError("VERIFY_AUTHENTICATED_COORDINATOR_REQUIRED")
