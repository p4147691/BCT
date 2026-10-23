from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import (
    AuthorizationError, FeatureRequest, FeatureResult, Outcome, Principal, Work,
)
from bct.core.operations import OperationCoordinator
from bct.core.policy import Policy
from bct.core.store import Store
from bct.relay_executor import RelayControlFeature
from bct.relay_settings import preview_relay_control


SCOPE = "network.runtime"


class FakeRelayFeature:
    capability = "relay_browser"

    def __init__(self):
        self.preparations = 0
        self.executions = 0
        self.last_request = None

    def prepare(self, *, work, arguments):
        self.preparations += 1
        if arguments.get("command") != "delivery-start":
            raise ValueError("FAKE_COMMAND_INVALID")
        return FeatureRequest(
            self.capability, str(arguments["instance_id"]), dict(arguments),
            ("rcc-instance:" + str(arguments["instance_id"]),),
            {"command": "delivery-start", "mutating": True},
        )

    def execute(self, request):
        self.executions += 1
        self.last_request = request
        return FeatureResult(
            Outcome.APPLIED,
            {"command": "delivery-start", "submitted": True},
            output={"echo": request.arguments["text"]},
        )


def control_document(*, enabled=True, function=None, route=None):
    function = function or {
        "driver": "rcc", "call": "delivery.start", "effect": "external",
        "arguments": {
            "instance_id": "${instance_id}",
            "delivery_id": "${delivery_id}",
            "manager_conversation_key": "${manager_conversation_key}",
            "worker_conversation_key": "${worker_conversation_key}",
            "text": "${task}",
            "scope_id": "${scope_id}",
        },
        "timeout_seconds": 30,
    }
    route = route or {
        "entry": "submit", "max_steps": 2,
        "steps": {"submit": {"use": "submit", "next": {"APPLIED": "END"}}},
    }
    return {
        "version": 1, "defaults": {}, "projects": {},
        "control": {
            "version": 1, "enabled": enabled, "variables": {},
            "functions": {"submit": function},
            "routes": {"worker.submit": route},
            "selected_routes": {"worker_submit": "worker.submit"},
            "projects": {},
        },
    }


class RelayControlExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "relay-message-settings.json"
        self.environment = patch.dict(
            os.environ, {"BCT_RELAY_SETTINGS_PATH": str(self.settings)}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.write(control_document())
        self.child = FakeRelayFeature()
        self.feature = RelayControlFeature(
            store=object(), features={"relay_browser": self.child},
        )
        self.work = Work(
            "work-runtime", "설정 실행 시험", (self.tmp.name,),
            frozenset({"relay_browser"}), "principal",
        )
        self.context = {
            "instance_id": "instance123",
            "delivery_id": "delivery-한글-01",
            "manager_conversation_key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "worker_conversation_key": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "task": "한글 업무 📦",
        }

    def write(self, value):
        self.settings.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def revision(self):
        return hashlib.sha256(self.settings.read_bytes()).hexdigest()

    def args(self):
        return {
            "purpose": "worker_submit", "scope_id": SCOPE,
            "context": self.context,
            "expected_settings_sha256": self.revision(),
        }

    def test_registered_route_freezes_exact_delegated_request(self):
        request = self.feature.prepare(work=self.work, arguments=self.args())
        self.assertEqual("relay_control", request.capability)
        self.assertEqual("relay_browser", request.preconditions["delegated_capability"])
        self.assertEqual(self.revision(), request.preconditions["settings_sha256"])
        self.assertEqual("한글 업무 📦", request.arguments["delegated"]["arguments"]["text"])
        self.assertEqual("delivery-start", request.arguments["delegated"]["arguments"]["command"])
        self.assertEqual(30, request.arguments["delegated"]["arguments"]["timeout_s"])
        result = self.feature.execute(
            FeatureRequest(**{**request.__dict__, "operation_id": "configured-flow-01"})
        )
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("relay_browser", result.evidence["delegated_capability"])
        self.assertEqual("delivery-start", result.evidence["command"])
        self.assertEqual("configured-flow-01", self.child.last_request.operation_id)

    def test_preview_reports_registry_truth_without_executing(self):
        value = preview_relay_control(SCOPE)
        self.assertTrue(value["execution_connected"])
        resolved = value["resolved_preview"]
        self.assertEqual("NONE_PREVIEW_ONLY", resolved["effect"])
        self.assertTrue(resolved["registry"]["submit"]["executable"])
        self.assertEqual(
            "REGISTERED",
            resolved["selected_routes"]["worker_submit"]["steps"]["submit"]
            ["resolved_function"]["runtime_availability"],
        )
        self.assertEqual(0, self.child.executions)

    def test_unregistered_or_effect_mismatched_function_fails_closed(self):
        for function in (
            {"driver": "chrome_api", "call": "tabs.sendMessage", "effect": "external"},
            {"driver": "rcc", "call": "delivery.start", "effect": "read"},
        ):
            with self.subTest(function=function):
                self.write(control_document(function=function))
                with self.assertRaisesRegex(Exception, "RELAY_CONTROL_(FUNCTION_NOT_REGISTERED|EFFECT_MISMATCH)"):
                    self.feature.prepare(work=self.work, arguments=self.args())
                self.assertEqual(0, self.child.executions)

    def test_disabled_revision_change_and_nonterminal_operation_are_pre_effect(self):
        self.write(control_document(enabled=False))
        with self.assertRaisesRegex(Exception, "RELAY_CONTROL_DISABLED"):
            self.feature.prepare(work=self.work, arguments=self.args())
        self.write(control_document())
        stale = self.args()
        stale["expected_settings_sha256"] = "0" * 64
        with self.assertRaisesRegex(Exception, "RELAY_CONTROL_SETTINGS_REVISION_CHANGED"):
            self.feature.prepare(work=self.work, arguments=stale)
        bad_route = {
            "entry": "first", "max_steps": 3,
            "steps": {
                "first": {"use": "submit", "next": {"APPLIED": "second"}},
                "second": {"use": "submit", "next": {"APPLIED": "END"}},
            },
        }
        self.write(control_document(route=bad_route))
        with self.assertRaisesRegex(Exception, "RELAY_CONTROL_OPERATION_MUST_TERMINATE"):
            self.feature.prepare(work=self.work, arguments=self.args())
        self.assertEqual(0, self.child.executions)

    def test_pure_message_output_can_feed_the_one_operation_step(self):
        value = control_document()
        value["control"]["functions"]["compose"] = {
            "driver": "message", "call": "compose.worker", "effect": "pure",
            "arguments": {
                "manager_conversation_key": "${manager_conversation_key}",
                "worker_conversation_key": "${worker_conversation_key}",
                "task": "${task}", "scope_id": "${scope_id}",
            },
        }
        value["control"]["functions"]["submit"]["arguments"].pop("scope_id")
        value["control"]["functions"]["submit"]["arguments"]["text"] = "${message.text}"
        value["control"]["routes"]["worker.submit"] = {
            "entry": "compose", "max_steps": 3,
            "steps": {
                "compose": {
                    "use": "compose", "save_as": "message",
                    "next": {"APPLIED": "submit"},
                },
                "submit": {"use": "submit", "next": {"APPLIED": "END"}},
            },
        }
        self.write(value)
        with patch.object(
            self.feature, "_pure_compose_worker",
            return_value={"text": "구성된 메시지 ✅", "sha256": "a" * 64, "utf16_units": 9},
        ):
            request = self.feature.prepare(work=self.work, arguments=self.args())
        self.assertEqual(
            "구성된 메시지 ✅", request.arguments["delegated"]["arguments"]["text"]
        )

    def test_coordinator_authorizes_delegated_capability_and_deduplicates(self):
        state = Path(self.tmp.name) / "state.sqlite3"
        policy_path = Path(self.tmp.name) / "policy.toml"
        policy_path.write_text(
            '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        store = Store(state)
        coordinator = OperationCoordinator(store=store, policy=Policy(policy_path))
        child = FakeRelayFeature()
        coordinator.register(child)
        configured = RelayControlFeature(
            store=store, features=coordinator._features,
        )
        coordinator.register(configured)
        principal = Principal(
            "principal", "test", frozenset({"relay_browser", "relay_control"})
        )
        store.create_work(self.work)
        first = coordinator.run(
            principal=principal, work_id=self.work.work_id,
            operation_id="configured-flow-durable-01", capability="relay_control",
            arguments=self.args(),
        )
        second = coordinator.run(
            principal=principal, work_id=self.work.work_id,
            operation_id="configured-flow-durable-01", capability="relay_control",
            arguments=self.args(),
        )
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertEqual(Outcome.APPLIED, second.outcome)
        self.assertEqual(1, child.executions)
        self.assertEqual("relay_control", store.get_operation_metadata_for(
            operation_id="configured-flow-durable-01", work_id=self.work.work_id,
            principal_id="principal",
        )["capability"])

    def test_coordinator_denies_before_preparing_delegated_effect(self):
        state = Path(self.tmp.name) / "denied.sqlite3"
        policy_path = Path(self.tmp.name) / "denied-policy.toml"
        policy_path.write_text(
            '[policy]\nnormal_actions=["relay_browser","read"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        store = Store(state)
        coordinator = OperationCoordinator(store=store, policy=Policy(policy_path))
        child = FakeRelayFeature()
        coordinator.register(child)
        coordinator.register(RelayControlFeature(
            store=store, features=coordinator._features,
        ))
        denied_work = Work(
            "denied-work", "권한 전 실행 금지", (self.tmp.name,),
            frozenset({"read"}), "principal",
        )
        store.create_work(denied_work)
        principal = Principal(
            "principal", "test", frozenset({"read", "relay_browser", "relay_control"})
        )
        with self.assertRaises(AuthorizationError):
            coordinator.run(
                principal=principal, work_id=denied_work.work_id,
                operation_id="configured-flow-denied-01", capability="relay_control",
                arguments=self.args(),
            )
        self.assertEqual(0, child.preparations)
        self.assertEqual(0, child.executions)


if __name__ == "__main__":
    unittest.main()
