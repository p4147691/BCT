"""Security-boundary adversarial tests: pure ACL simulation + read-only host probe.

No real user accounts or live ACLs are modified. Dual-token physical acceptance
is deliberately a separate supervisor gate.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.approval_boundary import (
    require_core_boundary, require_issuer_boundary, validate_acl,
    validate_identities, inspect_dacl,
)
from bct.core.approval import ApprovalVerifier
from bct.core.models import AuthorizationError

AUTOMATION = "S-1-5-21-100-200-300-1001"
CORE = "S-1-5-21-100-200-300-1002"
APPROVER = "S-1-5-21-100-200-300-1003"
ATTACKER = "S-1-5-21-100-200-300-1004"
SYSTEM = "S-1-5-18"
ADMINS = "S-1-5-32-544"


def manifest(root: Path):
    return {"schema": 1, "automation_sid": AUTOMATION,
            "core_sid": CORE, "approver_sid": APPROVER,
            "core_executable": str(root / "Core" / "server.exe"),
            "issuer_executable": str(root / "Issuer" / "approval_issuer.py"),
            "issuer_key_path": str(root / "Approver" / "identity-v1.json")}


def acl(*, owner=SYSTEM, protected=True, extra=()):
    entries = [{"sid": SYSTEM, "mask": 0x1F01FF, "allow": True},
               {"sid": ADMINS, "mask": 0x1F01FF, "allow": True}]
    entries += [{"sid": sid, "mask": mask, "allow": True} for sid, mask in extra]
    return {"owner": owner, "protected": protected, "aces": entries}


class BoundarySecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = manifest(self.root)
        isolated = patch("bct.core.approval_boundary._is_isolated_python", return_value=True)
        isolated.start()
        self.addCleanup(isolated.stop)

    def test_distinct_unprivileged_roles_required(self):
        self.assertEqual(CORE, validate_identities(self.config)["core_sid"])
        for key, value in [
            ("approver_sid", AUTOMATION),
            ("core_sid", APPROVER),
            ("automation_sid", ADMINS),
            ("core_sid", "not-a-sid"),
        ]:
            with self.subTest(key=key, value=value):
                cfg = {**self.config, key: value}
                with self.assertRaises(AuthorizationError):
                    validate_identities(cfg)

    def test_system_owned_protected_dacl_allows_read_only_automation(self):
        validate_acl(acl(extra=[(AUTOMATION, 0x120089), (CORE, 0x120089)]),
                     writers={SYSTEM, ADMINS},
                     forbidden={AUTOMATION, CORE, APPROVER})

    def test_same_account_code_modify_is_denied_as_boundary(self):
        with self.assertRaisesRegex(AuthorizationError, "UNTRUSTED_WRITER"):
            validate_acl(acl(extra=[(AUTOMATION, 0x1301BF)]),
                         writers={SYSTEM, ADMINS},
                         forbidden={AUTOMATION})

    def test_other_account_modify_or_approver_code_replace_blocked(self):
        for who in (ATTACKER, APPROVER, "S-1-5-11"):
            with self.subTest(sid=who), self.assertRaisesRegex(
                    AuthorizationError, "UNTRUSTED_WRITER"):
                validate_acl(acl(extra=[(who, 0x1F01FF)]),
                             writers={SYSTEM, ADMINS}, forbidden={AUTOMATION})

    def test_owner_rights_and_inherited_acl_blocked(self):
        with self.assertRaisesRegex(AuthorizationError, "OWNER_UNTRUSTED"):
            validate_acl(acl(owner=AUTOMATION),
                         writers={SYSTEM, ADMINS}, forbidden={AUTOMATION})
        with self.assertRaisesRegex(AuthorizationError, "DACL_NOT_PROTECTED"):
            validate_acl(acl(protected=False),
                         writers={SYSTEM, ADMINS}, forbidden={AUTOMATION})

    def test_core_wrong_account_refuses_to_enable_approvals(self):
        (self.root / "policy.toml").write_text(
            '[policy]\nnormal_actions=["approval_challenge"]\n',
            encoding="utf8",
        )
        with patch("bct.core.approval_boundary.current_sid", return_value=AUTOMATION):
            with self.assertRaisesRegex(AuthorizationError, "WRONG_CORE_ACCOUNT"):
                require_core_boundary(self.config,
                                      policy_path=self.root / "policy.toml",
                                      state_path=self.root / "State" / "state.sqlite")

    def test_issuer_cannot_run_under_automation_or_core_identity(self):
        for who in (AUTOMATION, CORE):
            with self.subTest(role=who):
                with patch("bct.core.approval_boundary.current_sid", return_value=who):
                    with self.assertRaisesRegex(AuthorizationError, "WRONG_APPROVER_ACCOUNT"):
                        require_issuer_boundary(
                            self.config, issuer_module=Path(self.config["issuer_executable"]),
                            issuer_key=Path(self.config["issuer_key_path"]),
                        )

    def test_core_checks_policy_state_journal_and_code_acl(self):
        config = self.config
        paths = [self.root / "policy.toml",
                 self.root / "Core" / "server.exe",
                 self.root / "State" / "state.sqlite",
                 self.root / "State" / "state.sqlite-wal",
                 self.root / "State" / "state.sqlite-shm"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        (self.root / "policy.toml").write_text(
            '[policy]\nnormal_actions=["approval_challenge","read"]\n',
            encoding="utf8",
        )
        snapshot = acl(extra=[(CORE, 0x1301BF)])
        def different_acl(path):
            if path.name in ("state.sqlite", "state.sqlite-wal", "state.sqlite-shm") or path.name == "State":
                return snapshot
            return acl()
        with patch("bct.core.approval_boundary.current_sid", return_value=CORE):
            with patch("bct.core.approval_boundary.inspect_dacl", side_effect=different_acl) as inspected:
                with patch("bct.core.approval_boundary.sys.executable",
                           str(self.root / "Core" / "server.exe")):
                    with patch("bct.core.approval_boundary._runtime_source_paths",
                               return_value=[self.root / "Core" / "server.exe"]):
                        require_core_boundary(config, policy_path=self.root / "policy.toml",
                                              state_path=self.root / "State" / "state.sqlite")
        examined = {Path(call.args[0]).name for call in inspected.call_args_list}
        self.assertTrue({"state.sqlite", "state.sqlite-wal", "state.sqlite-shm"}.issubset(examined))

    def test_core_fails_on_automation_malicious_state_writer(self):
        for path in (self.root / "policy.toml",
                     self.root / "State" / "state.sqlite",
                     self.root / "Core" / "server.exe"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        (self.root / "policy.toml").write_text(
            '[policy]\nnormal_actions=["approval_challenge","read"]\n',
            encoding="utf8",
        )
        def inspect(path):
            if path.name == "state.sqlite":
                return acl(extra=[(CORE, 0x1301BF), (AUTOMATION, 0x1301BF)])
            return acl(extra=[(CORE, 0x120089)])
        with patch("bct.core.approval_boundary.current_sid", return_value=CORE):
            with patch("bct.core.approval_boundary.inspect_dacl", side_effect=inspect):
                with patch("bct.core.approval_boundary.sys.executable",
                           str(self.root / "Core" / "server.exe")):
                    with patch("bct.core.approval_boundary._runtime_source_paths",
                               return_value=[self.root / "Core" / "server.exe"]):
                        with self.assertRaisesRegex(AuthorizationError, "UNTRUSTED_WRITER"):
                            require_core_boundary(self.config,
                                                  policy_path=self.root / "policy.toml",
                                                  state_path=self.root / "State" / "state.sqlite")

    def test_enabled_verifier_without_protected_manifest_fails_closed(self):
        policy = self.root / "policy.toml"
        policy.write_text(
            '[policy]\nnormal_actions=[]\napproval_actions=["file_action_apply"]\n'
            '[approval_verifier]\nenabled=true\ned25519_public_key="a"\n',
            encoding="utf8",
        )
        verifier = ApprovalVerifier(policy_path=policy,
                                    state_path=self.root / "State" / "state.sqlite")
        with self.assertRaisesRegex(AuthorizationError, "MANIFEST_REQUIRED"):
            verifier._public_key()

    @unittest.skipUnless(os.name == "nt", "Windows ACL API required")
    def test_current_temporary_acl_not_assumed_protected(self):
        path = self.root / "probe.txt"
        path.write_text("read only audit", encoding="utf8")
        inspected = inspect_dacl(path)
        self.assertIn("owner", inspected)
        self.assertIn("aces", inspected)
        with self.assertRaises(AuthorizationError):
            validate_acl(inspected, writers={SYSTEM, ADMINS},
                         forbidden={AUTOMATION})

    def test_privileged_core_refuses_generic_command_capabilities(self):
        from bct.core.approval_boundary import require_effect_only_core_policy
        require_effect_only_core_policy(["read", "approval_challenge"])
        for action in ("execute", "write", "deploy", "process_session",
                       "desktop_input", "git_commit", "verify"):
            with self.subTest(capability=action):
                with self.assertRaisesRegex(AuthorizationError, "GENERAL_EFFECTS_ENABLED"):
                    require_effect_only_core_policy(["read", action])

    def test_malicious_issuer_key_directory_writer_is_rejected(self):
        issuer = Path(self.config["issuer_executable"])
        key = Path(self.config["issuer_key_path"])
        issuer.parent.mkdir(parents=True)
        key.parent.mkdir(parents=True)
        issuer.write_bytes(b"not operated")
        key.write_bytes(b"encrypted-only-fixture")
        def read_acl(path):
            if path == key.parent or path == key:
                return acl(owner=APPROVER, extra=[
                    (APPROVER, 0x1F01FF), (AUTOMATION, 0x1301BF)])
            return acl()
        with patch("bct.core.approval_boundary.current_sid", return_value=APPROVER):
            with patch("bct.core.approval_boundary.inspect_dacl", side_effect=read_acl):
                with self.assertRaisesRegex(AuthorizationError, "UNTRUSTED_WRITER"):
                    require_issuer_boundary(self.config,
                                            issuer_module=issuer, issuer_key=key)

    def test_signed_approval_cannot_bypass_current_host_unsafe_policy(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        private = Ed25519PrivateKey.generate()
        pub = base64.urlsafe_b64encode(private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )).decode("ascii").rstrip("=")
        policy = self.root / "policy.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["execute","approval_challenge"]\n'
            'approval_actions=["file_action_apply"]\n'
            '[approval_verifier]\nenabled=true\n'
            f'ed25519_public_key="{pub}"\n',
            encoding="utf8",
        )
        verifier = ApprovalVerifier(policy_path=policy,
                                    state_path=self.root / "state.sqlite")
        # A *valid* public key is insufficient without the protected manifest.
        with self.assertRaisesRegex(AuthorizationError, "MANIFEST_REQUIRED"):
            verifier._public_key()

    def test_issuer_source_replacement_fenced_by_exact_path(self):
        issuer = Path(self.config["issuer_executable"])
        unrelated = self.root / "writable-clone" / "approval_issuer.py"
        with patch("bct.core.approval_boundary.current_sid", return_value=APPROVER):
            with self.assertRaisesRegex(AuthorizationError, "ISSUER_LOCATION_MISMATCH"):
                require_issuer_boundary(self.config, issuer_module=unrelated,
                                        issuer_key=Path(self.config["issuer_key_path"]))
