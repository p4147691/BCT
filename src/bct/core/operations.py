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
        if capability == "relay_control":
            # Relay settings select an already-registered capability; they do
            # not create a new authority.  Identify the static registry target
            # without composing messages or preparing the child effect, then
            # authorize that existing capability first.
            delegated = str(feature.delegated_capability(arguments))
            if delegated not in self._features or delegated == capability:
                raise PreconditionError("RELAY_CONTROL_DELEGATED_CAPABILITY_INVALID")
        # A Chrome-tab reconcile is a read-only proof step for an already
        # authorized select in this exact work.  Historical work records cannot
        # gain a newly introduced action, so derive its scope from the original
        # select authority.  The exact original operation, owner, target,
        # outcome, and error are still checked below before any feature I/O.
        policy_action = (
            delegated
            if capability == "relay_control"
            else
            "desktop_chrome_tab_select"
            if capability == "desktop_chrome_tab_reconcile"
            else "desktop_window_activate"
            if capability == "desktop_window_activate_reconcile"
            else self.store.get_operation_metadata_for(
                operation_id=str(arguments.get("original_operation_id") or ""),
                work_id=work_id, principal_id=principal.principal_id,
            )["capability"]
            if capability == "claim_reconcile"
            else capability
        )
        decision = self.policy.decide(principal=principal, work=work, action=policy_action,
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
                      or str(original.error or "").startswith((
                          "RCC_COMPOSE_", "RCC_NEW_CHAT_"))))
                or (rcc_command == "result"
                    and original.outcome is Outcome.APPLIED
                    and original.evidence.get("command") == "send-to-tab")
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
                or not str(original.error or "").startswith((
                    "RCC_COMPOSE_", "RCC_NEW_CHAT_"))
            ):
                raise PreconditionError("RCC_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED")
        request = replace(
            feature.prepare(work=work, arguments=arguments),
            operation_id=operation_id,
        )
        if (capability == "relay_control"
                and request.preconditions.get("delegated_capability") != delegated):
            raise PreconditionError("RELAY_CONTROL_DELEGATED_CAPABILITY_CHANGED")
        if capability == "claim_reconcile":
            original = self.store.get_operation_metadata_for(
                operation_id=request.arguments["original_operation_id"],
                work_id=work_id, principal_id=principal.principal_id,
            )
            if original["capability"] not in {
                "read", "system_inspect", "github_pr_status", "execute",
                "desktop_uia_element_action",
            }:
                raise PreconditionError("CLAIM_RECONCILE_CAPABILITY_NOT_SUPPORTED")
            request = replace(request, preconditions={
                **request.preconditions,
                "work_id": work_id,
                "principal_id": principal.principal_id,
            })
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
        if capability == "desktop_chrome_tab_reconcile":
            original_id = request.arguments["original_operation_id"]
            original = self.store.get_operation_for(
                operation_id=original_id,
                work_id=work_id,
                principal_id=principal.principal_id,
            )
            original_target = self.store.get_operation_target_for(
                operation_id=original_id,
                work_id=work_id,
                principal_id=principal.principal_id,
            )
            if (
                original.state is not OperationState.FINISHED
                or original.outcome is not Outcome.UNKNOWN
                or original_target != "select:chrome-tab"
                or str(original.error or "")
                != "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:CHROME_TAB_ACTION_CHANGED_FOREGROUND"
            ):
                raise PreconditionError("DESKTOP_CHROME_TAB_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED")
        if capability == "desktop_window_activate_reconcile":
            original_id = request.arguments["original_operation_id"]
            original = self.store.get_operation_for(
                operation_id=original_id,
                work_id=work_id,
                principal_id=principal.principal_id,
            )
            original_target = self.store.get_operation_target_for(
                operation_id=original_id,
                work_id=work_id,
                principal_id=principal.principal_id,
            )
            activate_feature = self._features["desktop_window_activate"]
            original_request = activate_feature.prepare(work=work, arguments={
                "lease_id": request.arguments["original_lease_id"],
            })
            original_digest = hashlib.sha256(json.dumps({
                "work_id": work_id, "capability": "desktop_window_activate",
                "target": original_request.target,
                "arguments": original_request.arguments,
                "preconditions": original_request.preconditions,
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if (
                original.state is not OperationState.FINISHED
                or original.outcome is not Outcome.UNKNOWN
                or original_target != "activate:interactive-session"
                or str(original.error or "") not in {
                    "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:WINDOW_ACTIVATION_EFFECT_UNKNOWN",
                    "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:WINDOW_ACTIVATION_FRAME_CLICK_EFFECT_UNKNOWN",
                }
                or self.store.get_operation_request_digest_for(
                    operation_id=original_id, work_id=work_id,
                    principal_id=principal.principal_id,
                ) != original_digest
            ):
                raise PreconditionError(
                    "DESKTOP_WINDOW_ACTIVATE_RECONCILE_ORIGINAL_UNKNOWN_REQUIRED"
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
            retired_desktop_claim = None
            retired_rcc_claim = None
            if "desktop-control:interactive-session" in request.resources:
                # A terminal desktop UNKNOWN is an effect receipt, not an
                # indefinite execution lock. A live agent (not a monitor
                # projection) proves idle before atomic replacement.
                candidate = self.store.retired_desktop_claim_candidate()
                if candidate is not None:
                    desktop = self._features.get("desktop_control_lease")
                    client = getattr(desktop, "client", None)
                    if client is not None:
                        try:
                            from bct.features.claim_reconciliation import desktop_control_is_idle
                            control = client.control(
                                request_id=operation_id + ":desktop-idle-before-reservation",
                                command="control_status",
                            )
                        except Exception:
                            control = None
                        if desktop_control_is_idle(control):
                            retired_desktop_claim = (
                                candidate["operation_id"], candidate["work_id"],
                                candidate["assignment_epoch"],
                            )
            if (
                capability == "relay_browser"
                and request.arguments.get("command") == "create-and-send"
                and request.resources == ("rcc-instance:" + request.target,)
            ):
                # A historical UNKNOWN is immutable effect evidence, not a
                # permanent execution lease.  Before replacing the one legacy
                # RCC-wide reservation, ask the exact current RCC instance for
                # both identity and absence of any pending/result record.  No
                # send/create command is issued here.
                candidate = self.store.retired_rcc_claim_candidate(request.target)
                relay = getattr(feature, "client", None)
                if candidate is not None and relay is not None:
                    proof_prefix = "rcc-retire-" + hashlib.sha256(
                        operation_id.encode("utf-8")
                    ).hexdigest()[:24]
                    try:
                        state_reply = relay.request(
                            instance_id=request.target,
                            request_id=proof_prefix + "-state",
                            command="state",
                            timeout_s=2.0,
                        )
                        result_reply = relay.request(
                            instance_id=request.target,
                            request_id=proof_prefix + "-result",
                            command="result",
                            text=candidate["operation_id"],
                            timeout_s=2.0,
                        )
                    except Exception:
                        state_reply = result_reply = None
                    observed_state = (
                        state_reply.get("state")
                        if isinstance(state_reply, dict)
                        and isinstance(state_reply.get("state"), dict)
                        else {}
                    )
                    if (
                        isinstance(result_reply, dict)
                        and isinstance(state_reply, dict)
                        and state_reply.get("ok") is True
                        and observed_state.get("instanceId") == request.target
                        and bool(str(observed_state.get("sessionId") or ""))
                        and result_reply.get("ok") is True
                        and result_reply.get("relayId") == candidate["operation_id"]
                        and result_reply.get("found") is False
                        and result_reply.get("completed") is False
                        and result_reply.get("pending") is False
                        and result_reply.get("result") is None
                        and result_reply.get("pendingStatus") is None
                    ):
                        retired_rcc_claim = (
                            candidate["operation_id"], candidate["work_id"],
                            candidate["assignment_epoch"], request.target,
                        )
            created, current = self.store.begin_operation(
                operation_id=operation_id, work=work, principal_id=principal.principal_id,
                request_digest=digest, capability=capability, target=request.target,
                resources=request.resources, policy_revision=decision.policy_revision,
                background_job=background_job,
                retired_desktop_claim=retired_desktop_claim,
                retired_rcc_claim=retired_rcc_claim,
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
        self.store.record_effect_stage(operation_id=operation_id, stage="DISPATCH_INTENT")
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
            self.store.record_effect_stage(
                operation_id=operation_id, stage="EFFECT_RESULT_OBSERVED",
                detail={"outcome": result.outcome.value},
            )
            trace_stage("feature_execution", tool_kind=request.capability,
                        elapsed_ms=(time.perf_counter_ns() - feature_started) / 1e6)
            receipt_started = time.perf_counter_ns()
            self.store.record_effect_stage(operation_id=operation_id,
                                           stage="RECEIPT_PERSIST_INTENT")
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
            self.store.record_effect_stage(
                operation_id=operation_id, stage="EFFECT_REJECTED",
                detail={"error_code": str(exc).split(":", 1)[0]},
            )
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.NOT_APPLIED,
                evidence={"phase": "PRECONDITION", "code": str(exc)}, error=str(exc),
                release_claims=True,
            )
        except ConfirmedFailure as exc:
            self.store.record_effect_stage(
                operation_id=operation_id, stage="EFFECT_RESULT_OBSERVED",
                detail={"outcome": Outcome.FAILED.value,
                        "error_code": str(exc).split(":", 1)[0]},
            )
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.FAILED,
                evidence={"phase": "EXECUTION", "code": str(exc)}, error=str(exc),
                release_claims=exc.release_claims,
            )
        except UnknownEffectError as exc:
            self.store.record_effect_stage(
                operation_id=operation_id, stage="EFFECT_UNCERTAIN",
                detail={"error_code": str(exc).split(":", 1)[0]},
            )
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.UNKNOWN,
                evidence={"phase": "EXECUTION", "code": str(exc)}, error=str(exc),
                release_claims=exc.release_claims,
            )
        except Exception as exc:
            # A downstream failure may occur *after* an atomic feature or
            # receipt commit. Never overwrite its durable terminal outcome
            # with an inferred UNKNOWN: recover the exact original receipt.
            if principal is not None and work_id is not None:
                try:
                    persisted = self.store.get_operation_for(
                        operation_id=operation_id, work_id=work_id,
                        principal_id=principal.principal_id,
                    )
                except Exception:
                    persisted = None
                if persisted is not None and persisted.state is OperationState.FINISHED:
                    return persisted
            self.store.record_effect_stage(
                operation_id=operation_id, stage="EFFECT_UNCERTAIN",
                detail={"error_type": type(exc).__name__},
            )
            return self.store.finish_operation(
                operation_id=operation_id, outcome=Outcome.UNKNOWN,
                evidence={"phase": "UNEXPECTED", "type": type(exc).__name__},
                error=str(exc), release_claims=False,
            )
