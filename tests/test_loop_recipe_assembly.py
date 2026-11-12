"""Contract tests for the role-neutral Loop block assembly."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import asyncio
import json
import tempfile
import unittest

from bct.loop_recipe_assembly import persistent_loop_assembly, persistent_loop_outline
from bct.loop_recipe_contracts import (
    Continuation, Endpoint, EndpointBinding, LoopContractError, RouteTable,
    prepare_delivery,
)
from bct.loop_recipe_flow import BlockResult, LinkKind, LoopFlowEngine
from bct.loop_recipe_ledger import LoopRecipeLedger
from bct.core.store import Store
from bct.loop_recipe_gateway import (
    DeliveryReceipt, LoopContinuationGateway, WatchReceipt,
)
from bct.loop_recipe_recovery import RecoveryAction, RecoveryEvidence, plan_recovery
from bct.persistent_loop_commands import PersistentLoopCommands
from bct.persistent_loop_runtime import (
    LOOP_SUPERVISOR_ROLE, PersistentLoopCoordinator, PersistentLoopRuntime,
)
from bct.persistent_loop_recovery import PersistentLoopRecovery
from bct.core.models import Principal, Work
from bct.conversation_network import (
    assign_conversation_membership, configure_conversation_scope,
    role_tags_sha256, upsert_project,
)
from bct.node_recovery import observe_node


def sample_continuation(**changes):
    value = Continuation(
        continuation_id="continuation-1", loop_id="loop-1", source_block_id="assess",
        next_block_id="plan", revision=4, operation_id="operation-4", watch_id="watch-4",
        receipt_ref="receipt-4", required_capabilities=frozenset({"execute"}),
        artifact_refs=("plan-4", "progress-4"),
    )
    return replace(value, **changes)


class PersistentLoopAssemblyTests(unittest.TestCase):
    def test_default_graph_contains_processing_only_not_endpoint_or_route_names(self):
        assembly = persistent_loop_assembly()
        self.assertEqual(assembly.entry_block_id, "resume")
        self.assertEqual(assembly.next_block("assess", "continue"), "plan")
        self.assertEqual(assembly.next_block("assess", "complete"), "complete")
        self.assertIsNone(assembly.next_block("plan", "complete"))
        text = " ".join(block.block_id for block in assembly.blocks).lower()
        for forbidden in ("self", "manager", "supervisor", "worker", "send", "wake"):
            self.assertNotIn(forbidden, text)

    def test_outline_is_display_only_and_exposes_no_delivery_choice(self):
        outline = persistent_loop_outline()
        assessment = next(item for item in outline if item["block_id"] == "assess")
        self.assertEqual(assessment["links"], [
            {"outcome": "continue", "target_block_id": "plan"},
            {"outcome": "wait", "target_block_id": "resume"},
            {"outcome": "handoff", "target_block_id": "plan"},
            {"outcome": "blocked", "target_block_id": "resume"},
            {"outcome": "complete", "target_block_id": "complete"},
        ])
        self.assertNotIn("endpoint", assessment)
        self.assertNotIn("delivery", assessment)

    def test_five_link_engine_creates_continuation_only_at_a_boundary(self):
        engine = LoopFlowEngine(persistent_loop_assembly())
        immediate = engine.advance(BlockResult("assess", LinkKind.CONTINUE))
        self.assertEqual(immediate.next_block_id, "plan")
        self.assertFalse(immediate.requires_continuation)
        handoff_result = BlockResult(
            "assess", LinkKind.HANDOFF, artifact_refs=("plan-4",),
            required_capabilities=frozenset({"review"}),
        )
        handoff = engine.advance(handoff_result)
        self.assertEqual(handoff.next_block_id, "plan")
        self.assertTrue(handoff.requires_continuation)
        continuation = engine.continuation(
            advance=handoff, result=handoff_result, continuation_id="continuation-5",
            loop_id="loop-1", revision=4, operation_id="operation-4", watch_id="watch-4",
            receipt_ref="receipt-4",
        )
        self.assertEqual(continuation.next_block_id, "plan")
        self.assertEqual(continuation.required_capabilities, frozenset({"review"}))
        self.assertEqual(continuation.operation_id, "operation-4")

    def test_engine_fails_closed_for_an_undeclared_link(self):
        engine = LoopFlowEngine(persistent_loop_assembly())
        with self.assertRaisesRegex(LoopContractError, "LOOP_ASSEMBLY_LINK_REQUIRED"):
            engine.advance(BlockResult("plan", LinkKind.HANDOFF))

    def test_durable_link_preserves_original_receipt_and_never_claims_unknown(self):
        engine = LoopFlowEngine(persistent_loop_assembly())
        result = BlockResult("assess", LinkKind.HANDOFF, required_capabilities=frozenset({"review"}))
        advance = engine.advance(result)
        continuation = engine.continuation(
            advance=advance, result=result, continuation_id="continuation-6", loop_id="loop-6",
            revision=0, operation_id="operation-6", watch_id="watch-6", receipt_ref="receipt-6",
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = LoopRecipeLedger(Store(Path(directory) / "state.sqlite"))
            ledger.start(loop_id="loop-6", work_id="work-6", entry_block_id="assess")
            staged = ledger.stage(continuation=continuation, link=LinkKind.HANDOFF)
            self.assertEqual(staged["state"], "PENDING")
            unknown = ledger.observe_original_receipt(
                continuation_id="continuation-6", observation="UNKNOWN")
            self.assertEqual(unknown["operation_id"], "operation-6")
            self.assertEqual(unknown["watch_id"], "watch-6")
            self.assertIsNone(ledger.claim_resume("continuation-6"))
            ready = ledger.observe_original_receipt(
                continuation_id="continuation-6", observation="DELIVERED")
            self.assertEqual(ready["receipt_ref"], "receipt-6")
            self.assertEqual(ledger.claim_resume("continuation-6")["state"], "CLAIMED")

    def test_gateway_stages_then_prearms_then_delivers_once(self):
        calls = []
        class Watch:
            def prearm(self, continuation):
                calls.append(("watch", continuation.continuation_id))
                return WatchReceipt(continuation.continuation_id, continuation.watch_id, "WATCHING")
        class Transport:
            def deliver(self, continuation):
                calls.append(("deliver", continuation.continuation_id))
                return DeliveryReceipt(continuation.operation_id, continuation.receipt_ref, "DELIVERED")
        engine = LoopFlowEngine(persistent_loop_assembly())
        result = BlockResult("assess", LinkKind.HANDOFF)
        continuation = engine.continuation(
            advance=engine.advance(result), result=result, continuation_id="continuation-7",
            loop_id="loop-7", revision=0, operation_id="operation-7", watch_id="watch-7",
            receipt_ref="receipt-7",
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = LoopRecipeLedger(Store(Path(directory) / "state.sqlite"))
            ledger.start(loop_id="loop-7", work_id="work-7", entry_block_id="assess")
            gateway = LoopContinuationGateway(ledger, Watch(), Transport())
            outcome = gateway.connect(continuation=continuation, link=LinkKind.HANDOFF)
            self.assertEqual(calls, [("watch", "continuation-7"), ("deliver", "continuation-7")])
            self.assertTrue(outcome.delivered)
            duplicate = gateway.connect(continuation=continuation, link=LinkKind.HANDOFF)
            self.assertEqual(duplicate.state, "EXISTING_READY")
            self.assertEqual(calls, [("watch", "continuation-7"), ("deliver", "continuation-7")])
            self.assertEqual(ledger.claim_resume("continuation-7")["state"], "CLAIMED")

    def test_blocked_link_has_no_watch_or_transport_effect(self):
        class FailWatch:
            def prearm(self, continuation):
                raise AssertionError("blocked must not arm a watch")
        class FailTransport:
            def deliver(self, continuation):
                raise AssertionError("blocked must not deliver")
        engine = LoopFlowEngine(persistent_loop_assembly())
        result = BlockResult("assess", LinkKind.BLOCKED)
        continuation = engine.continuation(
            advance=engine.advance(result), result=result, continuation_id="continuation-8",
            loop_id="loop-8", revision=0, operation_id="operation-8", watch_id="watch-8",
            receipt_ref="receipt-8",
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = LoopRecipeLedger(Store(Path(directory) / "state.sqlite"))
            ledger.start(loop_id="loop-8", work_id="work-8", entry_block_id="assess")
            outcome = LoopContinuationGateway(ledger, FailWatch(), FailTransport()).connect(
                continuation=continuation, link=LinkKind.BLOCKED)
            self.assertEqual(outcome.state, "BLOCKED")

    def test_recovery_planner_never_replays_unknown_and_requires_rechecks_before_replace(self):
        self.assertEqual(
            plan_recovery(RecoveryEvidence("UNKNOWN", "OK")),
            RecoveryAction.RECONCILE_ORIGINAL_RECEIPT,
        )
        self.assertEqual(
            plan_recovery(RecoveryEvidence("DELIVERED", "CHECK", unchanged_rechecks=1)),
            RecoveryAction.RECHECK,
        )
        self.assertEqual(
            plan_recovery(RecoveryEvidence("DELIVERED", "CHECK", unchanged_rechecks=2)),
            RecoveryAction.PREPARE_REPLACE,
        )
        self.assertEqual(
            plan_recovery(RecoveryEvidence("DELIVERED", "OK")), RecoveryAction.RESUME,
        )

    def test_route_table_can_replace_endpoint_without_changing_any_block(self):
        continuation = sample_continuation()
        endpoints = (
            Endpoint("endpoint-current", frozenset({"execute"})),
            Endpoint("endpoint-review", frozenset({"execute", "review"})),
        )
        original = RouteTable((EndpointBinding(frozenset({"execute"}), "endpoint-current"),))
        replacement = RouteTable((EndpointBinding(frozenset({"execute"}), "endpoint-review"),))
        first = prepare_delivery(continuation=continuation, source_endpoint_id="endpoint-current",
                                 route_table=original, endpoints=endpoints)
        second = prepare_delivery(continuation=continuation, source_endpoint_id="endpoint-current",
                                  route_table=replacement, endpoints=endpoints)
        self.assertEqual(first.target_endpoint_id, "endpoint-current")
        self.assertEqual(second.target_endpoint_id, "endpoint-review")
        self.assertEqual(persistent_loop_assembly().next_block("assess", "continue"), "plan")

    def test_delivery_intent_preserves_original_recovery_identity(self):
        continuation = sample_continuation()
        intent = prepare_delivery(
            continuation=continuation, source_endpoint_id="endpoint-current",
            route_table=RouteTable((EndpointBinding(frozenset({"execute"}), "endpoint-next"),)),
            endpoints=(Endpoint("endpoint-next", frozenset({"execute"})),),
        )
        self.assertIs(intent.continuation, continuation)
        self.assertEqual(intent.continuation.operation_id, "operation-4")
        self.assertEqual(intent.continuation.watch_id, "watch-4")
        self.assertEqual(intent.continuation.receipt_ref, "receipt-4")
        self.assertEqual(intent.continuation.revision, 4)

    def test_unbound_or_incapable_endpoint_fails_closed(self):
        continuation = sample_continuation()
        with self.assertRaisesRegex(LoopContractError, "LOOP_ROUTE_BINDING_REQUIRED"):
            prepare_delivery(continuation=continuation, source_endpoint_id="endpoint-current",
                             route_table=RouteTable(()), endpoints=())
        with self.assertRaisesRegex(LoopContractError, "LOOP_ROUTE_CAPABILITY_MISMATCH"):
            prepare_delivery(
                continuation=continuation, source_endpoint_id="endpoint-current",
                route_table=RouteTable((EndpointBinding(frozenset({"execute"}), "endpoint-next"),)),
                endpoints=(Endpoint("endpoint-next", frozenset({"review"})),),
            )

    def test_public_command_service_walks_standard_blocks_to_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.sqlite")
            store.create_work(Work("work-9", "loop fixture", (), frozenset(), "owner-9"))
            commands = PersistentLoopCommands(store, principal_id="owner-9")
            self.assertEqual(commands.outline()["effects"], "NONE_READ_ONLY")
            started = commands.start(loop_id="loop-9", work_id="work-9")
            self.assertEqual(started["run"]["current_block_id"], "resume")
            for block_id, next_block_id in (
                ("resume", "direction"), ("direction", "topology"),
                ("topology", "plan"), ("plan", "execute"),
                ("execute", "assess"),
            ):
                advanced = commands.transition(
                    loop_id="loop-9", block_id=block_id, link="continue")
                self.assertEqual(advanced["next_block_id"], next_block_id)
            completed = commands.transition(
                loop_id="loop-9", block_id="assess", link="complete")
            self.assertEqual(completed["status"], "COMPLETED")
            self.assertEqual(completed["run"]["state"], "COMPLETED")

    def test_public_command_service_prepares_handoff_and_plans_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.sqlite")
            store.create_work(Work("work-10", "loop fixture", (), frozenset(), "owner-10"))
            commands = PersistentLoopCommands(store, principal_id="owner-10")
            commands.start(loop_id="loop-10", work_id="work-10")
            for block_id in ("resume", "direction", "topology", "plan", "execute"):
                commands.transition(loop_id="loop-10", block_id=block_id, link="continue")
            prepared = commands.transition(
                loop_id="loop-10", block_id="assess", link="handoff",
                continuation_id="continuation-10", operation_id="operation-10",
                watch_id="watch-10", receipt_ref="receipt-10",
                required_capabilities=("review",), artifact_refs=("progress-10",),
            )
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertEqual(prepared["effects"], "STATE_ONLY")
            self.assertEqual(commands.status(loop_id="loop-10")["run"]["state"], "WAITING")
            recovery = commands.recovery_plan(
                continuation_id="continuation-10", receipt_observation="UNKNOWN",
                node_observation="OK")
            self.assertEqual(recovery["action"], "reconcile_original_receipt")

    def test_runtime_stages_prearms_then_sends_and_duplicate_never_replays(self):
        async def scenario():
            calls = []
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work("work-11", "loop fixture", (), frozenset(), "owner-11"))
                async def browser(work_id, operation_id, arguments):
                    calls.append((operation_id, arguments["command"]))
                    return {"outcome": "APPLIED", "operation_id": operation_id}
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-11", "test", frozenset()),
                    status_provider=None, make_executor=lambda capability: browser,
                )
                coordinator = PersistentLoopCoordinator(runtime)
                coordinator.commands.ledger.start(
                    loop_id="loop-11", work_id="work-11", entry_block_id="assess")
                values = dict(
                    loop_id="loop-11", block_id="assess", link="handoff",
                    continuation_id="continuation-11", watch_operation_id="watch-op-11",
                    task_id="loop-task-11", instance_id="instance-11",
                    conversation_key="11111111-1111-1111-1111-111111111111",
                    return_conversation_key="22222222-2222-2222-2222-222222222222",
                    return_instance_id="instance-11", send_operation_id="send-op-11",
                    send_text="review this", session_id="session-11", tab_id=11, window_id=12,
                )
                first = await coordinator.connect(**values)
                self.assertEqual(first["status"], "WATCHING")
                self.assertTrue(first["contract_appended"])
                self.assertEqual(calls, [("watch-op-11", "send-delayed-message"),
                                         ("send-op-11", "send-message")])
                duplicate = await coordinator.connect(**values)
                self.assertEqual(duplicate["effects"], "NONE_EXISTING_CONTINUATION")
                self.assertEqual(len(calls), 2)
                with self.assertRaisesRegex(LoopContractError, "LOOP_CONTINUATION_ID_CONFLICT"):
                    await coordinator.connect(**{**values, "send_text": "different review"})
        asyncio.run(scenario())

    def test_runtime_sync_resumes_terminal_watch_without_sending(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work("work-12", "loop fixture", (), frozenset(), "owner-12"))
                async def forbidden(*args):
                    raise AssertionError("sync must not execute a capability")
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-12", "test", frozenset()),
                    status_provider=None, make_executor=lambda capability: forbidden,
                )
                coordinator = PersistentLoopCoordinator(runtime)
                coordinator.commands.ledger.start(
                    loop_id="loop-12", work_id="work-12", entry_block_id="assess")
                coordinator.commands.transition(
                    loop_id="loop-12", block_id="assess", link="wait",
                    continuation_id="continuation-12", operation_id="watch-op-12",
                    watch_id="loop-task-12", receipt_ref="watch-op-12",
                )
                from bct.send_delayed_message import DurableWatchLedger
                DurableWatchLedger(store)
                context = json.dumps({"work_id": "work-12", "principal_id": "owner-12"})
                with store.transaction() as db:
                    db.execute(
                        "INSERT INTO delayed_send_watches(task_id,generation,conversation_key,"
                        "response_turn_id,source_send_receipt,state,context_json) "
                        "VALUES(?,?,?,?,?,?,?)",
                        ("loop-task-12", 1, "33333333-3333-3333-3333-333333333333",
                         "turn-12", "watch-op-12", "SELF_SENT", context),
                    )
                synced = await coordinator.sync(continuation_id="continuation-12")
                self.assertEqual(synced["status"], "RESUMED")
                self.assertEqual(coordinator.commands.status(loop_id="loop-12")["run"]["state"], "ACTIVE")
                duplicate = await coordinator.sync(continuation_id="continuation-12")
                self.assertEqual(duplicate["status"], "ALREADY_RESUMED")
        asyncio.run(scenario())

    def test_runtime_records_unknown_when_watch_transport_raises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work("work-15", "loop fixture", (), frozenset(), "owner-15"))
                async def broken(*args):
                    raise RuntimeError("uncertain transport")
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-15", "test", frozenset()),
                    status_provider=None, make_executor=lambda capability: broken,
                )
                coordinator = PersistentLoopCoordinator(runtime)
                coordinator.commands.ledger.start(
                    loop_id="loop-15", work_id="work-15", entry_block_id="assess")
                result = await coordinator.connect(
                    loop_id="loop-15", block_id="assess", link="wait",
                    continuation_id="continuation-15", watch_operation_id="watch-op-15",
                    task_id="loop-task-15", instance_id="instance-15",
                    conversation_key="55555555-5555-5555-5555-555555555555",
                    return_conversation_key="66666666-6666-6666-6666-666666666666",
                    return_instance_id="instance-15",
                )
                self.assertEqual(result["status"], "WATCH_UNKNOWN")
                stored = coordinator.commands.ledger.get_continuation("continuation-15")
                self.assertEqual(stored["state"], "UNKNOWN")
                self.assertEqual(coordinator.commands.status(loop_id="loop-15")["run"]["state"],
                                 "RECONCILING")
        asyncio.run(scenario())

    def test_runtime_creates_new_loop_network_with_only_manager(self):
        async def scenario():
            calls = []
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work("work-13", "loop fixture", (), frozenset(), "owner-13"))
                async def network(work_id, operation_id, arguments):
                    calls.append((operation_id, arguments))
                    return {"outcome": "APPLIED", "operation_id": operation_id}
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-13", "test", frozenset()),
                    status_provider=None, make_executor=lambda capability: network,
                )
                coordinator = PersistentLoopCoordinator(runtime)
                coordinator.commands.start(
                    loop_id="loop-13", work_id="work-13", instruction_text="finish goal",
                    direction_text="repeat until verified", network_project_id="loop-net-13",
                    manager_conversation_key="11111111-1111-1111-1111-111111111111",
                    supervisor_conversation_key="22222222-2222-2222-2222-222222222222",
                )
                result = await coordinator.configure_topology(
                    loop_id="loop-13", project_operation_id="project-op-13",
                    manager_operation_id="manager-op-13",
                    supervisor_operation_id="supervisor-op-13",
                    display_name="Loop 13", expected_manager_scope_id="old-manager",
                    expected_supervisor_scope_id="old-supervisor",
                )
                self.assertEqual(result["status"], "READY")
                self.assertEqual([item[1]["operation"] for item in calls],
                                 ["project-upsert", "membership-assign"])
                self.assertEqual(calls[1][1]["role_tags"], ["Manager"])
        asyncio.run(scenario())

    def test_missing_supervisor_reuses_create_send_bootstrap_watch_and_registration(self):
        async def scenario():
            manager_key = "11111111-1111-1111-1111-111111111111"
            supervisor_key = "22222222-2222-2222-2222-222222222222"
            instance_id = "instance-16"
            session_id = "a" * 32
            snapshot = {"monitor": {
                "current_nodes": {
                    "observed_at": 1, "observation": {"state": "FRESH"},
                    "items": [{
                        "conversation_uuid": manager_key, "status": "CONFIRMED",
                        "generating": False, "connection": {"disconnected": False},
                    }],
                },
                "rcc": {"instances": [{
                    "instance_id": instance_id, "session_id": session_id,
                    "state": "OPEN", "cached": False,
                    "tabs": [{"tab_id": 1, "window_id": 7,
                              "conversation_key": manager_key}],
                }]},
            }}
            calls = []
            receipts = {}

            async def execute(work_id, operation_id, arguments):
                calls.append((operation_id, arguments.copy()))
                if operation_id in receipts:
                    return receipts[operation_id]
                command = arguments.get("command")
                if command == "create-chat-tab":
                    snapshot["monitor"]["rcc"]["instances"][0]["tabs"].append(
                        {"tab_id": 9, "window_id": 7, "conversation_key": ""})
                    result = {"outcome": "APPLIED", "evidence": {
                        "created_tab_id": 9, "created_window_id": 7,
                        "created_request_id": operation_id,
                    }}
                elif command == "send-message":
                    snapshot["monitor"]["rcc"]["instances"][0]["tabs"][1][
                        "conversation_key"] = supervisor_key
                    snapshot["monitor"]["current_nodes"]["items"].append({
                        "conversation_uuid": supervisor_key, "status": "CONFIRMED",
                        "generating": False, "connection": {"disconnected": False},
                    })
                    result = {"outcome": "APPLIED", "evidence": {
                        "conversation_key": supervisor_key,
                    }}
                else:
                    result = {"outcome": "APPLIED", "evidence": {}}
                receipts[operation_id] = result
                return result

            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work(
                    "work-16", "loop fixture", (),
                    frozenset({"browser", "conversation_network_update"}), "owner-16",
                ))
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-16", "test", frozenset()),
                    status_provider=lambda: snapshot,
                    make_executor=lambda capability: execute,
                )
                result = await PersistentLoopCoordinator(runtime).prepare_supervisor(
                    work_id="work-16", manager_conversation_key=manager_key,
                    network_project_id="loop-network-16", instance_id=instance_id,
                    create_operation_id="create-supervisor-16",
                    send_operation_id="send-supervisor-16",
                    watch_operation_id="watch-supervisor-16",
                    register_operation_id="register-supervisor-16",
                    task_id="supervisor-task-16",
                    bootstrap_text="Prepare to supervise this Loop.",
                    display_name="Loop Supervisor 16", scope_name="Loop 16",
                    window_id=7,
                )
                self.assertEqual(result["status"], "READY")
                self.assertEqual(result["supervisor_conversation_key"], supervisor_key)
                self.assertEqual(
                    [item[1].get("command") or item[1].get("operation") for item in calls],
                    ["create-chat-tab", "send-message", "send-delayed-message", "set-node-info"],
                )
                watch = calls[2][1]
                self.assertEqual(watch["bootstrap_create_operation_id"],
                                 "create-supervisor-16")
                self.assertEqual(watch["planned_send_operation_id"],
                                 "send-supervisor-16")
                self.assertEqual(watch["manager_conversation_key"], manager_key)
                self.assertEqual(calls[3][1]["scope_name"], "")
                self.assertEqual(calls[3][1]["role_tags"], [LOOP_SUPERVISOR_ROLE])
                self.assertEqual(result["planned_scope_name"], "Loop 16")

        asyncio.run(scenario())

    def test_loop_supervisor_role_is_scoped_without_changing_global_supervisor_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.sqlite")
            configure_conversation_scope(
                store,
                conversation_key="11111111-1111-1111-1111-111111111111",
                display_name="Existing Chain Supervisor", scope_name="",
                role_tags=["Supervisor"], expected_scope_id="",
                expected_role_tags_sha256=role_tags_sha256([]),
            )
            loop_key = "22222222-2222-2222-2222-222222222222"
            registered = configure_conversation_scope(
                store, conversation_key=loop_key, display_name="Loop Supervisor",
                scope_name="", role_tags=[LOOP_SUPERVISOR_ROLE],
                expected_scope_id="",
                expected_role_tags_sha256=role_tags_sha256([]),
            )
            self.assertEqual(registered["scope_id"], "")
            upsert_project(store, project_id="loop-network-16", display_name="Loop 16")
            assigned = assign_conversation_membership(
                store, project_id="loop-network-16", conversation_key=loop_key,
                role_tags=[LOOP_SUPERVISOR_ROLE], expected_scope_id="",
            )
            self.assertEqual(assigned["project_id"], "loop-network-16")
            self.assertEqual(assigned["role_tags"], [LOOP_SUPERVISOR_ROLE])

    def test_supervisor_reentry_reads_exact_receipts_before_effect_executor(self):
        async def scenario():
            manager_key = "11111111-1111-1111-1111-111111111111"
            supervisor_key = "22222222-2222-2222-2222-222222222222"
            instance_id, session_id = "instance-17", "b" * 32
            snapshot = {"monitor": {
                "current_nodes": {"observed_at": 1,
                    "observation": {"state": "FRESH"}, "items": [
                        {"conversation_uuid": manager_key, "status": "CONFIRMED",
                         "generating": False, "connection": {"disconnected": False}},
                        {"conversation_uuid": supervisor_key, "status": "CONFIRMED",
                         "generating": False, "connection": {"disconnected": False}},
                    ]},
                "rcc": {"instances": [{"instance_id": instance_id,
                    "session_id": session_id, "state": "OPEN", "cached": False,
                    "tabs": [
                        {"tab_id": 1, "window_id": 7,
                         "conversation_key": manager_key},
                        {"tab_id": 9, "window_id": 7,
                         "conversation_key": supervisor_key},
                    ]}]},
            }}
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work(
                    "work-17", "loop fixture", (),
                    frozenset({"browser", "conversation_network_update"}), "owner-17",
                ))
                receipts = [
                    ("create-supervisor-17", "browser", {"created_tab_id": 9}),
                    ("send-supervisor-17", "browser",
                     {"conversation_key": supervisor_key}),
                    ("watch-supervisor-17", "browser",
                     {"command": "send-delayed-message", "task_id": "supervisor-task-17"}),
                ]
                with store.transaction() as db:
                    for operation_id, capability, evidence in receipts:
                        db.execute(
                            "INSERT INTO operations(operation_id,work_id,principal_id,request_digest,"
                            "capability,target,state,outcome,evidence_json,error,assignment_epoch,"
                            "policy_revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (operation_id, "work-17", "owner-17", operation_id, capability,
                             instance_id, "FINISHED", "APPLIED", json.dumps(evidence), None,
                             1, "test", 1.0, 1.0),
                        )
                calls = []
                async def execute(work_id, operation_id, arguments):
                    calls.append((operation_id, arguments.copy()))
                    return {"operation_id": operation_id, "state": "FINISHED",
                            "outcome": "APPLIED", "evidence": {}}
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-17", "test", frozenset()),
                    status_provider=lambda: snapshot,
                    make_executor=lambda capability: execute,
                )
                result = await PersistentLoopCoordinator(runtime).prepare_supervisor(
                    work_id="work-17", manager_conversation_key=manager_key,
                    network_project_id="loop-network-17", instance_id=instance_id,
                    create_operation_id="create-supervisor-17",
                    send_operation_id="send-supervisor-17",
                    watch_operation_id="watch-supervisor-17",
                    register_operation_id="register-supervisor-17",
                    task_id="supervisor-task-17", bootstrap_text="Supervise the Loop.",
                    display_name="Loop Supervisor 17", scope_name="Loop 17", window_id=7,
                )
                self.assertEqual(result["status"], "READY")
                self.assertEqual([item[0] for item in calls], ["register-supervisor-17"])
                for stage in ("creation", "send", "watch"):
                    self.assertTrue(result[stage]["duplicate"])

        asyncio.run(scenario())

    def test_loop_recovery_adapter_reuses_check_recheck_and_pause_without_chain_mutation(self):
        async def scenario():
            key = "44444444-4444-4444-4444-444444444444"
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite")
                store.create_work(Work("work-14", "loop fixture", (), frozenset(), "owner-14"))
                runtime = PersistentLoopRuntime(
                    bct=type("Bct", (), {"store": store})(),
                    principal=Principal("owner-14", "test", frozenset()),
                    status_provider=lambda: {}, make_executor=lambda capability: None,
                )
                recovery = PersistentLoopRecovery(runtime)
                def evidence(conversation_key):
                    return observe_node({"current_nodes": {
                        "observed_at": 1, "observation": {"state": "FRESH"},
                        "items": [{"conversation_uuid": key, "status": "CONFIRMED",
                                   "generating": False, "connection": {"disconnected": False},
                                   "telemetry": {"readiness": "IDLE"}}],
                    }}, conversation_key)
                recovery._evidence = evidence
                checked = await recovery.run(
                    action="check", work_id="work-14", conversation_key=key,
                    task_id="loop-task-14", case_id="case-14")
                self.assertEqual(checked["node_recovery"]["next_action"], "CONTINUE")
                paused = await recovery.run(
                    action="pause", work_id="work-14", case_id="case-14",
                    reason="verified stalled")
                self.assertEqual(paused["node_recovery"]["state"], "PAUSED")
        asyncio.run(scenario())
