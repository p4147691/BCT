from __future__ import annotations

import json
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
        self.results: list[dict | Exception] = []
        self.error: Exception | None = None

    def request(self, **values):
        self.calls.append(values)
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return dict(result)
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
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(
            self.client, result_readback_timeout_s=0.25,
        )
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

    def test_result_read_requires_exact_original_work_and_instance(self):
        self.client.result = {
            "type": "host:result", "ok": False, "state": "SUBMIT_UNKNOWN"
        }
        original = self.call("original-send", {
            "command": "send-to-created-tab", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10, "window_id": 11,
            "create_operation_id": "create-1", "text": "hello",
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.client.result = {
            "type": "host:result", "ok": True, "relayId": "original-send",
            "found": False, "pending": True, "pendingStatus": {"deliveryConfirmed": False},
        }
        result = self.call("result-read", {
            "command": "result", "instance_id": "instance123", "relay_id": "original-send",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("original-send", self.client.calls[-1]["text"])
        self.assertEqual("result", self.client.calls[-1]["command"])
        with self.assertRaisesRegex(PreconditionError, "RCC_RESULT_INSTANCE_MISMATCH"):
            self.call("wrong-instance", {
                "command": "result", "instance_id": "otherinstance", "relay_id": "original-send",
            })
        with self.assertRaisesRegex(PreconditionError, "RCC_RESULT_ORIGINAL_SEND_REQUIRED"):
            self.call("result-of-read", {
                "command": "result", "instance_id": "instance123", "relay_id": "result-read",
            })
        other = Principal("foreign", "test", frozenset({"relay_browser"}))
        self.bct.create_work(work_id="other-work", request_summary="foreign",
                             roots=[str(self.root)], actions=["relay_browser"], principal=other)
        with self.assertRaisesRegex(Exception, "OPERATION_RESULT_ACCESS_DENIED"):
            self.bct.operations.run(
                principal=other, work_id="other-work", operation_id="foreign-result",
                capability="relay_browser",
                arguments={"command": "result", "instance_id": "instance123",
                           "relay_id": "original-send"},
            )

    def test_terminal_result_reconciles_only_exact_unknown_claim(self):
        self.client.result = {
            "type": "host:result", "ok": False, "state": "SUBMIT_UNKNOWN"
        }
        original = self.call("unknown-bootstrap", {
            "command": "send-to-created-tab", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10, "window_id": 11,
            "create_operation_id": "create-1", "text": "hello",
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)

        self.client.result = {
            "type": "host:result", "ok": True, "relayId": "unknown-bootstrap",
            "found": True, "completed": True, "pending": False,
            "result": {
                "id": "unknown-bootstrap", "resultState": "RESULT_PERSISTED",
                "conversationKey": "conversation-1234", "ok": False,
                "error": "net::ERR_ABORTED", "ackState": "UNACKED",
                "tabId": 10,
                "fingerprint": '["create-1","instance123","session-1",10,11,"hello"]',
            },
        }
        reconciled = self.call("reconcile-bootstrap", {
            "command": "reconcile-send-to-created-tab",
            "instance_id": "instance123", "relay_id": "unknown-bootstrap",
        })
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        self.assertEqual("result", self.client.calls[-1]["command"])
        self.assertEqual("unknown-bootstrap", self.client.calls[-1]["text"])
        self.assertEqual(
            "unknown-bootstrap", reconciled.evidence["reconciled_operation_id"]
        )
        self.assertEqual(
            "LEGACY_OMITTED_VERIFIED_BY_ORIGINAL", reconciled.evidence["submit_state"]
        )
        self.client.result = {"type": "host:result", "ok": True}
        next_mutation = self.call("after-reconciliation", {
            "command": "create-chat-tab", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, next_mutation.outcome)

    def test_reconciliation_without_terminal_receipt_keeps_original_claim(self):
        self.client.result = {
            "type": "host:result", "ok": False, "state": "SUBMIT_UNKNOWN"
        }
        self.call("unknown-bootstrap", {
            "command": "send-to-created-tab", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10, "window_id": 11,
            "create_operation_id": "create-1", "text": "hello",
        })
        self.client.result = {
            "type": "host:result", "ok": True, "relayId": "unknown-bootstrap",
            "found": True, "completed": True, "pending": False,
            "result": {
                "id": "unknown-bootstrap", "resultState": "RESULT_PERSISTED",
                "submitState": "SUBMIT_UNKNOWN", "conversationKey": "conversation-1234",
                "tabId": 10, "fingerprint": '["not-a-bootstrap-fingerprint"]',
            },
        }
        rejected = self.call("reconcile-incomplete", {
            "command": "reconcile-send-to-created-tab",
            "instance_id": "instance123", "relay_id": "unknown-bootstrap",
        })
        self.assertEqual(Outcome.FAILED, rejected.outcome)
        self.assertEqual("RCC_RECONCILIATION_EVIDENCE_INSUFFICIENT", rejected.error)
        self.client.result = {"type": "host:result", "ok": True}
        with self.assertRaisesRegex(Exception, "unknown-bootstrap:FINISHED:UNKNOWN"):
            self.call("still-blocked", {
                "command": "create-chat-tab", "instance_id": "instance123",
            })

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

    def test_extension_reload_is_an_explicit_idempotent_mutation(self):
        self.client.result = {
            "type": "host:result", "requestId": "reload-1", "ok": True,
            "reloading": True,
        }
        first = self.call("reload-1", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        duplicate = self.call("reload-1", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(1, len(self.client.calls))
        self.assertEqual("reload-extension", self.client.calls[0]["command"])
        self.assertEqual("reload-1", self.client.calls[0]["extra"]["operationId"])

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

    def test_bootstrap_unknown_recovers_only_from_exact_terminal_success(self):
        fingerprint = json.dumps([
            "create-1", "instance123", "session-1", 10, 11, "hello",
        ], separators=(",", ":"))
        self.client.results = [
            {"type": "host:result", "ok": False, "state": "SUBMIT_UNKNOWN"},
            {"type": "host:result", "ok": True, "relayId": "send-readback",
             "found": False, "completed": False, "pending": True},
            {"type": "host:result", "ok": True, "relayId": "send-readback",
             "found": True, "completed": True, "pending": False,
             "result": {"id": "send-readback", "ok": True, "ambiguous": False,
                        "reply": "done", "tabId": 10,
                        "conversationKey": "conversation-1234",
                        "resultHash": "result-hash", "resultState": "RESULT_PERSISTED",
                        "fingerprint": fingerprint}},
        ]
        result = self.call("send-readback", {
            "command": "send-to-created-tab", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10, "window_id": 11,
            "create_operation_id": "create-1", "text": "hello",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(
            "SUBMITTED_CONFIRMED_BY_TERMINAL_RESULT",
            result.evidence["host_state"],
        )
        self.assertEqual(
            ["send-to-created-tab", "result", "result"],
            [call["command"] for call in self.client.calls],
        )
        self.assertEqual("send-readback", self.client.calls[1]["text"])

    def test_bootstrap_readback_mismatch_remains_unknown_without_resend(self):
        self.client.results = [
            {"type": "host:result", "ok": False, "state": "SUBMIT_UNKNOWN"},
            {"type": "host:result", "ok": True, "relayId": "send-mismatch",
             "found": True, "completed": True, "pending": False,
             "result": {"id": "send-mismatch", "ok": True, "ambiguous": False,
                        "reply": "done", "tabId": 99,
                        "conversationKey": "conversation-1234",
                        "resultHash": "result-hash", "resultState": "RESULT_PERSISTED",
                        "fingerprint": "[]"}},
        ]
        result = self.call("send-mismatch", {
            "command": "send-to-created-tab", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10, "window_id": 11,
            "create_operation_id": "create-1", "text": "hello",
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        self.assertEqual(
            ["send-to-created-tab", "result"],
            [call["command"] for call in self.client.calls],
        )

    @staticmethod
    def _compose_receipts(parent: str, *, mode: str = "tab", text: str = "hello"):
        import hashlib
        digest = hashlib.sha256(parent.encode("utf-8")).hexdigest()[:24]
        create, send = "bct-compose-c-" + digest, "bct-compose-s-" + digest
        base = {"instanceId": "instance123", "sessionId": "session1",
                "tabId": 10, "windowId": 11}
        created = {"type": "host:result", "ok": True, "created": True,
                   "state": "PENDING_UNBOUND", **base,
                   "creationReceipt": {**base, "bindingState": "PENDING_UNBOUND"}}
        sent = {"type": "host:result", "ok": True, "state": "SUBMITTED",
                "operationId": send, "createOperationId": create,
                "tabId": 10, "windowId": 11, "conversationKey": "c-123"}
        terminal = {"type": "host:result", "ok": True, "relayId": send,
                    "found": True, "completed": True, "pending": False,
                    "result": {"id": send, "ok": True, "ambiguous": False,
                               "reply": "OK", "tabId": 10,
                               "conversationKey": "c-123", "resultHash": "sha",
                               "resultState": "RESULT_PERSISTED",
                               "fingerprint": json.dumps(
                                   [create, "instance123", "session1", 10, 11, text])}}
        return create, send, created, sent, terminal

    def test_create_and_send_tab_returns_exact_terminal_result_in_one_call(self):
        create, send, created, sent, terminal = self._compose_receipts("compose-tab")
        self.client.results = [created, sent, terminal]
        first = self.call("compose-tab", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "text": "hello"})
        duplicate = self.call("compose-tab", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "text": "hello"})
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(["create-chat-tab","send-to-created-tab", "result"],
                         [c["command"] for c in self.client.calls])
        self.assertEqual([create, send], [c["request_id"] for c in self.client.calls[:2]])
        self.assertEqual(create, first.evidence["create_operation_id"])
        self.assertEqual(send, first.evidence["send_operation_id"])
        self.assertEqual(10, self.client.calls[1]["extra"]["tabId"])
        self.assertEqual("session1", self.client.calls[1]["extra"]["sessionId"])
        self.assertEqual("OK", first.output["result"]["result"]["reply"])
        self.client.results = [terminal]
        read = self.call("compose-result", {
            "command":"result-of-create-and-send",
            "instance_id":"instance123", "relay_id":"compose-tab"})
        self.assertEqual(Outcome.APPLIED, read.outcome)
        self.assertEqual(send, self.client.calls[-1]["text"])
        self.assertEqual("result", self.client.calls[-1]["command"])
        self.assertEqual("OK", read.output["result"]["result"]["reply"])
        with self.assertRaisesRegex(PreconditionError, "RCC_RESULT_ORIGINAL_SEND_REQUIRED"):
            self.call("wrong-read", {
                "command":"result-of-create-and-send", "instance_id":"instance123",
                "relay_id":"compose-result"})

    def test_create_and_send_independent_window_reuses_common_exact_send(self):
        create, send, created, sent, terminal = self._compose_receipts("compose-window", mode="window")
        self.client.results = [created,sent,terminal]
        result = self.call("compose-window", {
            "command":"create-and-send","instance_id":"instance123",
            "mode":"window","text":"hello"})
        self.assertEqual(Outcome.APPLIED,result.outcome)
        self.assertEqual(["create-chat-window","send-to-created-tab", "result"],
                         [c["command"] for c in self.client.calls])
        self.assertEqual(11,result.evidence["window_id"])
        self.assertEqual(create,self.client.calls[1]["extra"]["createOperationId"])
        with self.assertRaisesRegex(PreconditionError,"RCC_COMPOSE_WINDOW_ID_FORBIDDEN"):
            self.call("bad-window",{"command":"create-and-send",
                      "instance_id":"instance123","mode":"window",
                      "text":"hello","window_id":11})

    def test_create_and_send_unknown_keeps_claim_and_never_resends(self):
        create, send, created, _, terminal = self._compose_receipts("compose-unknown")
        self.client.results = [created,{"ok":False,"state":"SUBMIT_UNKNOWN"},{
            **terminal,"result":{**terminal["result"],"fingerprint":"[]"}}]
        result = self.call("compose-unknown",{
            "command":"create-and-send","instance_id":"instance123",
            "mode":"tab","text":"hello"})
        duplicate = self.call("compose-unknown",{
            "command":"create-and-send","instance_id":"instance123",
            "mode":"tab","text":"hello"})
        self.assertEqual(Outcome.UNKNOWN,result.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(1,sum(c["command"]=="send-to-created-tab" for c in self.client.calls))
        with self.assertRaisesRegex(Exception,"compose-unknown:FINISHED:UNKNOWN"):
            self.call("compose-blocked",{"command":"create-and-send",
                          "instance_id":"instance123","mode":"tab","text":"hello"})

    def test_create_and_send_unknown_initial_ack_recovers_exact_terminal(self):
        create, send, created, _, terminal = self._compose_receipts("compose-recovered")
        self.client.results = [created,{"ok":False,"state":"SUBMIT_UNKNOWN"},terminal]
        result = self.call("compose-recovered",{
            "command":"create-and-send","instance_id":"instance123",
            "mode":"tab","text":"hello"})
        self.assertEqual(Outcome.APPLIED,result.outcome)
        self.assertEqual("RESULT_PERSISTED",result.evidence["result_state"])
        self.assertEqual(1,sum(c["command"]=="send-to-created-tab" for c in self.client.calls))
        self.assertGreaterEqual(result.evidence["total_ms"],0)

    def test_create_and_send_recovers_completed_exact_dom_without_resend(self):
        create, send, created, sent, terminal = self._compose_receipts("compose-dom-recovery")
        pending = {
            "type": "host:result", "ok": True, "relayId": send,
            "found": False, "completed": False, "pending": True,
            "pendingStatus": {"networkStartedAt": 100, "networkCompletedAt": 200},
        }
        self.client.results = [created, sent, pending, terminal]
        result = self.call("compose-dom-recovery", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "text": "hello",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("OK", result.output["result"]["result"]["reply"])
        commands = [call["command"] for call in self.client.calls]
        self.assertEqual(
            ["create-chat-tab", "send-to-created-tab", "result",
             "recover-created-result"], commands,
        )
        self.assertEqual(1, commands.count("send-to-created-tab"))

    def test_create_and_send_unknown_parent_reconciles_from_exact_child_receipt(self):
        create, send, created, _, terminal = self._compose_receipts("compose-reconcile")
        self.client.results = [created, {"ok": False, "state": "SUBMIT_UNKNOWN"}, {
            **terminal, "result": {**terminal["result"], "fingerprint": "[]"},
        }]
        original = self.call("compose-reconcile", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "text": "hello",
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)

        self.client.results = [terminal]
        reconciled = self.call("compose-reconcile-proof", {
            "command": "reconcile-create-and-send", "instance_id": "instance123",
            "relay_id": "compose-reconcile",
        })
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        self.assertEqual("recover-created-result", self.client.calls[-1]["command"])
        self.assertEqual("compose-reconcile", reconciled.evidence["reconciled_operation_id"])
        self.assertEqual(send, reconciled.evidence["terminal_relay_id"])
        self.assertEqual(create, json.loads(
            reconciled.output["result"]["result"]["fingerprint"])[0])

        self.client.result = {"type": "host:result", "ok": False,
                              "state": "NOT_APPLIED"}
        next_mutation = self.call("compose-after-reconcile", {
            "command": "create-chat-tab", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.NOT_APPLIED, next_mutation.outcome)

    def test_create_receipt_mismatch_does_not_send(self):
        _,_,created,_,_ = self._compose_receipts("compose-bad-identity")
        created["creationReceipt"]["tabId"]=99
        self.client.results=[created]
        result=self.call("compose-bad-identity",{
            "command":"create-and-send","instance_id":"instance123",
            "mode":"tab","text":"hello"})
        self.assertEqual(Outcome.UNKNOWN,result.outcome)
        self.assertEqual(["create-chat-tab"],[c["command"] for c in self.client.calls])

    def test_conversation_rename_uses_exact_identity_and_duplicate_fence(self):
        self.client.result = {
            "type": "host:result", "requestId": "rename-1", "ok": True,
            "savedTitle": "새 대화 이름", "tabId": 10,
            "conversationKey": "conversation-1234",
        }
        arguments = {
            "command": "rename-conversation", "instance_id": "instance123",
            "session_id": "session-1", "tab_id": 10,
            "conversation_key": "conversation-1234", "title": "새 대화 이름",
        }
        first = self.call("rename-1", arguments)
        duplicate = self.call("rename-1", arguments)
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(1, len(self.client.calls))
        self.assertEqual({
            "sessionId": "session-1", "tabId": 10,
            "conversationKey": "conversation-1234", "title": "새 대화 이름",
            "operationId": "rename-1",
        }, self.client.calls[0]["extra"])

    def test_conversation_rename_rejects_missing_or_oversized_title(self):
        with self.assertRaisesRegex(PreconditionError, "RCC_RENAME_IDENTITY_REQUIRED"):
            self.call("rename-session-missing", {
                "command": "rename-conversation", "instance_id": "instance123",
                "tab_id": 10, "conversation_key": "conversation-1234", "title": "name",
            })
        with self.assertRaisesRegex(PreconditionError, "RCC_RENAME_IDENTITY_REQUIRED"):
            self.call("rename-missing", {
                "command": "rename-conversation", "instance_id": "instance123",
                "tab_id": 10, "conversation_key": "conversation-1234", "title": "",
            })
        with self.assertRaisesRegex(PreconditionError, "RCC_RENAME_IDENTITY_REQUIRED"):
            self.call("rename-long", {
                "command": "rename-conversation", "instance_id": "instance123",
                "tab_id": 10, "conversation_key": "conversation-1234", "title": "x" * 101,
            })

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
