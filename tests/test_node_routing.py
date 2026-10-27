from __future__ import annotations

import unittest

from bct.core.node_routing import (
    NodeAffinity, NodeReadiness, RoutingAction, RoutingCandidate,
    RoutingPolicy, decide_route,
)


def candidate(node_id: str, readiness: NodeReadiness) -> RoutingCandidate:
    return RoutingCandidate(node_id, node_id + "-attachment", readiness)


class NodeRoutingTests(unittest.TestCase):
    def test_idle_preferred_node_dispatches_immediately(self):
        result = decide_route(
            policy=RoutingPolicy(NodeAffinity.ANY),
            preferred=candidate("worker-b", NodeReadiness.IDLE), fallbacks=[], elapsed_s=0,
        )
        self.assertEqual(RoutingAction.DISPATCH_PREFERRED, result.action)

    def test_required_node_waits_ten_minutes_then_escalates(self):
        policy = RoutingPolicy(NodeAffinity.REQUIRED)
        preferred = candidate("worker-b", NodeReadiness.GENERATING)
        waiting = decide_route(policy=policy, preferred=preferred, fallbacks=[], elapsed_s=599)
        expired = decide_route(policy=policy, preferred=preferred, fallbacks=[], elapsed_s=600)
        self.assertEqual(RoutingAction.WAIT_REQUIRED, waiting.action)
        self.assertEqual(RoutingAction.ESCALATE_REQUIRED, expired.action)

    def test_operator_can_adjust_required_node_hold(self):
        policy = RoutingPolicy(
            NodeAffinity.REQUIRED, short_wait_s=20, required_wait_s=900,
        )
        preferred = candidate("worker-b", NodeReadiness.GENERATING)
        self.assertEqual(
            RoutingAction.WAIT_REQUIRED,
            decide_route(policy=policy, preferred=preferred, fallbacks=[], elapsed_s=899).action,
        )
        self.assertEqual(
            RoutingAction.ESCALATE_REQUIRED,
            decide_route(policy=policy, preferred=preferred, fallbacks=[], elapsed_s=900).action,
        )

    def test_invalid_routing_waits_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "NODE_ROUTING_POLICY_INTERVAL_INVALID"):
            RoutingPolicy(NodeAffinity.ANY, short_wait_s=20, required_wait_s=19)

    def test_independent_work_uses_idle_standby_after_fifteen_seconds(self):
        result = decide_route(
            policy=RoutingPolicy(NodeAffinity.PREFERRED),
            preferred=candidate("worker-b", NodeReadiness.GENERATING),
            fallbacks=[
                candidate("worker-c", NodeReadiness.GENERATING),
                candidate("standby", NodeReadiness.IDLE),
            ],
            elapsed_s=15,
        )
        self.assertEqual(RoutingAction.REROUTE_TO_STANDBY, result.action)
        self.assertEqual("standby", result.candidate.node_id)

    def test_independent_work_requests_provisioning_without_idle_standby(self):
        result = decide_route(
            policy=RoutingPolicy(NodeAffinity.ANY),
            preferred=candidate("worker-b", NodeReadiness.DISCONNECTED),
            fallbacks=[candidate("worker-c", NodeReadiness.GENERATING)], elapsed_s=15,
        )
        self.assertEqual(RoutingAction.PROVISION_NODE, result.action)

    def test_submitted_or_unknown_effect_can_never_reroute(self):
        for effect in ("APPLIED", "UNKNOWN"):
            with self.subTest(effect=effect):
                result = decide_route(
                    policy=RoutingPolicy(NodeAffinity.ANY),
                    preferred=candidate("worker-b", NodeReadiness.GENERATING),
                    fallbacks=[candidate("standby", NodeReadiness.IDLE)], elapsed_s=20,
                    delivery_effect=effect,
                )
                self.assertEqual(RoutingAction.PROTECT_EXISTING_EFFECT, result.action)
