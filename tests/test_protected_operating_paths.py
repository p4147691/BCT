from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path

from bct.core.models import PreconditionError
from bct.features.deploy import DeploymentProfiles
from bct.operating_paths import (
    AclEvidence,
    OperatingPathLayout,
    extension_id_from_key,
    prepare_core_migration,
    prepare_rcc_migration,
    sqlite_online_backup,
    validate_acl_evidence,
    validate_rcc_relocation,
)
from bct.service_runtime import atomic_json, read_json


class ProtectedOperatingPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

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
            AclEvidence(str(root.parent), user, False, False, ((user, "FULL_CONTROL", True),)),
            AclEvidence(str(root), user, True, False, ((user, "FULL_CONTROL", True),)),
        )
        validate_acl_evidence(
            good, protected_root=root, boundary_root=root.parent, current_user_sid=user
        )
        bad = (
            good[1],
            AclEvidence(str(root.parent), user, False, False, (("S-1-5-11", "DELETE_CHILD", True),)),
        )
        with self.assertRaisesRegex(PreconditionError, "PROTECTED_ACL_BROAD_WRITE"):
            validate_acl_evidence(
                bad, protected_root=root, boundary_root=root.parent, current_user_sid=user
            )
        with self.assertRaisesRegex(PreconditionError, "PROTECTED_ACL_REPARSE_POINT"):
            validate_acl_evidence(
                (AclEvidence(str(root), user, True, True, ((user, "FULL_CONTROL", True),)),),
                protected_root=root,
                boundary_root=root.parent,
                current_user_sid=user,
            )

    def test_sqlite_online_backup_includes_committed_wal_state(self):
        source = self.base / "source.sqlite"
        with closing(sqlite3.connect(source)) as database:
            database.execute("PRAGMA journal_mode=WAL")
            database.execute("CREATE TABLE receipt(id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            database.execute("INSERT INTO receipt VALUES('issue-111', 'preserved')")
            database.commit()
        destination = self.base / "backup" / "state.sqlite"
        receipt = sqlite_online_backup(source, destination)
        self.assertEqual("ok", receipt["quick_check"])
        with closing(sqlite3.connect(destination)) as database:
            self.assertEqual(("preserved",), database.execute(
                "SELECT value FROM receipt WHERE id='issue-111'"
            ).fetchone())

    def _source_runtime(self) -> tuple[Path, Path, str]:
        runtime = self.base / "old-runtime"
        data = self.base / "old-data"
        head = "a" * 40
        release = runtime / "releases" / head
        file_path = release / "src" / "bct" / "runtime_server.py"
        file_path.parent.mkdir(parents=True)
        file_path.write_text("# exact release\n", encoding="utf-8")
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        files = {"src/bct/runtime_server.py": digest}
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
        return runtime, data, head

    def test_prepare_requires_both_cores_quiesced_and_preserves_receipts(self):
        runtime, data, head = self._source_runtime()
        target = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        target.root.mkdir(parents=True)
        user = "S-1-5-21-1000"
        acl = (
            AclEvidence(str(target.root.parent), user, False, False, ((user, "FULL_CONTROL", True),)),
            AclEvidence(str(target.root), user, True, False, ((user, "FULL_CONTROL", True),)),
        )
        with self.assertRaisesRegex(PreconditionError, "SOURCE_CORE_NOT_QUIESCED"):
            prepare_core_migration(
                source_runtime=runtime,
                source_data=data,
                target=target,
                operation_id="migration-01",
                expected_source_head=head,
                source_service_state="RUNNING",
                target_service_state="MISSING",
                acl_evidence=acl,
                current_user_sid=user,
            )
        receipt = prepare_core_migration(
            source_runtime=runtime,
            source_data=data,
            target=target,
            operation_id="migration-01",
            expected_source_head=head,
            source_service_state="STOPPED",
            target_service_state="MISSING",
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
        with self.assertRaisesRegex(PreconditionError, "TARGET_MUST_BE_NEW"):
            prepare_core_migration(
                source_runtime=runtime,
                source_data=data,
                target=target,
                operation_id="migration-01",
                expected_source_head=head,
                source_service_state="STOPPED",
                target_service_state="MISSING",
                acl_evidence=acl,
                current_user_sid=user,
            )

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
        source = self.base / "RCC"
        extension = source / "extension"
        native = source / "native"
        extension.mkdir(parents=True)
        native.mkdir()
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
        target = OperatingPathLayout.from_local_app_data(self.base / "LocalAppData")
        target.root.mkdir(parents=True)
        user = "S-1-5-21-1000"
        acl = (
            AclEvidence(str(target.root.parent), user, False, False, ((user, "FULL_CONTROL", True),)),
            AclEvidence(str(target.root), user, True, False, ((user, "FULL_CONTROL", True),)),
        )
        receipt = prepare_rcc_migration(
            source_extension=extension,
            source_host_executable=host,
            source_native_manifest=host_manifest,
            target=target,
            expected_extension_id=extension_id,
            acl_evidence=acl,
            current_user_sid=user,
        )
        self.assertFalse(receipt["registry_changed"])
        self.assertFalse(receipt["chrome_changed"])
        self.assertFalse(receipt["activation_allowed"])
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
