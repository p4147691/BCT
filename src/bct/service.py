from __future__ import annotations

from pathlib import Path

from .core.identity import IdentityService
from .core.models import Principal, Work
from .core.operations import OperationCoordinator
from .core.policy import Policy
from .core.store import Store
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
from .features.rcc import RelayBrowserFeature
from .integrations.github import GhCliClient, GitHubClient


class BCT:
    """Small local entry point shared by direct and future MCP calls."""

    def __init__(self, *, state_path: str | Path, policy_path: str | Path,
                 github_client: GitHubClient | None = None):
        self.store = Store(state_path)
        self.policy = Policy(policy_path)
        self.identity = IdentityService(self.store)
        self.operations = OperationCoordinator(store=self.store, policy=self.policy)
        github = github_client or GhCliClient()
        deployment_profiles = DeploymentProfiles(policy_path)
        for feature in (
            FileReadFeature(), FileWriteFeature(), TestFeature(), GitCommitFeature(),
            GitHubPushFeature(), GitHubPullRequestFeature(github),
            GitHubPullRequestStatusFeature(github), GitHubPullRequestMergeFeature(github),
            GitHubSyncMainFeature(),
            DeployFeature(deployment_profiles), ServiceControlFeature(deployment_profiles),
            RelayBrowserFeature(),
        ):
            self.operations.register(feature)

    def create_work(self, *, work_id: str, request_summary: str, roots: list[str],
                    actions: list[str], principal: Principal) -> Work:
        work = Work(work_id, request_summary, tuple(str(Path(root).resolve()) for root in roots),
                    frozenset(actions), principal.principal_id)
        return self.store.create_work(work)
