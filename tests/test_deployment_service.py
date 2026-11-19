from __future__ import annotations

import asyncio
import ast
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import uvicorn

from bct import BCT
from bct.core.models import (
    ConfirmedFailure,
    ConflictError,
    Outcome,
    Principal,
    UnknownEffectError,
)
from bct.features.deploy import (
    DeploymentProfile,
    DeploymentProfiles,
    _publish_runtime_recovery_scripts,
    _start_with_one_safe_retry,
)
from bct.runtime_server import (
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    build_server_config,
    request_server_shutdown,
)
from bct.service_runtime import RuntimeServiceController, atomic_json, process_identity, read_json


def git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=True,
    )
    return process.stdout.strip()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def wait_for_loop_schema(controller, *, timeout=15, on_pending=None):
    """Test-fixture barrier, not a claim that HTTP readiness freezes the schema.

    The first completed Loop cycle follows construction of its durable ledgers.
    A fresh, empty test runtime has no work to dispatch. Wait for that existing
    completion signal rather than a delay or repeated matching schema hashes.
    """
    deadline = time.monotonic() + timeout
    while True:
        observed = controller.inspect()
        if observed.get("state") != "RUNNING":
            raise AssertionError("TEST_CORE_NOT_RUNNING:" + repr(observed))
        health = observed.get("health", {})
        loop = health.get("loop_recipe_recovery", {})
        if loop.get("runs", 0) > 0:
            if loop.get("last_error") is not None:
                raise AssertionError("TEST_LOOP_INITIALIZATION_FAILED:" + repr(loop))
            return health
        if time.monotonic() >= deadline:
            raise AssertionError("TEST_SCHEMA_INITIALIZATION_TIMEOUT:" + repr(health))
        if on_pending is not None:
            on_pending()
        time.sleep(0.05)


class LoopSchemaBarrierTests(unittest.TestCase):
    def test_http_ready_does_not_release_barrier(self):
        pending = {"state": "RUNNING", "health": {
            "ready": True, "loop_recipe_recovery": {"runs": 0}}}
        completed = {"state": "RUNNING", "health": {
            "ready": True, "loop_recipe_recovery": {"runs": 1, "last_error": None}}}
        controller = Mock()
        controller.inspect.side_effect = [pending, completed]
        on_pending = Mock()
        with patch("test_deployment_service.time.sleep"):
            self.assertEqual(wait_for_loop_schema(controller, on_pending=on_pending),
                             completed["health"])
        on_pending.assert_called_once_with()

    def test_initialization_timeout_fails_closed(self):
        controller = Mock()
        controller.inspect.return_value = {"state": "RUNNING", "health": {
            "ready": True, "loop_recipe_recovery": {"runs": 0}}}
        with self.assertRaisesRegex(AssertionError, "TEST_SCHEMA_INITIALIZATION_TIMEOUT"):
            wait_for_loop_schema(controller, timeout=0)

    def test_failed_loop_cycle_is_not_initialization_success(self):
        controller = Mock()
        controller.inspect.return_value = {"state": "RUNNING", "health": {
            "loop_recipe_recovery": {"runs": 1, "last_error": "OperationalError"}}}
        with self.assertRaisesRegex(AssertionError, "TEST_LOOP_INITIALIZATION_FAILED"):
            wait_for_loop_schema(controller)

    def test_dead_runtime_fails_without_waiting(self):
        controller = Mock()
        controller.inspect.return_value = {"state": "STOPPED"}
        with self.assertRaisesRegex(AssertionError, "TEST_CORE_NOT_RUNNING"):
            wait_for_loop_schema(controller)


class DeploymentServiceTests(unittest.TestCase):
    def test_external_maintenance_controls_real_isolated_core(self):
        deployed = self.deploy("initial-real-core", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome, deployed.as_dict())
        before_pid = deployed.evidence["service"]["pid"]
        profile = DeploymentProfiles(self.running_policy).get("test_runtime")
        controller = RuntimeServiceController(runtime_root=self.runtime,
                                              service_name=profile.service_name, port=self.port)
        wait_for_loop_schema(controller)
        self._external_maintenance_roundtrip(before_pid)

    def _external_maintenance_roundtrip(self, before_pid):
        import sqlite3
        import sys
        from contextlib import closing
        from bct_maintenance.cli import Maintenance, digest, state_snapshot
        manifest = read_json(self.runtime / "releases" / self.head / "manifest.json")
        schema = state_snapshot(self.runtime)["schema_sha256"]
        config = self.base / "external-maintenance.json"
        atomic_json(config, {
            "schema": 1, "enabled": True, "policy_path": str(self.running_policy),
            "policy_sha256": digest(self.running_policy), "profile": "test_runtime",
            "runtime_root": str(self.runtime), "python_path": sys.executable,
            "allowed_actions": ["stop", "start"], "admission_releases": [self.head],
            "verified_releases": {self.head: {"manifest_sha256": manifest["manifest_sha256"],
                                             "compatible_schema_sha256": [schema]}},
        })
        with closing(sqlite3.connect((self.runtime / "state/state.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
            works_before = db.execute("SELECT work_id FROM works ORDER BY work_id").fetchall()
        (self.runtime / "BCT_MAINTENANCE.PAUSE").touch()
        (self.runtime / "BCT_CORE_SUPERVISOR.STOP").touch()
        tool = Maintenance(config)
        self.assertTrue(tool.controller.inspect()["health"]["maintenance_paused"])
        stopped = tool.run("stop", operation_id="external-stop", expected_current=self.head)
        self.assertEqual(stopped["result"]["state"], "STOPPED")
        self.assertEqual(state_snapshot(self.runtime)["schema_sha256"], schema)
        started = tool.run("start", operation_id="external-start", expected_current=self.head)
        self.assertNotEqual(started["result"]["pid"], before_pid)
        self.assertEqual(state_snapshot(self.runtime)["schema_sha256"], schema)
        with closing(sqlite3.connect((self.runtime / "state/state.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
            self.assertEqual(db.execute("SELECT work_id FROM works ORDER BY work_id").fetchall(), works_before)

    def test_external_maintenance_waits_for_gated_loop_schema_initialization(self):
        """Reproduce the original fingerprint race deterministically, then fix it.

        Only the disposable copied release is instrumented. Its HTTP server can
        become ready while the real Loop constructors are held behind a file
        barrier. The production startup code and compatibility guard are intact.
        """
        import sqlite3
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import closing
        from bct_maintenance.cli import Maintenance, digest, state_snapshot
        from bct_maintenance.errors import PreconditionError
        import sys
        runtime_source = self.source / "src/bct/runtime_server.py"
        original = runtime_source.read_text(encoding="utf-8")
        anchor = "        public_loop = LoopTurnRunner(\n"
        self.assertEqual(original.count(anchor), 1)
        injected = '''        # Test-only barrier in this disposable fixture release.
        (runtime_root / "test-loop-schema.blocked").touch()
        test_deadline = time.monotonic() + 45
        while not (runtime_root / "test-loop-schema.release").exists():
            if time.monotonic() >= test_deadline:
                raise RuntimeError("TEST_LOOP_SCHEMA_GATE_TIMEOUT")
            time.sleep(0.01)
'''
        runtime_source.write_text(original.replace(anchor, injected + anchor), encoding="utf-8")
        git(self.source, "add", "src/bct/runtime_server.py")
        git(self.source, "commit", "-m", "test-only delayed Loop schema fixture")
        self.head = git(self.source, "rev-parse", "HEAD")
        deployed = self.deploy("gated-real-core", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome, deployed.as_dict())
        profile = DeploymentProfiles(self.running_policy).get("test_runtime")
        controller = RuntimeServiceController(runtime_root=self.runtime,
                                              service_name=profile.service_name, port=self.port)
        self.assertTrue(controller.inspect()["health"]["ready"])

        def inventory():
            with closing(sqlite3.connect((self.runtime / "state/state.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
                return {r[0]: r[1] for r in db.execute(
                    "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}

        before = inventory()
        early = state_snapshot(self.runtime)["schema_sha256"]
        pending = threading.Event()
        release_gate = self.runtime / "test-loop-schema.release"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(wait_for_loop_schema, controller, timeout=20,
                                 on_pending=pending.set)
            try:
                self.assertTrue(pending.wait(5), "Fixture did not observe pending initialization")
                self.assertFalse(future.done(), "HTTP-ready alone must not pass the schema barrier")
                self.assertNotIn("loop_recipe_turns", before)
            finally:
                release_gate.touch()
            future.result(timeout=25)
        after = inventory()
        self.assertIn("loop_recipe_turns", after)
        self.assertIn("loop_review_handoffs", after)
        self.assertIn("loop_result_reports", after)
        settled = state_snapshot(self.runtime)["schema_sha256"]
        self.assertNotEqual(early, settled)
        self.assertTrue(set(before).issubset(after))
        print("GATED_SCHEMA_REPRODUCTION:" + json.dumps({
            "added": sorted(set(after) - set(before)),
            "changed": sorted(k for k in before if before[k] != after[k]),
            "early_sha256": early, "settled_sha256": settled,
        }), flush=True)
        manifest = read_json(self.runtime / "releases" / self.head / "manifest.json")
        stale_config = self.base / "premature-schema-config.json"
        atomic_json(stale_config, {
            "schema": 1, "enabled": False, "allowed_actions": [],
            "policy_path": str(self.running_policy), "policy_sha256": digest(self.running_policy),
            "profile": "test_runtime", "runtime_root": str(self.runtime), "python_path": sys.executable,
            "verified_releases": {self.head: {"manifest_sha256": manifest["manifest_sha256"],
                                             "compatible_schema_sha256": [early]}},
        })
        with self.assertRaisesRegex(PreconditionError, "DB_COMPATIBILITY_NOT_VERIFIED"):
            Maintenance(stale_config).verify(self.head)
        self._external_maintenance_roundtrip(deployed.evidence["service"]["pid"])

    def test_production_release_list_closes_relative_python_imports(self):
        """A production release must not omit a module needed at runtime."""
        project = Path(__file__).resolve().parents[1]
        policy = tomllib.loads((project / "bct.toml").read_text(encoding="utf-8"))
        files = set(policy["deployment"]["profiles"]["bct_runtime_v1"]["files"])
        missing: set[str] = set()
        for relative in sorted(path for path in files if path.endswith(".py")):
            path = project / relative
            package = Path(relative).with_suffix("").parts[1:-1]
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level == 0:
                    continue
                parent = list(package[:len(package) - node.level + 1])
                imported = node.module.split(".") if node.module else []
                candidates = [parent + imported]
                if node.module is None:
                    candidates = [parent + [alias.name] for alias in node.names]
                for parts in candidates:
                    module = "src/" + "/".join(parts) + ".py"
                    package_init = "src/" + "/".join(parts) + "/__init__.py"
                    # ``from . import BCT`` can name an attribute exported by
                    # __init__, not a sibling module.  Only enforce names that
                    # are actual local modules/packages in the source tree.
                    if not (project / module).is_file() and not (project / package_init).is_file():
                        continue
                    if module not in files and package_init not in files:
                        missing.add(module if (project / module).is_file() else package_init)
        self.assertEqual(set(), missing)

    def test_production_profile_publishes_hash_verified_recovery_entrypoints(self):
        runtime = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, runtime, ignore_errors=True)
        release_root = runtime / "releases" / ("a" * 40)
        files: dict[str, str] = {}
        payloads = {
            "modules/mcp/ops/run_bct_core_supervisor.ps1": b"core-supervisor\n",
            "modules/mcp/ops/run_bct_tunnel_supervisor.ps1": b"tunnel-supervisor\n",
            "modules/mcp/ops/invoke_bct_tunnel_cutover.ps1": b"tunnel-cutover\n",
        }
        for relative, payload in payloads.items():
            path = release_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            files[relative] = hashlib.sha256(payload).hexdigest()
        manifest_sha256 = hashlib.sha256(json.dumps(
            files, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        manifest = {
            "source_head": "a" * 40,
            "manifest_sha256": manifest_sha256,
            "release_path": str(release_root.resolve()),
            "files": files,
        }
        atomic_json(release_root / "manifest.json", manifest)
        profile = DeploymentProfile(
            "bct_runtime_v1", runtime, runtime, "bct-core", 18790, tuple(files)
        )
        # Production re-publication receives the compact current.json pointer,
        # not the original staging object with its in-memory file map.
        _publish_runtime_recovery_scripts(profile, {
            key: manifest[key]
            for key in ("source_head", "manifest_sha256", "release_path")
        })
        self.assertEqual(payloads["modules/mcp/ops/run_bct_core_supervisor.ps1"], (
            runtime / "ops" / "run_bct_core_supervisor.ps1"
        ).read_bytes())
        self.assertEqual(payloads["modules/mcp/ops/run_bct_tunnel_supervisor.ps1"], (
            runtime / "ops" / "run_bct_tunnel_supervisor.ps1"
        ).read_bytes())
        self.assertEqual(payloads["modules/mcp/ops/invoke_bct_tunnel_cutover.ps1"], (
            runtime / "ops" / "invoke_bct_tunnel_cutover.ps1"
        ).read_bytes())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.runtime = self.base / "runtime"
        self.source.mkdir()
        project = Path(__file__).resolve().parents[1]
        shutil.copytree(
            project / "src" / "bct",
            self.source / "src" / "bct",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(project / "src" / "bct_maintenance",
                        self.source / "src" / "bct_maintenance",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.files = [
            path.relative_to(self.source).as_posix()
            for path in sorted((self.source / "src").rglob("*.py"))
        ]
        self.files.insert(0, "bct.toml")
        self.port = free_port()
        self.policy = self.source / "bct.toml"
        self.write_policy()
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "BCT Test")
        git(self.source, "config", "user.email", "bct-test@example.invalid")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "initial runtime")
        self.head = git(self.source, "rev-parse", "HEAD")
        self.running_policy = self.base / "running-bct.toml"
        shutil.copyfile(self.policy, self.running_policy)
        self.bct = BCT(state_path=self.base / "controller.sqlite", policy_path=self.running_policy)
        self.principal = Principal(
            "developer", "test", frozenset({"deploy", "service_control"})
        )
        self.bct.create_work(
            work_id="deployment",
            request_summary="deployment service acceptance",
            roots=[str(self.source)],
            actions=["deploy", "service_control"],
            principal=self.principal,
        )

    def write_policy(self):
        self.policy.write_text(
            "[policy]\n"
            "normal_actions=[\"deploy\",\"service_control\"]\n"
            "approval_actions=[]\n\n"
            "[deployment.profiles.test_runtime]\n"
            f"source_root={json.dumps(str(self.source))}\n"
            f"runtime_root={json.dumps(str(self.runtime))}\n"
            "service_name=\"bct-test\"\n"
            f"port={self.port}\n"
            f"files={json.dumps(self.files)}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        try:
            profile = DeploymentProfiles(self.running_policy).get("test_runtime")
            controller = RuntimeServiceController(
                runtime_root=profile.runtime_root,
                service_name=profile.service_name,
                port=profile.port,
                readiness_timeout=5,
            )
            try:
                if controller.inspect().get("state") == "RUNNING":
                    controller.stop()
            except Exception:
                receipt = read_json(self.runtime / "service.json")
                if receipt and isinstance(receipt.get("pid"), int):
                    process = subprocess.run(
                        ["taskkill", "/PID", str(receipt["pid"]), "/T"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        shell=False,
                    )
                    if process.returncode not in {0, 128}:
                        raise
                    deadline = time.monotonic() + 5
                    while process_identity(receipt["pid"]) is not None and time.monotonic() < deadline:
                        time.sleep(0.1)
                    time.sleep(0.2)
        finally:
            self.temp.cleanup()

    def call(self, operation: str, capability: str, arguments: dict[str, Any]):
        return self.bct.operations.run(
            principal=self.principal,
            work_id="deployment",
            operation_id=operation,
            capability=capability,
            arguments=arguments,
        )

    def deploy(self, operation: str, head: str, current: str | None):
        return self.call(operation, "deploy", {
            "profile": "test_runtime",
            "expected_source_head": head,
            "expected_current_source_head": current,
            "restart": True,
        })

    def failure_context(self, result, head: str) -> dict[str, Any]:
        stderr_path = self.runtime / "logs" / "service.stderr.log"
        return {
            "result": result.as_dict(),
            "deployment_receipt": read_json(self.runtime / "deployments" / f"{head}.json"),
            "service_receipt": read_json(self.runtime / "service.json"),
            "stderr": stderr_path.read_text(encoding="utf-8", errors="replace")[-8000:]
            if stderr_path.exists() else "",
        }

    def service(self, operation: str, action: str, head: str):
        return self.call(operation, "service_control", {
            "profile": "test_runtime", "action": action, "expected_release_sha": head,
        })

    def make_unknown_deploy_claim(self, operation: str) -> Path:
        arguments = {
            "profile": "test_runtime",
            "expected_source_head": self.head,
            "expected_current_source_head": self.head,
            "restart": True,
        }
        created, _ = self.bct.operations.begin(
            principal=self.principal,
            work_id="deployment",
            operation_id=operation,
            capability="deploy",
            arguments=arguments,
        )
        self.assertTrue(created)
        receipt_path = self.runtime / "deployments" / f"{self.head}.json"
        receipt = read_json(receipt_path)
        self.assertIsNotNone(receipt)
        atomic_json(receipt_path, {
            **receipt,
            "state": "ROLLBACK_FAILED",
            "failure": "UnknownEffectError:SERVICE_SHUTDOWN_UNVERIFIED",
            "rollback_failure": "PreconditionError:SERVICE_PROCESS_RUNNING_WITHOUT_HEALTH",
        })
        self.bct.store.finish_operation(
            operation_id=operation,
            outcome=Outcome.UNKNOWN,
            evidence={"phase": "EXECUTION"},
            error="DEPLOYMENT_ROLLBACK_UNVERIFIED:" + str(receipt_path),
            release_claims=False,
        )
        return receipt_path

    def reconcile(self, operation: str, original: str):
        return self.call(operation, "deploy", {
            "operation": "reconcile",
            "original_operation_id": original,
            "profile": "test_runtime",
            "expected_source_head": self.head,
            "expected_current_source_head": self.head,
            "restart": False,
        })

    def reconcile_rollback(self, operation: str, original: str, failed_head: str, rollback_head: str):
        return self.call(operation, "deploy", {
            "operation": "reconcile-rollback",
            "original_operation_id": original,
            "profile": "test_runtime",
            "expected_source_head": failed_head,
            "expected_current_source_head": rollback_head,
            "restart": False,
        })

    def test_deploy_duplicate_restart_stop_and_start(self):
        deployed = self.deploy("deploy-1", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome, deployed.as_dict())
        first_pid = deployed.evidence["service"]["pid"]
        duplicate = self.deploy("deploy-1", self.head, None)
        self.assertTrue(duplicate.duplicate)
        already = self.deploy("deploy-2", self.head, self.head)
        self.assertTrue(already.evidence["already_current"])
        self.assertEqual(first_pid, already.evidence["service"]["pid"])
        status = self.service("status-1", "status", self.head)
        self.assertEqual("RUNNING", status.evidence["service"]["state"])
        restarted = self.service("restart-1", "restart", self.head)
        self.assertEqual(Outcome.APPLIED, restarted.outcome, restarted.as_dict())
        second_pid = restarted.evidence["service"]["pid"]
        self.assertEqual(first_pid, restarted.evidence["service"]["pre_pid"])
        self.assertNotEqual(first_pid, second_pid)
        restart_duplicate = self.service("restart-1", "restart", self.head)
        self.assertTrue(restart_duplicate.duplicate)
        self.assertEqual(second_pid, restart_duplicate.evidence["service"]["pid"])
        stopped = self.service("stop-1", "stop", self.head)
        self.assertEqual(Outcome.APPLIED, stopped.outcome, self.failure_context(stopped, self.head))
        self.assertEqual("STOPPED", stopped.evidence["service"]["state"])
        started = self.service("start-1", "start", self.head)
        self.assertEqual("RUNNING", started.evidence["service"]["state"])
        self.assertNotEqual(second_pid, started.evidence["service"]["pid"])

    def test_exact_unknown_deploy_can_be_reconciled_from_live_state(self):
        deployed = self.deploy("deploy-before-unknown", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome, deployed.as_dict())
        self.make_unknown_deploy_claim("deploy-unknown")

        reconciled = self.reconcile("deploy-reconcile", "deploy-unknown")
        self.assertEqual(Outcome.APPLIED, reconciled.outcome, reconciled.as_dict())
        self.assertEqual(
            "deploy-unknown", reconciled.evidence["reconciled_operation_id"]
        )
        after = self.deploy("deploy-after-reconcile", self.head, self.head)
        self.assertEqual(Outcome.APPLIED, after.outcome, after.as_dict())

    def test_reconciliation_mismatch_keeps_original_claim(self):
        deployed = self.deploy("deploy-before-mismatch", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome, deployed.as_dict())
        receipt_path = self.make_unknown_deploy_claim("deploy-unknown-mismatch")
        receipt = read_json(receipt_path)
        atomic_json(receipt_path, {**receipt, "manifest_sha256": "0" * 64})

        rejected = self.reconcile("deploy-reconcile-mismatch", "deploy-unknown-mismatch")
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome, rejected.as_dict())
        successor = self.deploy("deploy-after-mismatch", self.head, self.head)
        self.assertEqual(Outcome.APPLIED, successor.outcome, successor.as_dict())
        original = self.bct.store.get_operation_for(
            operation_id="deploy-unknown-mismatch",
            work_id="deployment",
            principal_id=self.principal.principal_id,
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)

    def test_rollback_reconciliation_releases_only_verified_previous_live_state(self):
        deployed = self.deploy("deploy-before-rollback-unknown", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome, deployed.as_dict())
        previous = read_json(self.runtime / "current.json")
        self.assertIsNotNone(previous)
        failed_head = "b" * 40
        failed_release = self.runtime / "releases" / failed_head
        shutil.copytree(self.runtime / "releases" / self.head, failed_release)
        failed_manifest = read_json(failed_release / "manifest.json")
        atomic_json(failed_release / "manifest.json", {**failed_manifest, "source_head": failed_head,
            "release_path": str(failed_release)})
        receipt_path = self.runtime / "deployments" / f"{failed_head}.json"
        atomic_json(receipt_path, {
            "state": "ROLLBACK_FAILED", "profile": "test_runtime", "source_head": failed_head,
            "previous_current": previous,
        })
        created, _ = self.bct.operations.begin(
            principal=self.principal, work_id="deployment", operation_id="deploy-rollback-unknown",
            capability="deploy", arguments={"profile": "test_runtime", "expected_source_head": failed_head,
                "expected_current_source_head": self.head, "restart": True},
        )
        self.assertTrue(created)
        self.bct.store.finish_operation(
            operation_id="deploy-rollback-unknown", outcome=Outcome.UNKNOWN,
            evidence={"phase": "EXECUTION"}, error="DEPLOYMENT_ROLLBACK_UNVERIFIED:" + str(receipt_path),
            release_claims=False,
        )
        reconciled = self.reconcile_rollback(
            "deploy-rollback-reconcile", "deploy-rollback-unknown", failed_head, self.head,
        )
        self.assertEqual(Outcome.APPLIED, reconciled.outcome, reconciled.as_dict())
        self.assertTrue(reconciled.evidence["rollback_live_verified"])

    def test_runtime_server_has_bounded_graceful_shutdown(self):
        config = build_server_config(Mock(), port=self.port)
        self.assertEqual(5, GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
        self.assertEqual(5, config.timeout_graceful_shutdown)

        server = uvicorn.Server(config)
        server.servers = []
        server.lifespan = Mock(shutdown=AsyncMock())
        request_server_shutdown(server)
        self.assertTrue(server.should_exit)
        self.assertTrue(server.force_exit)
        asyncio.run(server.shutdown())
        server.lifespan.shutdown.assert_not_awaited()

    def test_start_retries_once_only_after_confirmed_no_effect(self):
        release = {"source_head": self.head}
        confirmed = Mock()
        confirmed.start.side_effect = [
            ConfirmedFailure("SERVICE_START_NOT_APPLIED", release_claims=True),
            {"state": "RUNNING"},
        ]
        confirmed.inspect.return_value = {"state": "STOPPED_STALE_RECEIPT"}
        self.assertEqual(
            "RUNNING", _start_with_one_safe_retry(confirmed, release)["state"]
        )
        self.assertEqual(2, confirmed.start.call_count)

        ambiguous = Mock()
        ambiguous.start.side_effect = UnknownEffectError("SERVICE_START_UNKNOWN")
        with self.assertRaises(UnknownEffectError):
            _start_with_one_safe_retry(ambiguous, release)
        self.assertEqual(1, ambiguous.start.call_count)

    def test_new_release_restarts_and_broken_release_rolls_back(self):
        first = self.deploy("deploy-first", self.head, None)
        first_pid = first.evidence["service"]["pid"]
        models = self.source / "src" / "bct" / "core" / "models.py"
        models.write_text(models.read_text(encoding="utf-8") + "\n# second release\n", encoding="utf-8")
        git(self.source, "add", "src/bct/core/models.py")
        git(self.source, "commit", "-m", "second release")
        second_head = git(self.source, "rev-parse", "HEAD")
        second = self.deploy("deploy-second", second_head, self.head)
        self.assertEqual(
            Outcome.APPLIED,
            second.outcome,
            self.failure_context(second, second_head),
        )
        second_pid = second.evidence["service"]["pid"]
        self.assertNotEqual(first_pid, second_pid)
        self.assertTrue((self.runtime / "releases" / self.head).is_dir())
        self.assertTrue((self.runtime / "releases" / second_head).is_dir())

        server = self.source / "src" / "bct" / "runtime_server.py"
        server.write_text("this is not valid Python !!!\n", encoding="utf-8")
        git(self.source, "add", "src/bct/runtime_server.py")
        git(self.source, "commit", "-m", "broken release")
        broken_head = git(self.source, "rev-parse", "HEAD")
        broken = self.deploy("deploy-broken", broken_head, second_head)
        self.assertEqual(Outcome.FAILED, broken.outcome, broken.as_dict())
        current = read_json(self.runtime / "current.json")
        self.assertEqual(second_head, current["source_head"])
        restored = self.service("status-restored", "status", second_head)
        self.assertEqual("RUNNING", restored.evidence["service"]["state"])
        self.assertEqual(second_head, restored.evidence["service"]["release_sha"])
        receipt = read_json(self.runtime / "deployments" / f"{broken_head}.json")
        self.assertEqual("ROLLED_BACK", receipt["state"])
        self.assertTrue(receipt["rollback_verified"])

    def test_stale_deploy_and_fingerprint_mismatch_fail_closed(self):
        deployed = self.deploy("deploy-safe", self.head, None)
        self.assertEqual(Outcome.APPLIED, deployed.outcome)
        stale = self.deploy("deploy-stale", self.head, "a" * 40)
        self.assertEqual(Outcome.NOT_APPLIED, stale.outcome)
        receipt_path = self.runtime / "service.json"
        receipt = read_json(receipt_path)
        tampered = {**receipt, "fingerprint": "0" * 64}
        atomic_json(receipt_path, tampered)
        denied = self.service("status-tampered", "status", self.head)
        self.assertEqual(Outcome.NOT_APPLIED, denied.outcome)
        atomic_json(receipt_path, receipt)
        healthy = self.service("status-after-restore", "status", self.head)
        self.assertEqual("RUNNING", healthy.evidence["service"]["state"])

    def test_source_dirty_is_rejected_before_activation(self):
        target = self.source / "src" / "bct" / "core" / "models.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# dirty\n", encoding="utf-8")
        result = self.deploy("deploy-dirty", self.head, None)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertFalse((self.runtime / "current.json").exists())
        self.assertFalse((self.runtime / "service.json").exists())

    def test_deployment_uses_clean_linked_worktree_at_exact_canonical_main(self):
        from bct.features.deploy import _target_profile, _validate_source
        from bct.core.models import PreconditionError

        alternate = self.base / "alternate"
        git(self.source, "worktree", "add", "--detach", str(alternate), self.head)
        scratch = self.source / "untracked.py"
        scratch.write_bytes(b"local work")
        profile = DeploymentProfiles(self.running_policy).get("test_runtime")
        selected = _target_profile(profile, self.head, alternate)
        self.assertEqual(str(alternate.resolve()), _validate_source(selected, self.head, alternate)["source_root"])
        self.assertEqual(b"local work", scratch.read_bytes())
        (alternate / "scratch.txt").write_bytes(b"dirty")
        with self.assertRaisesRegex(PreconditionError, "DEPLOYMENT_SOURCE_NOT_CLEAN"):
            _validate_source(selected, self.head, alternate)
        (alternate / "scratch.txt").unlink()
        clone = self.base / "clone"
        git(self.base, "clone", str(self.source), str(clone))
        with self.assertRaisesRegex(PreconditionError, "DEPLOYMENT_SOURCE_WORKTREE_REPOSITORY_MISMATCH"):
            _validate_source(selected, self.head, clone)
        git(self.source, "commit", "--allow-empty", "-m", "advance main")
        with self.assertRaisesRegex(PreconditionError, "DEPLOYMENT_CANONICAL_MAIN_HEAD_MISMATCH"):
            _validate_source(selected, self.head, alternate)

    def test_health_contract_allows_v1_upgrade_and_requires_v2_mcp_fields(self):
        identity = process_identity(os.getpid())
        self.assertIsNotNone(identity)
        controller = RuntimeServiceController(
            runtime_root=self.runtime,
            service_name="bct-test",
            port=self.port,
        )
        receipt = {
            "service": "bct-test",
            **identity.as_dict(),
            "release_sha": self.head,
            "manifest_sha256": "2" * 64,
            "generation": 1,
            "instance_id": "legacy",
        }
        legacy_health = {**receipt, "ready": True}
        self.assertEqual(identity, controller._validate_running(receipt, legacy_health))
        with self.assertRaisesRegex(Exception, "mcp_ready"):
            controller._validate_running({**receipt, "health_contract": 2}, {
                **legacy_health, "health_contract": 2,
            })

    def test_profile_file_addition_allows_upgrade_but_new_release_is_exact(self):
        first = self.deploy("deploy-before-profile-expansion", self.head, None)
        self.assertEqual(Outcome.APPLIED, first.outcome)
        added = self.source / "src" / "bct" / "new_runtime_module.py"
        added.write_text("VALUE = 1\n", encoding="utf-8")
        self.files.append("src/bct/new_runtime_module.py")
        self.write_policy()
        git(self.source, "add", "bct.toml", "src/bct/new_runtime_module.py")
        git(self.source, "commit", "-m", "expand deployment profile")
        expanded_head = git(self.source, "rev-parse", "HEAD")
        upgraded = self.deploy("deploy-after-profile-expansion", expanded_head, self.head)
        self.assertEqual(
            Outcome.APPLIED,
            upgraded.outcome,
            self.failure_context(upgraded, expanded_head),
        )
        old_manifest = read_json(self.runtime / "releases" / self.head / "manifest.json")
        new_manifest = read_json(self.runtime / "releases" / expanded_head / "manifest.json")
        self.assertNotIn("src/bct/new_runtime_module.py", old_manifest["files"])
        self.assertIn("src/bct/new_runtime_module.py", new_manifest["files"])

    def test_target_profile_cannot_change_trusted_deployment_boundaries(self):
        original = self.policy.read_text(encoding="utf-8")
        changes = {
            "SOURCE_ROOT": original.replace(
                f"source_root={json.dumps(str(self.source))}",
                f"source_root={json.dumps(str(self.base / 'foreign-source'))}",
            ),
            "RUNTIME_ROOT": original.replace(
                f"runtime_root={json.dumps(str(self.runtime))}",
                f"runtime_root={json.dumps(str(self.base / 'foreign-runtime'))}",
            ),
            "SERVICE_NAME": original.replace(
                'service_name="bct-test"', 'service_name="foreign-service"'
            ),
            "PORT": original.replace(f"port={self.port}", f"port={self.port + 1}"),
        }
        for label, changed in changes.items():
            with self.subTest(label=label):
                self.policy.write_text(changed, encoding="utf-8")
                git(self.source, "add", "bct.toml")
                git(self.source, "commit", "-m", f"attempt {label.lower()} drift")
                bad_head = git(self.source, "rev-parse", "HEAD")
                denied = self.deploy(f"deny-target-{label.lower()}", bad_head, None)
                self.assertEqual(Outcome.NOT_APPLIED, denied.outcome, denied.as_dict())
                self.assertIn(
                    f"DEPLOYMENT_TARGET_PROFILE_{label}_MISMATCH",
                    str(denied.error),
                )
                self.policy.write_text(original, encoding="utf-8")
                git(self.source, "add", "bct.toml")
                git(self.source, "commit", "-m", f"restore after {label.lower()} drift")


if __name__ == "__main__":
    unittest.main()
