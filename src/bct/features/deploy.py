from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from bct.core.models import (
    ConfirmedFailure,
    FeatureRequest,
    FeatureResult,
    Outcome,
    PreconditionError,
    UnknownEffectError,
    Work,
)
from bct.service_runtime import (
    RuntimeServiceController,
    RuntimeWriterLock,
    atomic_json,
    read_json,
)
from .common import resolve_in_work


from bct_maintenance.releases import (
    _SHA,
    _SHA256,
    _NAME,
    _LOCAL_APP_DATA_PREFIX,
    _RUNTIME_RECOVERY_SCRIPTS,
    _git,
    _git_filtered_oid,
    _sha256,
    DeploymentProfile,
    DeploymentProfiles,
    _validate_source_repository,
    _target_profile,
    _cutover_authority,
    _cutover_authority_path,
    _validate_profile_start_allowed,
    write_protected_cutover_rollback,
    _begin_protected_cutover,
    _record_protected_cutover,
    _validate_source,
    _validate_protected_activation,
    _validate_protected_deploy_gate,
    _validate_release,
    _validate_historic_release,
    _stage_release,
    _current_path,
    _write_current,
    _publish_runtime_recovery_scripts,
    _read_current,
    _start_with_one_safe_retry,
)
from bct_maintenance.engine import DeploymentEngine
from bct_maintenance.locking import maintenance_lock


class DeployFeature:
    capability = "deploy"

    def __init__(self, profiles: DeploymentProfiles):
        self.profiles = profiles

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        operation = str(arguments.get("operation") or "apply").strip().lower()
        if operation in {"rcc-inspect", "rcc-install", "rcc-rollback",
                         "rcc-inspect-pr388", "rcc-install-pr388", "rcc-rollback-pr388",
                         "rcc-inspect-rename-actions", "rcc-install-rename-actions",
                         "rcc-rollback-rename-actions",
                          "rcc-inspect-source-proof", "rcc-install-source-proof",
                          "rcc-rollback-source-proof",
                          "rcc-inspect-source-proof-v2", "rcc-install-source-proof-v2",
                          "rcc-rollback-source-proof-v2",
                          "rcc-inspect-semantic-turn", "rcc-install-semantic-turn",
                          "rcc-rollback-semantic-turn",
                          "rcc-inspect-submit-activation-fence",
                          "rcc-install-submit-activation-fence",
                          "rcc-rollback-submit-activation-fence",
                          "rcc-inspect-rendered-prompt-provenance",
                          "rcc-install-rendered-prompt-provenance",
                          "rcc-rollback-rendered-prompt-provenance",
                          "rcc-inspect-rendered-markdown-identity",
                          "rcc-install-rendered-markdown-identity",
                          "rcc-rollback-rendered-markdown-identity",
                          "rcc-inspect-rename-resilience",
                          "rcc-install-rename-resilience",
                          "rcc-rollback-rename-resilience",
                          "rcc-inspect-command-namespace",
                          "rcc-install-command-namespace",
                          "rcc-rollback-command-namespace",
                          "rcc-inspect-canonical-wire",
                          "rcc-install-canonical-wire",
                          "rcc-rollback-canonical-wire",
                          "rcc-inspect-dot-title-rename",
                          "rcc-install-dot-title-rename",
                          "rcc-rollback-dot-title-rename",
                          "rcc-inspect-composer-rebind",
                          "rcc-install-composer-rebind",
                          "rcc-rollback-composer-rebind",
                          "rcc-verify-installed", "rcc-verify-installed-pr388",
                          "rcc-verify-installed-rename-actions",
                          "rcc-verify-installed-source-proof",
                          "rcc-verify-installed-source-proof-v2",
                          "rcc-verify-installed-semantic-turn",
                          "rcc-verify-installed-submit-activation-fence",
                          "rcc-verify-installed-rendered-prompt-provenance",
                          "rcc-verify-installed-rendered-markdown-identity",
                          "rcc-verify-installed-rename-resilience",
                          "rcc-verify-installed-command-namespace",
                          "rcc-verify-installed-canonical-wire",
                          "rcc-verify-installed-dot-title-rename",
                          "rcc-verify-installed-composer-rebind"}:
            return self._prepare_rcc(work, operation, arguments)
        if operation not in {"apply", "reconcile", "reconcile-rollback"}:
            raise PreconditionError("DEPLOYMENT_OPERATION_INVALID")
        profile_name = str(arguments.get("profile") or "")
        profile = self.profiles.get(profile_name)
        expected_source_head = str(arguments.get("expected_source_head") or "").lower()
        expected_current = arguments.get("expected_current_source_head")
        source_worktree = arguments.get("source_worktree")
        if source_worktree is not None:
            if operation != "apply":
                raise PreconditionError("DEPLOYMENT_SOURCE_WORKTREE_APPLY_REQUIRED")
            source_worktree = str(resolve_in_work(work, source_worktree, must_exist=True))
        restart = arguments.get("restart", operation == "apply")
        if not _SHA.fullmatch(expected_source_head):
            raise PreconditionError("DEPLOYMENT_SOURCE_SHA_INVALID")
        if expected_current is not None:
            expected_current = str(expected_current).lower()
            if not _SHA.fullmatch(expected_current):
                raise PreconditionError("DEPLOYMENT_CURRENT_SHA_INVALID")
        if not isinstance(restart, bool):
            raise PreconditionError("DEPLOYMENT_RESTART_INVALID")
        if operation in {"reconcile", "reconcile-rollback"}:
            original_operation_id = str(
                arguments.get("original_operation_id") or ""
            ).strip()
            if not original_operation_id or len(original_operation_id) > 80:
                raise PreconditionError("DEPLOYMENT_RECONCILE_OPERATION_ID_INVALID")
            if restart:
                raise PreconditionError("DEPLOYMENT_RECONCILE_RESTART_FORBIDDEN")
            if operation == "reconcile" and expected_current != expected_source_head:
                raise PreconditionError("DEPLOYMENT_RECONCILE_EXACT_CURRENT_REQUIRED")
            if operation == "reconcile-rollback" and expected_current == expected_source_head:
                raise PreconditionError("DEPLOYMENT_RECONCILE_ROLLBACK_CURRENT_REQUIRED")
            receipt_path = (
                profile.runtime_root / "deployments" / (expected_source_head + ".json")
            )
            return FeatureRequest(
                self.capability,
                profile.name,
                {
                    "operation": operation,
                    "original_operation_id": original_operation_id,
                    "profile": profile.name,
                    "expected_source_head": expected_source_head,
                    "expected_current_source_head": expected_current,
                    "restart": False,
                },
                (
                    "deployment-reconcile:"
                    + str(profile.runtime_root).casefold()
                    + ":"
                    + original_operation_id.casefold(),
                ),
                {
                    "expected_source_head": expected_source_head,
                    "expected_current_source_head": expected_current,
                    "reconciliation_receipt": str(receipt_path),
                },
            )
        return FeatureRequest(
            self.capability,
            profile.name,
            {"profile": profile.name, "expected_source_head": expected_source_head,
             "expected_current_source_head": expected_current, "restart": restart,
             **({"source_worktree": source_worktree} if source_worktree is not None else {})},
            (f"deployment:{str(profile.runtime_root).casefold()}", f"service:{profile.service_name.casefold()}"),
            {"expected_source_head": expected_source_head, "expected_current_source_head": expected_current},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        if request.arguments.get("operation") in {
            "rcc-inspect", "rcc-install", "rcc-rollback",
            "rcc-inspect-pr388", "rcc-install-pr388", "rcc-rollback-pr388",
            "rcc-inspect-rename-actions", "rcc-install-rename-actions",
            "rcc-rollback-rename-actions",
            "rcc-inspect-source-proof", "rcc-install-source-proof",
            "rcc-rollback-source-proof",
            "rcc-inspect-source-proof-v2", "rcc-install-source-proof-v2",
            "rcc-rollback-source-proof-v2",
            "rcc-inspect-semantic-turn", "rcc-install-semantic-turn",
            "rcc-rollback-semantic-turn",
            "rcc-inspect-submit-activation-fence",
            "rcc-install-submit-activation-fence",
            "rcc-rollback-submit-activation-fence",
            "rcc-inspect-rendered-prompt-provenance",
            "rcc-install-rendered-prompt-provenance",
            "rcc-rollback-rendered-prompt-provenance",
            "rcc-inspect-rendered-markdown-identity",
            "rcc-install-rendered-markdown-identity",
            "rcc-rollback-rendered-markdown-identity",
            "rcc-inspect-rename-resilience",
            "rcc-install-rename-resilience",
            "rcc-rollback-rename-resilience",
            "rcc-inspect-command-namespace",
            "rcc-install-command-namespace",
            "rcc-rollback-command-namespace",
            "rcc-inspect-canonical-wire",
            "rcc-install-canonical-wire",
            "rcc-rollback-canonical-wire",
            "rcc-inspect-dot-title-rename",
            "rcc-install-dot-title-rename",
            "rcc-rollback-dot-title-rename",
            "rcc-inspect-composer-rebind",
            "rcc-install-composer-rebind",
            "rcc-rollback-composer-rebind",
            "rcc-verify-installed", "rcc-verify-installed-pr388",
            "rcc-verify-installed-rename-actions",
            "rcc-verify-installed-source-proof",
            "rcc-verify-installed-source-proof-v2",
            "rcc-verify-installed-semantic-turn",
            "rcc-verify-installed-submit-activation-fence",
            "rcc-verify-installed-rendered-prompt-provenance",
            "rcc-verify-installed-rendered-markdown-identity",
            "rcc-verify-installed-rename-resilience",
            "rcc-verify-installed-command-namespace",
            "rcc-verify-installed-canonical-wire",
            "rcc-verify-installed-dot-title-rename",
            "rcc-verify-installed-composer-rebind",
        }:
            return self._execute_rcc(request)
        if request.arguments.get("operation") == "reconcile":
            return self._reconcile(request)
        if request.arguments.get("operation") == "reconcile-rollback":
            return self._reconcile_rollback(request)
        trusted_profile = self.profiles.get(request.arguments["profile"])
        source_worktree = request.arguments.get("source_worktree")
        profile = (_target_profile(trusted_profile, request.arguments["expected_source_head"], Path(source_worktree))
                   if source_worktree else _target_profile(trusted_profile, request.arguments["expected_source_head"]))
        if not profile.protected_activation_required:
            _validate_profile_start_allowed(self.profiles, profile)
        source_lock = _validate_protected_deploy_gate(
            self.profiles, profile, request.arguments["expected_source_head"],
            acquire_lock=True,
        )
        try:
            return self._execute_apply(request, profile)
        finally:
            if source_lock is not None:
                source_lock.close()

    @staticmethod
    def _rcc_route_config(operation: str, manifest_sha256: str = "") -> dict[str, Any]:
        """Choose one immutable release without weakening prior install receipts."""
        from bct import rcc_protected_install as rcc
        loop_return_manifest = "b2b1e1efb58bef745de96e75a8b24fb34483a3eed4148e95e2ea57cd1d08b214"
        if operation.endswith("-composer-rebind") and manifest_sha256 == loop_return_manifest:
            from pathlib import Path
            stage = Path(r"D:\BCT\data\RCC_LOOP_SUPERVISOR_RETURN_20261112")
            return {"pinned_manifest_sha256": loop_return_manifest, "live": rcc.EXACT_INSTALLED,
                    "candidate": stage / "candidate", "backup_source": stage / "rollback",
                    "manifest_file": stage / "release_manifest_immutable.json",
                    "journal_root": Path(r"D:\BCT\runtime\backups\rcc-guarded-install-loop-return"),
                    "candidate_version": "1.0.70", "installed_version": "1.0.70"}
        hidden_stop_manifest = "4e6973c0efc10f215d04f1676285edd88103462188589e9b07ee10e9a3956c23"
        if operation.endswith("-composer-rebind") and manifest_sha256 == hidden_stop_manifest:
            from pathlib import Path
            stage = Path(r"D:\BCT\data\RCC_HIDDEN_STOP_20261112")
            return {"pinned_manifest_sha256": hidden_stop_manifest, "live": rcc.EXACT_INSTALLED,
                    "candidate": stage / "candidate", "backup_source": stage / "rollback",
                    "manifest_file": stage / "release_manifest_immutable.json",
                    "journal_root": Path(r"D:\BCT\runtime\backups\rcc-guarded-install-hidden-stop"),
                    "candidate_version": "1.0.70", "installed_version": "1.0.70"}
        if operation.endswith("-composer-rebind") and manifest_sha256 == rcc.VISIBLE_EDITOR_MANIFEST_SHA256:
            return {"pinned_manifest_sha256": manifest_sha256, "live": rcc.EXACT_INSTALLED,
                    "candidate": rcc.VISIBLE_EDITOR_ROOT / "candidate_1_0_70_visible_editor",
                    "backup_source": rcc.VISIBLE_EDITOR_ROOT / "rollback_1_0_70_visible_editor",
                    "manifest_file": rcc.VISIBLE_EDITOR_ROOT / "release_manifest_visible_editor_immutable.json",
                    "journal_root": rcc.VISIBLE_EDITOR_JOURNAL, "candidate_version": "1.0.70",
                    "installed_version": "1.0.70"}
        routes = (
            ("-composer-rebind", rcc.COMPOSER_REBIND_MANIFEST_SHA256,
             rcc.COMPOSER_REBIND_STAGE, rcc.COMPOSER_REBIND_ROLLBACK,
             rcc.COMPOSER_REBIND_MANIFEST, rcc.COMPOSER_REBIND_JOURNAL, "1.0.70", "1.0.69"),
            ("-dot-title-rename", rcc.DOT_TITLE_RENAME_MANIFEST_SHA256,
             rcc.DOT_TITLE_RENAME_STAGE, rcc.DOT_TITLE_RENAME_ROLLBACK,
             rcc.DOT_TITLE_RENAME_MANIFEST, rcc.DOT_TITLE_RENAME_JOURNAL, "1.0.69", "1.0.69"),
            ("-canonical-wire", rcc.CANONICAL_WIRE_MANIFEST_SHA256,
             rcc.CANONICAL_WIRE_STAGE, rcc.CANONICAL_WIRE_ROLLBACK,
             rcc.CANONICAL_WIRE_MANIFEST, rcc.CANONICAL_WIRE_JOURNAL, "1.0.67", "1.0.66"),
            ("-command-namespace", rcc.COMMAND_NAMESPACE_MANIFEST_SHA256,
             rcc.COMMAND_NAMESPACE_STAGE, rcc.COMMAND_NAMESPACE_ROLLBACK,
             rcc.COMMAND_NAMESPACE_MANIFEST, rcc.COMMAND_NAMESPACE_JOURNAL, "1.0.66", "1.0.65"),
            ("-rename-resilience", rcc.RENAME_RESILIENCE_MANIFEST_SHA256,
             rcc.RENAME_RESILIENCE_STAGE, rcc.RENAME_RESILIENCE_ROLLBACK,
             rcc.RENAME_RESILIENCE_MANIFEST, rcc.RENAME_RESILIENCE_JOURNAL, "1.0.65", "1.0.64"),
            ("-rendered-markdown-identity", rcc.RENDERED_MARKDOWN_IDENTITY_MANIFEST_SHA256,
             rcc.RENDERED_MARKDOWN_IDENTITY_STAGE, rcc.RENDERED_MARKDOWN_IDENTITY_ROLLBACK,
             rcc.RENDERED_MARKDOWN_IDENTITY_MANIFEST, rcc.RENDERED_MARKDOWN_IDENTITY_JOURNAL, "1.0.64", "1.0.63"),
            ("-rendered-prompt-provenance", rcc.RENDERED_PROMPT_PROVENANCE_MANIFEST_SHA256,
             rcc.RENDERED_PROMPT_PROVENANCE_STAGE, rcc.RENDERED_PROMPT_PROVENANCE_ROLLBACK,
             rcc.RENDERED_PROMPT_PROVENANCE_MANIFEST, rcc.RENDERED_PROMPT_PROVENANCE_JOURNAL, "1.0.63", "1.0.63"),
            ("-submit-activation-fence", rcc.SUBMIT_ACTIVATION_FENCE_MANIFEST_SHA256,
             rcc.SUBMIT_ACTIVATION_FENCE_STAGE, rcc.SUBMIT_ACTIVATION_FENCE_ROLLBACK,
             rcc.SUBMIT_ACTIVATION_FENCE_MANIFEST, rcc.SUBMIT_ACTIVATION_FENCE_JOURNAL, "1.0.63", "1.0.63"),
            ("-semantic-turn", rcc.SEMANTIC_TURN_MANIFEST_SHA256,
             rcc.SEMANTIC_TURN_STAGE, rcc.SEMANTIC_TURN_ROLLBACK,
             rcc.SEMANTIC_TURN_MANIFEST, rcc.SEMANTIC_TURN_JOURNAL, "1.0.63", "1.0.63"),
            ("-source-proof-v2", rcc.DELAYED_SOURCE_PROOF_V2_MANIFEST_SHA256,
             rcc.DELAYED_SOURCE_PROOF_V2_STAGE, rcc.DELAYED_SOURCE_PROOF_V2_ROLLBACK,
             rcc.DELAYED_SOURCE_PROOF_V2_MANIFEST, rcc.DELAYED_SOURCE_PROOF_V2_JOURNAL, "1.0.61", "1.0.61"),
            ("-source-proof", rcc.DELAYED_SOURCE_PROOF_MANIFEST_SHA256,
             rcc.DELAYED_SOURCE_PROOF_STAGE, rcc.DELAYED_SOURCE_PROOF_ROLLBACK,
             rcc.DELAYED_SOURCE_PROOF_MANIFEST, rcc.DELAYED_SOURCE_PROOF_JOURNAL, "1.0.61", "1.0.61"),
            ("-rename-actions", rcc.RENAME_ACTIONS_MANIFEST_SHA256,
             rcc.RENAME_ACTIONS_STAGE, rcc.RENAME_ACTIONS_ROLLBACK,
             rcc.RENAME_ACTIONS_MANIFEST, rcc.RENAME_ACTIONS_JOURNAL, "1.0.61", "1.0.61"),
            ("-pr388", rcc.PR388_MANIFEST_SHA256, rcc.PR388_STAGE, rcc.PR388_ROLLBACK,
             rcc.PR388_MANIFEST, rcc.PR388_JOURNAL, "1.0.61", None),
        )
        for suffix, manifest_sha, candidate, backup, manifest, journal, version, installed in routes:
            if operation.endswith(suffix):
                return {"pinned_manifest_sha256": manifest_sha, "live": rcc.EXACT_INSTALLED,
                        "candidate": candidate, "backup_source": backup, "manifest_file": manifest,
                        "journal_root": journal, "candidate_version": version,
                        "installed_version": installed}
        return {"pinned_manifest_sha256": rcc.PINNED_MANIFEST_SHA256, "live": rcc.EXACT_INSTALLED,
                "candidate": rcc.EXACT_STAGE, "backup_source": rcc.EXACT_ROLLBACK,
                "manifest_file": rcc.EXACT_MANIFEST, "journal_root": rcc.EXACT_JOURNAL,
                "candidate_version": "1.0.60", "installed_version": None}

    @staticmethod
    def _prepare_rcc(work: Work, operation: str, arguments: dict[str, Any]) -> FeatureRequest:
        """Reuse the BCT deploy policy and exact Work/Operation resource boundary."""
        from bct import rcc_protected_install as rcc
        from pathlib import Path
        allowed = {
            "operation", "expected_source_head", "expected_installed_aggregate",
            "expected_candidate_aggregate", "expected_manifest_sha256",
            "install_operation_id", "instance_id",
        }
        if set(arguments) - allowed:
            raise PreconditionError("RCC_INSTALL_FIELDS_UNSUPPORTED")
        source_head = str(arguments.get("expected_source_head") or "").lower()
        installed = str(arguments.get("expected_installed_aggregate") or "").lower()
        candidate = str(arguments.get("expected_candidate_aggregate") or "").lower()
        manifest = str(arguments.get("expected_manifest_sha256") or "").lower()
        original = str(arguments.get("install_operation_id") or "").strip()
        instance = str(arguments.get("instance_id") or "").strip()
        if not re.fullmatch("[0-9a-f]{40}", source_head):
            raise PreconditionError("RCC_INSTALL_SOURCE_HEAD_INVALID")
        if not all(re.fullmatch("[0-9a-f]{64}", item) for item in (installed, candidate, manifest)):
            raise PreconditionError("RCC_INSTALL_EXPECTED_DIGEST_REQUIRED")
        if not re.fullmatch("[a-f0-9]{32}", instance):
            raise PreconditionError("RCC_INSTALL_INSTANCE_ID_REQUIRED")
        is_rollback = operation in {
            "rcc-rollback", "rcc-rollback-pr388", "rcc-rollback-rename-actions",
            "rcc-rollback-source-proof", "rcc-rollback-source-proof-v2",
            "rcc-rollback-semantic-turn",
            "rcc-rollback-submit-activation-fence",
            "rcc-rollback-rendered-prompt-provenance",
            "rcc-rollback-rendered-markdown-identity",
            "rcc-rollback-rename-resilience",
            "rcc-rollback-command-namespace",
            "rcc-rollback-canonical-wire",
            "rcc-rollback-dot-title-rename",
            "rcc-rollback-composer-rebind",
        }
        is_post_install_verify = operation.startswith("rcc-verify-installed")
        if (is_rollback or is_post_install_verify) and not rcc.OP_ID.fullmatch(original):
            raise PreconditionError("RCC_INSTALL_ORIGINAL_OPERATION_ID_INVALID")
        if not (is_rollback or is_post_install_verify) and original:
            raise PreconditionError("RCC_INSTALL_ORIGINAL_OPERATION_FORBIDDEN")
        roots = [Path(raw).resolve(strict=False) for raw in work.roots]
        def covered(target):
            target = target.resolve(strict=False)
            return any(target == base or base in target.parents for base in roots)
        route = DeployFeature._rcc_route_config(operation, manifest)
        if not covered(route["live"]) or not covered(route["manifest_file"]):
            raise PreconditionError("RCC_INSTALL_WORK_ROOT_NOT_AUTHORIZED")
        resources = (
            "rcc-protected-install:" + str(rcc.EXACT_INSTALLED).casefold(),
            "rcc-instance:" + instance + ":maintenance:reload-extension",
        )
        return FeatureRequest(
            "deploy", "rcc-extension:" + rcc.EXTENSION_ID,
            {"operation": operation, "source_head": source_head,
             "installed_aggregate": installed, "candidate_aggregate": candidate,
             "manifest_sha256": manifest, "install_operation_id": original,
             "instance_id": instance}, resources,
            {"source_head": source_head,
             "expected_installed_aggregate": installed,
             "expected_candidate_aggregate": candidate},
        )

    RCC_SOURCE_ROOT = Path(r"D:\BCT\source")

    @staticmethod
    def _execute_rcc(request: FeatureRequest) -> FeatureResult:
        """No implicit Chrome reload, Core restart, browser edits, or LIVE PASS."""
        from bct import rcc_protected_install as rcc
        import subprocess
        values = request.arguments
        source = subprocess.run(
            ["git", "-C", str(DeployFeature.RCC_SOURCE_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False,
        )
        if source.returncode or source.stdout.strip().lower() != values["source_head"]:
            raise PreconditionError("RCC_INSTALL_CURRENT_SOURCE_SHA_CHANGED")
        expected = (
            values["installed_aggregate"], values["candidate_aggregate"],
            values["manifest_sha256"],
        )
        route = DeployFeature._rcc_route_config(values["operation"], values["manifest_sha256"])
        if values["operation"].endswith(("-pr388", "-rename-actions", "-source-proof", "-source-proof-v2", "-semantic-turn", "-submit-activation-fence", "-rendered-prompt-provenance", "-rendered-markdown-identity", "-rename-resilience", "-command-namespace", "-canonical-wire", "-dot-title-rename", "-composer-rebind")):
            from hashlib import sha256
            release_path = route["manifest_file"]
            if (not release_path.is_file() or sha256(release_path.read_bytes()).hexdigest()
                    != route["pinned_manifest_sha256"]):
                raise PreconditionError("RCC_PINNED_RELEASE_MANIFEST_MISMATCH")
        release_kwargs = {
            "live": route["live"], "candidate": route["candidate"],
            "backup_source": route["backup_source"],
            "manifest_file": route["manifest_file"],
            "journal_root": route["journal_root"],
            "candidate_version": route["candidate_version"],
            "installed_version": route["installed_version"],
        }
        if values["operation"].startswith("rcc-verify-installed"):
            original_id = values["install_operation_id"]
            receipt = route["journal_root"] / (original_id + ".json")
            if not receipt.is_file():
                raise PreconditionError("RCC_INSTALL_ORIGINAL_RECEIPT_REQUIRED")
            original = json.loads(receipt.read_text(encoding="utf-8"))
            if (original.get("installed_aggregate"), original.get("candidate_aggregate"),
                    original.get("manifest_sha256")) != expected:
                raise PreconditionError("RCC_INSTALL_POSTCHECK_EXPECTATIONS_CHANGED")
            result = rcc.verify_installed(
                request.operation_id, original_id,
                live=route["live"], manifest_file=route["manifest_file"],
                journal_root=route["journal_root"],
                candidate_version=route["candidate_version"],
            )
            return FeatureResult(
                Outcome.APPLIED,
                {"read_only": True, "installed_candidate_verified": True,
                 "reload": "NOT_PERFORMED", "live_accepted": False,
                 "original_install_operation_id": original_id},
                output=result,
            )
        if values["operation"] in {"rcc-rollback", "rcc-rollback-pr388", "rcc-rollback-rename-actions", "rcc-rollback-source-proof", "rcc-rollback-source-proof-v2", "rcc-rollback-semantic-turn", "rcc-rollback-submit-activation-fence", "rcc-rollback-rendered-prompt-provenance", "rcc-rollback-rendered-markdown-identity", "rcc-rollback-rename-resilience", "rcc-rollback-command-namespace", "rcc-rollback-canonical-wire", "rcc-rollback-dot-title-rename", "rcc-rollback-composer-rebind"}:
            original_id = values["install_operation_id"]
            receipt = route["journal_root"] / (original_id + ".json")
            if not receipt.is_file():
                raise PreconditionError("RCC_INSTALL_ORIGINAL_RECEIPT_REQUIRED")
            original = json.loads(receipt.read_text(encoding="utf-8"))
            if (original.get("installed_aggregate"), original.get("candidate_aggregate"),
                    original.get("manifest_sha256")) != expected:
                raise PreconditionError("RCC_INSTALL_ROLLBACK_EXPECTATIONS_CHANGED")
            result = rcc.rollback(
                original_id, authorization=lambda record:
                record.get("operation_id") == original_id
                and request.operation_id != original_id,
                live=route["live"],
                manifest_file=route["manifest_file"],
                journal_root=route["journal_root"],
            )
            return FeatureResult(
                Outcome.APPLIED, {"effect": "FILES_RESTORED",
                "reload": "NOT_PERFORMED", "live_accepted": False,
                "original_install_operation_id": original_id}, output=result,
            )
        plan = rcc.inspect(request.operation_id, **release_kwargs)
        if (plan["installed_aggregate"], plan["candidate_aggregate"],
                plan["manifest_sha256"]) != expected:
            raise PreconditionError("RCC_INSTALL_EXPECTATIONS_CHANGED")
        if values["operation"] in {"rcc-inspect", "rcc-inspect-pr388", "rcc-inspect-rename-actions", "rcc-inspect-source-proof", "rcc-inspect-source-proof-v2", "rcc-inspect-semantic-turn", "rcc-inspect-submit-activation-fence", "rcc-inspect-rendered-prompt-provenance", "rcc-inspect-rendered-markdown-identity", "rcc-inspect-rename-resilience", "rcc-inspect-command-namespace", "rcc-inspect-canonical-wire", "rcc-inspect-dot-title-rename", "rcc-inspect-composer-rebind"}:
            return FeatureResult(
                Outcome.APPLIED, {"read_only": True, "reload": "NOT_PERFORMED",
                                 "live_accepted": False},
                output=plan,
            )
        result = rcc.install(plan, authorization=lambda data:
                             data["operation_id"] == request.operation_id,
                             **release_kwargs)
        return FeatureResult(
            Outcome.APPLIED, {"effect": "FILES_INSTALLED_PENDING_RELOAD",
                             "reload": "NOT_PERFORMED", "live_accepted": False},
            output=result,
        )

    def _execute_apply(self, request: FeatureRequest, profile: DeploymentProfile) -> FeatureResult:
        return FeatureResult(Outcome.APPLIED, DeploymentEngine(self.profiles).apply(request, profile))

    def _reconcile(self, request: FeatureRequest) -> FeatureResult:
        """Resolve one exact UNKNOWN deploy from verified immutable LIVE state."""
        profile = self.profiles.get(request.arguments["profile"])
        expected_head = request.arguments["expected_source_head"]
        current = _read_current(profile)
        if current is None or current.get("source_head") != expected_head:
            raise PreconditionError("DEPLOYMENT_RECONCILE_CURRENT_MISMATCH")
        if current.get("source_head") != request.arguments["expected_current_source_head"]:
            raise PreconditionError("DEPLOYMENT_RECONCILE_CURRENT_MISMATCH")
        _validate_release(profile, current, require_profile_files=True)
        receipt_path = Path(request.preconditions["reconciliation_receipt"])
        receipt = read_json(receipt_path)
        if (
            receipt is None
            or receipt.get("state") != "ROLLBACK_FAILED"
            or receipt.get("profile") != profile.name
            or receipt.get("source_head") != expected_head
            or receipt.get("manifest_sha256") != current.get("manifest_sha256")
        ):
            raise PreconditionError("DEPLOYMENT_RECONCILE_RECEIPT_MISMATCH")
        controller = RuntimeServiceController(
            runtime_root=profile.runtime_root,
            service_name=profile.service_name,
            port=profile.port,
        )
        service = controller.inspect()
        if (
            service.get("state") != "RUNNING"
            or service.get("release_sha") != expected_head
            or service.get("manifest_sha256") != current.get("manifest_sha256")
        ):
            raise PreconditionError("DEPLOYMENT_RECONCILE_SERVICE_MISMATCH")
        original_operation_id = request.arguments["original_operation_id"]
        return FeatureResult(
            Outcome.APPLIED,
            {
                "profile": profile.name,
                "source_head": expected_head,
                "manifest_sha256": current["manifest_sha256"],
                "service": service,
                "deployment_receipt": str(receipt_path),
                "reconciled_operation_id": original_operation_id,
                "live_state_verified": True,
            },
            reconciled_operation_ids=(original_operation_id,),
        )

    def _reconcile_rollback(self, request: FeatureRequest) -> FeatureResult:
        """Release one UNKNOWN deploy claim only after its rollback is LIVE."""
        profile = self.profiles.get(request.arguments["profile"])
        failed_head = request.arguments["expected_source_head"]
        rollback_head = request.arguments["expected_current_source_head"]
        current = _read_current(profile)
        if current is None or current.get("source_head") != rollback_head:
            raise PreconditionError("DEPLOYMENT_RECONCILE_ROLLBACK_CURRENT_MISMATCH")
        _validate_historic_release(profile, current)
        receipt_path = Path(request.preconditions["reconciliation_receipt"])
        receipt = read_json(receipt_path)
        previous = receipt.get("previous_current") if isinstance(receipt, dict) else None
        if (
            receipt is None
            or receipt.get("state") != "ROLLBACK_FAILED"
            or receipt.get("profile") != profile.name
            or receipt.get("source_head") != failed_head
            or not isinstance(previous, dict)
            or previous.get("source_head") != rollback_head
            or previous.get("manifest_sha256") != current.get("manifest_sha256")
            or previous.get("release_path") != current.get("release_path")
        ):
            raise PreconditionError("DEPLOYMENT_RECONCILE_ROLLBACK_RECEIPT_MISMATCH")
        controller = RuntimeServiceController(
            runtime_root=profile.runtime_root,
            service_name=profile.service_name,
            port=profile.port,
        )
        service = controller.inspect()
        if (
            service.get("state") != "RUNNING"
            or service.get("release_sha") != rollback_head
            or service.get("manifest_sha256") != current.get("manifest_sha256")
        ):
            raise PreconditionError("DEPLOYMENT_RECONCILE_ROLLBACK_SERVICE_MISMATCH")
        original_operation_id = request.arguments["original_operation_id"]
        return FeatureResult(
            Outcome.APPLIED,
            {
                "profile": profile.name,
                "failed_source_head": failed_head,
                "rollback_source_head": rollback_head,
                "manifest_sha256": current["manifest_sha256"],
                "service": service,
                "deployment_receipt": str(receipt_path),
                "reconciled_operation_id": original_operation_id,
                "rollback_live_verified": True,
            },
            reconciled_operation_ids=(original_operation_id,),
        )


class ServiceControlFeature:
    capability = "service_control"

    def __init__(self, profiles: DeploymentProfiles):
        self.profiles = profiles

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        profile_name = str(arguments.get("profile") or "")
        profile = self.profiles.get(profile_name)
        action = str(arguments.get("action") or "")
        expected_release = str(arguments.get("expected_release_sha") or "").lower()
        if action not in {"status", "start", "restart", "stop"}:
            raise PreconditionError("SERVICE_ACTION_INVALID")
        if not _SHA.fullmatch(expected_release):
            raise PreconditionError("SERVICE_RELEASE_SHA_INVALID")
        return FeatureRequest(
            self.capability,
            profile.service_name,
            {"profile": profile.name, "action": action, "expected_release_sha": expected_release},
            (f"service:{profile.service_name.casefold()}",),
            {"expected_release_sha": expected_release},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        profile = self.profiles.get(request.arguments["profile"])
        if request.arguments["action"] == "status":
            return self._execute_locked(request, profile)
        with maintenance_lock(profile.runtime_root):
            return self._execute_locked(request, profile)

    def _execute_locked(self, request: FeatureRequest, profile: DeploymentProfile) -> FeatureResult:
        current = _read_current(profile)
        if current is None or current.get("source_head") != request.arguments["expected_release_sha"]:
            raise PreconditionError("SERVICE_CURRENT_RELEASE_MISMATCH")
        controller = RuntimeServiceController(
            runtime_root=profile.runtime_root,
            service_name=profile.service_name,
            port=profile.port,
        )
        action = request.arguments["action"]
        if action in {"start", "restart"}:
            _validate_profile_start_allowed(self.profiles, profile)
        if action == "status":
            result = controller.inspect()
        elif action == "start":
            result = controller.start(current)
        elif action == "restart":
            result = controller.restart(current)
        else:
            result = controller.stop()
        return FeatureResult(Outcome.APPLIED, {
            "profile": profile.name,
            "action": action,
            "release_sha": current["source_head"],
            "service": result,
        })
