"""Isolated approval issuer workflow (no real UI focus or operational effects)."""
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

from bct import BCT
from bct.approval_issuer import (
    IssuerKeyStore, challenge_display, issue_after_human_confirmation,
    validate_challenge,
)
from bct.core.models import AuthorizationError, Outcome, Principal
from bct.features.pc_safe_plans import FileActionPlanFeature


class IndependentApprovalIssuerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.secret = "very long human-only passphrase $2026!"
        self.store = IssuerKeyStore(self.root / "offline-user-key" / "identity-v1.json")
        self.public = self.store.initialize(self.secret)
        self.policy_path = self.root / "bct.toml"
        self.policy_path.write_text(
            '[policy]\n'
            'normal_actions=["file_action_plan","approval_challenge"]\n'
            'approval_actions=["file_action_apply","process_stop_apply"]\n'
            '[approval_verifier]\nenabled=true\n'
            f'ed25519_public_key="{self.public}"\n',
            encoding="utf8",
        )
        self.db = self.root / "test-state.sqlite"
        self.owner = Principal(
            "human-approval-sandbox", "test",
            frozenset({"file_action_plan", "approval_challenge", "file_action_apply"}),
        )
        self.bct = BCT(state_path=self.db, policy_path=self.policy_path,
                       data_root=self.root)
        self.bct.create_work(
            work_id="human-approval-work", request_summary="only temp",
            roots=[str(self.root)],
            actions=["file_action_plan","approval_challenge","file_action_apply"],
            principal=self.owner,
        )
        self.src = self.root / "source-file.txt"
        self.src.write_text("BCT isolated signing example", encoding="utf8")
        self.dst = self.root / "recovery" / "source-file.txt"
        self.dst.parent.mkdir()

    def build_request(self):
        work = self.bct.store.get_work("human-approval-work")
        plan_feature = FileActionPlanFeature()
        args = {"operation": "quarantine_preview",
                "source": str(self.src), "destination": str(self.dst)}
        prepared = plan_feature.prepare(work=work, arguments=args)
        plan = plan_feature.execute(prepared).output
        return {"operation": "recoverable_delete", "source": str(self.src),
                "destination": str(self.dst), "plan_sha256": plan["plan_sha256"]}

    def challenge(self, operation_id="human-approved-op"):
        args = self.build_request()
        receipt = self.bct.operations.run(
            principal=self.owner, work_id="human-approval-work",
            operation_id="challenge-" + operation_id,
            capability="approval_challenge", arguments={
                "capability": "file_action_apply", "operation_id": operation_id,
                "arguments": args,
            },
        )
        self.assertEqual(Outcome.APPLIED, receipt.outcome)
        self.assertFalse(receipt.evidence["approval_issued"])
        return receipt.output["challenge"], args

    def execute_file(self, op, args, token):
        return self.bct.operations.run(
            principal=self.owner, work_id="human-approval-work",
            operation_id=op, capability="file_action_apply",
            arguments=args, approval_ref=token,
        )

    def test_first_enrollment_stores_only_encrypted_key(self):
        raw = self.store.path.read_text(encoding="utf8")
        body = json.loads(raw)
        self.assertEqual("BCT_P2_ENCRYPTED_ED25519_V1", body["format"])
        self.assertNotIn(self.secret, raw)
        self.assertNotIn("BEGIN PRIVATE KEY", raw)
        self.assertEqual(self.public, self.store.public_key())
        with self.assertRaises(FileExistsError):
            self.store.initialize(self.secret)
        with self.assertRaises(ValueError):
            self.store.load("incorrect human passphrase length 2026")

    def test_user_denial_produces_no_grant_and_effect_denied(self):
        challenge, args = self.challenge("human-denied")
        token = issue_after_human_confirmation(
            challenge, self.store, self.secret, confirmed=False)
        self.assertIsNone(token)
        with self.assertRaises(AuthorizationError):
            self.execute_file("human-denied", args, token)
        self.assertTrue(self.src.exists())
        self.assertFalse(self.dst.exists())

    def test_approve_issue_effect_and_duplicate_after_restart(self):
        challenge, args = self.challenge()
        text = challenge_display(challenge)
        self.assertIn(args["source"], text)
        self.assertIn(args["destination"], text)
        self.assertIn("recoverable_delete", text)
        token = issue_after_human_confirmation(
            challenge, self.store, self.secret, confirmed=True)
        result = self.execute_file("human-approved-op", args, token)
        self.assertEqual(Outcome.APPLIED, result.outcome, result)
        self.assertFalse(self.src.exists())
        self.assertEqual("BCT isolated signing example",
                         self.dst.read_text(encoding="utf8"))
        # A freshly created BCT instance must reuse original durable receipt.
        restarted = BCT(state_path=self.db, policy_path=self.policy_path,
                        data_root=self.root)
        duplicate = restarted.operations.run(
            principal=self.owner, work_id="human-approval-work",
            operation_id="human-approved-op", capability="file_action_apply",
            arguments=args, approval_ref=token,
        )
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(Outcome.APPLIED, duplicate.outcome)

    def test_ui_request_cannot_lie_about_signed_contents(self):
        challenge, _ = self.challenge()
        challenge["arguments"]["destination"] = str(self.root / "different")
        with self.assertRaisesRegex(ValueError, "REQUEST_MISMATCH"):
            issue_after_human_confirmation(challenge, self.store,
                                           self.secret, confirmed=True)

    def test_issuer_rejects_new_extra_fields(self):
        challenge, _ = self.challenge()
        challenge["auto_approve"] = True
        with self.assertRaisesRegex(ValueError, "FIELDS_INVALID"):
            validate_challenge(challenge)

    def test_expired_grant_fails_before_effect(self):
        challenge, args = self.challenge("human-expired")
        token = issue_after_human_confirmation(
            challenge, self.store, self.secret,
            confirmed=True, now=time.time() - 500,
        )
        with self.assertRaisesRegex(AuthorizationError, "APPROVAL_EXPIRED"):
            self.execute_file("human-expired", args, token)
        self.assertTrue(self.src.exists())

    def test_signing_private_key_never_in_bct_policy(self):
        configuration = self.policy_path.read_text(encoding="utf8")
        self.assertIn(self.public, configuration)
        self.assertNotIn(self.secret, configuration)
        self.assertNotIn("ciphertext", configuration)

    def test_signer_has_no_batch_approval_cli(self):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        result = subprocess.run(
            [sys.executable, "-m", "bct.approval_issuer", "--approve"],
            cwd=self.root, env=environment, capture_output=True,
            text=True, timeout=8,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("GUI_ONLY", result.stderr + result.stdout)

    def test_approval_issuer_not_mcp_capability(self):
        self.assertNotIn("approval_issuer", self.bct.operations.capabilities)
        self.assertIn("approval_challenge", self.bct.operations.capabilities)
        self.assertIn("file_action_apply", self.bct.operations.capabilities)

    def test_untrusted_grant_cannot_change_operation(self):
        challenge, args = self.challenge("human-original")
        token = issue_after_human_confirmation(
            challenge, self.store, self.secret, confirmed=True,
        )
        with self.assertRaisesRegex(AuthorizationError, "SCOPE_MISMATCH"):
            self.execute_file("human-other", args, token)
        self.assertTrue(self.src.exists())


class SimulatedApprovalGuiTests(IndependentApprovalIssuerTests):
    """Headless UI callback test: not a claim of physical human consent."""

    def _run_mock_gui(self, challenge: dict, *, approve: bool):
        import types
        from unittest.mock import patch
        import bct.approval_issuer as issuer

        request_file = self.root / "request.json"
        request_file.write_text(json.dumps(challenge), encoding="utf8")
        output_file = self.root / "granted.approval"
        buttons = {}
        outcome = {"yes_no_count": 0}

        class FakeElement:
            def __init__(self, *a, **kw):
                pass
            def grid(self, *a, **kw):
                pass
            def pack(self, *a, **kw):
                pass
            def configure(self, *a, **kw):
                pass
            def delete(self, *a, **kw):
                pass
            def insert(self, *a, **kw):
                pass

        class FakeStringVar:
            def __init__(self, value=""):
                self.value = value
            def set(self, value):
                self.value = value

        class FakeRoot:
            def title(self, *_): pass
            def geometry(self, *_): pass
            def minsize(self, *_): pass
            def attributes(self, *_): pass
            def columnconfigure(self, *a, **kw): pass
            def rowconfigure(self, *a, **kw): pass
            def destroy(self): pass
            def mainloop(self):
                buttons["요청 파일 열기"]()
                buttons["승인하고 서명" if approve else "거부"]()

        class FakeButton(FakeElement):
            def __init__(self, *a, **kw):
                buttons[kw["text"]] = kw["command"]

        module = types.ModuleType("tkinter")
        module.Tk = FakeRoot
        module.Text = FakeElement
        module.StringVar = FakeStringVar
        module.ttk = types.SimpleNamespace(
            Label=FakeElement, Frame=FakeElement, Button=FakeButton,
        )
        module.filedialog = types.SimpleNamespace(
            askopenfilename=lambda **kw: str(request_file),
            asksaveasfilename=lambda **kw: str(output_file),
        )

        def confirmation(*a, **kw):
            outcome["yes_no_count"] += 1
            return True

        module.messagebox = types.SimpleNamespace(
            askyesno=confirmation,
            showerror=lambda *a, **kw: None,
            showwarning=lambda *a, **kw: None,
        )
        strings = iter([challenge["operation_id"], self.secret])
        module.simpledialog = types.SimpleNamespace(
            askstring=lambda *a, **kw: next(strings),
        )
        with patch.dict(sys.modules, {"tkinter": module}):
            with patch.object(issuer, "default_identity_path", return_value=self.store.path):
                issuer._launch_gui()
        return output_file, outcome

    def test_ui_callbacks_yes_signed_effect(self):
        challenge, args = self.challenge("ui-yes")
        output, confirmations = self._run_mock_gui(challenge, approve=True)
        self.assertEqual(1, confirmations["yes_no_count"])
        self.assertTrue(output.exists())
        grant = output.read_text(encoding="ascii").strip()
        result = self.execute_file("ui-yes", args, grant)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertTrue(self.dst.exists())

    def test_ui_callbacks_no_creates_no_grant(self):
        challenge, args = self.challenge("ui-no")
        output, confirmations = self._run_mock_gui(challenge, approve=False)
        self.assertEqual(0, confirmations["yes_no_count"])
        self.assertFalse(output.exists())
        self.assertTrue(self.src.exists())
