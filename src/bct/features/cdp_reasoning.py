"""Work-scoped request/status interface for deferred reasoning-level changes."""
from __future__ import annotations

import re

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.reasoning_control import LEVELS


_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_INSTANCE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_UUID = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")


class CDPReasoningFeature:
    capability = "cdp_reasoning"

    def __init__(self, recovery):
        self.recovery = recovery

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if not isinstance(arguments, dict):
            raise PreconditionError("CDP_REASONING_ARGUMENTS_REQUIRED")
        operation = arguments.get("operation")
        if operation == "status":
            if set(arguments) != {"operation", "request_id"} or not _ID.fullmatch(
                str(arguments.get("request_id") or "")
            ):
                raise PreconditionError("CDP_REASONING_STATUS_ARGUMENTS_INVALID")
            return FeatureRequest(
                self.capability, "reasoning-status:" + arguments["request_id"],
                dict(arguments), (), {"work_id": work.work_id},
            )
        if operation != "request" or set(arguments) != {
            "operation", "request_id", "instance_id", "conversation_uuid", "target_level",
        }:
            raise PreconditionError("CDP_REASONING_REQUEST_ARGUMENTS_INVALID")
        request_id = str(arguments.get("request_id") or "")
        instance_id = str(arguments.get("instance_id") or "")
        conversation = str(arguments.get("conversation_uuid") or "").lower()
        target = str(arguments.get("target_level") or "")
        if (not _ID.fullmatch(request_id) or not _INSTANCE.fullmatch(instance_id)
                or not _UUID.fullmatch(conversation) or target not in LEVELS):
            raise PreconditionError("CDP_REASONING_REQUEST_VALUE_INVALID")
        return FeatureRequest(
            self.capability, "chatgpt-reasoning:" + conversation,
            {**arguments, "conversation_uuid": conversation}, (),
            {"work_id": work.work_id},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        if values["operation"] == "status":
            row = self.recovery.get(values["request_id"])
            if row["work_id"] != request.preconditions["work_id"]:
                raise PreconditionError("CDP_REASONING_STATUS_WORK_MISMATCH")
        else:
            row = self.recovery.enqueue(
                request_id=values["request_id"],
                work_id=request.preconditions["work_id"],
                instance_id=values["instance_id"],
                conversation_key=values["conversation_uuid"],
                target_level=values["target_level"],
            )
        public = {
            key: row.get(key) for key in (
                "request_id", "instance_id", "conversation_key", "target_level",
                "state", "observed_before", "observed_after", "attempts", "error",
            )
        }
        return FeatureResult(
            Outcome.APPLIED,
            {"operation": values["operation"], "request_id": values["request_id"],
             "queue_state": row["state"]},
            output={"reasoning_change": public},
        )
