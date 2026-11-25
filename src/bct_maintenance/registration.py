"""Render a reviewed Core release registration for an administrator to install."""
from copy import deepcopy
from pathlib import Path
import re

from .cli import digest, state_snapshot
from .errors import PreconditionError
from .releases import (
    _target_profile,
    _validate_historic_release,
    _validate_profile_start_allowed,
    _validate_source,
)
from .service_runtime import read_json


def registration_plan(tool, review, source_worktree):
    """Compare exact operator-reviewed pins before rendering replacement settings."""
    return _registration(tool, review, source_worktree)[0]


def _registration(tool, review, source_worktree, *, automatic=False):
    if tool.config.get("enabled") is not True or "activate" not in tool.config.get("allowed_actions", ()):
        raise PreconditionError("MAINTENANCE_ACTION_NOT_AUTHORIZED")
    if tool.profile.protected_activation_required:
        raise PreconditionError("MAINTENANCE_CUTOVER_REQUIRES_EXISTING_APPROVAL_ROUTE")
    _validate_profile_start_allowed(tool.profiles, tool.profile)
    before = review["config_sha256"]
    if digest(tool.config_path) != before or read_json(tool.config_path) != tool.config:
        raise PreconditionError("MAINTENANCE_CONFIG_CHANGED")
    candidate = review["candidate"]
    rollback = review["rollback"]
    if candidate == rollback or any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (candidate, rollback)):
        raise PreconditionError("MAINTENANCE_REGISTRATION_SHA_INVALID")
    pointer = tool.current_pointer()
    if pointer["source_head"] != rollback:
        raise PreconditionError("MAINTENANCE_STALE_CURRENT")
    schema = review["schema_sha256"]
    if state_snapshot(tool.root)["schema_sha256"] != schema:
        raise PreconditionError("MAINTENANCE_DB_COMPATIBILITY_NOT_VERIFIED")

    source = Path(source_worktree) if source_worktree is not None else None
    profile = _target_profile(tool.profile, candidate, source)
    manifest = _validate_source(profile, candidate, source)
    if not automatic and manifest["manifest_sha256"] != review["candidate_manifest_sha256"]:
        raise PreconditionError("MAINTENANCE_CANDIDATE_NOT_VERIFIED")
    retained = read_json(tool.root / "releases" / rollback / "manifest.json")
    if (retained is None or retained.get("source_head") != rollback
            or retained.get("manifest_sha256") != review["rollback_manifest_sha256"]
            or pointer.get("manifest_sha256") != review["rollback_manifest_sha256"]):
        raise PreconditionError("MAINTENANCE_RELEASE_PIN_MISMATCH")
    _validate_historic_release(tool.profile, retained)

    settings = deepcopy(tool.config)
    releases = settings.setdefault("verified_releases", {})
    for sha, verified in ((candidate, manifest), (rollback, retained)):
        manifest_hash = verified["manifest_sha256"]
        existing = releases.get(sha)
        if existing is not None and (not isinstance(existing, dict)
                                     or existing.get("manifest_sha256") != manifest_hash):
            raise PreconditionError("MAINTENANCE_RELEASE_PIN_CONFLICT")
        pin = releases.setdefault(sha, {"manifest_sha256": manifest_hash})
        schemas = pin.setdefault("compatible_schema_sha256", [])
        if schema not in schemas:
            schemas.append(schema)
    # Stop permission is independent of the release pin and requires explicit review.
    admission = settings.setdefault("admission_releases", [])
    for sha in review.get("admission_releases", ()):
        if sha not in (candidate, rollback):
            raise PreconditionError("MAINTENANCE_ADMISSION_RELEASE_NOT_VERIFIED")
        if sha not in admission:
            admission.append(sha)
    if digest(tool.config_path) != before or tool.current_pointer() != pointer:
        raise PreconditionError("MAINTENANCE_REGISTRATION_STATE_CHANGED")
    return {"effect": "NONE_READ_ONLY", "previous_config_sha256": before, "settings": settings}, profile, manifest
