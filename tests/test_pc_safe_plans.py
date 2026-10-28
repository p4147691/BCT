import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Work, PreconditionError, Outcome
from bct.features.pc_safe_plans import FileActionPlanFeature, ProcessStopPlanFeature


class FileActionPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "record.bin"
        self.source.write_bytes(b"demo-content")
        self.destination = self.root / "quarantine" / "record.bin"
        self.destination.parent.mkdir()
        self.work = Work("p2-local", "test", (str(self.root),),
                         frozenset({"file_action_plan"}), "test")
        self.feature = FileActionPlanFeature()

    def prepare(self, **changes):
        return self.feature.prepare(work=self.work, arguments={
            "operation": "quarantine_preview", "source": str(self.source),
            "destination": str(self.destination), **changes,
        })

    def test_reversible_plan_never_changes_files(self):
        request = self.prepare()
        result = self.feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())
        self.assertTrue(result.evidence["read_only"])
        self.assertFalse(result.output["apply_available"])
        self.assertEqual(str(self.source.resolve()), result.output["recovery"]["to"])
        self.assertEqual(64, len(result.output["source_state"]["sha256"]))

    def test_move_preview(self):
        req = self.prepare(operation="move_preview")
        self.assertEqual("move_preview", self.feature.execute(req).output["operation"])

    def test_destination_must_not_exist(self):
        self.destination.write_bytes(b"occupied")
        with self.assertRaisesRegex(PreconditionError, "DESTINATION_EXISTS"):
            self.prepare()

    def test_outside_work_denied(self):
        with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
            self.prepare(destination=str(self.root.parent / "outside.bin"))

    def test_same_path_rejected(self):
        with self.assertRaises(PreconditionError):
            self.prepare(destination=str(self.source))

    def test_symlink_source_rejected(self):
        link = self.root / "symlink.bin"
        try:
            link.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest("symlink privileges unavailable")
        with self.assertRaises(PreconditionError):
            self.prepare(source=str(link))

    def test_change_after_prepare_is_blocked(self):
        req = self.prepare()
        self.destination.write_bytes(b"race")
        with self.assertRaisesRegex(PreconditionError, "DESTINATION_CHANGED"):
            self.feature.execute(req)

    def test_large_file_is_not_planned(self):
        req = self.prepare()
        with patch("bct.features.pc_safe_plans._file_fingerprint",
                   side_effect=PreconditionError("FILE_PLAN_SOURCE_TOO_LARGE_OR_CHANGED")):
            with self.assertRaisesRegex(PreconditionError, "TOO_LARGE"):
                self.feature.execute(req)

    def test_unknown_fields_and_no_delete(self):
        with self.assertRaisesRegex(PreconditionError, "FIELDS_INVALID"):
            self.prepare(delete_permanently=True)
        with self.assertRaisesRegex(PreconditionError, "OPERATION_INVALID"):
            self.prepare(operation="delete")


class ProcessStopPlanTests(unittest.TestCase):
    def setUp(self):
        self.feature = ProcessStopPlanFeature()
        self.work = Work("p2-local", "test", ("C:\\",),
                         frozenset({"process_stop_plan"}), "test")
        self.fingerprint = {"pid": 501, "parent_pid": 50,
                            "created_at": 1700000000.125,
                            "executable": "C:\\Windows\\notepad.exe",
                            "name": "notepad.exe"}

    def test_read_only_identity_plan(self):
        request = self.feature.prepare(work=self.work, arguments={"pid": 501})
        with patch("bct.features.pc_safe_plans.process_fingerprint",
                   return_value=self.fingerprint), patch(
                   "bct.features.pc_safe_plans.process_matches", return_value=True):
            output = self.feature.execute(request)
        self.assertEqual(Outcome.APPLIED, output.outcome)
        self.assertFalse(output.output["stop_available"])
        self.assertFalse(output.output["stopped"])
        self.assertTrue(output.evidence["read_only"])

    def test_exact_identity_constraints(self):
        request = self.feature.prepare(work=self.work, arguments={
            "pid": 501, "expected_created_at": self.fingerprint["created_at"],
            "expected_executable": self.fingerprint["executable"],
        })
        with patch("bct.features.pc_safe_plans.process_fingerprint",
                   return_value=self.fingerprint), patch(
                   "bct.features.pc_safe_plans.process_matches", return_value=True):
            self.assertTrue(self.feature.execute(request).output["read_only"])

    def test_mismatched_creation_blocked(self):
        request = self.feature.prepare(work=self.work, arguments={
            "pid": 501, "expected_created_at": 1.0,
        })
        with patch("bct.features.pc_safe_plans.process_fingerprint",
                   return_value=self.fingerprint), patch(
                   "bct.features.pc_safe_plans.process_matches", return_value=True):
            with self.assertRaisesRegex(PreconditionError, "MISMATCH"):
                self.feature.execute(request)

    def test_invalid_pid_bool_and_untrusted_input(self):
        for invalid in (0, True, -1, "501"):
            with self.subTest(pid=invalid):
                with self.assertRaises(PreconditionError):
                    self.feature.prepare(work=self.work, arguments={"pid": invalid})

    def test_no_termination_parameters(self):
        with self.assertRaisesRegex(PreconditionError, "FIELDS_INVALID"):
            self.feature.prepare(work=self.work, arguments={"pid": 501, "kill": True})


class WorkOperationPolicyTests(unittest.TestCase):
    def setUp(self):
        from bct import BCT
        from bct.core.models import Principal
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / "first.txt"
        self.dst = self.root / "second.txt"
        self.src.write_text("original", encoding="utf8")
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["file_action_plan","process_stop_plan"]\n'
            'approval_actions=["delete","file_action_apply","process_force_stop"]\n',
            encoding="utf8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite",
                       policy_path=self.policy)
        self.owner = Principal("p2-test-owner", "test",
                               frozenset({"file_action_plan","process_stop_plan"}))
        self.bct.create_work(work_id="p2-test-work",
                             request_summary="preview only", roots=[str(self.root)],
                             actions=["file_action_plan"], principal=self.owner)

    def test_durable_duplicate_receipt_does_not_mutate(self):
        from bct.core.models import Outcome
        args = {"operation":"move_preview", "source":str(self.src),
                "destination":str(self.dst)}
        first = self.bct.operations.run(
            principal=self.owner, work_id="p2-test-work",
            operation_id="preview-one", capability="file_action_plan",
            arguments=args,
        )
        second = self.bct.operations.run(
            principal=self.owner, work_id="p2-test-work",
            operation_id="preview-one", capability="file_action_plan",
            arguments=args,
        )
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(second.duplicate)
        self.assertEqual("original", self.src.read_text(encoding="utf8"))
        self.assertFalse(self.dst.exists())

    def test_work_cannot_escalate_to_stop(self):
        from bct.core.models import AuthorizationError
        with self.assertRaises(AuthorizationError):
            self.bct.operations.run(
                principal=self.owner, work_id="p2-test-work",
                operation_id="stop-not-authorized",
                capability="process_stop_plan", arguments={"pid": 123},
            )

    def test_approval_not_operational_until_verifier_exists(self):
        from bct.core.policy import Policy
        from bct.core.models import DecisionKind
        self.assertEqual(
            DecisionKind.DENY,
            Policy(self.policy).decide(
                principal=self.owner,
                work=self.bct.store.get_work("p2-test-work"),
                action="file_action_apply",
                approval_ref="opaque-not-a-verifier",
            ).kind,
        )
