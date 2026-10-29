"""Normal mode tests: scoped move, rename, recovery prompt, owned stop.

No existing operational file or process is touched.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct import BCT
from bct.core.models import AuthorizationError, Outcome, Principal, PreconditionError
from bct.features.pc_local_mode import LocalFileActionFeature, LocalProcessStopFeature


class LocalFileWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "policy.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["file_local_action","process_local_stop"]\n'
            'approval_actions=["file_action_apply","process_stop_apply"]\n'
            '[approval_verifier]\nenabled=false\n',
            encoding="utf8")
        self.bct = BCT(state_path=self.root / "state.sqlite",
                       policy_path=self.policy, data_root=self.root)
        self.owner = Principal("local-pc-owner", "test",
                               frozenset({"file_local_action", "process_local_stop",
                                          "file_action_apply"}))
        self.work_id = "file-local-fixtures"
        self.bct.create_work(work_id=self.work_id, request_summary="isolated",
                             roots=[str(self.root)],
                             actions=["file_local_action","process_local_stop",
                                      "file_action_apply"], principal=self.owner)
        self.original = self.root / "original.txt"
        self.original.write_text("local-action-fixture", encoding="utf8")

    def run_local(self, op_id, operation, *, source=None, destination=None):
        args = {"operation": operation, "source": str(source or self.original)}
        if destination is not None:
            args["destination"] = str(destination)
        return self.bct.operations.run(
            principal=self.owner, work_id=self.work_id,
            operation_id=op_id, capability="file_local_action", arguments=args)

    def test_rename_in_same_directory_without_signed_grant(self):
        target = self.root / "renamed.txt"
        result = self.run_local("rename-one", "rename", destination=target)
        self.assertEqual(Outcome.APPLIED, result.outcome, result)
        self.assertFalse(self.original.exists())
        self.assertEqual("local-action-fixture", target.read_text(encoding="utf8"))
        replay = self.run_local("rename-one", "rename", destination=target)
        self.assertTrue(replay.duplicate)
        self.assertEqual(Outcome.APPLIED, replay.outcome)

    def test_move_into_existing_subdirectory(self):
        newdir = self.root / "new-location"
        newdir.mkdir()
        target = newdir / "original.txt"
        result = self.run_local("move-one", "move", destination=target)
        self.assertEqual(Outcome.APPLIED, result.outcome, result)
        self.assertTrue(target.exists())
        self.assertFalse(self.original.exists())

    def test_rename_to_other_folder_rejected(self):
        sub = self.root / "other"
        sub.mkdir()
        with self.assertRaisesRegex(PreconditionError, "RENAME_MUST_STAY"):
            self.run_local("bad-rename", "rename", destination=sub / "renamed.txt")

    def test_normal_mode_user_yes_confirms_recoverable_delete(self):
        with patch("bct.features.pc_local_mode._confirm_recoverable_delete",
                   return_value=True) as confirm:
            result = self.run_local("local-recycle", "recoverable_delete")
        self.assertEqual(Outcome.APPLIED, result.outcome, result)
        confirm.assert_called_once()
        self.assertFalse(self.original.exists())
        target = self.root / ".bct-recovery" / self.original.name
        self.assertTrue(target.is_file())
        self.assertEqual("local-action-fixture", target.read_text(encoding="utf8"))
        self.assertTrue(result.evidence["local_mode"])
        replay = self.run_local("local-recycle", "recoverable_delete")
        self.assertTrue(replay.duplicate)

    def test_local_delete_user_no_does_not_mutate(self):
        with patch("bct.features.pc_local_mode._confirm_recoverable_delete",
                   return_value=False):
            result = self.run_local("local-decline", "recoverable_delete")
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertTrue(self.original.exists())
        self.assertFalse((self.root / ".bct-recovery").exists())

    def test_unavailable_confirmation_does_not_mutate(self):
        with patch("bct.features.pc_local_mode._confirm_recoverable_delete",
                   side_effect=PreconditionError("LOCAL_DELETE_CONFIRMATION_UNAVAILABLE")):
            result = self.run_local("local-unavailable", "recoverable_delete")
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertTrue(self.original.exists())

    def test_recovery_path_collision_is_not_overwritten(self):
        recovery = self.root / ".bct-recovery"
        recovery.mkdir()
        target = recovery / self.original.name
        target.write_text("existing recovery", encoding="utf8")
        with patch("bct.features.pc_local_mode._confirm_recoverable_delete") as confirm:
            result = self.run_local("local-collision", "recoverable_delete")
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        confirm.assert_not_called()
        self.assertEqual("existing recovery", target.read_text(encoding="utf8"))
        self.assertTrue(self.original.exists())

    def test_normal_move_destination_existing_not_overwritten(self):
        target = self.root / "occupied.txt"
        target.write_text("preserve me", encoding="utf8")
        result = self.run_local("local-occupied", "move", destination=target)
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual("preserve me", target.read_text(encoding="utf8"))

    def test_attempt_outside_work_root_is_denied(self):
        outside = self.root.parent / "outside.txt"
        with self.assertRaises(PreconditionError):
            self.run_local("outside", "move", destination=outside)

    def test_protected_path_blocks_even_with_local_work_authority(self):
        with patch("bct.features.pc_local_mode._protected", return_value=True):
            with self.assertRaisesRegex(PreconditionError, "PROTECTED"):
                self.run_local("protected", "move", destination=self.root / "bad.txt")

    def test_high_security_still_requires_approval(self):
        arguments = {
            "operation": "move", "source": str(self.original),
            "destination": str(self.root / "high.txt"), "plan_sha256": "0"*64,
        }
        with self.assertRaises(AuthorizationError):
            self.bct.operations.run(
                principal=self.owner, work_id=self.work_id,
                operation_id="high-mode-no-signature",
                capability="file_action_apply", arguments=arguments)
        self.assertTrue(self.original.exists())

    def test_other_owner_has_no_authority(self):
        stranger = Principal("someone-else","test",frozenset({"file_local_action"}))
        with self.assertRaises(AuthorizationError):
            self.bct.operations.run(
                principal=stranger, work_id=self.work_id,
                operation_id="other-person", capability="file_local_action",
                arguments={"operation":"move","source":str(self.original),
                           "destination":str(self.root/"other.txt")})

    def test_force_is_not_part_of_normal_process_api(self):
        feature = self.bct.operations._features["process_local_stop"]
        with self.assertRaisesRegex(PreconditionError, "LOCAL_PROCESS_FIELDS_INVALID"):
            feature.prepare(work=self.bct.store.get_work(self.work_id), arguments={
                "session_id":"no-session", "start_operation_id":"none",
                "expected_fingerprint":"0"*64, "mode":"force",
            })

    def test_no_permanent_delete_operation(self):
        with self.assertRaisesRegex(PreconditionError, "OPERATION_INVALID"):
            self.run_local("permanent-is-blocked","permanent_delete")

    def test_restore_from_recovery_with_normal_work_scope(self):
        with patch("bct.features.pc_local_mode._confirm_recoverable_delete",return_value=True):
            self.assertEqual(Outcome.APPLIED,
                             self.run_local("delete-for-restore","recoverable_delete").outcome)
        saved = self.root / ".bct-recovery" / self.original.name
        result = self.run_local("restore-from-trash","restore",
                                source=saved, destination=self.original)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertTrue(self.original.exists())
        self.assertFalse(saved.exists())

    def test_delete_confirmation_race_blocks_changed_source(self):
        def approve_after_edit(**_details):
            self.original.write_text("changed-while-dialog-open", encoding="utf8")
            return True
        with patch("bct.features.pc_local_mode._confirm_recoverable_delete",
                   side_effect=approve_after_edit):
            result = self.run_local("changed-confirmed", "recoverable_delete")
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual("changed-while-dialog-open",
                         self.original.read_text(encoding="utf8"))
        self.assertFalse((self.root/".bct-recovery"/self.original.name).exists())

    def test_restore_and_file_move_are_one_shot_on_unknown(self):
        from unittest.mock import patch
        target = self.root / "unknown-target.txt"
        actual = __import__("os").rename
        changed = []
        def effect_then_unknown(src, dst):
            changed.append(1)
            actual(src, dst)
            raise OSError("simulated lost filesystem ACK")
        with patch("bct.features.pc_safe_apply.os.rename",
                   side_effect=effect_then_unknown):
            result = self.run_local("unknown-original", "move", destination=target)
            again = self.run_local("unknown-original", "move", destination=target)
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        self.assertEqual(Outcome.UNKNOWN, again.outcome)
        self.assertTrue(again.duplicate)
        self.assertEqual(1, len(changed))

    def test_process_stop_scope_preserves_high_security(self):
        with self.assertRaises(AuthorizationError):
            self.bct.operations.run(
                principal=self.owner, work_id=self.work_id,
                operation_id="high-process-no-grant",
                capability="process_stop_apply",
                arguments={"session_id":"x","start_operation_id":"y",
                           "expected_fingerprint":"0"*64,"mode":"force"})
