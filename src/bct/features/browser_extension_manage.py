"""BCT-owned discoverable Chrome extension inventory capability.

The first milestone is deliberately read-only. The already accepted
Tampermonkey CDP CRUD adapter is not exposed as an uncontrolled generic
mutation API until the adapter is integrated and independently verified.
"""
from __future__ import annotations

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
    PreconditionError, Work,
)


class BrowserExtensionManageFeature:
    capability = "browser_extension_manage"
    _OPERATIONS = {
        "inventory": "list_extensions",
        "pages": "list_pages",
    }

    def __init__(self, manager):
        self.manager = manager

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if not isinstance(arguments, dict):
            raise PreconditionError("BROWSER_EXTENSION_ARGUMENTS_INVALID")
        operation = arguments.get("operation")
        if operation not in self._OPERATIONS or set(arguments) != {"operation"}:
            raise PreconditionError("BROWSER_EXTENSION_ONLY_READ_OPERATIONS_ENABLED")
        return FeatureRequest(
            capability=self.capability,
            target="cdp:authorized-existing-chrome",
            arguments={"operation": operation},
            resources=("cdp:authorized-existing-chrome",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        operation = request.arguments["operation"]
        try:
            response = self.manager.request("tools/call", {
                "name": self._OPERATIONS[operation], "arguments": {},
            })
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            raise ConfirmedFailure(
                "BROWSER_EXTENSION_READ_FAILED:" + str(exc),
                release_claims=True,
            ) from exc
        if response.get("isError"):
            raise ConfirmedFailure(
                "BROWSER_EXTENSION_MCP_REPORTED_ERROR", release_claims=True,
            )
        return FeatureResult(
            Outcome.APPLIED,
            {"operation": operation, "connection_generation": self.manager.generation},
            output={"result": response},
        )
