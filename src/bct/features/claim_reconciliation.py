from __future__ import annotations

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

    def __init__(self, store: Store):
        self.store = store

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        original = str(arguments.get("original_operation_id") or "").strip()
        reason = str(arguments.get("reason") or "").strip()
        if not original or len(original) > 200:
            raise PreconditionError("CLAIM_RECONCILE_OPERATION_ID_INVALID")
        if not reason or len(reason) > 300:
            raise PreconditionError("CLAIM_RECONCILE_REASON_REQUIRED")
        return FeatureRequest(
            self.capability, "readonly:" + original,
            {"original_operation_id": original, "reason": reason},
            ("claim-reconcile:" + original.casefold(),),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        original_id = request.arguments["original_operation_id"]
        # Coordinator already checked work/principal ownership. Re-read the
        # immutable operation state here immediately before atomic reconciliation.
        metadata = self.store.get_operation_metadata_for(
            operation_id=original_id,
            work_id=request.preconditions["work_id"],
            principal_id=request.preconditions["principal_id"],
        )
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
