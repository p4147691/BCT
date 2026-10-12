from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from bct import BCT
from bct.core.models import ConfirmedFailure, Outcome, Principal, UnknownEffectError
from bct.features.deploy import DeploymentProfiles, _start_with_one_safe_retry
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


class DeploymentServiceTests(unittest.TestCase):
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
        self.files = [
            path.relative_to(self.source).as_posix()
            for path in sorted((self.source / "src" / "bct").rglob("*.py"))
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
        self.bct = BCT(state_path=self.base / "controller.sqlite", policy_path=self.policy)
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
            profile = DeploymentProfiles(self.policy).get("test_runtime")
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
        self.assertEqual("STOPPED", stopped.evidence["service"]["state"])
        started = self.service("start-1", "start", self.head)
        self.assertEqual("RUNNING", started.evidence["service"]["state"])
        self.assertNotEqual(second_pid, started.evidence["service"]["pid"])

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


if __name__ == "__main__":
    unittest.main()
