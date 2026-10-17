from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import subprocess
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import closing
from pathlib import Path

from bct.core.models import FeatureRequest, PreconditionError
from bct.core.store import Store
from bct.features.deploy import (
    DeployFeature,
    DeploymentProfile,
    DeploymentProfiles,
    ServiceControlFeature,
    _begin_protected_cutover,
    _record_protected_cutover,
    _validate_profile_start_allowed,
    _validate_protected_activation,
    write_protected_cutover_rollback,
)
from bct.features.process_session import ProcessSessionFeature
from bct.operating_paths import (
    AclEvidence,
    OperatingPathLayout,
    build_rcc_host_from_trusted_source,
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
        self.assertEqual(
            Path(os.path.abspath(str(self.base / "LocalAppData" / "BCT"))), layout.root
        )
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
        store = Store(source)
        database = store._connect()
        try:
            database.execute(
                "INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                ("work", "fixture", "[]", "[]", "owner", 1, "ACTIVE"),
            )
            database.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("issue-111-op", "work", "owner", "d", "deploy", "core", "COMPLETED",
                 "UNKNOWN", "{}", None, 1, "policy", 1.0, 1.0),
            )
            database.execute(
                "INSERT INTO resource_claims VALUES(?,?,?,?,?)",
                ("issue-111-claim", "issue-111-op", "work", 1, 1),
            )
            database.execute(
                "INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                ("manager", "manager", "manager", "fixture", 1, 1),
            )
            database.execute(
                "INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("session", "work", 1, "fixture", "[]", "[]", "[]", 1,
                 "manager", 1, "ACTIVE", "{}", 1.0, 1.0),
            )
            database.execute(
                "INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("assignment", "session", 1, "r", "{}", "[]", "[]", "[]",
                 "COMPLETED", 1, "{}", 1.0, 1.0),
            )
            database.execute(
                "INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("result", "session", "assignment", 1, "RESULT", "manager", "manager",
                 "digest", "{}", 1.0, 2.0, 123.5),
            )
            database.execute(
                "INSERT INTO orchestration_manager_wakes"
                "(event_id,session_id,manager_epoch,assignment_id,assignment_generation,"
                "result_message_id,result_digest,state,created_at,updated_at,envelope_schema,receipt_mode)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("issue-111-wake", "session", 1, "assignment", 1, "result", "digest",
                 "UNKNOWN", 1.0, 1.0, 1, "LEGACY_RETURN_V1"),
            )
            database.execute(
                "INSERT INTO orchestration_consumption_decisions VALUES(?,?,?,?,?,?,?)",
                ("decision", "session", "assignment", 1, "request", "{}", 3.0),
            )
            database.execute(
                "INSERT INTO orchestration_consumption_receipts VALUES(?,?,?,?,?,?,?)",
                ("session", "assignment", "result", "digest", 1, "decision", 3.0),
            )
            database.commit()
            self.assertTrue(source.with_name(source.name + "-wal").is_file())
            destination = self.base / "backup" / "state.sqlite"
            receipt = sqlite_online_backup(source, destination)
            self.assertEqual("ok", receipt["quick_check"])
            self.assertEqual(1, receipt["logical_invariants"]["orchestration_mailbox"]["rows"])
            self.assertEqual(1, receipt["logical_invariants"]["orchestration_consumption_receipts"]["rows"])
            self.assertEqual(1, receipt["logical_invariants"]["orchestration_consumption_decisions"]["rows"])
        finally:
            database.close()
        with closing(sqlite3.connect(destination)) as database:
            self.assertEqual((123.5,), database.execute(
                "SELECT consumed_at FROM orchestration_mailbox WHERE message_id='result'"
            ).fetchone())

    def test_sqlite_backup_rejects_missing_required_core_schema(self):
        source = self.base / "incomplete.sqlite"
        with closing(sqlite3.connect(source)) as database:
            database.execute("CREATE TABLE operations(id TEXT)")
        with self.assertRaisesRegex(PreconditionError, "DATABASE_SCHEMA_MISSING"):
            sqlite_online_backup(source, self.base / "backup" / "state.sqlite")

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
        Store(state)
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

    def test_preparing_receipt_precedes_all_owned_staging(self):
        runtime, data, head, source = self._source_runtime()
        target = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        target.root.mkdir(parents=True)
        user = "S-1-5-21-1000"
        with patch("bct.operating_paths.atomic_json", side_effect=RuntimeError("receipt-failure")):
            with self.assertRaisesRegex(RuntimeError, "receipt-failure"):
                prepare_core_migration(
                    source_runtime=runtime, source_data=data, trusted_source_root=source,
                    target=target, operation_id="core-receipt-first", expected_source_head=head,
                    service_name="bct-core", service_port=19879,
                    acl_evidence=self._acl(target.root, user), current_user_sid=user,
                )
        self.assertFalse((target.root / "staging" / "core-receipt-first").exists())

        rcc_source = self.base / "rcc-receipt-source"
        extension = rcc_source / "modules" / "rcc" / "extension"
        host_source = rcc_source / "modules" / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        extension.mkdir(parents=True)
        host_source.parent.mkdir(parents=True)
        key = base64.b64encode(b"receipt-first-key").decode("ascii")
        extension_id = extension_id_from_key(key)
        (extension / "manifest.json").write_text(json.dumps({"key": key}), encoding="utf-8")
        (extension / "background.js").write_text("// exact\n", encoding="utf-8")
        host_source.write_text(
            "using System; public class RelayNativeHostV2 { public static void Main() {} }\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-b", "main", str(rcc_source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(rcc_source), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(rcc_source), "config", "user.name", "BCT Test"], check=True)
        subprocess.run(["git", "-C", str(rcc_source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(rcc_source), "commit", "-m", "fixture"], check=True, capture_output=True)
        rcc_head = subprocess.run(
            ["git", "-C", str(rcc_source), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        with patch("bct.operating_paths.atomic_json", side_effect=RuntimeError("receipt-failure")):
            with self.assertRaisesRegex(RuntimeError, "receipt-failure"):
                build_rcc_host_from_trusted_source(
                    target=target, trusted_source_root=rcc_source,
                    expected_source_head=rcc_head, operation_id="host-receipt-first",
                    acl_evidence=self._acl(target.root, user), current_user_sid=user,
                )
        self.assertFalse(
            (target.root / "staging" / "host-receipt-first" / "rcc-host-build").exists()
        )

        build = build_rcc_host_from_trusted_source(
            target=target, trusted_source_root=rcc_source,
            expected_source_head=rcc_head, operation_id="host-build-real",
            acl_evidence=self._acl(target.root, user), current_user_sid=user,
        )
        native_manifest = self.base / "source-native-manifest.json"
        native_manifest.write_text(json.dumps({
            "name": "com.ai_workspace_relay.host",
            "path": str(Path(build["artifact_path"])),
            "allowed_origins": [f"chrome-extension://{extension_id}/"],
        }), encoding="utf-8")
        with patch("bct.operating_paths.atomic_json", side_effect=RuntimeError("receipt-failure")):
            with self.assertRaisesRegex(RuntimeError, "receipt-failure"):
                prepare_rcc_migration(
                    source_extension=extension,
                    source_host_executable=Path(build["artifact_path"]),
                    source_native_manifest=native_manifest,
                    trusted_source_root=rcc_source,
                    expected_source_head=rcc_head,
                    host_build_operation_id="host-build-real",
                    operation_id="rcc-receipt-first",
                    target=target,
                    expected_extension_id=extension_id,
                    acl_evidence=self._acl(target.root, user),
                    current_user_sid=user,
                )
        self.assertFalse((target.root / "staging" / "rcc-receipt-first" / "rcc").exists())

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
            'cutover_successor_profile="protected"\n'
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
        with patch.dict("os.environ", {"LOCALAPPDATA": str(local)}):
            with self.assertRaisesRegex(PreconditionError, "TARGET_CUTOVER_AUTHORITY_MISSING"):
                _validate_profile_start_allowed(profiles, protected)
            _begin_protected_cutover(profiles, protected, "a" * 40)
            with self.assertRaisesRegex(PreconditionError, "SOURCE_PROFILE_RETIRED"):
                _validate_profile_start_allowed(profiles, legacy)
            _validate_profile_start_allowed(profiles, protected)
            _record_protected_cutover(
                profiles, protected, "a" * 40,
                {"generation": 93, "instance_id": "protected-instance"},
            )
            activated = read_json(protected.runtime_root.parent / "migration" / "cutover.json")
            _begin_protected_cutover(profiles, protected, "b" * 40)
            _record_protected_cutover(
                profiles, protected, "b" * 40,
                {"generation": 94, "instance_id": "protected-upgrade"},
            )
            self.assertEqual(
                activated,
                read_json(protected.runtime_root.parent / "migration" / "cutover.json"),
            )
            with self.assertRaisesRegex(PreconditionError, "SOURCE_PROFILE_RETIRED"):
                _validate_profile_start_allowed(profiles, legacy)
            marker_before = read_json(protected.runtime_root.parent / "migration" / "cutover.json")
            for runtime in (legacy.runtime_root, protected.runtime_root):
                held = RuntimeWriterLock(runtime / "state" / "core-writer.lock").acquire()
                try:
                    with self.assertRaisesRegex(PreconditionError, "RUNTIME_WRITER_LOCK_HELD"):
                        write_protected_cutover_rollback(
                            profiles=profiles,
                            source_profile_name="legacy",
                            operation_id="rollback-lock-test",
                            target_references_restored=True,
                        )
                    self.assertEqual(
                        marker_before,
                        read_json(protected.runtime_root.parent / "migration" / "cutover.json"),
                    )
                finally:
                    held.close()
            with patch(
                "bct.features.deploy.RuntimeServiceController.inspect",
                return_value={"state": "RUNNING"},
            ):
                with self.assertRaisesRegex(PreconditionError, "CORE_NOT_QUIESCED"):
                    write_protected_cutover_rollback(
                        profiles=profiles,
                        source_profile_name="legacy",
                        operation_id="rollback-running-test",
                        target_references_restored=True,
                    )
            self.assertEqual(
                marker_before,
                read_json(protected.runtime_root.parent / "migration" / "cutover.json"),
            )
            rollback = write_protected_cutover_rollback(
                profiles=profiles,
                source_profile_name="legacy",
                operation_id="rollback-01",
                target_references_restored=True,
            )
            self.assertEqual("ROLLED_BACK", rollback["state"])
            _validate_profile_start_allowed(profiles, legacy)
            with self.assertRaisesRegex(PreconditionError, "TARGET_PROFILE_RETIRED"):
                _validate_profile_start_allowed(profiles, protected)

    def test_deploy_records_activating_before_target_start(self):
        head = "a" * 40
        profile = DeploymentProfile(
            "protected", self.base / "source", self.base / "protected-runtime",
            "bct-core", 19879, ("bct.toml",), True, "legacy", None,
        )
        request = FeatureRequest(
            "deploy", "protected",
            {"expected_source_head": head, "expected_current_source_head": head, "restart": True},
            (), {},
        )
        controller = Mock()
        controller.inspect.return_value = {"state": "STOPPED"}
        order: list[str] = []
        current = {"source_head": head, "manifest_sha256": "b" * 64}
        feature = DeployFeature(Mock())
        with patch("bct.features.deploy._validate_source", return_value=current), patch(
            "bct.features.deploy._read_current", return_value=current
        ), patch("bct.features.deploy._validate_release"), patch(
            "bct.features.deploy.RuntimeServiceController", return_value=controller
        ), patch("bct.features.deploy._validate_protected_activation"), patch(
            "bct.features.deploy._begin_protected_cutover",
            side_effect=lambda *args: order.append("begin"),
        ), patch(
            "bct.features.deploy._start_with_one_safe_retry",
            side_effect=lambda *args: order.append("start") or {"state": "RUNNING"},
        ), patch(
            "bct.features.deploy._record_protected_cutover",
            side_effect=lambda *args: order.append("complete"),
        ):
            feature._execute_apply(request, profile)
        self.assertEqual(["begin", "start", "complete"], order)

    def test_service_control_and_runtime_server_deny_target_without_authority(self):
        local = self.base / "LocalAppData"
        runtime = local / "BCT" / "runtime"
        source = self.base / "source"
        source.mkdir()
        policy = self.base / "profiles.toml"
        policy_text = (
            "[deployment.profiles.legacy]\n"
            f"source_root={json.dumps(str(source))}\n"
            f"runtime_root={json.dumps(str(self.base / 'legacy-runtime'))}\n"
            'service_name="bct-core"\nport=19879\nfiles=["bct.toml"]\n'
            'cutover_successor_profile="protected"\n'
            "[deployment.profiles.protected]\n"
            f"source_root={json.dumps(str(source))}\n"
            'runtime_root="%LOCALAPPDATA%\\\\BCT\\\\runtime"\n'
            'service_name="bct-core"\nport=19879\nfiles=["bct.toml"]\n'
            'protected_activation_required=true\nmigration_source_profile="legacy"\n'
        )
        policy.write_text(policy_text, encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(local)}):
            profiles = DeploymentProfiles(policy)
            feature = ServiceControlFeature(profiles)
            request = FeatureRequest(
                "service_control", "bct-core",
                {"profile": "protected", "action": "start", "expected_release_sha": "a" * 40},
                (), {},
            )
            with patch("bct.features.deploy._read_current", return_value={"source_head": "a" * 40}):
                with self.assertRaisesRegex(PreconditionError, "TARGET_CUTOVER_AUTHORITY_MISSING"):
                    feature.execute(request)

            release = runtime / "releases" / ("a" * 40)
            release.mkdir(parents=True)
            (release / "bct.toml").write_text(policy_text, encoding="utf-8")
            from bct import runtime_server
            arguments = SimpleNamespace(
                runtime_root=str(runtime), service_name="bct-core", release_sha="a" * 40,
                manifest_sha256="b" * 64, generation=1, instance_id="fixture", port=19879,
            )
            writer_lock = Mock()
            with patch.object(runtime_server, "parse_arguments", return_value=arguments), patch.object(
                runtime_server, "acquire_runtime_writer_lock", return_value=writer_lock
            ):
                with self.assertRaisesRegex(PreconditionError, "TARGET_CUTOVER_AUTHORITY_MISSING"):
                    runtime_server.main()

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
        host_source = source / "modules" / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        host_source.parent.mkdir(parents=True)
        host_source.write_text(
            "using System; public class RelayNativeHostV2 { public static void Main() {} }\n",
            encoding="utf-8",
        )
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
        build_receipt = build_rcc_host_from_trusted_source(
            target=target,
            trusted_source_root=source,
            expected_source_head=head,
            operation_id="fixture-build-01",
            acl_evidence=acl,
            current_user_sid=user,
        )
        host = Path(build_receipt["artifact_path"])
        receipt = prepare_rcc_migration(
            source_extension=extension,
            source_host_executable=host,
            source_native_manifest=host_manifest,
            trusted_source_root=source,
            expected_source_head=head,
            host_build_operation_id="fixture-build-01",
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
        duplicate = prepare_rcc_migration(
            source_extension=extension,
            source_host_executable=host,
            source_native_manifest=host_manifest,
            trusted_source_root=source,
            expected_source_head=head,
            host_build_operation_id="fixture-build-01",
            operation_id="rcc-migration-01",
            target=target,
            expected_extension_id=extension_id,
            acl_evidence=acl,
            current_user_sid=user,
        )
        self.assertEqual(receipt, duplicate)

        failed_target = OperatingPathLayout.from_local_app_data(self.base / "FailedLocalAppData")
        failed_target.root.mkdir(parents=True)
        failed_acl = self._acl(failed_target.root, user)
        failed_build = build_rcc_host_from_trusted_source(
            target=failed_target,
            trusted_source_root=source,
            expected_source_head=head,
            operation_id="fixture-build-02",
            acl_evidence=failed_acl,
            current_user_sid=user,
        )
        failed_host = Path(failed_build["artifact_path"])
        with patch("bct.operating_paths._copy_git_tree", side_effect=RuntimeError("fixture")):
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                prepare_rcc_migration(
                    source_extension=extension, source_host_executable=failed_host,
                    source_native_manifest=host_manifest, trusted_source_root=source,
                    expected_source_head=head, host_build_operation_id="fixture-build-02",
                    operation_id="rcc-migration-failure",
                    target=failed_target, expected_extension_id=extension_id,
                    acl_evidence=failed_acl, current_user_sid=user,
                )
        recovery = quarantine_failed_migration(
            target=failed_target, operation_id="rcc-migration-failure", component="rcc"
        )
        self.assertIn("staging-rcc", recovery["quarantine"])
        self.assertFalse(
            (failed_target.root / "staging" / "rcc-migration-failure" / "rcc").exists()
        )


if __name__ == "__main__":
    unittest.main()
