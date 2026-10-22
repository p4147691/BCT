"""Read-only CDP inspection, fenced by normal BCT Work/Operation policy."""
from __future__ import annotations

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome, PreconditionError, Work,
)


class CDPInspectFeature:
    capability = "cdp_inspect"

    def __init__(self, manager):
        self.manager = manager

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if arguments != {"operation": "list_pages"}:
            raise PreconditionError("CDP_INSPECT_ONLY_LIST_PAGES_SUPPORTED")
        return FeatureRequest(
            self.capability,
            "cdp:authorized-existing-chrome",
            {"operation": "list_pages"},
            ("cdp:authorized-existing-chrome",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            response = self.manager.request("tools/call", {
                "name": "list_pages", "arguments": {},
            })
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            # This capability cannot mutate the browser; no retained exclusive
            # claim is required for a failed read or a missed consent prompt.
            raise ConfirmedFailure(
                "CDP_INSPECT_READ_FAILED:" + str(exc), release_claims=True
            ) from exc
        if response.get("isError") is True:
            raise ConfirmedFailure(
                "CDP_INSPECT_TOOL_RETURNED_ERROR", release_claims=True)
        return FeatureResult(
            Outcome.APPLIED,
            {"operation": "list_pages", "connection_generation": self.manager.generation},
            output={"result": response},
        )
