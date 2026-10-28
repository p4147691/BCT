from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bct import BCT
from bct.core.approval import request_hash
from bct.core.models import AuthorizationError, Outcome, Principal
from bct.features.pc_safe_plans import FileActionPlanFeature
from bct.service_runtime import process_identity


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class SignedP2ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = Ed25519PrivateKey.generate()
        public = b64(self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ))
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["file_action_plan","process_stop_plan"]\n'
            'approval_actions=["file_action_apply","process_stop_apply"]\n'
            '[approval_verifier]\nenabled=true\n'
            f'ed25519_public_key="{public}"\n', encoding="utf8",
        )
        self.bct = BCT(
            state_path=self.root / "bct.sqlite", policy_path=self.policy,
            data_root=self.root,
        )
        self.owner = Principal("sandbox-test-principal", "test",
                               frozenset({"file_action_apply", "file_action_plan",
                                          "process_stop_apply", "process_stop_plan"}))
        self.work_id = "sandbox-approval-p2"
        self.bct.create_work(work_id=self.work_id, request_summary="sandbox only",
                             roots=[str(self.root)],
                             actions=sorted(self.owner.capabilities), principal=self.owner)
        self.source = self.root / "sample.bin"
        self.source.write_bytes(b"isolated-sample-2026")
        self.target = self.root / "recovery" / "sample.bin"
        self.target.parent.mkdir()
        self.addCleanup(self._cleanup_benign_processes)
        self.processes = []

    def _cleanup_benign_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    def make_file_args(self, source=None, target=None, operation="recoverable_delete"):
        source = source or self.source
        target = target or self.target
        preview = FileActionPlanFeature()
        work = self.bct.store.get_work(self.work_id)
        op = "quarantine_preview" if operation == "recoverable_delete" else "move_preview"
        prepared = preview.prepare(work=work, arguments={
            "operation": op, "source": str(source),
            "destination": str(target),
        })
        proof = preview.execute(prepared).output
        return {"operation": operation, "source": str(source),
                "destination": str(target), "plan_sha256": proof["plan_sha256"]}

    def grant(self, *, operation_id, capability, arguments, expires=None,
              confirmed=True, principal_id=None, work_id=None, nonce=None):
        work_id = work_id or self.work_id
        principal_id = principal_id or self.owner.principal_id
        feature = self.bct.operations._features[capability]
        request = feature.prepare(work=self.bct.store.get_work(self.work_id), arguments=arguments)
        now = time.time()
        claims = {
            "aud": "bct-p2-action-v1", "user_confirmed": confirmed,
            "nonce": nonce or os.urandom(16).hex(),
            "principal_id": principal_id, "work_id": work_id,
            "operation_id": operation_id, "capability": capability,
            "target": request.target,
            "request_sha256": request_hash(work_id, capability, request.target,
                                            request.arguments, request.preconditions),
            "issued_at": now - 3, "expires_at": expires or now + 180,
        }
        body = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf8")
        return b64(body) + "." + b64(self.private.sign(body))

    def call(self, operation_id, arguments, grant=None, capability="file_action_apply"):
        return self.bct.operations.run(
            principal=self.owner, work_id=self.work_id,
            operation_id=operation_id, capability=capability,
            arguments=arguments, approval_ref=grant,
        )

    def register_start_receipt(self, session_id, identity):
        work = self.bct.store.get_work(self.work_id)
        operation_id = "start-" + session_id
        self.bct.store.begin_operation(
            operation_id=operation_id, work=work,
            principal_id=self.owner.principal_id,
            request_digest="a" * 64, capability="process_session",
            target=session_id, resources=("process-session:" + session_id,),
            policy_revision="test-ephemeral-only",
        )
        self.bct.store.finish_operation(
            operation_id=operation_id, outcome=Outcome.APPLIED,
            evidence={"already_running": False, "session": {
                "session_id": session_id, "work_id": self.work_id,
                "process": identity.as_dict(),
            }}, error=None, release_claims=True,
        )
        return operation_id

    def test_signed_recoverable_delete_and_receipt(self):
        args = self.make_file_args()
        token = self.grant(operation_id="quarantine-1",
                           capability="file_action_apply", arguments=args)
        result = self.call("quarantine-1", args, token)
        self.assertEqual(Outcome.APPLIED, result.outcome, result)
        self.assertFalse(self.source.exists())
        self.assertEqual(b"isolated-sample-2026", self.target.read_bytes())
        self.assertEqual(str(self.source.resolve()), result.output["recovery"]["destination"])
        self.assertTrue(result.output["recovery"]["requires_new_signed_approval"])

    def test_exact_duplicate_no_second_effect(self):
        args = self.make_file_args()
        token = self.grant(operation_id="once", capability="file_action_apply", arguments=args)
        a = self.call("once", args, token)
        b = self.call("once", args, token)
        self.assertEqual(Outcome.APPLIED, a.outcome)
        self.assertTrue(b.duplicate)
        self.assertTrue(self.target.exists())

    def test_restore_requires_separate_signed_request(self):
        first = self.make_file_args()
        token = self.grant(operation_id="quarantine",
                           capability="file_action_apply", arguments=first)
        self.assertEqual(Outcome.APPLIED, self.call("quarantine", first, token).outcome)
        restore = self.make_file_args(self.target, self.source, operation="restore")
        restore_token = self.grant(operation_id="restore",
                                   capability="file_action_apply", arguments=restore)
        self.assertEqual(Outcome.APPLIED, self.call("restore", restore, restore_token).outcome)
        self.assertEqual(b"isolated-sample-2026", self.source.read_bytes())
        self.assertFalse(self.target.exists())

    def test_missing_or_forged_grant_rejected(self):
        args = self.make_file_args()
        for token in (None, "fake", "a.b"):
            with self.subTest(token=token), self.assertRaises(AuthorizationError):
                self.call("no-user-approval", args, token)
        self.assertTrue(self.source.exists())

    def test_wrong_operation_grant_rejected(self):
        args = self.make_file_args()
        token = self.grant(operation_id="right",capability="file_action_apply",arguments=args)
        with self.assertRaisesRegex(AuthorizationError, "SCOPE_MISMATCH"):
            self.call("wrong", args, token)

    def test_expired_or_unconfirmed_grant_rejected(self):
        args = self.make_file_args()
        for kwargs in ({"expires": time.time() - 1}, {"confirmed": False}):
            token = self.grant(operation_id="expired",capability="file_action_apply",arguments=args,**kwargs)
            with self.assertRaises(AuthorizationError):
                self.call("expired", args, token)

    def test_source_changed_after_preview_not_applied(self):
        args = self.make_file_args()
        token = self.grant(operation_id="changed",capability="file_action_apply",arguments=args)
        self.source.write_bytes(b"changed-by-test")
        result = self.call("changed", args, token)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())

    def test_destination_collision_not_applied(self):
        args = self.make_file_args()
        token = self.grant(operation_id="collision",capability="file_action_apply",arguments=args)
        self.target.write_bytes(b"preserve")
        result = self.call("collision", args, token)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual(b"preserve", self.target.read_bytes())

    def test_approval_consume_one_time_even_when_precondition_fails(self):
        args = self.make_file_args()
        nonce = os.urandom(16).hex()
        token = self.grant(operation_id="failed",capability="file_action_apply",
                           arguments=args,nonce=nonce)
        self.target.write_bytes(b"collision")
        self.assertEqual(Outcome.NOT_APPLIED, self.call("failed",args,token).outcome)
        # A new operation cannot reuse the signed exact request or consumed nonce.
        with self.assertRaises(AuthorizationError):
            self.call("other", args, token)

    def test_process_force_only_exact_owned_ephemeral_child(self):
        # The only terminated process is a fresh disposable test subprocess.
        process = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.processes.append(process)
        identity = None
        for _ in range(30):
            identity = process_identity(process.pid)
            if identity:
                break
            time.sleep(0.05)
        self.assertIsNotNone(identity)
        session_id = "p2-signed-ephemeral-owned"
        d = self.root / "process-sessions" / session_id
        d.mkdir(parents=True)
        (d / "session.json").write_text(json.dumps({
            "session_id": session_id, "work_id": self.work_id,
            "state": "RUNNING", "process": identity.as_dict(),
        }),encoding="utf8")
        start_id = self.register_start_receipt(session_id, identity)
        args = {"session_id": session_id, "start_operation_id": start_id,
                "expected_fingerprint": identity.fingerprint, "mode": "force"}
        token = self.grant(operation_id="ephemeral-stop",
                           capability="process_stop_apply", arguments=args)
        result = self.call("ephemeral-stop", args, token,capability="process_stop_apply")
        self.assertEqual(Outcome.APPLIED,result.outcome,result)
        self.assertTrue(result.output["stopped"])
        self.assertIsNotNone(process.poll())


    def test_begin_resume_consumes_one_exact_grant(self):
        args = self.make_file_args()
        token = self.grant(operation_id="resume-grant", capability="file_action_apply",
                           arguments=args)
        created, pending = self.bct.operations.begin(
            principal=self.owner, work_id=self.work_id,
            operation_id="resume-grant", capability="file_action_apply",
            arguments=args, approval_ref=token)
        self.assertTrue(created)
        result = self.bct.operations.resume(
            principal=self.owner, work_id=self.work_id,
            operation_id="resume-grant", capability="file_action_apply",
            arguments=args, approval_ref=token)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertTrue(self.target.exists())
        second = self.call("resume-grant", args, token)
        self.assertTrue(second.duplicate)

    def test_unknown_move_never_reexecutes_with_new_operation(self):
        from unittest.mock import patch
        from bct.core.models import Outcome
        args = self.make_file_args()
        token = self.grant(operation_id="uncertain-move", capability="file_action_apply",
                           arguments=args)
        real_rename = os.rename
        calls = []

        def effect_then_lost_ack(src, dst):
            calls.append((src, dst))
            real_rename(src, dst)
            raise OSError("simulated lost response after exact rename")

        with patch("bct.features.pc_safe_apply.os.rename", side_effect=effect_then_lost_ack):
            initial = self.call("uncertain-move",args,token)
            second = self.call("uncertain-move",args,token)
        self.assertEqual(Outcome.UNKNOWN, initial.outcome)
        self.assertEqual(Outcome.UNKNOWN, second.outcome)
        self.assertTrue(second.duplicate)
        self.assertEqual(1,len(calls))
        self.assertFalse(self.source.exists())
        self.assertTrue(self.target.exists())

    def test_distinct_force_request_cannot_use_graceful_approval(self):
        # Signing a graceful request never permits a force request or PID swap.
        args = {"session_id":"owned-test-session",
                "start_operation_id":"nonexistent-start",
                "expected_fingerprint":"0"*64,"mode":"graceful"}
        # The signer cannot mint an approval for an unowned session.
        with self.assertRaises(Exception):
            self.grant(operation_id="graceful-only",
                       capability="process_stop_apply", arguments=args)

    def test_verifier_disabled_rejects_valid_signature(self):
        args = self.make_file_args()
        token = self.grant(operation_id="disabled-verifier",
                           capability="file_action_apply",arguments=args)
        self.policy.write_text(self.policy.read_text(encoding="utf8").replace(
            "enabled=true","enabled=false"),encoding="utf8")
        with self.assertRaisesRegex(AuthorizationError, "APPROVAL_VERIFIER_DISABLED"):
            self.call("disabled-verifier",args,token)
        self.assertTrue(self.source.exists())

    def test_approval_policy_cannot_be_normal_action(self):
        args = self.make_file_args()
        token = self.grant(operation_id="unsafe-policy",
                           capability="file_action_apply",arguments=args)
        policy = self.policy.read_text(encoding="utf8")
        policy = policy.replace(
            'normal_actions=["file_action_plan","process_stop_plan"]',
            'normal_actions=["file_action_plan","process_stop_plan","file_action_apply"]'
        ).replace(
            'approval_actions=["file_action_apply","process_stop_apply"]',
            'approval_actions=["process_stop_apply"]'
        )
        self.policy.write_text(policy,encoding="utf8")
        with self.assertRaisesRegex(AuthorizationError,"P2_APPROVAL_ONLY_POLICY_REQUIRED"):
            self.call("unsafe-policy",args,token)

    def test_wrong_request_hash_rejected_even_if_signed(self):
        args = self.make_file_args()
        token = self.grant(operation_id="hash-mismatch",
                           capability="file_action_apply",arguments=args)
        changed = {**args,"plan_sha256":"0"*64}
        with self.assertRaisesRegex(AuthorizationError,"APPROVAL_SCOPE_MISMATCH"):
            self.call("hash-mismatch",changed,token)


    def _make_owned_ephemeral(self, session_id="p2-protected-ephemeral"):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.processes.append(process)
        identity = process_identity(process.pid)
        self.assertIsNotNone(identity)
        directory = self.root / "process-sessions" / session_id
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({
            "session_id": session_id, "work_id": self.work_id,
            "state": "RUNNING", "process": identity.as_dict(),
        }),encoding="utf8")
        start_id = self.register_start_receipt(session_id, identity)
        args = {"session_id": session_id, "start_operation_id": start_id,
                "expected_fingerprint": identity.fingerprint, "mode": "force"}
        return process, args

    def test_forged_session_file_without_bct_start_receipt_blocked(self):
        from bct.core.models import PreconditionError
        session_id = "forged-session-file"
        fake = {
            "pid": 9999, "executable": r"C:\\Temp\\fake.exe",
            "creation_marker": "unverified", "fingerprint": "b" * 64,
        }
        directory = self.root / "process-sessions" / session_id
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({
            "session_id": session_id, "work_id": self.work_id,
            "state": "RUNNING", "process": fake,
        }), encoding="utf8")
        args = {"session_id": session_id,
                "start_operation_id": "no-such-start-receipt",
                "expected_fingerprint": "b" * 64, "mode": "force"}
        with self.assertRaisesRegex(PreconditionError, "START_RECEIPT_NOT_FOUND"):
            self.bct.operations._features["process_stop_apply"].prepare(
                work=self.bct.store.get_work(self.work_id), arguments=args,
            )

    def test_no_signed_approval_never_terminates_test_child(self):
        process, args = self._make_owned_ephemeral()
        with self.assertRaises(AuthorizationError):
            self.call("unauthorized-force", args, None, capability="process_stop_apply")
        self.assertIsNone(process.poll())

    def test_protected_binary_never_terminated(self):
        from unittest.mock import patch
        process, args = self._make_owned_ephemeral()
        token = self.grant(operation_id="protected-force",
                           capability="process_stop_apply",arguments=args)
        with patch("bct.features.pc_process_apply._protected",return_value=True):
            result = self.call("protected-force",args,token,capability="process_stop_apply")
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertIsNone(process.poll())

    def test_child_processes_block_force_stop(self):
        from unittest.mock import patch
        process, args = self._make_owned_ephemeral()
        token = self.grant(operation_id="descendants-force",
                           capability="process_stop_apply",arguments=args)
        with patch("bct.features.pc_process_apply.psutil.Process.children",
                   return_value=[object()]):
            result = self.call("descendants-force",args,token,capability="process_stop_apply")
        self.assertEqual(Outcome.NOT_APPLIED,result.outcome)
        self.assertIsNone(process.poll())

    def test_graceful_request_does_not_force_python(self):
        process, args = self._make_owned_ephemeral()
        args["mode"] = "graceful"
        token = self.grant(operation_id="graceful-py",
                           capability="process_stop_apply",arguments=args)
        result = self.call("graceful-py",args,token,capability="process_stop_apply")
        self.assertEqual(Outcome.NOT_APPLIED,result.outcome)
        self.assertIsNone(process.poll())
