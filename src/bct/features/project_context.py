"""Small, explicit shared-context ledger for BCT projects and work streams."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.core.project_memory import (
    ProjectMemoryConflict, ProjectMemoryError, ProjectMemoryStore,
)


_WORK_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class ProjectContextFeature:
    """One central context plus compact journals keyed by project and Work.

    The storage implementation is the existing append-only Project Memory
    ledger.  This adapter makes its intended scopes explicit without copying
    browser transcripts or creating a second database/daemon.
    """

    capability = "project_context"

    def __init__(self, data_root: str | Path):
        root = Path(data_root) / "project-context"
        self.central = ProjectMemoryStore(root / "central")
        self.journal_root = root / "work-journals"

    @staticmethod
    def _project(value: object) -> str:
        project = str(value or "").strip().lower()
        # Delegate the complete path/device-name validation to ProjectMemory.
        if not project:
            raise PreconditionError("PROJECT_CONTEXT_PROJECT_REQUIRED")
        return project

    @staticmethod
    def _work_id(value: object) -> str:
        work_id = str(value or "").strip()
        if not _WORK_ID.fullmatch(work_id):
            raise PreconditionError("PROJECT_CONTEXT_WORK_ID_INVALID")
        return work_id

    def _journals(self, project: str) -> ProjectMemoryStore:
        digest = hashlib.sha256(project.encode("utf-8")).hexdigest()[:24]
        return ProjectMemoryStore(self.journal_root / digest)

    @staticmethod
    def _journal_key(work_id: str) -> str:
        return "w-" + hashlib.sha256(work_id.encode("utf-8")).hexdigest()[:61]

    @staticmethod
    def _record(arguments: dict[str, Any]) -> dict[str, Any]:
        record = arguments.get("record")
        if not isinstance(record, dict):
            raise PreconditionError("PROJECT_CONTEXT_RECORD_REQUIRED")
        return record

    @staticmethod
    def _author(arguments: dict[str, Any]) -> str:
        author = str(arguments.get("author") or "").strip()
        if not author or len(author) > 96:
            raise PreconditionError("PROJECT_CONTEXT_AUTHOR_INVALID")
        return author

    @staticmethod
    def _expected_revision(arguments: dict[str, Any]) -> int:
        value = arguments.get("expected_revision")
        if isinstance(value, bool):
            raise PreconditionError("PROJECT_CONTEXT_EXPECTED_REVISION_INVALID")
        try:
            revision = int(value)
        except (TypeError, ValueError) as exc:
            raise PreconditionError("PROJECT_CONTEXT_EXPECTED_REVISION_INVALID") from exc
        if revision < 0:
            raise PreconditionError("PROJECT_CONTEXT_EXPECTED_REVISION_INVALID")
        return revision

    @staticmethod
    def _journal_has_work(record: dict[str, Any], work_id: str) -> bool:
        return any(item == {"type": "bct_work", "id": work_id}
                   for item in record.get("links", []))

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "").strip().lower()
        allowed = {"operation", "project"}
        if operation in {"central-save", "worklog-save"}:
            allowed.update({"record", "author", "expected_revision"})
        if operation in {"worklog-get", "worklog-save"}:
            allowed.add("journal_work_id")
        if operation not in {"central-get", "central-save", "worklog-get", "worklog-save", "overview"}:
            raise PreconditionError("PROJECT_CONTEXT_OPERATION_INVALID")
        if set(arguments) - allowed:
            raise PreconditionError("PROJECT_CONTEXT_FIELD_NOT_ALLOWED")
        project = self._project(arguments.get("project"))
        values: dict[str, Any] = {"operation": operation, "project": project}
        if operation in {"central-save", "worklog-save"}:
            values.update({"record": self._record(arguments), "author": self._author(arguments),
                           "expected_revision": self._expected_revision(arguments)})
        if operation in {"worklog-get", "worklog-save"}:
            work_id = self._work_id(arguments.get("journal_work_id"))
            if operation == "worklog-save" and not self._journal_has_work(values["record"], work_id):
                raise PreconditionError("PROJECT_CONTEXT_WORK_LINK_REQUIRED")
            values["journal_work_id"] = work_id
        return FeatureRequest(self.capability, "project-context:" + project, values,
                              ("project-context:" + project,))

    @staticmethod
    def _public(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {key: row[key] for key in ("project_id", "revision", "sha256", "author", "created_at", "record")
                if key in row}

    def execute(self, request: FeatureRequest) -> FeatureResult:
        values = request.arguments
        operation, project = values["operation"], values["project"]
        try:
            if operation == "central-get":
                result = self.central.get(project)
            elif operation == "central-save":
                result = self.central.save(project, expected_revision=values["expected_revision"],
                                           author=values["author"], record=values["record"])
            elif operation == "worklog-get":
                result = self._journals(project).get(self._journal_key(values["journal_work_id"]))
            elif operation == "worklog-save":
                result = self._journals(project).save(
                    self._journal_key(values["journal_work_id"]),
                    expected_revision=values["expected_revision"], author=values["author"],
                    record=values["record"],
                )
            else:
                logs = []
                for key in self._journals(project).projects()[:200]:
                    row = self._journals(project).get(key)
                    if row is not None:
                        logs.append(self._public(row))
                result = {"central": self._public(self.central.get(project)), "worklogs": logs}
        except ProjectMemoryConflict as exc:
            raise PreconditionError("PROJECT_CONTEXT_STALE_REVISION") from exc
        except ProjectMemoryError as exc:
            raise PreconditionError(str(exc)) from exc
        return FeatureResult(Outcome.APPLIED, {"operation": operation, "project": project},
                             output=self._public(result) if isinstance(result, dict) and "record" in result else result)
