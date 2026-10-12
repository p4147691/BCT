from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import PreconditionError, Principal


class ProcessSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sessions = self.root / "sessions"
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["process_session"]\napproval_actions=[]\n\n'
            '[execution.sessions]\nstate_root=' + json.dumps(str(self.sessions)) + '\n',
            encoding="utf-8",
        )
        self.script = self.root / "echo_session.py"
        self.script.write_text(
            "import sys\n"
            "print('READY', flush=True)\n"
            "for line in sys.stdin:\n"
            "    value=line.rstrip('\\r\\n')\n"
            "    print('ECHO:'+value, flush=True)\n",
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.principal = Principal("owner", "test", frozenset({"process_session"}))
        self.bct.create_work(
            work_id="session-work", request_summary="process session test",
            roots=[str(self.root)], actions=["process_session"], principal=self.principal,
        )
        self.session_id = "python-echo"

    def tearDown(self):
        try:
            self.call("cleanup-stop", {"operation": "stop", "session_id": self.session_id})
        except Exception:
            pass
        self.temporary.cleanup()

    def call(self, operation_id, arguments):
        return self.bct.operations.run(
            principal=self.principal, work_id="session-work", operation_id=operation_id,
            capability="process_session", arguments=arguments,
        )

    def start_arguments(self):
        return {
            "operation": "start", "session_id": self.session_id,
            "kind": "python", "cwd": str(self.root), "script": str(self.script),
        }

    def output_until(self, needle: str, prefix: str) -> dict:
        deadline = time.monotonic() + 5
        sequence = 0
        while time.monotonic() < deadline:
            sequence += 1
            result = self.call(f"{prefix}-{sequence}", {
                "operation": "output", "session_id": self.session_id,
                "stdout_offset": 0, "stderr_offset": 0,
            })
            if needle in result.output["stdout"]:
                return result.output
            time.sleep(0.05)
        self.fail("missing process output: " + needle)

    def test_python_session_input_output_stop_and_duplicate_guard(self):
        started = self.call("session-start", self.start_arguments())
        duplicate = self.call("session-start", self.start_arguments())
        already = self.call("session-start-again", self.start_arguments())
        self.assertEqual("APPLIED", started.outcome.value)
        self.assertTrue(duplicate.duplicate)
        self.assertTrue(already.evidence["already_running"])
        process_pid = started.evidence["session"]["process"]["pid"]
        self.assertEqual(process_pid, already.evidence["session"]["process"]["pid"])
        self.output_until("READY", "ready-output")

        entered = self.call("session-input", {
            "operation": "input", "session_id": self.session_id,
            "text": "hello BCT", "append_newline": True,
        })
        self.assertEqual("APPLIED", entered.outcome.value)
        output = self.output_until("ECHO:hello BCT", "echo-output")
        self.assertIn("ECHO:hello BCT", output["stdout"])

        status = self.call("session-status", {"operation": "status", "session_id": self.session_id})
        self.assertEqual("RUNNING", status.output["session"]["state"])
        stopped = self.call("session-stop", {"operation": "stop", "session_id": self.session_id})
        stopped_duplicate = self.call("session-stop", {"operation": "stop", "session_id": self.session_id})
        self.assertEqual("APPLIED", stopped.outcome.value)
        self.assertFalse(stopped.evidence["session"]["process_alive"])
        self.assertTrue(stopped_duplicate.duplicate)

    def test_terminal_session_id_is_not_reused(self):
        self.call("terminal-start", self.start_arguments())
        self.call("terminal-stop", {"operation": "stop", "session_id": self.session_id})
        result = self.call("terminal-restart", self.start_arguments())
        self.assertEqual("NOT_APPLIED", result.outcome.value)
        self.assertIn("PROCESS_SESSION_ID_TERMINAL", result.error)

    def test_missing_or_foreign_session_is_not_adopted(self):
        with self.assertRaisesRegex(PreconditionError, "PROCESS_SESSION_NOT_FOUND"):
            self.call("missing-status", {"operation": "status", "session_id": "external-process"})

        self.call("owned-start", self.start_arguments())
        other = Principal("other", "test", frozenset({"process_session"}))
        self.bct.create_work(
            work_id="other-work", request_summary="must not adopt session",
            roots=[str(self.root)], actions=["process_session"], principal=other,
        )
        with self.assertRaisesRegex(PreconditionError, "PROCESS_SESSION_NOT_OWNED"):
            self.bct.operations.run(
                principal=other, work_id="other-work", operation_id="foreign-status",
                capability="process_session",
                arguments={"operation": "status", "session_id": self.session_id},
            )


if __name__ == "__main__":
    unittest.main()
