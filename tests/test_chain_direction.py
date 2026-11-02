from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.chain_direction import ChainDirectionLedger
from bct.core.models import Work
from bct.core.store import Store
from bct.delayed_send_message import DurableWatchLedger, DelayedSendMessageRunner, Watch
from bct.mcp_server import build_mcp


class Operations:
    capabilities = ()


class ChainDirectionLedgerTests(unittest.TestCase):
    def test_new_task_direction_links_to_a_planned_then_started_chain(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            saved = ledger.save(
                direction_id="direction-1", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Check the release evidence, then ask B for E2E.",
            )
            self.assertFalse(saved["duplicate"])
            planned = ledger.plan_chain(
                direction_id="direction-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
            )
            self.assertEqual("CHAIN_PLANNED", planned["chain_state"])
            started = ledger.mark_chain_started(
                direction_id="direction-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
            )
            self.assertEqual("CHAIN_STARTED", started["chain_state"])
            self.assertEqual("chain-1-send", started["chain_send_operation_id"])

    def test_only_new_task_can_plan_a_chain(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            ledger.save(
                direction_id="direction-hold", work_id="work-1", source_kind="USER",
                decision="HOLD", direction_text="Wait for the listening review.",
            )
            with self.assertRaisesRegex(ValueError, "NOT_A_NEW_TASK"):
                ledger.plan_chain(
                    direction_id="direction-hold", work_id="work-1",
                    task_id="task-1", operation_id="chain-1",
                )


class ChainDirectionPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_manager_return_can_become_an_a_direction(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work("work-1", "fixture", (), frozenset(), "bct-mcp-local", 1))
            delayed = DurableWatchLedger(store)
            delayed.prearm_task(
                task_id="task-1", work_id=work.work_id, principal_id="bct-mcp-local",
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
                delayed,
                read_response=lambda _: {
                    "conversation_key": "worker-uuid", "response_turn_id": watch.response_turn_id,
                    "response_turn_key": "rcc-turn-1", "response_sha256": "c" * 64,
                    "response_text": "Done.\nNEXT TASK — MANAGER\nReport complete.",
                    "response_complete": True, "input_ready": True,
                },
                send_message=lambda *_: "send-receipt",
            ).poll_once(watch, manager_conversation_key="manager-uuid")
            # Compatibility: an older real BA return recorded the exact
            # RETURNED_TO_MANAGER watch but did not yet have the B-decision
            # table.  Its observed response hash remains the safe link.
            with store.transaction() as db:
                db.execute("DELETE FROM continuation_decisions")
            mcp = build_mcp(SimpleNamespace(operations=Operations(), store=store), compact_catalogue=True)
            _, saved = await mcp.call_tool("bct_set_chain_direction", {
                "work_id": "work-1", "direction_id": "direction-return-1",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-1",
                "source_generation": 1, "decision": "NEW_TASK",
                "direction_text": "Check live evidence before asking B for the next task.",
            })
            self.assertEqual("OK", saved["status"])
            self.assertEqual("c" * 64, saved["chain_direction"]["source_result_sha256"])
            _, read = await mcp.call_tool("bct_get_chain_direction", {
                "work_id": "work-1", "direction_id": "direction-return-1",
            })
            self.assertEqual("NEW_TASK", read["chain_direction"]["decision"])
