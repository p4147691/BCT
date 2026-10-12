from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import AuthorizationError, Outcome, PreconditionError, Principal
from bct.features.rcc import RelayBrowserFeature
from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable
from bct.service import BCT


class FakeRelayClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.result: dict = {"type": "host:result", "ok": True}
        self.error: Exception | None = None

    def request(self, **values):
        self.calls.append(values)
        if self.error:
            raise self.error
        return dict(self.result)


class RccIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        policy = self.root / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.client = FakeRelayClient()
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=policy)
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(self.client)
        self.principal = Principal("codex", "test", frozenset({"relay_browser"}))
        self.bct.create_work(
            work_id="rcc-work", request_summary="test exact relay integration",
            roots=[str(self.root)], actions=["relay_browser"], principal=self.principal,
        )

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation_id: str, arguments: dict):
        return self.bct.operations.run(
            principal=self.principal, work_id="rcc-work", operation_id=operation_id,
            capability="relay_browser", arguments=arguments,
        )

    def test_read_state_and_duplicate_do_not_call_twice(self):
        self.client.result = {
            "type": "host:result", "requestId": "state-1", "ok": True,
            "state": {"instanceId": "instance123", "tabs": []},
        }
        first = self.call("state-1", {"command": "state", "instance_id": "instance123"})
        duplicate = self.call("state-1", {"command": "state", "instance_id": "instance123"})
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(1, len(self.client.calls))
        self.assertEqual("state-1", self.client.calls[0]["request_id"])
        self.assertEqual("STATE_RETURNED", first.evidence["host_state"])

    def test_state_output_removes_native_secrets(self):
        self.client.result = {
            "type": "host:result", "ok": True,
            "state": {
                "instanceId": "instance123",
                "settings": {"token": "must-not-persist", "armed": False},
                "registrations": {"WORK": {"authorization": "internal", "tabId": 7}},
            },
        }
        result = self.call("state-secret", {
            "command": "state", "instance_id": "instance123",
        })
        state = result.output["result"]["state"]
        self.assertNotIn("token", state["settings"])
        self.assertNotIn("authorization", state["registrations"]["WORK"])
        self.assertEqual(7, state["registrations"]["WORK"]["tabId"])

    def test_browser_mutation_uses_bct_operation_id(self):
        self.client.result = {
            "type": "host:result", "requestId": "create-1", "ok": True,
            "state": "PENDING_UNBOUND", "windowId": 5, "tabId": 9,
        }
        result = self.call("create-1", {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("create-1", self.client.calls[0]["extra"]["operationId"])
        self.assertEqual("instance123", self.client.calls[0]["extra"]["instanceId"])

    def test_bootstrap_send_requires_exact_creation_identity(self):
        with self.assertRaisesRegex(PreconditionError, "RCC_BOOTSTRAP_IDENTITY_REQUIRED"):
            self.call("send-bad", {
                "command": "send-to-created-tab", "instance_id": "instance123",
                "text": "hello",
            })
        result = self.call("send-good", {
            "command": "send-to-created-tab", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10, "window_id": 11,
            "create_operation_id": "create-1", "text": "hello",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        extra = self.client.calls[-1]["extra"]
        self.assertEqual("send-good", extra["operationId"])
        self.assertEqual("create-1", extra["createOperationId"])

    def test_confirmed_not_applied_releases_claim(self):
        self.client.result = {
            "type": "host:result", "ok": False, "state": "NOT_APPLIED",
            "error": "PENDING_CREATE_RECEIPT_REQUIRED",
        }
        result = self.call("not-applied", {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.client.result = {"type": "host:result", "ok": True}
        second = self.call("after-not-applied", {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, second.outcome)

    def test_ambiguous_effect_is_not_retried(self):
        self.client.error = RelayEffectUnknown("RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH")
        result = self.call("unknown-1", {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        duplicate = self.call("unknown-1", {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(1, len(self.client.calls))

    def test_unavailable_before_dispatch_is_failed_confirmed(self):
        self.client.error = RelayUnavailable("RCC_INSTANCE_UNAVAILABLE:instance123")
        result = self.call("unavailable-1", {
            "command": "state", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.FAILED, result.outcome)

    def test_wrong_owner_and_unlisted_fields_are_denied(self):
        other = Principal("other", "test", frozenset({"relay_browser"}))
        with self.assertRaises(AuthorizationError):
            self.bct.operations.run(
                principal=other, work_id="rcc-work", operation_id="wrong-owner",
                capability="relay_browser",
                arguments={"command": "state", "instance_id": "instance123"},
            )
        with self.assertRaisesRegex(PreconditionError, "RCC_ARGUMENT_NOT_ALLOWED"):
            self.call("bad-field", {
                "command": "state", "instance_id": "instance123", "role": "MANAGER",
            })


if __name__ == "__main__":
    unittest.main()
