"""Read-only fail-closed decision for a future BCT-owned desktop Agent.

Staging module only: it deliberately does not launch/kill processes, replace
VTL's Supervisor, publish an endpoint, or change LIVE. An executor must verify
the exact source, authority and lifecycle separately before using decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PureWindowsPath


class AgentDecision(str, Enum):
    READY = "READY"
    ABSENT = "ABSENT"
    HOLD = "HOLD"


@dataclass(frozen=True)
class AgentObservation:
    # The detector must distinguish genuine OS NoSuchProcess from access failures.
    kind: str  # PRESENT, ABSENT, UNKNOWN
    pid: int
    session_id: int | None = None
    executable: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class Decision:
    state: AgentDecision
    reason: str


def _same_executable(actual: str | None, expected: str) -> bool:
    if not actual or not expected:
        return False
    # Never compare only basenames. This must not follow symlinks or authorize
    # the executable on its own; caller must independently verify its identity.
    return str(PureWindowsPath(actual)).casefold() == str(PureWindowsPath(expected)).casefold()


def decide_agent_recovery(
    *,
    endpoint_pid: int,
    endpoint_session: int,
    current_session: int,
    observation: AgentObservation,
    expected_executable: str,
) -> Decision:
    """Classify a bounded read-only fact, not permission to start a process.

    ABSENT means the observed *exact endpoint PID* is confirmed nonexistent.
    Unknown inspection results, PID substitution, path ambiguity or a live
    cross-session Agent remain HOLD. No automatic stop is ever authorized.
    """
    if any(type(v) is not int or v <= 0 for v in (
        endpoint_pid, endpoint_session, current_session, observation.pid
    )):
        return Decision(AgentDecision.HOLD, "IDENTITY_INVALID")
    if observation.pid != endpoint_pid:
        return Decision(AgentDecision.HOLD, "PID_OBSERVATION_MISMATCH")
    if observation.kind == "ABSENT":
        return Decision(AgentDecision.ABSENT, "ENDPOINT_PID_CONFIRMED_GONE")
    if observation.kind != "PRESENT":
        return Decision(AgentDecision.HOLD, "PROCESS_INSPECTION_UNCERTAIN")
    if observation.session_id is None or type(observation.session_id) is not int:
        return Decision(AgentDecision.HOLD, "PROCESS_SESSION_UNVERIFIED")
    if observation.session_id != endpoint_session:
        return Decision(AgentDecision.HOLD, "PROCESS_ENDPOINT_SESSION_CONFLICT")
    if endpoint_session != current_session:
        return Decision(AgentDecision.HOLD, "LIVE_FOREIGN_SESSION_AGENT")
    if not _same_executable(observation.executable, expected_executable):
        return Decision(AgentDecision.HOLD, "PROCESS_EXECUTABLE_MISMATCH")
    return Decision(AgentDecision.READY, "EXACT_SESSION_AGENT_OBSERVED")
