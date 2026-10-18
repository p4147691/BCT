from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from bct import BCT
from bct.core.models import PreconditionError, Principal


class ExecutionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["execute","system_inspect"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.principal = Principal("developer", "test", frozenset({"execute", "system_inspect"}))
        self.bct.create_work(
            work_id="work-exec", request_summary="exercise structured execution",
            roots=[str(self.root)], actions=["execute", "system_inspect"], principal=self.principal,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, operation_id: str, capability: str, arguments: dict):
        return self.bct.operations.run(
            principal=self.principal, work_id="work-exec", operation_id=operation_id,
            capability=capability, arguments=arguments,
        )

    def test_python_execution_and_duplicate_do_not_run_twice(self):
        marker = self.root / "marker.json"
        script = self.root / "once.py"
        script.write_text(
            "from pathlib import Path\n"
            "import json, sys\n"
            "p=Path(sys.argv[1])\n"
            "n=int(p.read_text()) if p.exists() else 0\n"
            "p.write_text(str(n+1))\n"
            "print(json.dumps({'count': n+1}))\n",
            encoding="utf-8",
        )
        arguments = {
            "kind": "python", "cwd": str(self.root), "script": str(script),
            "args": [str(marker)], "timeout_s": 10,
        }
        first = self.call("exec-once", "execute", arguments)
        second = self.call("exec-once", "execute", arguments)
        self.assertEqual(first.outcome.value, "APPLIED")
        self.assertEqual(first.output["returncode"], 0)
        self.assertEqual(json.loads(first.output["stdout"]), {"count": 1})
        self.assertTrue(second.duplicate)
        self.assertEqual(marker.read_text(encoding="utf-8"), "1")

    @unittest.skipUnless(os.name == "nt", "PowerShell acceptance is Windows-specific")
    def test_powershell_is_a_supported_structured_execution_kind(self):
        result = self.call(str(uuid.uuid4()), "execute", {
            "kind": "powershell", "cwd": str(self.root),
            "command": "[Console]::Out.Write('BCT_POWERSHELL_OK')", "timeout_s": 10,
        })
        self.assertEqual(result.outcome.value, "APPLIED")
        self.assertEqual(result.output["stdout"], "BCT_POWERSHELL_OK")

    def test_missing_executable_is_not_applied_without_orphan_claim(self):
        missing = str(self.root / "missing-python-executable.exe")
        args = {"kind": "argv", "cwd": str(self.root),
                "argv": [missing, "-V"], "timeout_s": 10}
        first = self.call("missing-executable", "execute", args)
        self.assertEqual("NOT_APPLIED", first.outcome.value)
        self.assertEqual("PROCESS_NOT_CREATED", first.evidence["phase"])
        self.assertEqual("EXECUTABLE_NOT_FOUND", first.evidence["reason"])
        replay = self.call("missing-executable", "execute", args)
        self.assertTrue(replay.duplicate)
        with self.bct.store.transaction() as db:
            claim = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("missing-executable",),
            ).fetchone()
            self.assertEqual(0, claim["unresolved"])
        follow = self.call("missing-executable-next", "execute", args)
        self.assertEqual("NOT_APPLIED", follow.outcome.value)

    def test_exact_historical_missing_executable_recovery_is_atomic(self):
        missing = str(self.root / "missing-original.exe")
        args = {"kind": "argv", "cwd": str(self.root),
                "argv": [missing], "timeout_s": 10}
        result = self.call("original-unknown-execute", "execute", args)
        self.assertEqual("NOT_APPLIED", result.outcome.value)
        # Reconstruct the historical UNKNOWN in this disposable fixture only.
        with self.bct.store.transaction() as db:
            digest = db.execute(
                "SELECT request_digest FROM operations WHERE operation_id=?",
                ("original-unknown-execute",),
            ).fetchone()[0]
            db.execute(
                "UPDATE operations SET outcome='UNKNOWN',error=?,evidence_json=? "
                "WHERE operation_id=?", (
                    "[WinError 2] 지정된 파일을 찾을 수 없습니다",
                    json.dumps({"phase": "UNEXPECTED", "type": "FileNotFoundError"}),
                    "original-unknown-execute",
                ),
            )
            db.execute(
                "UPDATE resource_claims SET unresolved=1 WHERE operation_id=?",
                ("original-unknown-execute",),
            )
        recovery = {
            "operation": "reconcile-not-started", "cwd": str(self.root),
            "original_operation_id": "original-unknown-execute",
            "original_request_digest": digest,
        }
        with self.assertRaisesRegex(PreconditionError, "EXECUTE_RECOVERY_NOT_PROVEN"):
            self.call("reject-tampered-digest", "execute", {
                **recovery, "original_request_digest": "a" * 64,
            })
        resolved = self.call("reconcile-once", "execute", recovery)
        self.assertEqual("APPLIED", resolved.outcome.value)
        replay = self.call("reconcile-once", "execute", recovery)
        self.assertTrue(replay.duplicate)
        with self.bct.store.transaction() as db:
            old = db.execute(
                "SELECT outcome,error,evidence_json FROM operations WHERE operation_id=?",
                ("original-unknown-execute",),
            ).fetchone()
            claim = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("original-unknown-execute",),
            ).fetchone()
            events = db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='OPERATION_RECONCILED' "
                "AND subject_id=?", ("original-unknown-execute",),
            ).fetchone()[0]
            self.assertEqual("UNKNOWN", old["outcome"])
            self.assertEqual(0, claim["unresolved"])
            self.assertEqual(1, events)

    def test_execute_recovery_rejects_stale_or_wrong_claim_and_other_unknown(self):
        for mutation in ("wrong_owner", "stale_epoch", "different_claim", "other_unknown"):
            with self.subTest(mutation=mutation):
                original_id = "unknown-" + mutation
                target = self.root / original_id
                target.mkdir()
                missing = str(target / "missing.exe")
                self.call(original_id, "execute", {
                    "kind": "argv", "cwd": str(target),
                    "argv": [missing], "timeout_s": 5,
                })
                with self.bct.store.transaction() as db:
                    original = db.execute(
                        "SELECT request_digest FROM operations WHERE operation_id=?",
                        (original_id,),
                    ).fetchone()
                    db.execute(
                        "UPDATE operations SET outcome='UNKNOWN',error=?,evidence_json=? "
                        "WHERE operation_id=?", (
                            "[WinError 2] 지정된 파일을 찾을 수 없습니다",
                            json.dumps({"phase": "UNEXPECTED", "type": "FileNotFoundError"}),
                            original_id,
                        ),
                    )
                    db.execute("UPDATE resource_claims SET unresolved=1 WHERE operation_id=?", (original_id,))
                    if mutation == "wrong_owner":
                        db.execute("UPDATE resource_claims SET work_id='foreign' WHERE operation_id=?", (original_id,))
                    elif mutation == "stale_epoch":
                        db.execute("UPDATE resource_claims SET assignment_epoch=99 WHERE operation_id=?", (original_id,))
                    elif mutation == "different_claim":
                        db.execute("UPDATE resource_claims SET unresolved=0 WHERE operation_id=?", (original_id,))
                    else:
                        db.execute("UPDATE operations SET evidence_json='{}' WHERE operation_id=?", (original_id,))
                recovery = {
                    "operation": "reconcile-not-started", "cwd": str(target),
                    "original_operation_id": original_id,
                    "original_request_digest": original["request_digest"],
                }
                with self.assertRaises(PreconditionError):
                    self.call("resolver-" + mutation, "execute", recovery)
                with self.bct.store.transaction() as db:
                    self.assertEqual(0, db.execute(
                        "SELECT COUNT(*) FROM events WHERE kind='OPERATION_RECONCILED' AND subject_id=?",
                        (original_id,),
                    ).fetchone()[0])

    def test_system_process_inspection_returns_exact_current_pid(self):
        result = self.call("inspect-self", "system_inspect", {
            "operation": "process", "pid": os.getpid(),
        })
        self.assertEqual(result.outcome.value, "APPLIED")
        self.assertEqual(result.output["process"]["pid"], os.getpid())
        self.assertGreater(result.output["process"]["created_at"], 0)

    def test_execution_cwd_outside_work_is_not_applied(self):
        outside = Path(self.root.anchor)
        with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
            self.call("outside", "execute", {
                "kind": "python", "cwd": str(outside), "module": "sys", "timeout_s": 1,
            })


if __name__ == "__main__":
    unittest.main()
