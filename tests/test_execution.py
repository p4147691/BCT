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
