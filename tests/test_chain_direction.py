from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.chain_direction import ChainDirectionLedger
from bct.chain_message_plan import ChainMessagePlanLedger
from bct.core.models import Work
from bct.core.store import Store
from bct.delayed_send_message import DurableWatchLedger, DelayedSendMessageRunner, Watch
from bct.mcp_server import build_mcp


class Operations:
    capabilities = ("browser",)

    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(as_dict=lambda: {
            "state": "FINISHED", "outcome": "APPLIED", "evidence": {"command": "tested"},
        })


class ChainDirectionLedgerTests(unittest.TestCase):
    def test_new_task_direction_derives_a_planned_then_started_message_plan(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            saved = ledger.save(
                direction_id="direction-1", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Check the release evidence, then ask B for E2E.",
            )
            self.assertFalse(saved["duplicate"])
            plans = ChainMessagePlanLedger(store)
            plans.save(
                plan_id="plan-1", direction_id="direction-1", work_id="work-1",
                plan_text="Progress 1/1. Verify E2E and return exact evidence.",
            )
            planned = plans.bind_chain(
                plan_id="plan-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
            )
            self.assertEqual("CHAIN_PLANNED", planned["chain_state"])
            started = plans.mark_chain_started(
                plan_id="plan-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
            )
            self.assertEqual("CHAIN_STARTED", started["chain_state"])
            self.assertEqual("chain-1-send", started["chain_send_operation_id"])

    def test_direction_and_concrete_plan_are_distinct_records(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            ledger.save(
                direction_id="direction-exact", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Send this exact instruction.",
            )
            plan = ChainMessagePlanLedger(store).save(
                plan_id="plan-1", work_id="work-1", direction_id="direction-exact",
                plan_text="Step 1 of 2: inspect evidence. Step 2 of 2: run E2E.",
            )
            self.assertNotEqual("Send this exact instruction.", plan["plan_text"])
            self.assertEqual(64, len(plan["plan_sha256"]))

    def test_only_new_task_can_plan_a_chain(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            ledger.save(
                direction_id="direction-hold", work_id="work-1", source_kind="USER",
                decision="HOLD", direction_text="Wait for the listening review.",
            )
            with self.assertRaisesRegex(ValueError, "NOT_A_NEW_TASK"):
                ChainMessagePlanLedger(store).save(
                    plan_id="plan-hold", direction_id="direction-hold",
                    work_id="work-1", plan_text="This must not become a task.",
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

    async def test_ababa_is_two_linked_chains_then_a_complete_direction(self):
        """A1→B1→A2→B2→A3 stays two exact 1:1 chains, not a hidden loop."""
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work("work-ababa", "fixture", (), frozenset(), "bct-mcp-local", 1))
            delayed = DurableWatchLedger(store)
            ops = Operations()
            mcp = build_mcp(SimpleNamespace(operations=ops, store=store), compact_catalogue=True)

            def return_to_manager(task_id: str, response_sha: str, text: str) -> None:
                delayed.prearm_task(
                    task_id=task_id, work_id=work.work_id, principal_id="bct-mcp-local",
                    assignment_epoch=1, instance_id="worker-instance",
                    conversation_key="worker-uuid", manager_conversation_key="manager-uuid",
                    manager_instance_id="manager-instance",
                    baseline={
                        "responseTurnCount": 1, "generating": True,
                        "responseTurnKey": "old-" + task_id, "responseSha256": "a" * 64,
                        "latestUserTurnKey": "source-" + task_id, "latestUserSha256": "b" * 64,
                    }, registration_receipt="prearm-" + task_id,
                )
                watch = Watch(task_id, 1, "worker-uuid", f"task:{task_id}:1", "prearm-" + task_id)
                outcome = DelayedSendMessageRunner(
                    delayed,
                    read_response=lambda _: {
                        "conversation_key": "worker-uuid", "response_turn_id": watch.response_turn_id,
                        "response_turn_key": "rcc-" + task_id, "response_sha256": response_sha,
                        "response_text": text + "\nNEXT TASK — MANAGER\nReturn the report to A.",
                        "response_complete": True, "input_ready": True,
                    },
                    send_message=lambda *_: "send-" + task_id,
                ).poll_once(watch, manager_conversation_key="manager-uuid")
                self.assertEqual("RETURNED_TO_MANAGER", outcome.status)

            # B1 → A2: exact BA return.
            return_to_manager("task-one", "c" * 64, "First B report.")
            _, direction = await mcp.call_tool("bct_set_chain_direction", {
                "work_id": work.work_id, "direction_id": "direction-two",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-one",
                "source_generation": 1, "decision": "NEW_TASK",
                "direction_text": "Do the second bounded task, then return to A.",
            })
            self.assertEqual("NEW_TASK", direction["chain_direction"]["decision"])

            # A2 turns its human direction into a concrete Chain Message Plan.
            concrete_plan = (
                "Progress 1/2. Inspect the exact release evidence; then run the bounded E2E. "
                "Preserve existing artifacts and return the evidence to A."
            )
            _, planned = await mcp.call_tool("bct_set_chain_message_plan", {
                "work_id": work.work_id, "direction_id": "direction-two",
                "plan_id": "plan-two", "plan_text": concrete_plan,
            })
            self.assertEqual("OK", planned["status"])
            self.assertNotEqual(
                direction["chain_direction"]["direction_text"],
                planned["chain_message_plan"]["plan_text"],
            )

            # A2 → B2: a new Chain Message starts immediately.  The exact Plan,
            # not the Direction, is reserved and delivered.
            _, rejected = await mcp.call_tool("bct_chain_message", {
                "work_id": work.work_id, "task_id": "task-two", "operation_id": "chain-two",
                "instance_id": "worker-instance", "session_id": "a" * 32,
                "worker_tab_id": 12, "worker_window_id": 13,
                "worker_conversation_key": "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12,
                "manager_conversation_key": "c" * 8 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 12,
                "instruction": "A different instruction must never share this plan.",
                "chain_direction_id": "direction-two",
                "chain_message_plan_id": "plan-two",
            })
            self.assertEqual("CHAIN_MESSAGE_PLAN_TEXT_MISMATCH", rejected["reason"])
            self.assertEqual([], ops.calls)
            _, started = await mcp.call_tool("bct_chain_message", {
                "work_id": work.work_id, "task_id": "task-two", "operation_id": "chain-two",
                "instance_id": "worker-instance", "session_id": "a" * 32,
                "worker_tab_id": 12, "worker_window_id": 13,
                "worker_conversation_key": "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12,
                "manager_conversation_key": "c" * 8 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 12,
                "chain_direction_id": "direction-two",
                "chain_message_plan_id": "plan-two",
            })
            self.assertEqual("WATCHING", started["status"])
            self.assertEqual("CHAIN_STARTED", started["chain_message_plan"]["chain_state"])
            self.assertEqual(["chain-two-arm", "chain-two-send"], [call["operation_id"] for call in ops.calls])
            self.assertEqual(
                concrete_plan,
                ops.calls[1]["arguments"]["text"],
            )

            # B2 → A3: the final BA return; A3 closes instead of creating B3.
            return_to_manager("task-two", "d" * 64, "Second B report.")
            _, completed = await mcp.call_tool("bct_set_chain_direction", {
                "work_id": work.work_id, "direction_id": "direction-complete",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-two",
                "source_generation": 1, "decision": "COMPLETE",
                "direction_text": "A3 accepts the final evidence and closes the chain.",
            })
            self.assertEqual("COMPLETE", completed["chain_direction"]["decision"])
            self.assertNotIn("chain_state", completed["chain_direction"])
