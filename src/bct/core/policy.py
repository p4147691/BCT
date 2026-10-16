from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from .models import Decision, DecisionKind, Principal, Work


class Policy:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._revision = ""
        self._normal: frozenset[str] = frozenset()
        self._approval: frozenset[str] = frozenset()
        self.reload()

    @property
    def revision(self) -> str:
        return self._revision

    def reload(self) -> None:
        raw = self.path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
        policy = data.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("POLICY_SECTION_REQUIRED")
        normal = policy.get("normal_actions")
        approval = policy.get("approval_actions")
        if not isinstance(normal, list) or not all(isinstance(item, str) for item in normal):
            raise ValueError("NORMAL_ACTIONS_INVALID")
        if not isinstance(approval, list) or not all(isinstance(item, str) for item in approval):
            raise ValueError("APPROVAL_ACTIONS_INVALID")
        overlap = set(normal) & set(approval)
        if overlap:
            raise ValueError("POLICY_ACTION_OVERLAP:" + ",".join(sorted(overlap)))
        self._normal = frozenset(normal)
        self._approval = frozenset(approval)
        self._revision = hashlib.sha256(raw).hexdigest()

    def validate_unattended_actions(self, actions: list[str]) -> str:
        """Fail closed unless every action is currently a normal action.

        Manager decisions do not carry an authenticated Principal or an
        approval.  They may therefore create successor assignments only for
        actions that the *current* policy classifies as normal.
        """
        self.reload()
        denied = sorted(set(actions) - self._normal)
        if denied:
            raise ValueError("POLICY_ACTION_NOT_UNATTENDED:" + ",".join(denied))
        return self.revision

    def decide(self, *, principal: Principal, work: Work, action: str,
               approval_ref: str | None = None) -> Decision:
        self.reload()
        if principal.principal_id != work.owner_principal_id:
            return Decision(DecisionKind.DENY, "WRONG_WORK_OWNER", "use the assigned principal or hand off the work", self.revision)
        if work.state != "ACTIVE":
            return Decision(DecisionKind.DENY, "WORK_NOT_ACTIVE", "inspect the work state", self.revision)
        if action not in work.actions:
            return Decision(DecisionKind.DENY, "ACTION_OUTSIDE_USER_SCOPE", "start or update work with the requested action", self.revision)
        if action not in principal.capabilities:
            return Decision(DecisionKind.DENY, "PRINCIPAL_CAPABILITY_MISSING", "use an authenticated principal with this capability", self.revision)
        if action in self._approval:
            if approval_ref:
                return Decision(DecisionKind.DENY, "APPROVAL_VERIFIER_UNAVAILABLE", "use the future approval store before enabling this action", self.revision)
            return Decision(DecisionKind.APPROVAL_REQUIRED, "EXPLICIT_APPROVAL_REQUIRED", "provide an approval bound to this work and request", self.revision)
        if action in self._normal:
            return Decision(DecisionKind.ALLOW, "USER_SCOPED_NORMAL_ACTION", "execute with current preconditions", self.revision)
        return Decision(DecisionKind.DENY, "ACTION_NOT_CONFIGURED", "add the action to the reviewed policy", self.revision)
