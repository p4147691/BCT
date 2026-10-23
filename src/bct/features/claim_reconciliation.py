from __future__ import annotations

from bct.core.models import (
    FeatureRequest, FeatureResult, OperationState, Outcome, PreconditionError, Work,
)
from bct.core.store import Store


READ_ONLY_CAPABILITIES = frozenset({"read", "system_inspect", "github_pr_status"})
# A finished UIA command can have an UNKNOWN *effect* while having no live
# exclusive desktop ownership. Reclaiming that reservation never replays UIA.
_RETIRED_UIA_ERROR = "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:DESKTOP_UIA_ACTION_CHANGED_FOREGROUND"
_DESKTOP_CLAIM = "desktop-control:interactive-session"


def desktop_control_is_idle(state: dict) -> bool:
    control = state.get("control") if isinstance(state, dict) else None
    emergency = control.get("emergencyStop") if isinstance(control, dict) else None
    return bool(isinstance(control, dict)
                and control.get("lease", "MISSING") is None
                and isinstance(emergency, dict)
                and emergency.get("active") is False)


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
    if (capability == "relay_control"
            and metadata.get("evidence") == {
                "phase": "UNEXPECTED", "type": "ConflictError"
            }
            and metadata.get("error") == "DELIVERY_ID_REUSE_MISMATCH"):
        # Legacy receipt from before delivery-start converted this immutable
        # ledger mismatch to ConfirmedFailure. DeliveryLedger.create_or_get
        # raises before RelayBrowserFeature invokes the RCC client.
        return True, "RELAY_DELIVERY_ID_REUSE_REJECTED_BEFORE_RCC_DISPATCH"
    if (capability == "relay_browser"
            and metadata.get("evidence") == {
                "phase": "UNEXPECTED", "type": "KeyError"
            }
            and metadata.get("error") == "'DELIVERY_NOT_FOUND'"):
        # Legacy receipt from before RelayBrowserFeature converted a missing
        # ledger row to ConfirmedFailure. The lookup failed before the RCC
        # client could be called, so no browser effect crossed the boundary.
        return True, "RELAY_DELIVERY_NOT_FOUND_BEFORE_RCC_DISPATCH"
    return False, ""


class ReadOnlyClaimReconcileFeature:
    """Release one exact read-only UNKNOWN Claim without rewriting its receipt."""

    capability = "claim_reconcile"

    def __init__(self, store: Store, desktop_client=None):
        self.store = store
        self.desktop_client = desktop_client

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
        if (metadata["capability"] == "desktop_uia_element_action"
                and metadata["state"] == OperationState.FINISHED.value
                and metadata["outcome"] == Outcome.UNKNOWN.value
                and metadata.get("error") == _RETIRED_UIA_ERROR
                and metadata.get("evidence") == {
                    "phase": "EXECUTION", "code": _RETIRED_UIA_ERROR
                }):
            # Live, read-only agent state: no lease, no emergency stop.
            # A missing/ambiguous session or an unavailable agent fails closed.
            if self.desktop_client is None:
                raise PreconditionError("DESKTOP_UIA_RECLAIM_AGENT_REQUIRED")
            try:
                state = self.desktop_client.control(
                    request_id=request.operation_id + ":retired-lease-proof",
                    command="control_status",
                )
            except Exception as exc:
                raise PreconditionError("DESKTOP_UIA_RECLAIM_AGENT_UNAVAILABLE") from exc
            if not desktop_control_is_idle(state):
                raise PreconditionError("DESKTOP_UIA_RECLAIM_CONTROL_NOT_IDLE")
            # The Store rechecks original identity, capability, error, and
            # the exact one unresolved claim *in the finish transaction*.
            proven, proof = True, "RETIRED_DESKTOP_CLAIM_ONLY_EFFECT_REMAINS_UNKNOWN"
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
