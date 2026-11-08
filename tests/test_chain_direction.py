from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.chain_direction import ChainDirectionLedger
from bct.chain_execution_plan import ChainExecutionPlanLedger, check_execute_plan
from bct.core.models import Work
from bct.core.store import Store
from bct.send_delayed_message import DurableWatchLedger, SendDelayedMessageRunner, Watch
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
    def test_new_task_direction_links_to_a_planned_then_started_chain(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            saved = ledger.save(
                direction_id="direction-1", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Check the release evidence, then ask B for E2E.",
            )
            self.assertFalse(saved["duplicate"])
            self.assertEqual("READY", saved["chain_continuation"]["state"])
            self.assertEqual("START_CHAIN_RECIPE", saved["chain_continuation"]["next_safe_step"])
            planned = ledger.plan_chain(
                direction_id="direction-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
                instruction_text="Check the release evidence, then ask B for E2E.",
            )
            self.assertEqual("CHAIN_PLANNED", planned["chain_state"])
            self.assertEqual("PREARM_AND_SEND", planned["chain_continuation"]["next_safe_step"])
            started = ledger.mark_chain_started(
                direction_id="direction-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
            )
            self.assertEqual("CHAIN_STARTED", started["chain_state"])
            self.assertEqual("chain-1-send", started["chain_send_operation_id"])
            self.assertEqual("WAIT_FOR_RETURN", started["chain_continuation"]["next_safe_step"])

    def test_saved_direction_persists_chain_start_handoff_after_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.sqlite"
            store = Store(path)
            ChainDirectionLedger(store).save(
                direction_id="direction-handoff", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Keep the chain visible until it starts.",
            )
            reopened = ChainDirectionLedger(Store(path)).get(direction_id="direction-handoff")
            self.assertEqual("READY", reopened["chain_continuation"]["state"])
            self.assertEqual("START_CHAIN_RECIPE", reopened["chain_continuation"]["next_safe_step"])
            self.assertIn("has not started", reopened["chain_continuation"]["reason"])

    def test_direction_rejects_a_different_delivery_text_before_planning(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ledger = ChainDirectionLedger(store)
            ledger.save(
                direction_id="direction-exact", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Send this exact instruction.",
            )
            with self.assertRaisesRegex(ValueError, "TEXT_MISMATCH"):
                ledger.plan_chain(
                    direction_id="direction-exact", work_id="work-1",
                    task_id="task-1", operation_id="chain-1",
                    instruction_text="Send a different instruction.",
                )
            self.assertEqual("NOT_PLANNED", ledger.get(direction_id="direction-exact")["chain_state"])

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

    def test_b_plan_cannot_exist_before_a_direction_is_delivered(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            ChainDirectionLedger(store).save(
                direction_id="direction-waiting", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Improve the result without replacing the original.",
            )
            with self.assertRaisesRegex(ValueError, "SOURCE_NOT_STARTED"):
                ChainExecutionPlanLedger(store).save(
                    plan_id="plan-too-early", work_id="work-1",
                    direction_id="direction-waiting", task_id="task-1",
                    generation=1, plan_text="Inspect, modify reversibly, then verify.",
                )

    def test_chain_rejects_a_second_execute_plan_instead_of_guessing_one(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            directions = ChainDirectionLedger(store)
            directions.save(
                direction_id="direction-1", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Perform the bounded task.",
            )
            directions.plan_chain(
                direction_id="direction-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
                instruction_text="Perform the bounded task.",
            )
            directions.mark_chain_started(
                direction_id="direction-1", work_id="work-1",
                task_id="task-1", operation_id="chain-1",
            )
            plans = ChainExecutionPlanLedger(store)
            plans.save(
                plan_id="plan-1", work_id="work-1", direction_id="direction-1",
                task_id="task-1", generation=1, plan_text="Inspect then verify.",
            )
            with self.assertRaisesRegex(ValueError, "CHAIN_CONFLICT"):
                plans.save(
                    plan_id="plan-2", work_id="work-1", direction_id="direction-1",
                    task_id="task-1", generation=2, plan_text="Do something else.",
                )

    def test_execute_plan_update_preserves_initial_plan_and_exposes_current_revision(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            directions = ChainDirectionLedger(store)
            directions.save(
                direction_id="direction-update", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Perform the bounded task.",
            )
            directions.plan_chain(
                direction_id="direction-update", work_id="work-1",
                task_id="task-1", operation_id="chain-update",
            )
            directions.mark_chain_started(
                direction_id="direction-update", work_id="work-1",
                task_id="task-1", operation_id="chain-update",
            )
            plans = ChainExecutionPlanLedger(store)
            plans.save(
                plan_id="plan-update", work_id="work-1", direction_id="direction-update",
                task_id="task-1", generation=1, plan_text="1. Inspect. 2. Verify.",
            )
            revised = plans.update(
                plan_id="plan-update", plan_text="1. Inspect. 2. Repair. 3. Verify.",
                update_reason="The inspection added one safe repair step.",
            )
            self.assertEqual(1, revised["revision"])
            self.assertEqual("1. Inspect. 2. Verify.", revised["original_plan_text"])
            self.assertEqual("1. Inspect. 2. Repair. 3. Verify.", revised["plan_text"])

    def test_chain_plan_continues_across_later_b_generations(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            directions = ChainDirectionLedger(store)
            directions.save(
                direction_id="direction-continuing", work_id="work-1", source_kind="USER",
                decision="NEW_TASK", direction_text="Perform the bounded task.",
            )
            directions.plan_chain(
                direction_id="direction-continuing", work_id="work-1",
                task_id="task-1", operation_id="chain-continuing",
            )
            directions.mark_chain_started(
                direction_id="direction-continuing", work_id="work-1",
                task_id="task-1", operation_id="chain-continuing",
            )
            plans = ChainExecutionPlanLedger(store)
            plans.save(
                plan_id="plan-continuing", work_id="work-1",
                direction_id="direction-continuing", task_id="task-1",
                generation=1, plan_text="1. Inspect. 2. Verify.",
            )
            plans.update(
                plan_id="plan-continuing",
                plan_text="1. Inspect. 2. Repair. 3. Verify.",
                update_reason="One bounded repair was found.",
            )
            continued = plans.get_for_chain(
                store=store, work_id="work-1", direction_id="direction-continuing",
                task_id="task-1",
            )
            self.assertEqual("plan-continuing", continued["plan_id"])
            self.assertEqual(1, continued["generation"])
            self.assertEqual(1, continued["revision"])
            self.assertEqual("1. Inspect. 2. Repair. 3. Verify.", continued["plan_text"])
            assessment = check_execute_plan(
                plan=continued,
                response_text="PLAN REVISION: 1\nPROGRESS: 2/3 — repair complete; verify next",
            )
            check = plans.record_execute_plan_check(
                work_id="work-1", direction_id="direction-continuing", task_id="task-1",
                generation=2, response_sha256="a" * 64, assessment=assessment,
            )
            self.assertEqual(2, check["completed_steps"])
            self.assertEqual(3, check["total_steps"])
            self.assertEqual((), check["issues"])
            listed = ChainExecutionPlanLedger.list_latest_execute_plan_checks(
                store=store,
            )
            self.assertEqual(1, len(listed))
            self.assertEqual("OK", listed[0]["status"])
            self.assertEqual(1, listed[0]["current_plan_revision"])
            self.assertEqual(2, listed[0]["completed_steps"])


class ChainDirectionPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_exposes_execute_plan_checks_without_creating_them(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            mcp = build_mcp(
                SimpleNamespace(operations=Operations(), store=store),
                compact_catalogue=True, status_provider=lambda: {"monitor": {}},
            )
            _, status = await mcp.call_tool("bct_status", {"scope": "bct"})
            self.assertEqual([], status["execute_plan_checks"])
            self.assertEqual([], status["pending_chain_starts"])
            with store._readonly() as db:
                self.assertIsNone(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='chain_directions'"
                ).fetchone())

    async def test_status_exposes_saved_direction_waiting_to_start(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work(
                "work-pending", "fixture", (), frozenset({"browser"}), "bct-mcp-local", 1,
            ))
            ChainDirectionLedger(store).save(
                direction_id="pending-direction", work_id=work.work_id,
                source_kind="USER", decision="NEW_TASK", direction_text="Inspect before sending.",
            )
            mcp = build_mcp(
                SimpleNamespace(operations=Operations(), store=store),
                compact_catalogue=True, status_provider=lambda: {"monitor": {}},
            )
            _, status = await mcp.call_tool("bct_status", {"scope": "bct"})
            self.assertEqual(["pending-direction"], [
                item["direction_id"] for item in status["pending_chain_starts"]
            ])
            self.assertEqual("START_CHAIN_RECIPE", status["pending_chain_starts"][0]["next_safe_step"])

    async def test_direction_and_execute_plan_names_are_public(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            mcp = build_mcp(SimpleNamespace(operations=Operations(), store=store), compact_catalogue=True)
            names = {tool.name for tool in await mcp.list_tools()}
            self.assertTrue({
                "bct_set_direction", "bct_get_direction",
                "bct_set_execute_plan", "bct_update_execute_plan", "bct_get_execute_plan",
                "bct_set_project_plan", "bct_get_conversation_network",
                "bct_prepare_supervisor_chain",
            } <= names)

    async def test_exact_ba_can_be_bound_then_sent_to_one_current_supervisor(self):
        """B reports BA; only A can bind a fresh C route and start A→C."""
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work(
                "work-supervisor", "fixture", (), frozenset({"browser"}), "bct-mcp-local", 1,
            ))
            delayed = DurableWatchLedger(store)
            delayed.prearm_task(
                task_id="task-b", work_id=work.work_id, principal_id="bct-mcp-local",
                assignment_epoch=1, instance_id="worker-instance",
                conversation_key="worker-uuid", manager_conversation_key="manager-uuid",
                manager_instance_id="manager-instance",
                baseline={
                    "responseTurnCount": 1, "generating": True,
                    "responseTurnKey": "old", "responseSha256": "a" * 64,
                    "latestUserTurnKey": "source-user", "latestUserSha256": "b" * 64,
                }, registration_receipt="prearm-b",
            )
            watch = Watch("task-b", 1, "worker-uuid", "task:task-b:1", "prearm-b")
            returned = SendDelayedMessageRunner(
                delayed,
                read_response=lambda _: {
                    "conversation_key": "worker-uuid", "response_turn_id": watch.response_turn_id,
                    "response_turn_key": "rcc-b", "response_sha256": "c" * 64,
                    "response_text": "Ready for release review.\nNEXT TASK — MANAGER\nAsk C to select CI, merge, LIVE and E2E order.",
                    "response_complete": True, "input_ready": True,
                },
                send_message=lambda *_: "return-send",
            ).poll_once(watch, manager_conversation_key="manager-uuid")
            self.assertEqual("RETURNED_TO_MANAGER", returned.status)
            supervisor = "d" * 8 + "-" + "d" * 4 + "-" + "d" * 4 + "-" + "d" * 4 + "-" + "d" * 12
            snapshot = {"monitor": {
                "current_nodes": {"observation": {"state": "FRESH"}, "items": [{
                    "status": "CONFIRMED", "conversation_uuid": supervisor,
                    "tab_id": 20, "window_id": 30, "generating": False,
                    "node_number": "N4",
                }]},
                "rcc": {"instances": [{
                    "state": "OPEN", "instance_id": "a" * 32, "session_id": "b" * 32,
                    "tabs": [{
                        "presence": "OPEN", "conversation_key": supervisor,
                        "tab_id": 20, "window_id": 30, "title": "Supervisor C",
                        "conversation_scope": {"role_tags": ["supervisor"]},
                    }],
                }]},
            }}
            ops = Operations()
            mcp = build_mcp(
                SimpleNamespace(operations=ops, store=store),
                compact_catalogue=True, status_provider=lambda: snapshot,
            )
            _, direction = await mcp.call_tool("bct_set_direction", {
                "work_id": work.work_id, "direction_id": "direction-c",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-b",
                "source_generation": 1, "decision": "NEW_TASK",
                "direction_text": "You are C. Choose the safe CI, merge, LIVE deployment, and E2E order; execute only the approved next boundary.",
            })
            self.assertEqual("OK", direction["status"])
            _, prepared = await mcp.call_tool("bct_prepare_supervisor_chain", {
                "work_id": work.work_id, "direction_id": "direction-c",
            })
            self.assertEqual("READY", prepared["status"])
            self.assertEqual(supervisor, prepared["supervisor_route"]["conversation_key"])
            # A human may move C's tab while A is deciding.  Start re-reads
            # the same C identity and refreshes only that attachment.
            snapshot["monitor"]["current_nodes"]["items"][0]["tab_id"] = 21
            snapshot["monitor"]["rcc"]["instances"][0]["tabs"][0]["tab_id"] = 21
            node_guard = patch("bct.node_recovery.NodeRecoveryLedger.assert_send_allowed", return_value=None)
            node_guard.start()
            self.addCleanup(node_guard.stop)
            _, started = await mcp.call_tool("bct_chain_message", {
                "work_id": work.work_id, "task_id": "task-c", "operation_id": "chain-c",
                "origin_conversation_key": "manager-uuid", "origin_instance_id": "manager-instance",
                "chain_direction_id": "direction-c",
            })
            self.assertEqual("WATCHING", started["status"])
            self.assertEqual(supervisor, started["supervisor_route"]["conversation_key"])
            self.assertEqual(["chain-c-arm", "chain-c-send"], [call["operation_id"] for call in ops.calls])
            self.assertEqual("a" * 32, ops.calls[1]["arguments"]["instance_id"])
            self.assertEqual(21, ops.calls[1]["arguments"]["tab_id"])
            self.assertEqual(supervisor, ops.calls[1]["arguments"]["conversation_key"])

    async def test_supervisor_route_does_not_guess_a_missing_or_multiple_c(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work("work-no-c", "fixture", (), frozenset({"browser"}), "bct-mcp-local", 1))
            ChainDirectionLedger(store).save(
                direction_id="direction-no-c", work_id=work.work_id,
                source_kind="USER", decision="NEW_TASK", direction_text="This cannot route itself.",
            )
            mcp = build_mcp(
                SimpleNamespace(operations=Operations(), store=store), compact_catalogue=True,
                status_provider=lambda: {"monitor": {"current_nodes": {
                    "observation": {"state": "FRESH"}, "items": []
                }, "rcc": {"instances": []}}},
            )
            _, blocked = await mcp.call_tool("bct_prepare_supervisor_chain", {
                "work_id": work.work_id, "direction_id": "direction-no-c",
            })
            self.assertEqual("BLOCKED", blocked["status"])
            self.assertEqual("SUPERVISOR_ROUTE_MISSING", blocked["reason"])

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
            SendDelayedMessageRunner(
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
            _, saved = await mcp.call_tool("bct_set_direction", {
                "work_id": "work-1", "direction_id": "direction-return-1",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-1",
                "source_generation": 1, "decision": "NEW_TASK",
                "direction_text": "Check live evidence before asking B for the next task.",
            })
            self.assertEqual("OK", saved["status"])
            self.assertEqual("c" * 64, saved["chain_direction"]["source_result_sha256"])
            _, read = await mcp.call_tool("bct_get_direction", {
                "work_id": "work-1", "direction_id": "direction-return-1",
            })
            self.assertEqual("NEW_TASK", read["chain_direction"]["decision"])

    async def test_ababa_is_two_linked_chains_then_a_complete_direction(self):
        """A1→B1→A2→B2→A3 stays two exact 1:1 chains, not a hidden loop."""
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work("work-ababa", "fixture", (), frozenset({"browser"}), "bct-mcp-local", 1))
            node_guard = patch("bct.node_recovery.NodeRecoveryLedger.assert_send_allowed", return_value=None)
            node_guard.start()
            self.addCleanup(node_guard.stop)
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
                outcome = SendDelayedMessageRunner(
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
            _, direction = await mcp.call_tool("bct_set_direction", {
                "work_id": work.work_id, "direction_id": "direction-two",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-one",
                "source_generation": 1, "decision": "NEW_TASK",
                "direction_text": "Do the second bounded task, then return to A.",
            })
            self.assertEqual("NEW_TASK", direction["chain_direction"]["decision"])

            # A2 → B2: a new Chain Message starts immediately.  The fake executor
            # records the prearm/send pair in place of a real browser delivery.
            _, rejected = await mcp.call_tool("bct_chain_message", {
                "work_id": work.work_id, "task_id": "task-two", "operation_id": "chain-two",
                "instance_id": "worker-instance", "session_id": "a" * 32,
                "worker_tab_id": 12, "worker_window_id": 13,
                "worker_conversation_key": "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12,
                "manager_conversation_key": "c" * 8 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 12,
                "instruction": "A different instruction must never share this direction.",
                "chain_direction_id": "direction-two",
            })
            self.assertEqual("CHAIN_DIRECTION_TEXT_MISMATCH", rejected["reason"])
            self.assertEqual([], ops.calls)
            _, started = await mcp.call_tool("bct_chain_message", {
                "work_id": work.work_id, "task_id": "task-two", "operation_id": "chain-two",
                "instance_id": "worker-instance", "session_id": "a" * 32,
                "worker_tab_id": 12, "worker_window_id": 13,
                "worker_conversation_key": "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12,
                "manager_conversation_key": "c" * 8 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 12,
                "chain_direction_id": "direction-two",
            })
            self.assertEqual("WATCHING", started["status"])
            self.assertEqual("CHAIN_STARTED", started["chain_direction"]["chain_state"])
            self.assertEqual(["chain-two-arm", "chain-two-send"], [call["operation_id"] for call in ops.calls])
            sent_text = ops.calls[1]["arguments"]["text"]
            self.assertTrue(sent_text.startswith(
                "Do the second bounded task, then return to A.\n\n"
            ))
            self.assertIn("bct_set_execute_plan(", sent_text)
            self.assertIn("PROGRESS: <completed>/<total>", sent_text)

            # Only after delivery does B author its own concrete plan. It may
            # develop A's direction and is intentionally not text-equal to it.
            b_plan_text = (
                "Progress 1/2. Inspect the current evidence, perform the bounded "
                "change reversibly, verify E2E, and return exact artifacts to A."
            )
            _, b_plan = await mcp.call_tool("bct_set_execute_plan", {
                "work_id": work.work_id, "direction_id": "direction-two",
                "task_id": "task-two", "generation": 1,
                "plan_id": "b-plan-two", "plan_text": b_plan_text,
            })
            self.assertEqual("OK", b_plan["status"])
            self.assertNotEqual(
                direction["chain_direction"]["direction_text"],
                b_plan["chain_execution_plan"]["plan_text"],
            )
            _, read_plan = await mcp.call_tool("bct_get_execute_plan", {
                "work_id": work.work_id, "plan_id": "b-plan-two",
            })
            self.assertEqual(b_plan_text, read_plan["chain_execution_plan"]["plan_text"])

            # B2 → A3: the final BA return; A3 closes instead of creating B3.
            return_to_manager("task-two", "d" * 64, "Second B report.")
            _, completed = await mcp.call_tool("bct_set_direction", {
                "work_id": work.work_id, "direction_id": "direction-complete",
                "source_kind": "MANAGER_RETURN", "source_task_id": "task-two",
                "source_generation": 1, "decision": "COMPLETE",
                "direction_text": "A3 accepts the final evidence and closes the chain.",
            })
            self.assertEqual("COMPLETE", completed["chain_direction"]["decision"])
            self.assertEqual("NOT_PLANNED", completed["chain_direction"]["chain_state"])
