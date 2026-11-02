from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.core.models import Work
from bct.core.store import Store
from bct.delayed_send_message import DelayedSendMessageRunner, DurableWatchLedger, Watch
from bct.mcp_server import build_mcp


class Operations:
    capabilities = ()


class ExecutionContextPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_the_prior_b_decision_only_for_its_own_work(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work(
                "work-1", "fixture", (), frozenset(), "owner", 1,
            ))
            ledger = DurableWatchLedger(store)
            ledger.prearm_task(
                task_id="task-1", work_id=work.work_id, principal_id="owner",
                assignment_epoch=1, instance_id="worker-instance",
                conversation_key="worker-uuid", manager_conversation_key="manager-uuid",
                manager_instance_id="manager-instance",
                baseline={
                    "responseTurnCount": 1, "generating": True,
                    "responseTurnKey": "old", "responseSha256": "a" * 64,
                    "latestUserTurnKey": "source-user", "latestUserSha256": "b" * 64,
                }, registration_receipt="prearm-receipt",
            )
            watch = Watch("task-1", 1, "worker-uuid", "task:task-1:1", "prearm-receipt")
            DelayedSendMessageRunner(
                ledger,
                read_response=lambda _: {
                    "conversation_key": "worker-uuid", "response_turn_id": "task:task-1:1",
                    "response_turn_key": "rcc-turn-1", "response_sha256": "c" * 64,
                    "response_text": "Worked.\nNEXT TASK — SELF\nContinue verification.",
                    "response_complete": True, "input_ready": True,
                },
                send_message=lambda *_: "send-receipt",
            ).poll_once(watch, manager_conversation_key="manager-uuid")
            mcp = build_mcp(SimpleNamespace(operations=Operations(), store=store), compact_catalogue=True)
            _, result = await mcp.call_tool("bct_execution_context", {
                "work_id": "work-1", "task_id": "task-1",
            })
            self.assertEqual("OK", result["status"])
            execution = result["execution"]
            self.assertEqual("SELF", execution["decision"]["route"])
            self.assertEqual("Continue verification.", execution["decision"]["payload"])
            self.assertEqual("Worked.\nNEXT TASK — SELF\nContinue verification.",
                             execution["prior_turn"]["response_text"])
            _, missing = await mcp.call_tool("bct_execution_context", {
                "work_id": "other-work", "task_id": "task-1",
            })
            self.assertEqual("NOT_FOUND", missing["status"])
