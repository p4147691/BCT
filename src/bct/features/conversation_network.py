from __future__ import annotations

import re
from typing import Any

from bct.conversation_network import (
    ConversationNetworkError,
    patch_conversation_role_tags,
    resolve_project_id,
)
from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.core.store import Store


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NODE_LABEL = re.compile(r"N[1-9][0-9]*\Z", re.I)


class ConversationNetworkUpdateFeature:
    """Narrow AI mutation path for existing advisory conversation roles."""

    capability = "conversation_network_update"

    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def _tags(value: object, code: str) -> list[str]:
        if not isinstance(value, list) or len(value) > 24:
            raise PreconditionError(code)
        result: list[str] = []
        for item in value:
            tag = str(item or "").strip()
            if not tag or "\x00" in tag or len(tag) > 48:
                raise PreconditionError(code)
            if tag not in result:
                result.append(tag)
        return result

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {
            "operation", "project", "node_label", "add", "remove",
            "expected_role_tags_sha256",
        }
        if set(arguments) - allowed:
            raise PreconditionError("CONVERSATION_NETWORK_UPDATE_FIELD_NOT_ALLOWED")
        operation = str(arguments.get("operation") or "role-patch").strip().casefold()
        if operation != "role-patch":
            raise PreconditionError("CONVERSATION_NETWORK_UPDATE_OPERATION_INVALID")
        project_reference = str(arguments.get("project") or "").strip()
        node_label = str(arguments.get("node_label") or "").strip().upper()
        expected = str(arguments.get("expected_role_tags_sha256") or "").strip().lower()
        if not project_reference:
            raise PreconditionError("CONVERSATION_NETWORK_PROJECT_REQUIRED")
        if not _NODE_LABEL.fullmatch(node_label):
            raise PreconditionError("CONVERSATION_NETWORK_NODE_LABEL_INVALID")
        if not _SHA256.fullmatch(expected):
            raise PreconditionError("CONVERSATION_NETWORK_ROLE_TAGS_SHA256_INVALID")
        additions = self._tags(arguments.get("add", []), "CONVERSATION_NETWORK_ROLE_ADD_INVALID")
        removals = self._tags(arguments.get("remove", []), "CONVERSATION_NETWORK_ROLE_REMOVE_INVALID")
        if not additions and not removals:
            raise PreconditionError("CONVERSATION_NETWORK_ROLE_PATCH_EMPTY")
        if set(additions) & set(removals):
            raise PreconditionError("CONVERSATION_NETWORK_ROLE_PATCH_OVERLAP")
        try:
            project_id = resolve_project_id(self.store, project_reference=project_reference)
        except ConversationNetworkError as exc:
            raise PreconditionError(str(exc)) from exc
        return FeatureRequest(
            self.capability,
            f"conversation-network:{project_id}:{node_label}",
            {
                "operation": operation,
                "project_id": project_id,
                "node_label": node_label,
                "add": additions,
                "remove": removals,
                "expected_role_tags_sha256": expected,
            },
            (f"conversation-network-role:{project_id}:{node_label}",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        try:
            result = patch_conversation_role_tags(
                self.store,
                project_id=request.arguments["project_id"],
                node_label=request.arguments["node_label"],
                add=request.arguments["add"],
                remove=request.arguments["remove"],
                expected_role_tags_sha256=request.arguments["expected_role_tags_sha256"],
            )
        except ConversationNetworkError as exc:
            raise PreconditionError(str(exc)) from exc
        return FeatureResult(
            Outcome.APPLIED,
            {
                "operation": "role-patch",
                "project_id": result["project_id"],
                "node_label": result["node_label"],
                "changed": result["changed"],
                "role_tags_sha256": result["role_tags_sha256"],
            },
            output=result,
        )
