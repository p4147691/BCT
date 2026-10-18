from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import time
from typing import Any

from .models import (
    AuthorizationError, ConfirmedFailure, DecisionKind, Feature, FeatureResult,
    OperationResult, OperationState, Outcome, PreconditionError, Principal,
    UnknownEffectError,
)
from .policy import Policy
from bct.trace_timing import trace_stage
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
            "result", "reconcile-send-to-created-tab", "reconcile-send",
            "result-of-create-and-send", "reconcile-create-and-send",
            "inspect-rename-receipt", "reconcile-rename-conversation",
            "reclassify-rename-claim", "quarantine-legacy-rename-claim",
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
            if rcc_command in {
                "inspect-rename-receipt", "reconcile-rename-conversation",
                "reclassify-rename-claim", "quarantine-legacy-rename-claim",
            }:
                if (original.state is not OperationState.FINISHED
                        or original.outcome is not Outcome.UNKNOWN
                        or not str(original.error or "").startswith("RCC_HOST_OUTCOME_UNVERIFIED:")):
                    raise PreconditionError("RCC_RENAME_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED")
                if rcc_command != "inspect-rename-receipt":
                    original_args = {
                        "command": "rename-conversation",
                        "instance_id": arguments.get("instance_id"),
                        "session_id": arguments.get("session_id"),
                        "tab_id": arguments.get("tab_id"),
                        "conversation_key": arguments.get("conversation_key"),
                        "title": arguments.get("title"),
                        "timeout_s": arguments.get("original_timeout_s", 30.0),
                    }
                    original_request = feature.prepare(work=work, arguments=original_args)
                    original_digest = hashlib.sha256(json.dumps({
                        "work_id": work_id, "capability": capability,
                        "target": original_request.target,
                        "arguments": original_request.arguments,
                        "preconditions": original_request.preconditions,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                    if self.store.get_operation_request_digest_for(
                        operation_id=relay_id, work_id=work_id,
                        principal_id=principal.principal_id) != original_digest:
                        raise PreconditionError("RCC_RENAME_ORIGINAL_REQUEST_DIGEST_MISMATCH")
            if original.state is not OperationState.FINISHED or not (
                (rcc_command in {"inspect-rename-receipt", "reconcile-rename-conversation", "reclassify-rename-claim", "quarantine-legacy-rename-claim"})
                or (rcc_command == "reconcile-send"
                    and original.outcome is Outcome.UNKNOWN
                    and str(original.error or "") in {
                        "RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH",
                        "RCC_TRANSPORT_UNKNOWN_AFTER_DISPATCH",
                    })
                or (rcc_command in {"result-of-create-and-send", "reconcile-create-and-send"}
                 and (original.evidence.get("command") == "create-and-send"
                      or str(original.error or "").startswith("RCC_COMPOSE_")))
                or (rcc_command not in {"result-of-create-and-send", "reconcile-create-and-send", "reconcile-send"}
                    and (original.evidence.get("command") == "send-to-created-tab"
                         or str(original.error or "").startswith(
                             "RCC_HOST_OUTCOME_UNVERIFIED:")))
            ):
                raise PreconditionError("RCC_RESULT_ORIGINAL_SEND_REQUIRED")
            if rcc_command == "reconcile-send":
                # Verify the IMMUTABLE original send request BEFORE any RCC I/O.
                # The caller cannot substitute another chat, text or timeout.
                original_request = feature.prepare(work=work, arguments={
                    "command": "send",
                    "instance_id": arguments.get("instance_id"),
                    "to": arguments.get("original_to"),
                    "text": arguments.get("original_text"),
                    "timeout_s": arguments.get("original_timeout_s"),
                })
                original_digest = hashlib.sha256(json.dumps({
                    "work_id": work_id, "capability": capability,
                    "target": original_request.target,
                    "arguments": original_request.arguments,
                    "preconditions": original_request.preconditions,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                if self.store.get_operation_request_digest_for(
                    operation_id=relay_id, work_id=work_id,
                    principal_id=principal.principal_id,
                ) != original_digest:
                    raise PreconditionError("RCC_GENERIC_SEND_ORIGINAL_DIGEST_MISMATCH")
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
        if capability == "relay_browser" and rcc_command == "history-read":
            # A read cannot attach to an arbitrary ChatGPT tab. The original
            # history-open receipt must belong to the same work, principal,
            # instance and exact conversation, and must have applied.
            open_id = str(arguments.get("open_operation_id") or "")
            if not open_id:
                raise PreconditionError("RCC_HISTORY_OPEN_OPERATION_REQUIRED")
            source = self.store.get_operation_for(
                operation_id=open_id, work_id=work_id,
                principal_id=principal.principal_id,
            )
            evidence = source.evidence
            if (source.state is not OperationState.FINISHED
                    or source.outcome is not Outcome.APPLIED
                    or evidence.get("command") != "history-open"
                    or evidence.get("open_operation_id") != open_id
                    or evidence.get("instance_id") != str(arguments.get("instance_id") or "")
                    or evidence.get("conversation_key") != str(arguments.get("conversation_key") or "").lower()
                    or evidence.get("tab_id") != arguments.get("tab_id")
                    or evidence.get("window_id") != arguments.get("window_id")
                    or evidence.get("session_id") != arguments.get("session_id")
                    or evidence.get("inactive") is not True
                    or evidence.get("no_message_sent") is not True):
                raise PreconditionError("RCC_HISTORY_OPEN_RECEIPT_MISMATCH")
        request = replace(
            feature.prepare(work=work, arguments=arguments),
            operation_id=operation_id,
        )
        if capability == "relay_browser" and rcc_command in {
            "reclassify-rename-claim", "quarantine-legacy-rename-claim",
        }:
            request = replace(request, preconditions={
                **request.preconditions, "original_request_digest": original_digest,
            })
        if capability == "verify":
            for step in request.arguments["steps"]:
                child_decision = self.policy.decide(
                    principal=principal, work=work,
                    action=step["request"]["capability"], approval_ref=approval_ref,
                )
                if child_decision.kind is not DecisionKind.ALLOW:
                    raise AuthorizationError(child_decision.reason_code)
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
               capability: str, arguments: dict[str, Any], approval_ref: str | None,
               background_job: dict[str, Any] | None = None):
        prepare_started = time.perf_counter_ns()
        try:
            feature, work, decision, request, digest = self._prepare(
                principal=principal, work_id=work_id, operation_id=operation_id,
                capability=capability, arguments=arguments, approval_ref=approval_ref,
            )
        finally:
            trace_stage("authorization_prepare", tool_kind=capability,
                        elapsed_ms=(time.perf_counter_ns() - prepare_started) / 1e6)
        claim_started = time.perf_counter_ns()
        try:
            created, current = self.store.begin_operation(
                operation_id=operation_id, work=work, principal_id=principal.principal_id,
                request_digest=digest, capability=capability, target=request.target,
                resources=request.resources, policy_revision=decision.policy_revision,
                background_job=background_job,
            )
        finally:
            trace_stage("claim_reservation", tool_kind=capability,
                        elapsed_ms=(time.perf_counter_ns() - claim_started) / 1e6)
        return feature, request, created, current

    def begin(self, *, principal: Principal, work_id: str, operation_id: str,
              capability: str, arguments: dict[str, Any],
              approval_ref: str | None = None,
              background_job: dict[str, Any] | None = None,
              ) -> tuple[bool, OperationResult]:
        """Durably fence an operation before an external one-shot worker starts."""
        _, _, created, current = self._begin(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=approval_ref,
            background_job=background_job,
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
        return self._execute(feature=feature, request=request, principal=principal,
                             work_id=work_id, approval_ref=approval_ref)

    def run(self, *, principal: Principal, work_id: str, operation_id: str,
            capability: str, arguments: dict[str, Any], approval_ref: str | None = None) -> OperationResult:
        feature, request, created, current = self._begin(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=approval_ref,
        )
        if not created:
            return current
        execute_started = time.perf_counter_ns()
        try:
            return self._execute(feature=feature, request=request, principal=principal,
                                 work_id=work_id, approval_ref=approval_ref)
        finally:
            trace_stage("execution_and_receipt", tool_kind=capability,
                        elapsed_ms=(time.perf_counter_ns() - execute_started) / 1e6)

    def _execute(self, *, feature: Feature, request, principal=None, work_id=None,
                 approval_ref=None) -> OperationResult:
        operation_id = request.operation_id
        feature_started = time.perf_counter_ns()
        try:
            if request.capability == "verify":
                initial_work = self.store.get_work(work_id)

                def authorize(action):
                    work = self.store.get_work(work_id)
                    if work.assignment_epoch != initial_work.assignment_epoch:
                        raise PreconditionError("VERIFY_OWNERSHIP_CHANGED")
                    decision = self.policy.decide(principal=principal, work=work,
                                                  action=action, approval_ref=approval_ref)
                    if decision.kind is not DecisionKind.ALLOW:
                        raise PreconditionError(decision.reason_code)

                result = feature.execute_authorized(request, authorize)
            elif request.capability == "orchestrate":
                initial_work = self.store.get_work(work_id)

                def authorize(_action="orchestrate"):
                    work = self.store.get_work(work_id)
                    if work.assignment_epoch != initial_work.assignment_epoch:
                        raise PreconditionError("ORCHESTRATION_OWNERSHIP_CHANGED")
                    decision = self.policy.decide(
                        principal=principal, work=work,
                        action="orchestrate", approval_ref=approval_ref,
                    )
                    if decision.kind is not DecisionKind.ALLOW:
                        raise PreconditionError(decision.reason_code)

                result = feature.execute_authorized(request, authorize)
            else:
                result = feature.execute(request)
            if not isinstance(result, FeatureResult):
                raise TypeError("FEATURE_RESULT_REQUIRED")
            trace_stage("feature_execution", tool_kind=request.capability,
                        elapsed_ms=(time.perf_counter_ns() - feature_started) / 1e6)
            receipt_started = time.perf_counter_ns()
            current = self.store.get_operation_for(
                operation_id=operation_id, work_id=work_id,
                principal_id=principal.principal_id,
            )
            if current.state is OperationState.FINISHED:
                # Some orchestration recovery paths atomically persist their
                # assignment/session evidence and both operation receipts in one
                # SQLite transaction.  Do not attempt a second finish across that
                # deliberately closed crash boundary.
                trace_stage("receipt_persistence", tool_kind=request.capability,
                            elapsed_ms=(time.perf_counter_ns() - receipt_started) / 1e6)
                return replace(current, output=result.output)
            if (request.capability == "relay_browser"
                    and request.arguments["command"] == "reclassify-rename-claim"
                    and result.outcome is Outcome.APPLIED):
                stored = self.store.finish_rename_claim_reclassification(
                    resolver_operation_id=operation_id,
                    original_operation_id=result.evidence["original_operation_id"],
                    expected_original_digest=result.evidence["expected_original_digest"],
                    expected_work_id=work_id,
                    instance_id=result.evidence["instance_id"],
                    new_resource_key=result.evidence["new_resource_key"],
                    evidence=result.evidence,
                )
            elif (request.capability == "relay_browser"
                    and request.arguments["command"] == "quarantine-legacy-rename-claim"
                    and result.outcome is Outcome.APPLIED):
                stored = self.store.finish_rename_claim_operator_quarantine(
                    resolver_operation_id=operation_id,
                    original_operation_id=result.evidence["original_operation_id"],
                    expected_original_digest=result.evidence["expected_original_digest"],
                    expected_work_id=work_id,
                    instance_id=result.evidence["instance_id"],
                    new_resource_key=result.evidence["new_resource_key"],
                    evidence=result.evidence,
                )
            else:
                stored = self.store.finish_operation(
                    operation_id=operation_id, outcome=result.outcome, evidence=result.evidence,
                    error=None, release_claims=result.release_claims,
                    reconciled_operation_ids=result.reconciled_operation_ids,
                )
            trace_stage("receipt_persistence", tool_kind=request.capability,
                        elapsed_ms=(time.perf_counter_ns() - receipt_started) / 1e6)
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
