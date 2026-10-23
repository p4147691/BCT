from __future__ import annotations

import tomllib
import re
from pathlib import Path

from .core.identity import IdentityService
from .core.models import Principal, Work
from .core.operations import OperationCoordinator
from .core.policy import Policy
from .core.store import Store
from .core.orchestration import OrchestrationService
from .manager_decision_recovery import ManagerDecisionRecovery
from .relay_executor import RelayControlFeature
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
from .features.vtl import VtlValidateFeature
from .features.rcc import RelayBrowserFeature
from .features.execution import ExecuteFeature, SystemInspectFeature
from .features.process_session import ProcessSessionFeature
from .features.cdp_inspect import CDPInspectFeature
from .features.monitor import MonitorFeature
from .features.claim_reconciliation import ReadOnlyClaimReconcileFeature
from .features.orchestration import OrchestrationFeature
from .features.desktop_session import (
    DesktopCaptureFeature, DesktopClipboardFeature, DesktopControlLeaseFeature, DesktopEmergencyStopFeature,
    DesktopApplicationTargetFeature, DesktopChromeTabReconcileFeature,
    DesktopChromeContentActionFeature, DesktopChromeContentListFeature,
    DesktopChromeTabSelectFeature, DesktopExploreFeature,
    DesktopInputFeature, DesktopProgramLaunchFeature, DesktopSessionStatusFeature,
    DesktopUiaElementActionFeature, DesktopUiaElementsListFeature,
    DesktopWindowActivateFeature, DesktopWindowActivateReconcileFeature,
    DesktopWindowManageFeature,
    DesktopWindowListFeature, desktop_session_client,
)
from .integrations.github import GhCliClient, GitHubClient
from .integrations.rcc import NamedPipeRelayClient
from .integrations.cdp_connection import CDPConnectionManager


def _cdp_mcp_command(policy_path: str | Path) -> tuple[str, ...] | None:
    """Fail closed unless a reviewed local policy explicitly enables CDP."""
    data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
    section = data.get("cdp", {})
    if not isinstance(section, dict):
        raise ValueError("CDP_CONFIG_SECTION_INVALID")
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("CDP_CONFIG_ENABLED_INVALID")
    if not enabled:
        return None
    argv = section.get("argv")
    if (not isinstance(argv, list) or not argv
            or any(not isinstance(a, str) or not a for a in argv)):
        raise ValueError("CDP_CONFIG_ARGV_INVALID")
    return tuple(argv)


def _manager_wake_receipt_v2_enabled(policy_path: str | Path) -> bool:
    data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
    orchestration = data.get("orchestration", {})
    if not isinstance(orchestration, dict):
        raise ValueError("ORCHESTRATION_SECTION_INVALID")
    enabled = orchestration.get("manager_wake_receipt_v2_enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("MANAGER_WAKE_RECEIPT_V2_ENABLED_INVALID")
    return enabled



def _excluded_new_assignment_instances(policy_path: str | Path) -> frozenset[str]:
    data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
    section = data.get("orchestration", {})
    if not isinstance(section, dict):
        raise ValueError("ORCHESTRATION_SECTION_INVALID")
    values = section.get("excluded_new_assignment_instance_ids", [])
    if not isinstance(values, list) or len(values) > 32 or any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value)
        for value in values
    ):
        raise ValueError("ORCHESTRATION_EXCLUDED_INSTANCE_IDS_INVALID")
    return frozenset(values)


def _require_current_session_instances(policy_path: str | Path) -> frozenset[str]:
    data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
    section = data.get("orchestration", {})
    if not isinstance(section, dict):
        raise ValueError("ORCHESTRATION_SECTION_INVALID")
    values = section.get("require_current_session_instance_ids", [])
    if not isinstance(values, list) or len(values) > 32 or any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value)
        for value in values
    ):
        raise ValueError("ORCHESTRATION_CURRENT_SESSION_INSTANCE_IDS_INVALID")
    return frozenset(values)

class BCT:
    """Small local entry point shared by direct and future MCP calls."""

    def __init__(self, *, state_path: str | Path, policy_path: str | Path,
                 data_root: str | Path | None = None,
                 github_client: GitHubClient | None = None):
        self.cdp_connections = CDPConnectionManager()  # lazy, no Chrome side effects
        cdp_command = _cdp_mcp_command(policy_path)
        if cdp_command is not None:
            self.cdp_connections.configure(cdp_command)
        self.store = Store(state_path)
        self.policy = Policy(policy_path)
        self.identity = IdentityService(self.store)
        v2_enabled = _manager_wake_receipt_v2_enabled(policy_path)
        self.orchestration = OrchestrationService(
            self.store,
            policy=self.policy,
            manager_wake_receipt_v2_enabled=v2_enabled,
            excluded_new_assignment_instances=_excluded_new_assignment_instances(policy_path),
            require_current_session_instances=_require_current_session_instances(policy_path),
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
        desktop_session = desktop_session_client(policy_path, data_root=data_root)
        for feature in (
            FileReadFeature(self.store), FileWriteFeature(), TestFeature(), GitCommitFeature(policy_path),
            GitHubPushFeature(), GitHubPullRequestFeature(github),
            GitHubPullRequestStatusFeature(github), GitHubPullRequestMergeFeature(github, policy_path),
            GitHubSyncMainFeature(policy_path),
            DeployFeature(deployment_profiles), ServiceControlFeature(deployment_profiles),
            RelayBrowserFeature(store=self.store),
            SystemInspectFeature(), ExecuteFeature(),
            ProcessSessionFeature(policy_path, data_root=data_root),
            MonitorFeature(policy_path),
            CDPInspectFeature(self.cdp_connections),
            ReadOnlyClaimReconcileFeature(self.store, desktop_session),
            OrchestrationFeature(self.orchestration),
            DesktopSessionStatusFeature(desktop_session),
            DesktopCaptureFeature(desktop_session),
            DesktopExploreFeature(desktop_session),
            DesktopApplicationTargetFeature(desktop_session),
            DesktopChromeContentListFeature(desktop_session),
            DesktopChromeContentActionFeature(desktop_session),
            DesktopUiaElementsListFeature(desktop_session),
            DesktopUiaElementActionFeature(desktop_session),
            DesktopChromeTabReconcileFeature(desktop_session),
            DesktopChromeTabSelectFeature(desktop_session),
            DesktopControlLeaseFeature(desktop_session),
            DesktopEmergencyStopFeature(desktop_session),
            DesktopInputFeature(desktop_session),
            DesktopClipboardFeature(desktop_session),
            DesktopWindowListFeature(desktop_session),
            DesktopWindowActivateFeature(desktop_session),
            DesktopWindowActivateReconcileFeature(desktop_session),
            DesktopWindowManageFeature(desktop_session),
            DesktopProgramLaunchFeature(desktop_session),
            VtlValidateFeature(policy_path, data_root=data_root),
        ):
            self.operations.register(feature)
        self.operations.register(RelayControlFeature(
            store=self.store, features=self.operations._features,
        ))
        self.operations.register(VerificationFeature(self.operations._features, self.store))

    def create_work(self, *, work_id: str, request_summary: str, roots: list[str],
                    actions: list[str], principal: Principal) -> Work:
        work = Work(work_id, request_summary, tuple(str(Path(root).resolve()) for root in roots),
                    frozenset(actions), principal.principal_id)
        return self.store.create_work(work)
