from __future__ import annotations

import tomllib
from pathlib import Path

from .core.identity import IdentityService
from .core.models import Principal, Work
from .core.operations import OperationCoordinator
from .core.policy import Policy
from .core.store import Store
from .core.orchestration import OrchestrationService
from .manager_decision_recovery import ManagerDecisionRecovery
from .worker_dispatch_recovery import WorkerDispatchRecovery
from .features.files import FileReadFeature, FileWriteFeature
from .features.git import GitCommitFeature
from .features.deploy import DeployFeature, DeploymentProfiles, ServiceControlFeature
from .features.github import (
    GitHubPullRequestFeature,
    GitHubPullRequestMergeFeature,
    GitHubPullRequestStatusFeature,
    GitHubPushFeature,
    GitHubSyncMainFeature,
)
from .features.tests import TestFeature
from .features.verification import VerificationFeature
from .features.rcc import RelayBrowserFeature
from .features.execution import ExecuteFeature, SystemInspectFeature
from .features.process_session import ProcessSessionFeature
from .features.monitor import MonitorFeature
from .features.orchestration import OrchestrationFeature
from .integrations.github import GhCliClient, GitHubClient
from .integrations.rcc import NamedPipeRelayClient


def _manager_wake_receipt_v2_enabled(policy_path: str | Path) -> bool:
    data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
    orchestration = data.get("orchestration", {})
    if not isinstance(orchestration, dict):
        raise ValueError("ORCHESTRATION_SECTION_INVALID")
    enabled = orchestration.get("manager_wake_receipt_v2_enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("MANAGER_WAKE_RECEIPT_V2_ENABLED_INVALID")
    return enabled


class BCT:
    """Small local entry point shared by direct and future MCP calls."""

    def __init__(self, *, state_path: str | Path, policy_path: str | Path,
                 data_root: str | Path | None = None,
                 github_client: GitHubClient | None = None):
        self.store = Store(state_path)
        self.policy = Policy(policy_path)
        self.identity = IdentityService(self.store)
        v2_enabled = _manager_wake_receipt_v2_enabled(policy_path)
        self.orchestration = OrchestrationService(
            self.store,
            policy=self.policy,
            manager_wake_receipt_v2_enabled=v2_enabled,
        )
        relay = NamedPipeRelayClient()
        self.worker_dispatch_recovery = (
            WorkerDispatchRecovery(self.orchestration, relay)
            if self.orchestration.manager_wake_receipt_v2_active else None
        )
        self.manager_decision_recovery = (
            ManagerDecisionRecovery(
                self.orchestration, relay,
                on_deliveries=(
                    self.worker_dispatch_recovery.notify
                    if self.worker_dispatch_recovery is not None else None
                ),
            )
            if self.orchestration.manager_wake_receipt_v2_active else None
        )
        self.operations = OperationCoordinator(store=self.store, policy=self.policy)
        github = github_client or GhCliClient()
        deployment_profiles = DeploymentProfiles(policy_path)
        for feature in (
            FileReadFeature(), FileWriteFeature(), TestFeature(), GitCommitFeature(),
            GitHubPushFeature(), GitHubPullRequestFeature(github),
            GitHubPullRequestStatusFeature(github, self.store), GitHubPullRequestMergeFeature(github),
            GitHubSyncMainFeature(),
            DeployFeature(deployment_profiles), ServiceControlFeature(deployment_profiles),
            RelayBrowserFeature(),
            SystemInspectFeature(), ExecuteFeature(),
            ProcessSessionFeature(policy_path, data_root=data_root),
            MonitorFeature(policy_path),
            OrchestrationFeature(self.orchestration),
        ):
            self.operations.register(feature)
        self.operations.register(VerificationFeature(self.operations._features, self.store))

    def create_work(self, *, work_id: str, request_summary: str, roots: list[str],
                    actions: list[str], principal: Principal) -> Work:
        work = Work(work_id, request_summary, tuple(str(Path(root).resolve()) for root in roots),
                    frozenset(actions), principal.principal_id)
        return self.store.create_work(work)
