from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct.core.models import AuthorizationError, Outcome, PreconditionError, Principal
from bct.core.rcc_result import rcc_result_hash
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

    def _generic_unknown_send(self):
        request = {
            "command": "send", "instance_id": "instance123",
            "to": "BCT_ROSTER", "text": "benign roster result",
            "timeout_s": 30,
        }
        self.client.error = RelayEffectUnknown("RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH")
        original = self.call("generic-roster-original", request)
        self.client.error = None
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        fingerprint = json.dumps(
            ["BCT_ROSTER", "benign roster result", False,
             "", "", "", "", "", 0, "", 0],
            ensure_ascii=False, separators=(",", ":"),
        )
        receipt = {
            "id": "generic-roster-original", "ok": True,
            "reply": "BCT_ROSTER_ACK", "error": "",
            "failureEvidence": None, "ambiguous": False,
            "resultState": "RESULT_PERSISTED",
            "submitState": "SUBMITTED_CONFIRMED",
            "tabId": 701, "conversationKey": "conversation-fresh",
            "fingerprint": fingerprint, "messageHash": fingerprint,
        }
        receipt["resultHash"] = rcc_result_hash(receipt)
        self.client.result = {
            "ok": True, "relayId": "generic-roster-original",
            "found": True, "completed": True, "pending": False,
            "result": receipt,
        }
        recover = {
            "command": "reconcile-send", "instance_id": "instance123",
            "relay_id": "generic-roster-original",
            "original_to": "BCT_ROSTER",
            "original_text": "benign roster result",
            "original_timeout_s": 30,
        }
        return receipt, recover

    def test_generic_send_timeout_reconciles_exact_persisted_result_once(self):
        receipt, recover = self._generic_unknown_send()
        result = self.call("generic-roster-recover", recover)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(receipt["resultHash"], result.evidence["result_hash"])
        self.assertTrue(result.evidence["no_resend"])
        self.assertTrue(self.call("generic-roster-recover", recover).duplicate)
        self.assertEqual(1, len([
            c for c in self.client.calls if c["command"] == "send"
        ]))
        self.assertEqual(1, len([
            c for c in self.client.calls if c["command"] == "result"
        ]))
        db = self.bct.store._connect()
        try:
            claimed = db.execute(
                "SELECT unresolved FROM resource_claims "
                "WHERE operation_id='generic-roster-original'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(0, claimed)
        original = self.bct.store.get_operation_for(
            operation_id="generic-roster-original", work_id="rcc-work",
            principal_id="codex",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)

    def test_generic_send_wrong_original_digest_rejected_before_result_read(self):
        _, recover = self._generic_unknown_send()
        initial_calls = len(self.client.calls)
        recover["original_text"] = "different text"
        with self.assertRaisesRegex(
            PreconditionError, "RCC_GENERIC_SEND_ORIGINAL_DIGEST_MISMATCH"
        ):
            self.call("generic-mismatched-original", recover)
        self.assertEqual(initial_calls, len(self.client.calls))
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims "
                "WHERE operation_id='generic-roster-original'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

    def test_generic_send_tampered_receipt_never_releases_unknown_claim(self):
        _, recover = self._generic_unknown_send()
        self.client.result["result"]["resultHash"] = "0" * 64
        rejected = self.call("generic-roster-bad-receipt", recover)
        self.assertEqual(Outcome.FAILED, rejected.outcome)
        self.assertEqual("RCC_GENERIC_SEND_RECEIPT_NOT_PROVEN", rejected.error)
        self.assertEqual(1, len([
            c for c in self.client.calls if c["command"] == "send"
        ]))
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims "
                "WHERE operation_id='generic-roster-original'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

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

    def test_create_and_send_retries_read_only_dom_recovery_without_resend(self):
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(
            self.client,
            result_readback_timeout_s=0.5,
            recovery_retry_interval_s=0.01,
        )
        _, send, created, sent, terminal = self._compose_receipts(
            "compose-dom-recovery-retry"
        )
        pending = {
            "type": "host:result", "ok": True, "relayId": send,
            "found": False, "completed": False, "pending": True,
            "pendingStatus": {"networkStartedAt": 100, "networkCompletedAt": 200},
        }
        self.client.results = [
            created, sent, pending,
            RelayEffectUnknown("DOM_NOT_STABLE_YET"),
            pending, terminal,
        ]
        result = self.call("compose-dom-recovery-retry", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "text": "hello",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        commands = [call["command"] for call in self.client.calls]
        self.assertEqual(2, commands.count("recover-created-result"))
        self.assertEqual(1, commands.count("send-to-created-tab"))
        recover_ids = [
            call["request_id"] for call in self.client.calls
            if call["command"] == "recover-created-result"
        ]
        self.assertEqual(2, len(set(recover_ids)))
        self.assertEqual(2, result.evidence["recovery_attempts"])

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

    def _rename_recovery_fixture(self, tag="legacy", title="새 제목"):
        original = {
            "command": "rename-conversation", "instance_id": "instance123",
            "session_id": "session-original", "tab_id": 114,
            "conversation_key": "conv-abc", "title": title,
        }
        self.client.result = {"type": "host:result", "ok": False}
        first = self.call("original-" + tag, original)
        self.assertEqual(Outcome.UNKNOWN, first.outcome)
        recovery = dict(original)
        recovery.update({"command": "reconcile-rename-conversation",
                         "relay_id": "original-" + tag})
        return first, recovery

    def _rename_success_proof(self, title="새 제목"):
        return {
            "type": "host:result", "ok": True,
            "relayId": "original-legacy", "instanceId": "instance123",
            "receipt": {
                "command": "rename-conversation",
                "fingerprint": json.dumps(["conv-abc", 114, "session-original", title],
                                          ensure_ascii=False, separators=(",", ":")),
                "result": {"ok": True, "operationId": "original-legacy",
                           "savedTitle": title, "tabId": 114,
                           "conversationKey": "conv-abc"},
            },
            "observed": {"tabId": 114, "conversationKey": "conv-abc",
                         "title": title, "presence": "OPEN",
                         "currentSessionId": "session-after-reload"},
        }

    def test_rename_unknown_fences_exact_conversation_not_entire_instance(self):
        self.client.result = {"type": "host:result", "ok": False}
        first = self.call("unknown-first", {
            "command": "rename-conversation", "instance_id": "instance123",
            "session_id": "original-session", "tab_id": 114,
            "conversation_key": "conv-abc", "title": "새 제목",
        })
        second = self.call("unknown-other", {
            "command": "rename-conversation", "instance_id": "instance123",
            "session_id": "original-session", "tab_id": 115,
            "conversation_key": "conv-def", "title": "다른 제목",
        })
        self.assertEqual(Outcome.UNKNOWN, first.outcome)
        self.assertEqual(Outcome.UNKNOWN, second.outcome)
        with self.assertRaisesRegex(Exception, "RESOURCE_ALREADY_CLAIMED"):
            self.call("unknown-duplicate-target", {
                "command": "rename-conversation", "instance_id": "instance123",
                "session_id": "original-session", "tab_id": 114,
                "conversation_key": "conv-abc", "title": "다시 변경",
            })
        db = self.bct.store._connect()
        try:
            keys = [x[0] for x in db.execute(
                "SELECT resource_key FROM resource_claims WHERE unresolved=1")]
        finally:
            db.close()
        self.assertEqual(2, len(keys))
        self.assertTrue(all(":rename:" in x for x in keys))

    def test_rename_reconcile_exact_terminal_and_rotated_session(self):
        self._rename_recovery_fixture()
        self.client.result = self._rename_success_proof()
        recovered = self.call("rename-reconcile-applied", {
            "command": "reconcile-rename-conversation", "instance_id": "instance123",
            "relay_id": "original-legacy", "session_id": "session-original",
            "tab_id": 114, "conversation_key": "conv-abc", "title": "새 제목",
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        self.assertEqual("rename-receipt", self.client.calls[-1]["command"])
        again = self.call("rename-reconcile-applied", {
            "command": "reconcile-rename-conversation", "instance_id": "instance123",
            "relay_id": "original-legacy", "session_id": "session-original",
            "tab_id": 114, "conversation_key": "conv-abc", "title": "새 제목",
        })
        self.assertTrue(again.duplicate)
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id='original-legacy'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(0, unresolved)

    def test_rename_inspection_reads_receipt_before_session_and_title_are_known(self):
        self._rename_recovery_fixture("inspect")
        proof = self._rename_success_proof()
        proof["relayId"] = "original-inspect"
        proof["receipt"]["result"]["operationId"] = "original-inspect"
        self.client.result = proof
        inspected = self.call("rename-inspect-receipt", {
            "command": "inspect-rename-receipt", "instance_id": "instance123",
            "relay_id": "original-inspect", "tab_id": 114,
            "conversation_key": "conv-abc",
        })
        self.assertEqual(Outcome.APPLIED, inspected.outcome)
        self.assertEqual("rename-receipt", self.client.calls[-1]["command"])
        self.assertTrue(inspected.evidence["receipt_found"])
        db = self.bct.store._connect()
        try:
            claim = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("original-inspect",)).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, claim)

    def test_rename_inspection_rejects_wrong_target_without_changing_original_claim(self):
        self._rename_recovery_fixture("inspect-wrong")
        proof = self._rename_success_proof()
        proof["relayId"] = "original-inspect-wrong"
        proof["receipt"]["result"]["operationId"] = "original-inspect-wrong"
        proof["observed"]["conversationKey"] = "different-conversation"
        self.client.result = proof
        result = self.call("rename-inspect-wrong", {
            "command": "inspect-rename-receipt", "instance_id": "instance123",
            "relay_id": "original-inspect-wrong", "tab_id": 114,
            "conversation_key": "conv-abc",
        })
        self.assertNotEqual(Outcome.APPLIED, result.outcome)
        db = self.bct.store._connect()
        try:
            claim = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("original-inspect-wrong",)).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, claim)

    def test_rename_reconcile_missing_receipt_or_wrong_identity_stays_unknown(self):
        for case in ("missing", "tab", "conversation", "title", "fingerprint", "host"):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                _, recovery = self._rename_recovery_fixture(case)
                proof = self._rename_success_proof()
                proof["relayId"] = "original-" + case
                proof["receipt"]["result"]["operationId"] = "original-" + case
                if case == "missing":
                    proof["receipt"] = None
                elif case == "tab":
                    proof["observed"]["tabId"] = 115
                elif case == "conversation":
                    proof["observed"]["conversationKey"] = "other"
                elif case == "title":
                    proof["observed"]["title"] = "이전 제목"
                elif case == "fingerprint":
                    proof["receipt"]["fingerprint"] = "[]"
                else:
                    proof["instanceId"] = "wrong-instance"
                self.client.result = proof
                failed = self.call("attempt-" + case, recovery)
                self.assertNotEqual(Outcome.APPLIED, failed.outcome)
                old = self.bct.store.get_operation_for(
                    operation_id="original-" + case, work_id="rcc-work",
                    principal_id="codex")
                self.assertEqual(Outcome.UNKNOWN, old.outcome)
                db = self.bct.store._connect()
                try:
                    claim = db.execute(
                        "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                        ("original-" + case,)).fetchone()[0]
                finally:
                    db.close()
                self.assertEqual(1, claim)

    def test_rename_reconcile_wrong_original_digest_prevents_external_read(self):
        self._rename_recovery_fixture("digest")
        prior = len(self.client.calls)
        with self.assertRaisesRegex(PreconditionError, "ORIGINAL_REQUEST_DIGEST_MISMATCH"):
            self.call("rename-reconcile-wrong-digest", {
                "command": "reconcile-rename-conversation", "instance_id": "instance123",
                "relay_id": "original-digest", "session_id": "session-original",
                "tab_id": 114, "conversation_key": "conv-abc", "title": "다른 제목",
            })
        self.assertEqual(prior, len(self.client.calls))

    def test_legacy_broad_claim_atomic_reclassification_preserves_original_unknown(self):
        first, recovery = self._rename_recovery_fixture("legacy-broad")
        db = self.bct.store._connect()
        try:
            db.execute(
                "UPDATE resource_claims SET resource_key=? WHERE operation_id=?",
                ("rcc-instance:instance123", "original-legacy-broad"))
            db.commit()
        finally:
            db.close()
        self.client.result = {
            "type": "host:result", "ok": True,
            "instanceId": "instance123", "relayId": "original-legacy-broad",
            "receipt": None,
            "observed": {
                "tabId": 114, "conversationKey": "conv-abc", "title": "이전 제목",
                "presence": "OPEN", "currentSessionId": "session-after-reload",
            },
        }
        recovery["command"] = "reclassify-rename-claim"
        migrated = self.call("reclass-legacy", recovery)
        self.assertEqual(Outcome.APPLIED, migrated.outcome)
        original = self.bct.store.get_operation_for(
            operation_id="original-legacy-broad", work_id="rcc-work", principal_id="codex")
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual("RCC_HOST_OUTCOME_UNVERIFIED:MISSING", original.error)
        db = self.bct.store._connect()
        try:
            claim = db.execute(
                "SELECT resource_key,unresolved FROM resource_claims WHERE operation_id=?",
                ("original-legacy-broad",)).fetchone()
        finally:
            db.close()
        self.assertEqual(("rcc-instance:instance123:rename:114:conv-abc", 1), tuple(claim))
        duplicate = self.call("reclass-legacy", recovery)
        self.assertTrue(duplicate.duplicate)
        self.client.result = {"type": "host:result", "ok": False}
        other = self.call("unrelated-rename-after-narrow", {
            "command": "rename-conversation", "instance_id": "instance123",
            "session_id": "session-elsewhere", "tab_id": 115,
            "conversation_key": "different-conversation", "title": "이름",
        })
        self.assertEqual(Outcome.UNKNOWN, other.outcome)

    def test_legacy_broad_claim_identity_mismatch_preserves_instance_fence(self):
        _, recovery = self._rename_recovery_fixture("legacy-mismatch")
        db = self.bct.store._connect()
        try:
            db.execute("UPDATE resource_claims SET resource_key=? WHERE operation_id=?",
                       ("rcc-instance:instance123", "original-legacy-mismatch"))
            db.commit()
        finally:
            db.close()
        recovery["command"] = "reclassify-rename-claim"
        self.client.result = {
            "type": "host:result", "ok": True, "instanceId": "instance123",
            "relayId": "original-legacy-mismatch", "receipt": None,
            "observed": {
                "tabId": 114, "conversationKey": "WRONG",
                "title": "이전", "presence": "OPEN",
                "currentSessionId": "session-after-reload",
            },
        }
        result = self.call("reclass-invalid", recovery)
        self.assertNotEqual(Outcome.APPLIED, result.outcome)
        db = self.bct.store._connect()
        try:
            claim = db.execute(
                "SELECT resource_key,unresolved FROM resource_claims WHERE operation_id=?",
                ("original-legacy-mismatch",)).fetchone()
        finally:
            db.close()
        self.assertEqual(("rcc-instance:instance123", 1), tuple(claim))

    def _make_legacy_broad_rename_claim(self, tag="operator-quarantine"):
        self._rename_recovery_fixture(tag)
        original_id = "original-" + tag
        db = self.bct.store._connect()
        try:
            db.execute("UPDATE resource_claims SET resource_key=? WHERE operation_id=?",
                       ("rcc-instance:instance123", original_id))
            db.commit()
        finally:
            db.close()
        return original_id

    def _operator_quarantine_args(self, original_id):
        return {
            "command": "quarantine-legacy-rename-claim", "instance_id": "instance123",
            "relay_id": original_id, "session_id": "session-original", "tab_id": 114,
            "conversation_key": "conv-abc", "title": "새 제목",
            "operator_justification": "Historical terminal receipt was evicted; isolate only this rename.",
            "operator_acknowledgement": "Original UNKNOWN remains unresolved and is not retried.",
        }

    def _missing_rename_receipt_observation(self, original_id):
        return {
            "type": "host:result", "ok": True, "instanceId": "instance123",
            "relayId": original_id, "receipt": None, "receiptState": "MISSING",
            "observed": {"tabId": 114, "conversationKey": "conv-abc",
                         "presence": "OPEN", "title": "이전 제목"},
        }

    def test_operator_quarantine_narrows_only_missing_receipt_legacy_claim(self):
        original_id = self._make_legacy_broad_rename_claim()
        self.client.result = self._missing_rename_receipt_observation(original_id)
        quarantined = self.call("operator-quarantine", self._operator_quarantine_args(original_id))
        self.assertEqual(Outcome.APPLIED, quarantined.outcome)
        self.assertEqual("rename-receipt", self.client.calls[-1]["command"])
        self.assertEqual("OPERATOR_QUARANTINE_NOT_RECONCILIATION",
                         quarantined.evidence["audit_kind"])
        original = self.bct.store.get_operation_for(
            operation_id=original_id, work_id="rcc-work", principal_id="codex")
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual("RCC_HOST_OUTCOME_UNVERIFIED:MISSING", original.error)
        db = self.bct.store._connect()
        try:
            claim = db.execute(
                "SELECT resource_key,unresolved FROM resource_claims WHERE operation_id=?",
                (original_id,)).fetchone()
            audit = db.execute(
                "SELECT kind FROM events WHERE subject_id=? ORDER BY event_id DESC",
                (original_id,)).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(("rcc-instance:instance123:rename:114:conv-abc", 1), tuple(claim))
        self.assertEqual("RCC_RENAME_CLAIM_OPERATOR_QUARANTINED", audit)

    def test_operator_quarantine_fails_closed_for_receipt_or_observation_mismatch(self):
        for case in ("terminal", "wrong-tab", "closed"):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                original_id = self._make_legacy_broad_rename_claim(case)
                proof = self._missing_rename_receipt_observation(original_id)
                if case == "terminal":
                    proof["receiptState"] = "TERMINAL"
                elif case == "wrong-tab":
                    proof["observed"]["tabId"] = 115
                else:
                    proof["observed"]["presence"] = "CLOSED"
                self.client.result = proof
                result = self.call("operator-quarantine-" + case,
                                   self._operator_quarantine_args(original_id))
                self.assertNotEqual(Outcome.APPLIED, result.outcome)
                original = self.bct.store.get_operation_for(
                    operation_id=original_id, work_id="rcc-work", principal_id="codex")
                self.assertEqual(Outcome.UNKNOWN, original.outcome)
                db = self.bct.store._connect()
                try:
                    claim = db.execute(
                        "SELECT resource_key,unresolved FROM resource_claims WHERE operation_id=?",
                        (original_id,)).fetchone()
                finally:
                    db.close()
                self.assertEqual(("rcc-instance:instance123", 1), tuple(claim))

    def test_operator_quarantine_requires_acknowledgement_and_exact_owner(self):
        original_id = self._make_legacy_broad_rename_claim("operator-fences")
        arguments = self._operator_quarantine_args(original_id)
        arguments["operator_acknowledgement"] = ""
        with self.assertRaisesRegex(PreconditionError, "OPERATOR_QUARANTINE_ACK_REQUIRED"):
            self.call("operator-quarantine-no-ack", arguments)
        foreign = Principal("foreign", "test", frozenset({"relay_browser"}))
        self.bct.create_work(work_id="foreign-work", request_summary="foreign",
                             roots=[str(self.root)], actions=["relay_browser"], principal=foreign)
        with self.assertRaisesRegex(Exception, "OPERATION_RESULT_ACCESS_DENIED"):
            self.bct.operations.run(
                principal=foreign, work_id="foreign-work", operation_id="operator-foreign",
                capability="relay_browser", arguments=self._operator_quarantine_args(original_id),
            )

    def test_operator_quarantine_requires_exact_original_request_digest_before_read(self):
        for field, replacement in {
            "session_id": "session-other", "tab_id": 115,
            "conversation_key": "conv-other", "title": "다른 제목",
        }.items():
            with self.subTest(field=field):
                self.tearDown()
                self.setUp()
                original_id = self._make_legacy_broad_rename_claim("digest-" + field)
                arguments = self._operator_quarantine_args(original_id)
                arguments[field] = replacement
                prior_calls = len(self.client.calls)
                with self.assertRaisesRegex(PreconditionError,
                                            "RCC_RENAME_ORIGINAL_REQUEST_DIGEST_MISMATCH"):
                    self.call("operator-quarantine-digest-" + field, arguments)
                self.assertEqual(prior_calls, len(self.client.calls))
                original = self.bct.store.get_operation_for(
                    operation_id=original_id, work_id="rcc-work", principal_id="codex")
                self.assertEqual(Outcome.UNKNOWN, original.outcome)
                db = self.bct.store._connect()
                try:
                    claim = db.execute(
                        "SELECT resource_key,unresolved FROM resource_claims WHERE operation_id=?",
                        (original_id,)).fetchone()
                finally:
                    db.close()
                self.assertEqual(("rcc-instance:instance123", 1), tuple(claim))

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
