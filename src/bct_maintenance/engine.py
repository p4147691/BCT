from __future__ import annotations
from pathlib import Path
from typing import Any
import time
from .locking import maintenance_lock
from .errors import PreconditionError, UnknownEffectError
from .service_runtime import RuntimeServiceController, atomic_json
from .releases import (
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

class DeploymentEngine:
    """Shared activation/automatic rollback engine; no Work, Store or BCT import."""
    def __init__(self, profiles):
        self.profiles = profiles

    def apply(self, request, profile):
        with maintenance_lock(profile.runtime_root):
            return self._apply(request, profile)

    def _apply(self, request, profile: DeploymentProfile) -> dict[str, Any]:
        source_worktree = request.arguments.get('source_worktree')
        head = request.arguments['expected_source_head']
        manifest = _validate_source(profile, head, Path(source_worktree) if source_worktree else None)
        current = _read_current(profile)
        current_head = current.get('source_head') if current else None
        if current_head != request.arguments['expected_current_source_head']:
            raise PreconditionError('DEPLOYMENT_CURRENT_SHA_MISMATCH')
        controller = RuntimeServiceController(runtime_root=profile.runtime_root, service_name=profile.service_name, port=profile.port)
        service_before = controller.inspect()
        if profile.protected_activation_required and service_before.get('state') == 'RUNNING':
            _validate_profile_start_allowed(self.profiles, profile)
        if current_head == manifest['source_head']:
            _validate_release(profile, current, require_profile_files=True)
            _publish_runtime_recovery_scripts(profile, current)
            if request.arguments['restart']:
                if service_before.get('state') == 'RUNNING' and service_before.get('release_sha') == current_head:
                    _record_protected_cutover(self.profiles, profile, manifest['source_head'], service_before)
                    return {'profile': profile.name, 'source_head': current_head, 'manifest_sha256': manifest['manifest_sha256'], 'service': service_before, 'already_current': True}
                _validate_protected_deploy_gate(self.profiles, profile, request.arguments['expected_source_head'], acquire_lock=False)
                _begin_protected_cutover(self.profiles, profile, request.arguments['expected_source_head'])
                service = _start_with_one_safe_retry(controller, current)
                try:
                    _record_protected_cutover(self.profiles, profile, manifest['source_head'], service)
                except Exception:
                    controller.stop()
                    raise
            else:
                service = service_before
            return {'profile': profile.name, 'source_head': current_head, 'manifest_sha256': manifest['manifest_sha256'], 'service': service, 'already_current': True}
        release = _stage_release(profile, manifest)
        if source_worktree:
            _validate_source_repository(profile, head, Path(source_worktree))
        receipt_path = profile.runtime_root / 'deployments' / (manifest['source_head'] + '.json')
        receipt = {'profile': profile.name, 'state': 'PREPARED', 'source_head': manifest['source_head'], 'manifest_sha256': manifest['manifest_sha256'], 'previous_source_head': current_head, 'previous_current': current, 'release_path': release['release_path'], 'prepared_at': time.time()}
        atomic_json(receipt_path, receipt)
        activated = False
        try:
            _write_current(profile, release)
            activated = True
            current_after = _read_current(profile)
            if current_after is None or current_after.get('source_head') != manifest['source_head']:
                raise RuntimeError('DEPLOYMENT_CURRENT_POST_STATE_INVALID')
            _publish_runtime_recovery_scripts(profile, release)
            if request.arguments['restart']:
                _validate_protected_deploy_gate(self.profiles, profile, request.arguments['expected_source_head'], acquire_lock=False)
                if service_before.get('state') == 'RUNNING':
                    controller.stop()
                _begin_protected_cutover(self.profiles, profile, request.arguments['expected_source_head'])
                service = _start_with_one_safe_retry(controller, release)
                try:
                    _record_protected_cutover(self.profiles, profile, manifest['source_head'], service)
                except Exception:
                    controller.stop()
                    raise
            else:
                service = controller.inspect()
            completed = {**receipt, 'state': 'COMPLETED', 'completed_at': time.time(), 'service': service}
            atomic_json(receipt_path, completed)
            return {'profile': profile.name, 'source_head': manifest['source_head'], 'manifest_sha256': manifest['manifest_sha256'], 'release_path': release['release_path'], 'previous_source_head': current_head, 'service': service, 'deployment_receipt': str(receipt_path), 'already_current': False}
        except Exception as exc:
            if not activated:
                raise
            try:
                target_state = controller.inspect()
                if target_state.get('state') == 'RUNNING' and target_state.get('release_sha') == manifest['source_head']:
                    controller.stop()
                _write_current(profile, current)
                if current is not None:
                    _publish_runtime_recovery_scripts(profile, current)
                if request.arguments['restart'] and service_before.get('state') == 'RUNNING':
                    assert current is not None
                    restored = _start_with_one_safe_retry(controller, current)
                    if restored.get('release_sha') != current_head:
                        raise RuntimeError('DEPLOYMENT_ROLLBACK_SERVICE_MISMATCH')
                current_rollback = _read_current(profile)
                if (current_rollback.get('source_head') if current_rollback else None) != current_head:
                    raise RuntimeError('DEPLOYMENT_ROLLBACK_POINTER_MISMATCH')
                atomic_json(receipt_path, {**receipt, 'state': 'ROLLED_BACK', 'failed_at': time.time(), 'failure': type(exc).__name__ + ':' + str(exc), 'rollback_verified': True})
            except Exception as rollback_exc:
                atomic_json(receipt_path, {**receipt, 'state': 'ROLLBACK_FAILED', 'failed_at': time.time(), 'failure': type(exc).__name__ + ':' + str(exc), 'rollback_failure': type(rollback_exc).__name__ + ':' + str(rollback_exc)})
                raise UnknownEffectError('DEPLOYMENT_ROLLBACK_UNVERIFIED:' + str(receipt_path)) from rollback_exc
            raise ConfirmedFailure('DEPLOYMENT_ROLLED_BACK:' + str(receipt_path), release_claims=True) from exc
