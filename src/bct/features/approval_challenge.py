"""Read-only preparation of an exact P2 human approval challenge.

This capability NEVER issues or signs approvals. It only serializes the
immutable prepared request for a separately operated approval issuer UI.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bct.core.approval import request_hash
from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work


class ApprovalChallengeFeature:
    capability = "approval_challenge"
    _ALLOWED = frozenset({"file_action_apply", "process_stop_apply"})

    def __init__(self, registered_features: dict):
        self.registered_features = registered_features

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        if set(arguments) != {"capability", "operation_id", "arguments"}:
            raise PreconditionError("APPROVAL_CHALLENGE_FIELDS_INVALID")
        effect = arguments["capability"]
        operation = arguments["operation_id"]
        if effect not in self._ALLOWED or effect not in work.actions:
            raise PreconditionError("APPROVAL_CHALLENGE_EFFECT_OUTSIDE_WORK")
        if not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", operation):
            raise PreconditionError("APPROVAL_CHALLENGE_OPERATION_INVALID")
        supplied = arguments["arguments"]
        if not isinstance(supplied, dict):
            raise PreconditionError("APPROVAL_CHALLENGE_ARGUMENTS_INVALID")
        feature = self.registered_features.get(effect)
        if feature is None:
            raise PreconditionError("APPROVAL_CHALLENGE_EFFECT_UNAVAILABLE")
        prepared = feature.prepare(work=work, arguments=supplied)
        digest = request_hash(work.work_id, effect, prepared.target,
                              prepared.arguments, prepared.preconditions)
        challenge = {
            "principal_id": work.owner_principal_id,
            "work_id": work.work_id, "operation_id": operation,
            "capability": effect, "target": prepared.target,
            "request_sha256": digest, "arguments": prepared.arguments,
            "preconditions": prepared.preconditions,
        }
        if len(json.dumps(challenge, ensure_ascii=False).encode("utf8")) > 8192:
            raise PreconditionError("APPROVAL_CHALLENGE_TOO_LARGE")
        return FeatureRequest(
            self.capability, f"challenge:{work.work_id}:{operation}",
            {"challenge": challenge}, (f"approval-challenge:{work.work_id.casefold()}",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        challenge = request.arguments["challenge"]
        return FeatureResult(Outcome.APPLIED, {
            "read_only": True,
            "approval_issued": False,
            "request_sha256": challenge["request_sha256"],
            "operation_id": challenge["operation_id"],
        }, output={"challenge": challenge})
