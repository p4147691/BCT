"""BCT-owned fixed ComfyUI read-only operation, policy-fenced by the coordinator."""
from __future__ import annotations
from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, ConfirmedFailure, UnknownEffectError
from bct.features.comfy_bridge_contract import validate_read_request, verify_read_response

class ComfyCanvasReadFeature:
    capability = "comfy_canvas_read"
    def __init__(self, adapter=None):
        self.adapter = adapter
    def prepare(self, *, work, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"tab_id", "url", "session_id", "observed"}:
            raise PreconditionError("COMFY_READ_ARGUMENTS_INVALID")
        try:
            request = validate_read_request(**arguments)
        except (TypeError, ValueError) as exc:
            raise PreconditionError("COMFY_READ_TARGET_INVALID") from exc
        return FeatureRequest(self.capability, "comfy:127.0.0.1:8188", request, ("comfy:127.0.0.1:8188",), preconditions={"work_id":work.work_id})
    def execute(self, request):
        if self.adapter is None:
            raise ConfirmedFailure("COMFY_BRIDGE_NOT_CONFIGURED", release_claims=True)
        try:
            response = self.adapter.read_canvas({**request.arguments, "_operation_id":request.operation_id, "_work_id":request.preconditions["work_id"]})
            graph = verify_read_response(response, request=request.arguments)
        except UnknownEffectError:
            raise
        except (ValueError, TypeError, PermissionError) as exc:
            raise ConfirmedFailure("COMFY_READ_FAILED:" + str(exc), release_claims=True) from exc
        except (RuntimeError, OSError) as exc:
            raise UnknownEffectError("COMFY_REVERSE_RESULT_UNKNOWN_NO_RETRY") from exc
        try:
            graph = verify_read_response(response, request=request.arguments)
        except (ValueError, TypeError) as exc:
            raise ConfirmedFailure("COMFY_READ_INVALID_GRAPH:" + str(exc), release_claims=True) from exc
        return FeatureResult(Outcome.APPLIED, {"source":"live_canvas_memory","read_only":True}, output={"graph":graph})
