"""Local, explicitly configured maintenance. No BCT server or Store dependency."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from types import SimpleNamespace
import psutil

from .admission import admission_fence, assert_quiescent
from .engine import DeploymentEngine
from .errors import PreconditionError, UnknownEffectError
from .locking import maintenance_lock
from .releases import (DeploymentProfiles, _read_current, _target_profile,
                       _validate_source, _validate_historic_release,
                       _validate_profile_start_allowed, _write_current)
from .service_runtime import (RuntimeServiceController, RuntimeWriterLock,
                              atomic_json, process_identity, read_json)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state_snapshot(root):
    """Read only: never instantiate Store, migrate, release claims or replay work."""
    path = Path(root) / "state" / "state.sqlite"
    if not path.is_file():
        raise PreconditionError("MAINTENANCE_STATE_DB_MISSING")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        schema_hash = hashlib.sha256(json.dumps(schema, ensure_ascii=True).encode()).hexdigest()
        active = db.execute("SELECT COUNT(*) FROM operations WHERE state IN ('RECORDED','RUNNING')").fetchone()[0]
        claims = db.execute("SELECT COUNT(*) FROM resource_claims WHERE unresolved=1").fetchone()[0]
        return {"schema_sha256": schema_hash, "running_operations": active,
                "unresolved_claims": claims}


class Maintenance:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve(strict=True)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if self.config.get("schema") != 1:
            raise PreconditionError("MAINTENANCE_CONFIG_VERSION")
        policy = Path(self.config["policy_path"])
        if not policy.is_absolute() or digest(policy) != self.config["policy_sha256"]:
            raise PreconditionError("MAINTENANCE_POLICY_NOT_PINNED")
        self.profiles = DeploymentProfiles(policy)
        self.profile = self.profiles.get(self.config["profile"])
        self.root = self.profile.runtime_root
        if self.root != Path(self.config["runtime_root"]).resolve():
            raise PreconditionError("MAINTENANCE_RUNTIME_MISMATCH")
        if Path(sys.executable).resolve() != Path(self.config["python_path"]).resolve():
            raise PreconditionError("MAINTENANCE_PYTHON_MISMATCH")
        self.controller = RuntimeServiceController(runtime_root=self.root,
                                                   service_name=self.profile.service_name,
                                                   port=self.profile.port)

    def current_pointer(self):
        # Recovery must be able to observe a damaged payload without importing or
        # validating it. The destination release is always independently validated.
        current = read_json(self.root / "current.json")
        if current is None:
            raise PreconditionError("MAINTENANCE_CURRENT_POINTER_MISSING_OR_INVALID")
        sha = current.get("source_head", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise PreconditionError("MAINTENANCE_CURRENT_POINTER_SHA_INVALID")
        if Path(current.get("release_path", "")).resolve() != self.root / "releases" / sha:
            raise PreconditionError("MAINTENANCE_CURRENT_POINTER_PATH_INVALID")
        return current

    def status(self):
        try:
            service = self.controller.inspect()
        except Exception as exc:
            service = {"state": "UNVERIFIED", "reason": str(exc)}
        try:
            database = state_snapshot(self.root)
        except Exception as exc:
            database = {"state": "UNVERIFIED", "reason": str(exc)}
        try:
            current = self.current_pointer()
        except Exception as exc:
            current = {"state": "UNVERIFIED", "reason": str(exc)}
        return {"runtime_root": str(self.root), "current": current,
                "service": service, "database": database,
                "supervisor_stop_flag": (self.root / "BCT_CORE_SUPERVISOR.STOP").is_file()}

    def pinned_release(self, sha):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise PreconditionError("MAINTENANCE_RELEASE_SHA_INVALID")
        pins = self.config.get("verified_releases", {})
        pin = pins.get(sha)
        if not isinstance(pin, dict):
            raise PreconditionError("MAINTENANCE_RELEASE_NOT_APPROVED")
        release = read_json(self.root / "releases" / sha / "manifest.json")
        if release is None or release.get("manifest_sha256") != pin.get("manifest_sha256"):
            raise PreconditionError("MAINTENANCE_RELEASE_PIN_MISMATCH")
        _validate_historic_release(self.profile, release)
        return release

    def verify(self, sha):
        release = self.pinned_release(sha)
        state = state_snapshot(self.root)
        self.compatible(sha, state)
        return {"release_sha": sha, "manifest_sha256": release["manifest_sha256"],
                "database": state, "effect": "NONE_READ_ONLY"}

    def compatible(self, sha, state):
        pin = self.config.get("verified_releases", {}).get(sha, {})
        if state["schema_sha256"] not in pin.get("compatible_schema_sha256", []):
            raise PreconditionError("MAINTENANCE_DB_COMPATIBILITY_NOT_VERIFIED")

    def quiescent(self):
        state = state_snapshot(self.root)
        with closing(sqlite3.connect((self.root / "state/state.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
            state.update(assert_quiescent(db, self.config.get("retained_history_sha256")))
        return state

    def backup(self, destination):
        path = self.root / "state" / "state.sqlite"
        if destination.exists():
            raise PreconditionError("MAINTENANCE_BACKUP_ALREADY_EXISTS")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise PreconditionError("MAINTENANCE_BACKUP_INVALID")
        return {"path": str(destination), "sha256": digest(destination)}

    def reconcile(self, operation_id):
        receipt = read_json(self.receipt_path(operation_id))
        if receipt is None:
            raise PreconditionError("MAINTENANCE_RECEIPT_MISSING")
        # Observation never changes UNKNOWN into permission to repeat an effect.
        return {"receipt": receipt, "observed": self.status(), "replayed": False}

    def receipt_path(self, operation_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", operation_id):
            raise PreconditionError("MAINTENANCE_OPERATION_ID_INVALID")
        return self.root / "maintenance" / (operation_id + ".json")

    def unresponsive_identity(self, fingerprint):
        receipt = read_json(self.root / "service.json") or {}
        identity = self.controller._receipt_identity(receipt)
        if identity is None or not fingerprint or identity.fingerprint != fingerprint:
            raise PreconditionError("MAINTENANCE_PROCESS_APPROVAL_MISMATCH")
        process = psutil.Process(identity.pid)
        if process_identity(identity.pid) != identity:
            raise PreconditionError("MAINTENANCE_PROCESS_IDENTITY_MISMATCH")
        argv = process.cmdline()
        if "bct.runtime_server" not in argv or "--runtime-root" not in argv:
            raise PreconditionError("MAINTENANCE_NOT_CORE_PROCESS")
        index = argv.index("--runtime-root")
        if index + 1 >= len(argv) or Path(argv[index + 1]).resolve() != self.root:
            raise PreconditionError("MAINTENANCE_PROCESS_ROOT_MISMATCH")
        try:
            self.controller.inspect()
        except PreconditionError as exc:
            if str(exc) != "SERVICE_PROCESS_RUNNING_WITHOUT_HEALTH":
                raise
        else:
            raise PreconditionError("MAINTENANCE_PROCESS_NOT_UNRESPONSIVE")
        return process, identity, receipt

    def check_pending_effects(self, action, resolves=None):
        unresolved = []
        journal = self.root / "maintenance"
        for item in journal.glob("*.json"):
            entry = read_json(item)
            if entry is None:
                raise PreconditionError("MAINTENANCE_JOURNAL_INVALID")
            if entry.get("state") in {"STARTED", "UNKNOWN"}:
                # A completed recovery references, but never rewrites, the old receipt.
                covered = any((read_json(other) or {}).get("state") == "COMPLETED"
                              and (read_json(other) or {}).get("request", {}).get("resolves") == item.stem
                              for other in journal.glob("*.json"))
                if not covered:
                    unresolved.append(item.stem)
        if unresolved and not (action == "recover" and unresolved == [resolves]):
            raise PreconditionError("MAINTENANCE_PRIOR_EFFECT_UNRESOLVED")
        if resolves and resolves not in unresolved:
            raise PreconditionError("MAINTENANCE_RESOLUTION_TARGET_INVALID")

    def run(self, action, *, operation_id, expected_current, target=None, expected_fingerprint=None, resolves=None, source_worktree=None):
        if self.config.get("enabled") is not True or action not in self.config.get("allowed_actions", []):
            raise PreconditionError("MAINTENANCE_ACTION_NOT_AUTHORIZED")
        if action not in {"pause", "resume", "start", "stop", "bootstrap-stop", "stop-unresponsive", "recover", "activate", "backup"}:
            raise PreconditionError("MAINTENANCE_ACTION_INVALID")
        if action != "pause" and not (self.root / "BCT_CORE_SUPERVISOR.STOP").is_file():
            raise PreconditionError("MAINTENANCE_SUPERVISOR_NOT_PAUSED")
        if action != "pause" and not (self.root / "BCT_MAINTENANCE.PAUSE").is_file():
            raise PreconditionError("MAINTENANCE_ADMISSION_NOT_PAUSED")
        path = self.receipt_path(operation_id)
        request = {"action": action, "operation_id": operation_id,
                   "expected_current": expected_current, "target": target,
                   "expected_fingerprint": expected_fingerprint,
                   "resolves": resolves, "source_worktree": source_worktree,
                   "config_sha256": digest(self.config_path)}
        with maintenance_lock(self.root):
            old = read_json(path)
            if old is not None:
                if old.get("request") != request:
                    raise PreconditionError("MAINTENANCE_OPERATION_ID_REUSED")
                if old.get("state") == "COMPLETED":
                    return {**old, "replayed": False, "observed": self.status()}
                raise PreconditionError("MAINTENANCE_RECONCILE_REQUIRED")
            self.check_pending_effects(action, resolves)
            current = self.current_pointer()
            if current is None or current.get("source_head") != expected_current:
                raise PreconditionError("MAINTENANCE_STALE_CURRENT")
            state = self.quiescent()
            _validate_profile_start_allowed(self.profiles, self.profile)
            if action in {"stop", "bootstrap-stop", "stop-unresponsive"} and expected_current not in self.config.get("admission_releases", []):
                raise PreconditionError("MAINTENANCE_ADMISSION_RELEASE_NOT_VERIFIED")
            release = None
            if action in {"start", "recover"}:
                target = expected_current if action == "start" else target
                release = self.pinned_release(target or "")
                self.compatible(target, state)
            if action == "activate":
                # Same source / local-main / manifest checks as BCT deployment.
                profile = _target_profile(self.profile, target or "", Path(source_worktree) if source_worktree else None)
                if profile.protected_activation_required:
                    raise PreconditionError("MAINTENANCE_CUTOVER_REQUIRES_EXISTING_APPROVAL_ROUTE")
                source = _validate_source(profile, target, Path(source_worktree) if source_worktree else None)
                pin = self.config.get("verified_releases", {}).get(target, {})
                if source["manifest_sha256"] != pin.get("manifest_sha256"):
                    raise PreconditionError("MAINTENANCE_CANDIDATE_NOT_VERIFIED")
                self.compatible(target, state)
                self.pinned_release(expected_current)
                self.compatible(expected_current, state)
            unresponsive = None
            if action == "stop-unresponsive":
                unresponsive = self.unresponsive_identity(expected_fingerprint)
                before = unresponsive[2]
            else:
                before = self.controller.inspect()
            if action == "bootstrap-stop":
                # First transition is tied to one reviewed legacy release AND
                # one live process identity; never a generic pause bypass.
                pin = self.config.get("bootstrap", {})
                if (pin.get("release_sha") != expected_current
                        or not expected_fingerprint
                        or pin.get("fingerprint") != expected_fingerprint
                        or before.get("fingerprint") != expected_fingerprint
                        or before.get("state") != "RUNNING"):
                    raise PreconditionError("MAINTENANCE_BOOTSTRAP_IDENTITY_MISMATCH")
                self.pinned_release(expected_current)
            if action == "stop" and before["state"] == "RUNNING":
                health = before.get("health", {})
                if health.get("maintenance_contract") != 1 or health.get("maintenance_paused") is not True:
                    raise PreconditionError("MAINTENANCE_ADMISSION_NOT_ACKNOWLEDGED")
            if action in {"start", "recover", "activate"} and before["state"] not in {"STOPPED", "STOPPED_STALE_RECEIPT"}:
                raise PreconditionError("MAINTENANCE_STOP_CORE_FIRST")
            flags = [self.root / name for name in ("BCT_CORE_SUPERVISOR.STOP", "BCT_MAINTENANCE.PAUSE")]
            if action in {"pause", "resume"}:
                for flag in flags:
                    if flag.exists() and flag.read_text(encoding="utf-8") != "independent-maintenance\n":
                        raise PreconditionError("MAINTENANCE_FLAG_OWNED_ELSEWHERE")
                if action == "resume":
                    self.pinned_release(expected_current)
                    if (before.get("state") != "RUNNING"
                            or before.get("release_sha") != expected_current
                            or before.get("health", {}).get("maintenance_contract") != 1):
                        raise PreconditionError("MAINTENANCE_RESUME_HEALTH_UNVERIFIED")
            path.parent.mkdir(parents=True, exist_ok=True)
            receipt = {"schema": 1, "request": request, "state": "STARTED",
                       "previous_current": current, "before": before, "started_at": time.time()}
            # Exclusive initial creation: interrupted records are never overwritten.
            with path.open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                if action in {"pause", "resume"}:
                    for flag in flags:
                        if action == "pause":
                            if not flag.exists():
                                with flag.open("x", encoding="utf-8", newline="\n") as stream:
                                    stream.write("independent-maintenance\n")
                                    stream.flush()
                                    os.fsync(stream.fileno())
                        else:
                            flag.unlink()
                    result = {"admission_paused": action == "pause"}
                elif action == "stop-unresponsive":
                    process, identity, before = self.unresponsive_identity(expected_fingerprint)
                    # psutil checks PID reuse; terminate only this exact process, never a tree.
                    process.terminate()
                    process.wait(timeout=10)
                    if process_identity(identity.pid) == identity:
                        raise UnknownEffectError("MAINTENANCE_TERMINATION_UNVERIFIED")
                    if self.controller._health() is not None:
                        raise UnknownEffectError("MAINTENANCE_ENDPOINT_STILL_PRESENT")
                    result = {**before, "state": "STOPPED", "stopped_at": time.time()}
                    atomic_json(self.root / "service.json", result)
                elif action in {"stop", "bootstrap-stop"}:
                    with admission_fence(self.root) as db:
                        receipt["admission"] = assert_quiescent(db, self.config.get("retained_history_sha256"))
                        atomic_json(path, receipt)
                        live = self.controller.inspect()
                        if (live.get("fingerprint") != before.get("fingerprint")
                                or self.current_pointer().get("source_head") != expected_current):
                            raise PreconditionError("MAINTENANCE_PROCESS_CHANGED")
                        result = self.controller.stop(shutdown_timeout=45)
                    with RuntimeWriterLock(self.root / "state/core-writer.lock"):
                        receipt["after_admission"] = self.quiescent()
                        receipt["backup"] = self.backup(path.with_suffix(".sqlite"))
                else:
                    # Prove the Core DB writer is absent before snapshot/pointer effects.
                    with RuntimeWriterLock(self.root / "state" / "core-writer.lock"):
                        self.quiescent()
                        receipt["backup"] = self.backup(path.with_suffix(".sqlite"))
                        atomic_json(path, receipt)
                        if action == "recover":
                            _write_current(self.profile, release)
                    if action in {"start", "recover"}:
                        result = self.controller.start(release)
                    elif action == "activate":
                        request_object = SimpleNamespace(arguments={
                            "expected_source_head": target, "expected_current_source_head": expected_current,
                            "restart": True, "source_worktree": source_worktree})
                        result = DeploymentEngine(self.profiles).apply(request_object, profile)
                    else:
                        result = receipt["backup"]
                completed = {**receipt, "state": "COMPLETED", "result": result, "completed_at": time.time()}
                atomic_json(path, completed)
                return completed
            except Exception as exc:
                # Do not rewind DB or guess whether a process/external effect occurred.
                atomic_json(path, {**receipt, "state": "UNKNOWN", "error": str(exc)})
                raise UnknownEffectError("MAINTENANCE_RECONCILE_REQUIRED:" + operation_id) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("action", choices=("status", "verify", "reconcile", "pause", "resume", "start", "stop", "bootstrap-stop", "stop-unresponsive", "recover", "activate", "backup"))
    parser.add_argument("--operation-id")
    parser.add_argument("--expected-current")
    parser.add_argument("--target")
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--resolves")
    parser.add_argument("--source-worktree")
    args = parser.parse_args(argv)
    try:
        tool = Maintenance(args.config)
        if args.action == "status":
            result = tool.status()
        elif args.action == "verify":
            result = tool.verify(args.target or "")
        elif args.action == "reconcile":
            result = tool.reconcile(args.operation_id or "")
        else:
            result = tool.run(args.action, operation_id=args.operation_id or "",
                              expected_current=args.expected_current, target=args.target,
                              expected_fingerprint=args.expected_fingerprint, resolves=args.resolves,
                              source_worktree=args.source_worktree)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
