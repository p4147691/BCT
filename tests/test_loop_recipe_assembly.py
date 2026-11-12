"""Contract tests for the role-neutral Loop block assembly."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
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
