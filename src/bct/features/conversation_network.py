from __future__ import annotations

import re
from typing import Any

from bct.conversation_network import (
    ConversationNetworkError,
    assign_conversation_membership,
    patch_conversation_role_tags,
    resolve_project_id,
    upsert_project,
)
from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.core.store import Store


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NODE_LABEL = re.compile(r"N[1-9][0-9]*\Z", re.I)
_UUID = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z", re.I
)


class ConversationNetworkUpdateFeature:
    """Narrow AI mutation path for advisory scope membership and roles."""

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
        operation = str(arguments.get("operation") or "role-patch").strip().casefold()
        if operation == "project-upsert":
            return self._prepare_project_upsert(arguments)
        if operation == "role-patch":
            return self._prepare_role_patch(arguments)
        if operation == "membership-assign":
            return self._prepare_membership_assign(arguments)
        raise PreconditionError("CONVERSATION_NETWORK_UPDATE_OPERATION_INVALID")

    def _prepare_project_upsert(self, arguments: dict[str, Any]) -> FeatureRequest:
        if set(arguments) != {"operation", "project_id", "display_name"}:
            raise PreconditionError("CONVERSATION_NETWORK_UPDATE_FIELD_NOT_ALLOWED")
        project_id = str(arguments["project_id"] or "").strip()
        display_name = str(arguments["display_name"] or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", project_id):
            raise PreconditionError("CONVERSATION_NETWORK_PROJECT_ID_INVALID")
        if not display_name or len(display_name) > 120:
            raise PreconditionError("CONVERSATION_NETWORK_PROJECT_NAME_INVALID")
        return FeatureRequest(
            self.capability, "conversation-network:" + project_id,
            {"operation": "project-upsert", "project_id": project_id,
             "display_name": display_name},
            ("conversation-network-project:" + project_id,),
        )

    def _project_id(self, project_reference: str) -> str:
        if not project_reference:
            raise PreconditionError("CONVERSATION_NETWORK_PROJECT_REQUIRED")
        try:
            return resolve_project_id(self.store, project_reference=project_reference)
        except ConversationNetworkError as exc:
            raise PreconditionError(str(exc)) from exc

    def _prepare_role_patch(self, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {
            "operation", "project", "node_label", "add", "remove",
            "expected_role_tags_sha256",
        }
        if set(arguments) - allowed:
            raise PreconditionError("CONVERSATION_NETWORK_UPDATE_FIELD_NOT_ALLOWED")
        project_reference = str(arguments.get("project") or "").strip()
        node_label = str(arguments.get("node_label") or "").strip().upper()
        expected = str(arguments.get("expected_role_tags_sha256") or "").strip().lower()
        project_id = self._project_id(project_reference)
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
        return FeatureRequest(
            self.capability,
            f"conversation-network:{project_id}:{node_label}",
            {
                "operation": "role-patch",
                "project_id": project_id,
                "node_label": node_label,
                "add": additions,
                "remove": removals,
                "expected_role_tags_sha256": expected,
            },
            (f"conversation-network-role:{project_id}:{node_label}",),
        )

    def _prepare_membership_assign(self, arguments: dict[str, Any]) -> FeatureRequest:
        allowed = {
            "operation", "project", "conversation_key", "role_tags", "expected_scope_id",
        }
        if set(arguments) - allowed:
            raise PreconditionError("CONVERSATION_NETWORK_UPDATE_FIELD_NOT_ALLOWED")
        project_reference = str(arguments.get("project") or "").strip()
        conversation_key = str(arguments.get("conversation_key") or "").strip().lower()
        expected_scope_id = str(arguments.get("expected_scope_id") or "").strip()
        project_id = self._project_id(project_reference)
        if not _UUID.fullmatch(conversation_key):
            raise PreconditionError("CONVERSATION_NETWORK_CONVERSATION_KEY_INVALID")
        if expected_scope_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", expected_scope_id):
            raise PreconditionError("CONVERSATION_NETWORK_EXPECTED_SCOPE_INVALID")
        role_tags = self._tags(arguments.get("role_tags"), "CONVERSATION_NETWORK_ROLE_TAGS_INVALID")
        if not role_tags:
            raise PreconditionError("CONVERSATION_NETWORK_ROLE_TAGS_EMPTY")
        return FeatureRequest(
            self.capability,
            f"conversation-network:{project_id}:{conversation_key}",
            {
                "operation": "membership-assign",
                "project_id": project_id,
                "conversation_key": conversation_key,
                "role_tags": role_tags,
                "expected_scope_id": expected_scope_id,
            },
            (f"conversation-network-membership:{conversation_key}",),
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        operation = request.arguments["operation"]
        if operation == "project-upsert":
            try:
                result = upsert_project(
                    self.store, project_id=request.arguments["project_id"],
                    display_name=request.arguments["display_name"],
                )
            except ConversationNetworkError as exc:
                raise PreconditionError(str(exc)) from exc
            return FeatureResult(
                Outcome.APPLIED, {"operation": operation, **result}, output=result
            )
        if operation == "membership-assign":
            try:
                result = assign_conversation_membership(
                    self.store,
                    project_id=request.arguments["project_id"],
                    conversation_key=request.arguments["conversation_key"],
                    role_tags=request.arguments["role_tags"],
                    expected_scope_id=request.arguments["expected_scope_id"],
                )
            except ConversationNetworkError as exc:
                raise PreconditionError(str(exc)) from exc
            return FeatureResult(
                Outcome.APPLIED,
                {
                    "operation": operation,
                    "project_id": result["project_id"],
                    "node_label": result["node_label"],
                    "changed": result["changed"],
                    "role_tags_sha256": result["role_tags_sha256"],
                },
                output=result,
            )
        if operation != "role-patch":
            raise PreconditionError("CONVERSATION_NETWORK_UPDATE_OPERATION_INVALID")
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
