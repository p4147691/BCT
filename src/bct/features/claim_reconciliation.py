from __future__ import annotations

import re
from bct.integrations.desktop_session import DesktopSessionClient, DesktopSessionUnavailable, DesktopSessionEffectUnknown, DesktopSessionRequestFailed

from bct.core.models import (
    FeatureRequest, FeatureResult, OperationState, Outcome, PreconditionError, Work,
)
from bct.core.store import Store


READ_ONLY_CAPABILITIES = frozenset({"read", "system_inspect", "github_pr_status"})


def _proven_no_effect(metadata: dict) -> tuple[bool, str]:
    capability = metadata["capability"]
    if capability in READ_ONLY_CAPABILITIES:
        return True, "CAPABILITY_IS_READ_ONLY_NO_EXTERNAL_MUTATION"
    evidence = metadata.get("evidence") or {}
    if (capability == "execute"
            and evidence == {"phase": "UNEXPECTED", "type": "FileNotFoundError"}
            and str(metadata.get("error") or "").startswith("[WinError 2]")):
        # subprocess.Popen did not return a process object. On Windows this
        # exact exception is raised before CreateProcess succeeds.
        return True, "EXECUTE_CREATEPROCESS_FILE_NOT_FOUND"
    return False, ""


class ReadOnlyClaimReconcileFeature:
    """Release one exact read-only UNKNOWN Claim without rewriting its receipt."""

    capability = "claim_reconcile"

    def __init__(self, store: Store, client: DesktopSessionClient | None = None):
        self.store = store
        self.client = client

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        original = str(arguments.get("original_operation_id") or "").strip()
        reason = str(arguments.get("reason") or "").strip()
        if not original or len(original) > 200:
            raise PreconditionError("CLAIM_RECONCILE_OPERATION_ID_INVALID")
        if not reason or len(reason) > 300:
            raise PreconditionError("CLAIM_RECONCILE_REASON_REQUIRED")
        mode = str(arguments.get("mode") or "no_effect").strip()
        if mode not in {"no_effect", "quarantine_uia_expand"}:
            raise PreconditionError("CLAIM_RECONCILE_MODE_INVALID")
        if mode == "no_effect":
            if set(arguments) - {"original_operation_id", "reason", "mode"}:
                raise PreconditionError("CLAIM_RECONCILE_FIELDS_INVALID")
            normalized = {"original_operation_id": original, "reason": reason}
        else:
            digest = str(arguments.get("expected_original_digest") or "").strip()
            ack = str(arguments.get("operator_acknowledgement") or "").strip()
            if set(arguments) - {"original_operation_id", "reason", "mode",
                                  "expected_original_digest", "operator_acknowledgement"}:
                raise PreconditionError("UIA_QUARANTINE_FIELDS_INVALID")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise PreconditionError("UIA_QUARANTINE_ORIGINAL_DIGEST_INVALID")
            if ack != "ACK_UNKNOWN_UIA_EXPAND_EFFECT_NO_REPLAY":
                raise PreconditionError("UIA_QUARANTINE_OPERATOR_ACK_REQUIRED")
            normalized = {"original_operation_id": original, "reason": reason,
                          "mode": mode, "expected_original_digest": digest,
                          "operator_acknowledgement": ack}
        return FeatureRequest(self.capability, mode + ":" + original, normalized,
                              ("claim-reconcile:" + original.casefold(),))

    def execute(self, request: FeatureRequest) -> FeatureResult:
        original_id = request.arguments["original_operation_id"]
        # Coordinator already checked work/principal ownership. Re-read the
        # immutable operation state here immediately before atomic reconciliation.
        metadata = self.store.get_operation_metadata_for(
            operation_id=original_id,
            work_id=request.preconditions["work_id"],
            principal_id=request.preconditions["principal_id"],
        )
        if request.arguments.get("mode") == "quarantine_uia_expand":
            if (self.client is None
                    or metadata["capability"] != "desktop_uia_element_action"
                    or metadata["target"] != "expand:desktop-uia"
                    or metadata["state"] != OperationState.FINISHED.value
                    or metadata["outcome"] != Outcome.UNKNOWN.value
                    or metadata["error"] !=
                       "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:DESKTOP_UIA_ACTION_CHANGED_FOREGROUND"
                    or metadata["request_digest"] != request.arguments["expected_original_digest"]):
                raise PreconditionError("UIA_QUARANTINE_ORIGINAL_FENCE_MISMATCH")
            try:
                observed = self.client.control(request_id=request.operation_id,
                                               command="control_status", arguments={})
            except (DesktopSessionUnavailable, DesktopSessionEffectUnknown,
                    DesktopSessionRequestFailed) as exc:
                raise PreconditionError("UIA_QUARANTINE_AGENT_STATUS_UNAVAILABLE") from exc
            control = observed.get("control")
            session = observed.get("session")
            if (not isinstance(control, dict) or not isinstance(session, dict)
                    or control.get("lease") is not None
                    or not isinstance(control.get("emergencyStop"), dict)
                    or control["emergencyStop"].get("active") is not False
                    or session.get("inputDesktopAvailable") is not True
                    or not isinstance(observed.get("instanceId"), str)
                    or not observed["instanceId"]
                    or not isinstance(control.get("observedAtUtc"), str)
                    or not control["observedAtUtc"]):
                raise PreconditionError("UIA_QUARANTINE_ACTIVE_LEASE_OR_UNVERIFIED_AGENT")
            new_key = "desktop-control:quarantined-uia-expand:" + original_id
            return FeatureResult(Outcome.APPLIED, {
                "operation": "quarantine_uia_expand",
                "audit_kind": "OPERATOR_QUARANTINE_NOT_RECONCILIATION",
                "original_operation_id": original_id,
                "expected_original_digest": request.arguments["expected_original_digest"],
                "new_resource_key": new_key,
                "original_outcome_preserved": "UNKNOWN",
                "lease_state": "NONE",
                "agent_instance_id": observed["instanceId"],
                "observed_at_utc": control["observedAtUtc"],
                "operator_acknowledgement": request.arguments["operator_acknowledgement"],
                "operator_justification": request.arguments["reason"],
            })
        proven, proof = _proven_no_effect(metadata)
        if (not proven or metadata["state"] != OperationState.FINISHED.value
                or metadata["outcome"] != Outcome.UNKNOWN.value):
            raise PreconditionError("CLAIM_RECONCILE_EXACT_NO_EFFECT_UNKNOWN_REQUIRED")
        return FeatureResult(
            Outcome.APPLIED,
            {
                "operation": "reconcile-readonly-unknown",
                "original_operation_id": original_id,
                "original_capability": metadata["capability"],
                "proof": proof,
                "original_receipt_preserved": True,
                "reason": request.arguments["reason"],
            },
            reconciled_operation_ids=(original_id,),
        )
