from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from .models import (
    AuthorizationError, ConfirmedFailure, DecisionKind, Feature, FeatureResult,
    OperationResult, Outcome, PreconditionError, Principal, UnknownEffectError,
)
from .policy import Policy
from .store import Store


class OperationCoordinator:
    def __init__(self, *, store: Store, policy: Policy):
        self.store = store
        self.policy = policy
        self._features: dict[str, Feature] = {}

    def register(self, feature: Feature) -> None:
        if feature.capability in self._features:
            raise ValueError("FEATURE_ALREADY_REGISTERED:" + feature.capability)
        self._features[feature.capability] = feature

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._features))

    def run(self, *, principal: Principal, work_id: str, operation_id: str,
            capability: str, arguments: dict[str, Any], approval_ref: str | None = None) -> OperationResult:
        feature = self._features.get(capability)
        if feature is None:
            raise KeyError("FEATURE_NOT_REGISTERED:" + capability)
        work = self.store.get_work(work_id)
        decision = self.policy.decide(principal=principal, work=work, action=capability,
                                      approval_ref=approval_ref)
        if decision.kind is not DecisionKind.ALLOW:
            raise AuthorizationError(decision.reason_code + ":" + decision.next_action)
        request = replace(
            feature.prepare(work=work, arguments=arguments),
            operation_id=operation_id,
        )
        if not request.resources:
            raise ValueError("FEATURE_RESOURCE_REQUIRED")
        digest = hashlib.sha256(json.dumps({
            "work_id": work_id,
            "capability": capability,
            "target": request.target,
            "arguments": request.arguments,
            "preconditions": request.preconditions,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        created, current = self.store.begin_operation(
            operation_id=operation_id, work=work, principal_id=principal.principal_id,
            request_digest=digest, capability=capability, target=request.target,
            resources=request.resources, policy_revision=decision.policy_revision,
        )
        if not created:
            return current
        try:
            result = feature.execute(request)
            if not isinstance(result, FeatureResult):
                raise TypeError("FEATURE_RESULT_REQUIRED")
            stored = self.store.finish_operation(
                operation_id=operation_id, outcome=result.outcome, evidence=result.evidence,
                error=None, release_claims=result.release_claims,
            )
            return replace(stored, output=result.output)
        except PreconditionError as exc:
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.NOT_APPLIED,
                evidence={"phase": "PRECONDITION", "code": str(exc)}, error=str(exc),
                release_claims=True,
            )
        except ConfirmedFailure as exc:
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.FAILED,
                evidence={"phase": "EXECUTION", "code": str(exc)}, error=str(exc),
                release_claims=exc.release_claims,
            )
        except UnknownEffectError as exc:
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.UNKNOWN,
                evidence={"phase": "EXECUTION", "code": str(exc)}, error=str(exc),
                release_claims=False,
            )
        except Exception as exc:
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.UNKNOWN,
                evidence={"phase": "UNEXPECTED", "type": type(exc).__name__},
                error=str(exc), release_claims=False,
            )
