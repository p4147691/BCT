"""Independent guarded rollout for a reviewed exact main release."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import time

from .cli import Maintenance, digest, state_snapshot
from .errors import PreconditionError
from .locking import maintenance_lock
from .registration import _registration
from .release_risk import release_risk, verify_ci
from .releases import _SHA256, _stage_release, _sha256
from .service_runtime import atomic_json, read_json


def _identity(tool, sha, manifest, *, paused):
    state = tool.controller.inspect()
    health = state.get("health", {})
    return (state.get("state") == "RUNNING" and state.get("release_sha") == sha
            and state.get("manifest_sha256") == manifest
            and health.get("ready") is True and health.get("mcp_ready") is True
            and health.get("maintenance_contract") == 1
            and health.get("maintenance_paused") is paused)


def _wait_identity(tool, sha, manifest, *, paused):
    deadline = time.monotonic() + 15
    while not _identity(tool, sha, manifest, paused=paused):
        if time.monotonic() >= deadline:
            raise PreconditionError("RELEASE_LIVE_IDENTITY_NOT_VERIFIED")
        time.sleep(0.25)


def _check_drill(review, candidate, baseline, schema):
    evidence_path = Path(review.get("compatibility_receipt", ""))
    if (not evidence_path.is_file() or evidence_path.is_symlink()
            or digest(evidence_path) != review.get("compatibility_receipt_sha256")):
        raise PreconditionError("RELEASE_COMPATIBILITY_RECEIPT_REQUIRED")
    evidence = read_json(evidence_path)
    if (evidence.get("candidate") != candidate or evidence.get("rollback") != baseline
            or evidence.get("schema_sha256") != schema
            or evidence.get("result_schema_sha256") != review.get("result_schema_sha256", schema)
            or evidence.get("candidate_start") != "PASS" or evidence.get("rollback_start") != "PASS"
            or evidence.get("preserved_history") != "PASS"):
        raise PreconditionError("RELEASE_COMPATIBILITY_NOT_VERIFIED")


def _check_stop_backup(tool, backup, operation_id):
    expected = tool.receipt_path(operation_id).with_suffix(".sqlite")
    if (Path(backup["path"]).resolve() != expected.resolve() or expected.is_symlink()
            or _sha256(expected) != backup["sha256"]):
        raise PreconditionError("RELEASE_STOP_BACKUP_NOT_VERIFIED")


def _recover(tool, prefix, baseline, old_manifest, candidate, manifest, phase):
    """Recover only from an observed release state and this rollout's receipts."""
    state = tool.controller.inspect()
    pointer = tool.current_pointer()["source_head"]
    if phase == "stop" and pointer == baseline and _identity(tool, baseline, old_manifest, paused=True):
        # A stop rejected before its journal started has no external effect.
        if not tool.receipt_path(prefix + "-stop").exists():
            tool.run("resume", operation_id=prefix + "-restore-resume", expected_current=baseline)
            _wait_identity(tool, baseline, old_manifest, paused=False)
            return True
    if phase not in {"activate", "check"} or pointer not in {baseline, candidate}:
        return False
    activation_id = prefix + "-activate"
    activation = read_json(tool.receipt_path(activation_id))
    resolves = None
    if activation is not None and activation["state"] == "UNKNOWN":
        deployment = read_json(tool.root / "deployments" / (candidate + ".json")) or {}
        if (pointer != baseline or state.get("state") not in {"STOPPED", "STOPPED_STALE_RECEIPT"}
                or deployment.get("state") != "ROLLED_BACK" or deployment.get("rollback_verified") is not True
                or deployment.get("previous_source_head") != baseline
                or deployment.get("source_head") != candidate
                or deployment.get("manifest_sha256") != manifest):
            return False
        resolves = activation_id
    elif phase == "check" and pointer == candidate and state.get("state") == "RUNNING":
        if not _identity(tool, candidate, manifest, paused=True):
            return False
        tool.run("stop", operation_id=prefix + "-rollback-stop", expected_current=candidate)
    elif not (activation is None and pointer == baseline
              and state.get("state") in {"STOPPED", "STOPPED_STALE_RECEIPT"}):
        return False
    tool.run("recover", operation_id=prefix + "-recover", expected_current=pointer,
             target=baseline, resolves=resolves)
    _wait_identity(tool, baseline, old_manifest, paused=True)
    tool.run("resume", operation_id=prefix + "-restore-resume", expected_current=baseline)
    _wait_identity(tool, baseline, old_manifest, paused=False)
    return True


def rollout(tool, candidate, baseline, run_id, prefix, *, review=None, source_worktree=None):
    """Register and deploy within one explicitly requested, journaled window."""
    tool.receipt_path(prefix + "-restore-resume")
    entry_path = tool.config_path.parent.parent / "operational-entry.json"
    entry = read_json(entry_path)
    if not entry or Path(entry["config"]).resolve() != tool.config_path:
        raise PreconditionError("RELEASE_OPERATIONAL_ENTRY_CHANGED")
    entry_hash = digest(entry_path)
    risk = release_risk(tool.profile.source_root, baseline, candidate)
    journal = tool.root / "maintenance" / "rollouts" / (prefix + ".json")
    request = {"candidate": candidate, "baseline": baseline, "run_id": run_id,
               "source_worktree": source_worktree}
    prior = read_json(journal)
    if prior:
        if prior.get("request") != request or prior.get("state") in {"STARTED", "UNKNOWN"}:
            raise PreconditionError("RELEASE_RECONCILE_REQUIRED")
        return prior
    if not set(risk["paths"]).intersection(tool.profile.files):
        raise PreconditionError("RELEASE_NO_LIVE_PAYLOAD_CHANGE")
    ci = verify_ci(Path(tool.config["policy_path"]), candidate, run_id)

    with maintenance_lock(tool.root):
        if digest(entry_path) != entry_hash or tool.current_pointer()["source_head"] != baseline:
            raise PreconditionError("RELEASE_OPERATIONAL_ENTRY_CHANGED")
        for path in journal.parent.glob("*.json"):
            if (read_json(path) or {}).get("state") in {"STARTED", "UNKNOWN"}:
                raise PreconditionError("RELEASE_RECONCILE_REQUIRED")
        tool.check_pending_effects("activate")
        old = tool.verify(baseline)
        old_manifest = old["manifest_sha256"]
        if (baseline not in tool.config.get("admission_releases", ())
                or not _identity(tool, baseline, old_manifest, paused=False)
                or any((tool.root / flag).exists() for flag in ("BCT_CORE_SUPERVISOR.STOP", "BCT_MAINTENANCE.PAUSE"))):
            raise PreconditionError("RELEASE_RUNNING_BASELINE_NOT_VERIFIED")
        tool.quiescent()
        schema = old["database"]["schema_sha256"]
        pins = {"candidate": candidate, "rollback": baseline, "config_sha256": digest(tool.config_path),
                "rollback_manifest_sha256": old_manifest, "schema_sha256": schema,
                "admission_releases": [baseline, candidate]}
        if risk["level"] == "HIGH":
            if not review or any(review.get(key) != value for key, value in pins.items()):
                raise PreconditionError("RELEASE_HIGH_REVIEW_REQUIRED")
            _check_drill(review, candidate, baseline, schema)
        plan, profile, manifest = _registration(tool, review if risk["level"] == "HIGH" else pins,
                                                source_worktree, automatic=risk["level"] != "HIGH")
        result_schema = review.get("result_schema_sha256", schema) if risk["level"] == "HIGH" else schema
        if result_schema != schema:
            if not isinstance(result_schema, str) or not _SHA256.fullmatch(result_schema):
                raise PreconditionError("RELEASE_RESULT_SCHEMA_INVALID")
            for sha in (baseline, candidate):
                schemas = plan["settings"]["verified_releases"][sha]["compatible_schema_sha256"]
                if result_schema not in schemas:
                    schemas.append(result_schema)

        config_path = tool.config_path.with_name("operational-" + candidate + ".json")
        python_path = tool.root / "config" / "core-python-pins.json"
        bindings = read_json(python_path)
        target_hash = manifest["manifest_sha256"]
        if bindings:
            bindings = deepcopy(bindings)
            releases = bindings["releases"]
            if baseline in releases:
                candidate_pin = {**releases[baseline], "manifest_sha256": target_hash}
                if releases.get(candidate, candidate_pin) != candidate_pin:
                    raise PreconditionError("RELEASE_PYTHON_PIN_CONFLICT")
                releases[candidate] = candidate_pin
        previous_config = read_json(config_path)
        if previous_config is not None and previous_config != plan["settings"]:
            raise PreconditionError("RELEASE_CONFIG_ALREADY_EXISTS")
        if any(tool.receipt_path(prefix + "-" + action).exists() for action in
               ("pause", "stop", "activate", "resume", "rollback-stop", "recover", "restore-resume")):
            raise PreconditionError("RELEASE_OPERATION_ID_ALREADY_USED")
        receipt = {"state": "STARTED", "action": "release", "receipt_prefix": prefix,
                   "journal": str(journal), "request": request, "risk": risk, "ci": ci,
                   "manifest_sha256": target_hash, "rollback_manifest_sha256": old_manifest,
                   "schema_sha256": schema, "result_schema_sha256": result_schema, "started_at": time.time()}
        if risk["level"] == "HIGH":
            receipt["compatibility_receipt_sha256"] = review["compatibility_receipt_sha256"]
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream)
            stream.flush()
            os.fsync(stream.fileno())
        phase = "register"
        try:
            _stage_release(profile, manifest)
            atomic_json(config_path, plan["settings"])
            if bindings:
                atomic_json(python_path, bindings)
            registered = Maintenance(config_path)
            candidate_proof = registered.verify(candidate)
            if candidate_proof["manifest_sha256"] != target_hash or candidate_proof["python_binding"] != old["python_binding"]:
                raise PreconditionError("RELEASE_REGISTERED_BINDING_CHANGED")
            phase = "pause"
            registered.run("pause", operation_id=prefix + "-pause", expected_current=baseline)
            phase = "stop"
            _wait_identity(registered, baseline, old_manifest, paused=True)
            stop = registered.run("stop", operation_id=prefix + "-stop", expected_current=baseline)
            receipt["backup"] = stop["backup"]
            _check_stop_backup(registered, stop["backup"], prefix + "-stop")
            phase = "activate"
            registered.run("activate", operation_id=prefix + "-activate", expected_current=baseline,
                           target=candidate, source_worktree=source_worktree)
            phase = "check"
            _wait_identity(registered, candidate, target_hash, paused=True)
            if state_snapshot(tool.root)["schema_sha256"] != result_schema:
                raise PreconditionError("RELEASE_RUNTIME_SCHEMA_CHANGED")
            phase = "resume"
            registered.run("resume", operation_id=prefix + "-resume", expected_current=candidate)
            _wait_identity(registered, candidate, target_hash, paused=False)
            if digest(entry_path) != entry_hash:
                raise PreconditionError("RELEASE_OPERATIONAL_ENTRY_CHANGED")
            atomic_json(entry_path, {**entry, "config": str(config_path)})
            service = registered.controller.inspect()
            receipt.update(state="COMPLETED", pid=service["pid"], generation=service["generation"])
        except Exception as exc:
            receipt.update(state="FAILED" if phase == "register" else "UNKNOWN", phase=phase, error=str(exc))
            if phase not in {"register", "pause", "resume"}:
                try:
                    if _recover(registered, prefix, baseline, old_manifest, candidate, target_hash, phase):
                        receipt["state"] = "ROLLED_BACK"
                except Exception as recovery_error:
                    receipt["recovery_error"] = str(recovery_error)
        receipt["operations"] = {}
        for action in ("pause", "stop", "activate", "resume", "rollback-stop", "recover", "restore-resume"):
            path = tool.receipt_path(prefix + "-" + action)
            if path.is_file():
                receipt["operations"][action] = {"path": str(path), "sha256": digest(path)}
        receipt["finished_at"] = time.time()
        atomic_json(journal, receipt)
        return receipt

