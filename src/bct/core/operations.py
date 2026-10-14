from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import (
    AuthorizationError, ConfirmedFailure, DecisionKind, Feature, FeatureResult,
    OperationResult, OperationState, Outcome, PreconditionError, Principal,
    UnknownEffectError,
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

    def _prepare(self, *, principal: Principal, work_id: str, operation_id: str,
                 capability: str, arguments: dict[str, Any], approval_ref: str | None):
        feature = self._features.get(capability)
        if feature is None:
            raise KeyError("FEATURE_NOT_REGISTERED:" + capability)
        work = self.store.get_work(work_id)
        decision = self.policy.decide(principal=principal, work=work, action=capability,
                                      approval_ref=approval_ref)
        if decision.kind is not DecisionKind.ALLOW:
            raise AuthorizationError(decision.reason_code + ":" + decision.next_action)
        rcc_command = str(arguments.get("command") or "").strip().lower()
        if capability == "relay_browser" and rcc_command in {
            "result", "reconcile-send-to-created-tab",
            "result-of-create-and-send", "reconcile-create-and-send",
        }:
            # The RCC result endpoint is scoped to an operation owned by this exact work.
            # It must never be a cross-work arbitrary relay receipt lookup.
            relay_id = str(arguments.get("relay_id") or "").strip()
            if not relay_id:
                raise PreconditionError("RCC_RESULT_OPERATION_ID_REQUIRED")
            original = self.store.get_operation_for(
                operation_id=relay_id, work_id=work_id, principal_id=principal.principal_id,
            )
            if self.store.get_operation_target_for(
                operation_id=relay_id, work_id=work_id, principal_id=principal.principal_id,
            ) != str(arguments.get("instance_id") or "").strip():
                raise PreconditionError("RCC_RESULT_INSTANCE_MISMATCH")
            if original.state is not OperationState.FINISHED or not (
                (rcc_command in {"result-of-create-and-send", "reconcile-create-and-send"}
                 and (original.evidence.get("command") == "create-and-send"
                      or str(original.error or "").startswith("RCC_COMPOSE_")))
                or (rcc_command not in {"result-of-create-and-send", "reconcile-create-and-send"}
                    and (original.evidence.get("command") == "send-to-created-tab"
                         or str(original.error or "").startswith(
                             "RCC_HOST_OUTCOME_UNVERIFIED:")))
            ):
                raise PreconditionError("RCC_RESULT_ORIGINAL_SEND_REQUIRED")
            if rcc_command == "reconcile-send-to-created-tab" and (
                original.outcome is not Outcome.UNKNOWN
                or str(original.error or "") != "RCC_HOST_OUTCOME_UNVERIFIED:SUBMIT_UNKNOWN"
            ):
                raise PreconditionError("RCC_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED")
            if rcc_command == "reconcile-create-and-send" and (
                original.outcome is not Outcome.UNKNOWN
                or not str(original.error or "").startswith("RCC_COMPOSE_")
            ):
                raise PreconditionError("RCC_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED")
        request = replace(
            feature.prepare(work=work, arguments=arguments),
            operation_id=operation_id,
        )
        if capability == "deploy" and request.arguments.get("operation") == "reconcile":
            original_id = request.arguments["original_operation_id"]
            original = self.store.get_operation_for(
                operation_id=original_id,
                work_id=work_id,
                principal_id=principal.principal_id,
            )
            if self.store.get_operation_target_for(
                operation_id=original_id,
                work_id=work_id,
                principal_id=principal.principal_id,
            ) != request.target:
                raise PreconditionError("DEPLOYMENT_RECONCILE_TARGET_MISMATCH")
            error_prefix = "DEPLOYMENT_ROLLBACK_UNVERIFIED:"
            original_error = str(original.error or "")
            receipt_matches = False
            if original_error.startswith(error_prefix):
                try:
                    receipt_matches = Path(original_error[len(error_prefix):]).samefile(
                        request.preconditions["reconciliation_receipt"]
                    )
                except OSError:
                    receipt_matches = False
            if (
                original.state is not OperationState.FINISHED
                or original.outcome is not Outcome.UNKNOWN
                or not receipt_matches
            ):
                raise PreconditionError("DEPLOYMENT_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED")
        if not request.resources:
            raise ValueError("FEATURE_RESOURCE_REQUIRED")
        digest = hashlib.sha256(json.dumps({
            "work_id": work_id,
            "capability": capability,
            "target": request.target,
            "arguments": request.arguments,
            "preconditions": request.preconditions,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return feature, work, decision, request, digest

    def _begin(self, *, principal: Principal, work_id: str, operation_id: str,
               capability: str, arguments: dict[str, Any], approval_ref: str | None):
        feature, work, decision, request, digest = self._prepare(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=approval_ref,
        )
        created, current = self.store.begin_operation(
            operation_id=operation_id, work=work, principal_id=principal.principal_id,
            request_digest=digest, capability=capability, target=request.target,
            resources=request.resources, policy_revision=decision.policy_revision,
        )
        return feature, request, created, current

    def begin(self, *, principal: Principal, work_id: str, operation_id: str,
              capability: str, arguments: dict[str, Any],
              approval_ref: str | None = None) -> tuple[bool, OperationResult]:
        """Durably fence an operation before an external one-shot worker starts."""
        _, _, created, current = self._begin(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=approval_ref,
        )
        return created, current

    def resume(self, *, principal: Principal, work_id: str, operation_id: str,
               capability: str, arguments: dict[str, Any],
               approval_ref: str | None = None) -> OperationResult:
        """Execute an exact operation already fenced by :meth:`begin`."""
        feature, request, created, current = self._begin(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=approval_ref,
        )
        if created:
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.NOT_APPLIED,
                evidence={"phase": "DISPATCH", "code": "BACKGROUND_OPERATION_NOT_PREPARED"},
                error="BACKGROUND_OPERATION_NOT_PREPARED", release_claims=True,
            )
        if current.state is OperationState.FINISHED:
            return current
        return self._execute(feature=feature, request=request)

    def run(self, *, principal: Principal, work_id: str, operation_id: str,
            capability: str, arguments: dict[str, Any], approval_ref: str | None = None) -> OperationResult:
        feature, request, created, current = self._begin(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=approval_ref,
        )
        if not created:
            return current
        return self._execute(feature=feature, request=request)

    def _execute(self, *, feature: Feature, request) -> OperationResult:
        operation_id = request.operation_id
        try:
            result = feature.execute(request)
            if not isinstance(result, FeatureResult):
                raise TypeError("FEATURE_RESULT_REQUIRED")
            stored = self.store.finish_operation(
                operation_id=operation_id, outcome=result.outcome, evidence=result.evidence,
                error=None, release_claims=result.release_claims,
                reconciled_operation_ids=result.reconciled_operation_ids,
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
