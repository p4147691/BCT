from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import patch
from contextlib import closing
from pathlib import Path

from bct.core.models import PreconditionError
from bct.features.deploy import DeploymentProfiles, _validate_protected_activation
from bct.features.process_session import ProcessSessionFeature
from bct.operating_paths import (
    AclEvidence,
    OperatingPathLayout,
    extension_id_from_key,
    prepare_core_migration,
    prepare_rcc_migration,
    quarantine_failed_migration,
    sqlite_online_backup,
    validate_acl_evidence,
    validate_rcc_relocation,
)
from bct.service_runtime import RuntimeWriterLock, atomic_json, read_json


class ProtectedOperatingPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _acl(root: Path, user: str = "S-1-5-21-1000") -> tuple[AclEvidence, ...]:
        return (
            AclEvidence(str(root.parent), user, False, False, ((user, 0x1F01FF, True, "FullControl"),)),
            AclEvidence(str(root), user, True, False, ((user, 0x1F01FF, True, "FullControl"),)),
        )

    def test_layout_is_bounded_below_local_app_data(self):
        layout = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        self.assertEqual((self.base / "LocalAppData" / "BCT").resolve(), layout.root)
        self.assertEqual(layout.root / "runtime", layout.runtime)
        self.assertEqual(layout.root / "data", layout.data)
        self.assertEqual(layout.root / "rcc" / "extension", layout.rcc_extension)

    def test_deployment_profile_expands_only_local_app_data_runtime(self):
        policy = self.base / "bct.toml"
        source = self.base / "source"
        source.mkdir()
        policy.write_text(
            "[deployment.profiles.protected]\n"
            f"source_root={json.dumps(str(source))}\n"
            'runtime_root="%LOCALAPPDATA%\\\\BCT\\\\runtime"\n'
            'service_name="bct-core"\nport=18790\nfiles=["bct.toml"]\n',
            encoding="utf-8",
        )
        local = self.base / "LocalAppData"
        with patch.dict("os.environ", {"LOCALAPPDATA": str(local)}):
            profile = DeploymentProfiles(policy).get("protected")
        self.assertEqual((local / "BCT" / "runtime").resolve(), profile.runtime_root)
        policy.write_text(policy.read_text(encoding="utf-8").replace(
            "%LOCALAPPDATA%", "%USERPROFILE%"
        ), encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError, "PATH_VARIABLE_INVALID"):
            DeploymentProfiles(policy).get("protected")

    def test_acl_rejects_broad_ancestor_delete_child_and_reparse(self):
        root = self.base / "LocalAppData" / "BCT"
        user = "S-1-5-21-1000"
        good = (
            AclEvidence(str(root.parent), user, False, False, ((user, 0x1F01FF, True, "FullControl"),)),
            AclEvidence(str(root), user, True, False, ((user, 0x1F01FF, True, "FullControl"),)),
        )
        validate_acl_evidence(
            good, protected_root=root, boundary_root=root.parent, current_user_sid=user
        )
        bad = (
            good[1],
            AclEvidence(str(root.parent), user, False, False, (("S-1-5-11", 0x40, True, "DeleteSubdirectoriesAndFiles"),)),
        )
        with self.assertRaisesRegex(PreconditionError, "PROTECTED_ACL_FOREIGN_WRITE"):
            validate_acl_evidence(
                bad, protected_root=root, boundary_root=root.parent, current_user_sid=user
            )
        with self.assertRaisesRegex(PreconditionError, "PROTECTED_ACL_REPARSE_POINT"):
            validate_acl_evidence(
                (AclEvidence(str(root), user, True, True, ((user, 0x1F01FF, True, "FullControl"),)),),
                protected_root=root,
                boundary_root=root.parent,
                current_user_sid=user,
            )
        foreign = "S-1-5-21-2000"
        with self.assertRaisesRegex(PreconditionError, "PROTECTED_ACL_FOREIGN_ACCESS"):
            validate_acl_evidence(
                (
                    good[0],
                    AclEvidence(str(root), user, True, False, (
                        (user, 0x1F01FF, True, "FullControl"),
                        (foreign, 0x1, True, "ReadData"),
                    )),
                ),
                protected_root=root, boundary_root=root.parent, current_user_sid=user,
            )

    def test_sqlite_online_backup_includes_committed_wal_state(self):
        source = self.base / "source.sqlite"
        database = sqlite3.connect(source)
        try:
            database.execute("PRAGMA journal_mode=WAL")
            database.execute("CREATE TABLE receipt(id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            database.execute("INSERT INTO receipt VALUES('issue-111', 'preserved')")
            database.execute("CREATE TABLE operations(operation_id TEXT, outcome TEXT)")
            database.execute("INSERT INTO operations VALUES('issue-111-op', 'UNKNOWN')")
            database.execute("CREATE TABLE resource_claims(resource_key TEXT, unresolved INTEGER)")
            database.execute("INSERT INTO resource_claims VALUES('issue-111-claim', 1)")
            database.execute("CREATE TABLE orchestration_manager_wakes(wake_id TEXT, consumed_at REAL)")
            database.execute("INSERT INTO orchestration_manager_wakes VALUES('issue-111-wake', 123.5)")
            database.commit()
            self.assertTrue(source.with_name(source.name + "-wal").is_file())
            destination = self.base / "backup" / "state.sqlite"
            receipt = sqlite_online_backup(source, destination)
            self.assertEqual("ok", receipt["quick_check"])
            self.assertEqual(
                {"operations", "resource_claims", "orchestration_manager_wakes"},
                set(receipt["logical_invariants"]),
            )
        finally:
            database.close()
        with closing(sqlite3.connect(destination)) as database:
            self.assertEqual(("preserved",), database.execute(
                "SELECT value FROM receipt WHERE id='issue-111'"
            ).fetchone())

    def _source_runtime(self) -> tuple[Path, Path, str, Path]:
        runtime = self.base / "old-runtime"
        data = self.base / "old-data"
        source = self.base / "source"
        tracked = {
            "src/bct/runtime_server.py": b"# exact release\n",
            "modules/mcp/ops/run_bct_core_supervisor.ps1": b"# core\n",
            "modules/mcp/ops/run_bct_tunnel_supervisor.ps1": b"# tunnel\n",
            "modules/mcp/ops/BCT-Core-Supervisor.protected.task.xml.template": b"<Task/>\n",
            "modules/mcp/ops/BCT-Tunnel-Supervisor.protected.task.xml.template": b"<Task/>\n",
        }
        for relative, content in tracked.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "BCT Test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
        head = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        release = runtime / "releases" / head
        files = {}
        for relative, content in tracked.items():
            file_path = release / relative
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            files[relative] = hashlib.sha256(content).hexdigest()
        manifest_hash = hashlib.sha256(json.dumps(
            files, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        atomic_json(release / "manifest.json", {
            "source_head": head,
            "manifest_sha256": manifest_hash,
            "files": files,
        })
        atomic_json(runtime / "current.json", {
            "source_head": head,
            "manifest_sha256": manifest_hash,
            "release_path": str(release.resolve()),
        })
        atomic_json(runtime / "service.json", {"state": "STOPPED", "generation": 92})
        (runtime / "BCT_CORE_SUPERVISOR.STOP").write_text("migration\n", encoding="ascii")
        for name in ("control.token", "mcp.token"):
            (runtime / name).write_text("1" * 64 + "\n", encoding="ascii")
        state = runtime / "state" / "state.sqlite"
        state.parent.mkdir()
        with closing(sqlite3.connect(state)) as database:
            database.execute("CREATE TABLE durable_receipt(id TEXT PRIMARY KEY)")
            database.execute("INSERT INTO durable_receipt VALUES('issue-111')")
            database.commit()
        atomic_json(runtime / "deployments" / f"{head}.json", {"source_head": head})
        (data / "process-sessions").mkdir(parents=True)
        (data / "process-sessions" / "receipt.json").write_text("{}\n", encoding="utf-8")
        return runtime, data, head, source

    def test_prepare_requires_both_cores_quiesced_and_preserves_receipts(self):
        runtime, data, head, source = self._source_runtime()
        target = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        target.root.mkdir(parents=True)
        user = "S-1-5-21-1000"
        acl = (
            AclEvidence(str(target.root.parent), user, False, False, ((user, 0x1F01FF, True, "FullControl"),)),
            AclEvidence(str(target.root), user, True, False, ((user, 0x1F01FF, True, "FullControl"),)),
        )
        (runtime / "BCT_CORE_SUPERVISOR.STOP").unlink()
        with self.assertRaisesRegex(PreconditionError, "SOURCE_SUPERVISOR_NOT_DISABLED"):
            prepare_core_migration(
                source_runtime=runtime,
                source_data=data,
                trusted_source_root=source,
                target=target,
                operation_id="migration-01",
                expected_source_head=head,
                service_name="bct-core",
                service_port=19879,
                acl_evidence=acl,
                current_user_sid=user,
            )
        (runtime / "BCT_CORE_SUPERVISOR.STOP").write_text("migration\n", encoding="ascii")
        receipt = prepare_core_migration(
            source_runtime=runtime,
            source_data=data,
            trusted_source_root=source,
            target=target,
            operation_id="migration-01",
            expected_source_head=head,
            service_name="bct-core",
            service_port=19879,
            acl_evidence=acl,
            current_user_sid=user,
        )
        self.assertFalse(receipt["activation_allowed"])
        self.assertFalse(receipt["legacy_sensitive_copies_retired"])
        self.assertFalse((target.runtime / "service.json").exists())
        self.assertEqual(head, read_json(target.runtime / "current.json")["source_head"])
        self.assertTrue((target.runtime / "migration" / "legacy-service.json").is_file())
        with closing(sqlite3.connect(target.runtime / "state" / "state.sqlite")) as database:
            self.assertEqual(("issue-111",), database.execute(
                "SELECT id FROM durable_receipt"
            ).fetchone())
        duplicate = prepare_core_migration(
            source_runtime=runtime, source_data=data, trusted_source_root=source,
            target=target, operation_id="migration-01", expected_source_head=head,
            service_name="bct-core", service_port=19879,
            acl_evidence=acl, current_user_sid=user,
        )
        self.assertEqual("PUBLISHED", duplicate["state"])

    def test_failed_core_stage_is_receipted_and_recoverably_quarantined(self):
        runtime, data, head, source = self._source_runtime()
        target = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        target.root.mkdir(parents=True)
        with patch("bct.operating_paths.sqlite_online_backup", side_effect=RuntimeError("fixture")):
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                prepare_core_migration(
                    source_runtime=runtime, source_data=data, trusted_source_root=source,
                    target=target, operation_id="migration-failure", expected_source_head=head,
                    service_name="bct-core", service_port=19879,
                    acl_evidence=self._acl(target.root), current_user_sid="S-1-5-21-1000",
                )
        failed = read_json(target.root / "migration" / "migration-failure.json")
        self.assertEqual("FAILED", failed["state"])
        self.assertFalse(target.runtime.exists())
        recovery = quarantine_failed_migration(
            target=target, operation_id="migration-failure"
        )
        self.assertEqual("QUARANTINED", recovery["state"])
        self.assertIn("staging", recovery["quarantine"])

    def test_protected_activation_requires_published_migration_and_operating_evidence(self):
        local = self.base / "LocalAppData"
        source = self.base / "source"
        source.mkdir()
        policy = self.base / "bct.toml"
        policy.write_text(
            "[deployment.profiles.legacy]\n"
            f"source_root={json.dumps(str(source))}\n"
            f"runtime_root={json.dumps(str(self.base / 'legacy-runtime'))}\n"
            'service_name="bct-core"\nport=19879\nfiles=["bct.toml"]\n'
            "[deployment.profiles.protected]\n"
            f"source_root={json.dumps(str(source))}\n"
            'runtime_root="%LOCALAPPDATA%\\\\BCT\\\\runtime"\n'
            'service_name="bct-core"\nport=19879\nfiles=["bct.toml"]\n'
            'protected_activation_required=true\nmigration_source_profile="legacy"\n',
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"LOCALAPPDATA": str(local)}):
            profiles = DeploymentProfiles(policy)
            protected = profiles.get("protected")
            with self.assertRaisesRegex(PreconditionError, "ACTIVATION_RECEIPT_INVALID"):
                _validate_protected_activation(profiles, protected, "a" * 40)
        legacy = profiles.get("legacy")
        legacy.runtime_root.mkdir(parents=True)
        (legacy.runtime_root / "BCT_CORE_SUPERVISOR.STOP").write_text("stop\n", encoding="ascii")
        atomic_json(protected.runtime_root.parent / "migration" / "cutover-1.json", {
            "state": "PUBLISHED", "source_head": "a" * 40,
            "source_runtime": str(legacy.runtime_root),
        })
        atomic_json(protected.runtime_root.parent / "migration" / "activation.json", {
            "schema": "BCT_PROTECTED_ACTIVATION_V1", "state": "APPROVED",
            "operation_id": "cutover-1", "source_profile": "legacy",
            "target_profile": "protected", "source_head": "a" * 40,
            "source_runtime": str(legacy.runtime_root),
            "target_runtime": str(protected.runtime_root),
            "acl_evidence_sha256": "b" * 64,
            "source_supervisor_disabled": True,
            "cross_account_denial_verified": True, "rcc_canary_verified": True,
        })
        with patch.dict("os.environ", {"LOCALAPPDATA": str(local)}):
            lock = _validate_protected_activation(profiles, protected, "a" * 40)
        self.assertIsNotNone(lock)
        lock.close()

    def test_runtime_data_root_overrides_legacy_process_session_path(self):
        policy = self.base / "policy.toml"
        policy.write_text('[execution.sessions]\nstate_root="D:\\\\BCT\\\\data\\\\process-sessions"\n', encoding="utf-8")
        data_root = self.base / "protected" / "data"
        feature = ProcessSessionFeature(policy, data_root=data_root)
        self.assertEqual((data_root / "process-sessions").resolve(), feature.state_root)

    def test_runtime_writer_lock_fences_a_second_core(self):
        path = self.base / "runtime" / "state" / "core-writer.lock"
        first = RuntimeWriterLock(path).acquire()
        try:
            with self.assertRaisesRegex(PreconditionError, "RUNTIME_WRITER_LOCK_HELD"):
                RuntimeWriterLock(path).acquire()
        finally:
            first.close()
        second = RuntimeWriterLock(path).acquire()
        second.close()

    def test_protected_task_templates_are_path_parameterized(self):
        root = Path(__file__).resolve().parents[1] / "modules" / "mcp" / "ops"
        for name in (
            "BCT-Core-Supervisor.protected.task.xml.template",
            "BCT-Tunnel-Supervisor.protected.task.xml.template",
        ):
            text = (root / name).read_text(encoding="utf-8")
            ET.fromstring(text)
            self.assertIn("__RUNTIME_DIR__", text)
            self.assertNotIn(r"D:\BCT", text)

    def test_rcc_identity_is_path_independent_but_chrome_switch_is_explicit(self):
        extension_manifest = self.base / "manifest.json"
        native_manifest = self.base / "host.json"
        key = base64.b64encode(b"fixed-public-key").decode("ascii")
        extension_id = extension_id_from_key(key)
        extension_manifest.write_text(json.dumps({"key": key}), encoding="utf-8")
        native_manifest.write_text(json.dumps({
            "name": "com.ai_workspace_relay.host",
            "path": r"D:\ChromeExtensions\RCC\native\RelayNativeHostV2.exe",
            "allowed_origins": [f"chrome-extension://{extension_id}/"],
        }), encoding="utf-8")
        result = validate_rcc_relocation(
            extension_manifest=extension_manifest,
            native_manifest=native_manifest,
            expected_extension_id=extension_id,
            target_host_executable=self.base / "BCT" / "rcc" / "native" / "RelayNativeHostV2.exe",
        )
        self.assertEqual(extension_id, result["extension_id"])
        self.assertTrue(result["chrome_path_switch_required"])
        self.assertTrue(result["existing_tabs_must_be_preserved"])

    def test_rcc_staging_rewrites_only_host_path_and_does_not_activate(self):
        source = self.base / "rcc-source"
        extension = source / "modules" / "rcc" / "extension"
        native = self.base / "RCC-build" / "native"
        extension.mkdir(parents=True)
        native.mkdir(parents=True)
        key = base64.b64encode(b"fixed-public-key").decode("ascii")
        extension_id = extension_id_from_key(key)
        (extension / "manifest.json").write_text(json.dumps({"key": key}), encoding="utf-8")
        (extension / "background.js").write_text("// exact\n", encoding="utf-8")
        host = native / "RelayNativeHostV2.exe"
        host.write_bytes(b"fixture-host")
        host_manifest = native / "com.ai_workspace_relay.host.json"
        host_manifest.write_text(json.dumps({
            "name": "com.ai_workspace_relay.host",
            "path": str(host),
            "allowed_origins": [f"chrome-extension://{extension_id}/"],
        }), encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "BCT Test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
        head = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        target = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        target.root.mkdir(parents=True)
        user = "S-1-5-21-1000"
        acl = (
            AclEvidence(str(target.root.parent), user, False, False, ((user, 0x1F01FF, True, "FullControl"),)),
            AclEvidence(str(target.root), user, True, False, ((user, 0x1F01FF, True, "FullControl"),)),
        )
        receipt = prepare_rcc_migration(
            source_extension=extension,
            source_host_executable=host,
            source_native_manifest=host_manifest,
            trusted_source_root=source,
            expected_source_head=head,
            expected_host_sha256=hashlib.sha256(host.read_bytes()).hexdigest(),
            operation_id="rcc-migration-01",
            target=target,
            expected_extension_id=extension_id,
            acl_evidence=acl,
            current_user_sid=user,
        )
        self.assertFalse(receipt["registry_changed"])
        self.assertFalse(receipt["chrome_changed"])
        self.assertFalse(receipt["activation_allowed"])
        self.assertEqual("PUBLISHED", receipt["state"])
        staged_manifest = read_json(target.rcc_native / host_manifest.name)
        self.assertEqual(
            str((target.rcc_native / "RelayNativeHostV2.exe").resolve()),
            staged_manifest["path"],
        )
        self.assertEqual(
            [f"chrome-extension://{extension_id}/"], staged_manifest["allowed_origins"]
        )


if __name__ == "__main__":
    unittest.main()
