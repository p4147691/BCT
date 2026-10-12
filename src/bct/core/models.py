from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class DecisionKind(StrEnum):
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENY = "DENY"


class OperationState(StrEnum):
    RECORDED = "RECORDED"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"


class Outcome(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Principal:
    principal_id: str
    auth_source: str
    capabilities: frozenset[str]


@dataclass(frozen=True)
class Work:
    work_id: str
    request_summary: str
    roots: tuple[str, ...]
    actions: frozenset[str]
    owner_principal_id: str
    assignment_epoch: int = 1
    state: str = "ACTIVE"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    reason_code: str
    next_action: str
    policy_revision: str


@dataclass(frozen=True)
class FeatureRequest:
    capability: str
    target: str
    arguments: dict[str, Any]
    resources: tuple[str, ...]
    preconditions: dict[str, Any] = field(default_factory=dict)
    operation_id: str = ""


@dataclass(frozen=True)
class FeatureResult:
    outcome: Outcome
    evidence: dict[str, Any]
    release_claims: bool = True
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    state: OperationState
    outcome: Outcome | None
    evidence: dict[str, Any]
    duplicate: bool = False
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        value["outcome"] = self.outcome.value if self.outcome else None
        if not self.output:
            value.pop("output", None)
        return value


class Feature(Protocol):
    capability: str

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest: ...

    def execute(self, request: FeatureRequest) -> FeatureResult: ...


class BCTError(RuntimeError):
    code = "BCT_ERROR"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.code)


class AuthorizationError(BCTError):
    code = "AUTHORIZATION_DENIED"


class ConflictError(BCTError):
    code = "RESOURCE_CONFLICT"


class PreconditionError(BCTError):
    code = "PRECONDITION_FAILED"


class UnknownEffectError(BCTError):
    code = "EFFECT_UNKNOWN"


class ConfirmedFailure(BCTError):
    code = "EXECUTION_FAILED"

    def __init__(self, message: str | None = None, *, release_claims: bool = False):
        super().__init__(message)
        self.release_claims = release_claims


def normalize_root(value: str) -> str:
    return str(Path(value).resolve())
