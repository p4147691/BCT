from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bct.core.models import AuthorizationError, Outcome, PreconditionError, Principal
from bct.core.rcc_result import rcc_result_hash
from bct.core.delivery_ledger import DeliveryLedger
from bct.core.delivery_state import DeliveryEvent
from bct.features.rcc import RelayBrowserFeature
from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable
from bct.service import BCT


class FakeRelayClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.result: dict = {"type": "host:result", "ok": True}
        self.results: list[dict | Exception] = []
        self.error: Exception | None = None
        self.target_state: dict | None = None

    def request(self, **values):
        self.calls.append(values)
        if (str(values.get("request_id") or "").startswith("rcc-target-")
                and self.target_state is not None):
            return dict(self.target_state)
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
            self.client, store=self.bct.store, result_readback_timeout_s=0.25,
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

    @staticmethod
    def _target_state(*, session_id="session1", tab_id=10, window_id=11):
        return {
            "type": "host:result", "ok": True,
            "state": {
                "instanceId": "instance123", "sessionId": session_id,
                "tabs": [{"tabId": tab_id, "windowId": window_id,
                          "conversationKey": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"}],
            },
        }

    def _fresh_window_target(self) -> str:
        self.client.target_state = self._target_state()
        feature = self.bct.operations._features["relay_browser"]
        targets = feature._issue_target_refs(
            work_id="rcc-work", instance_id="instance123", session_id="session1",
            tabs=self.client.target_state["state"]["tabs"],
        )
        return next(target["target_ref"] for target in targets
                    if target["target_kind"] == "window")

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

    def test_direct_send_request_digest_preserves_legacy_fingerprint(self):
        work = self.bct.store.get_work("rcc-work")
        feature = self.bct.operations._features["relay_browser"]
        prepared = feature.prepare(work=work, arguments={
            "command": "send", "instance_id": "instance123",
            "to": "BCT_ROSTER", "text": "benign task", "timeout_s": 30,
        })
        self.assertEqual({}, prepared.arguments["extra"])
        # Transport dispatch still sets returnOnAck in the neighboring test.
        # The stored request remains compatible with old UNKNOWN receipts.

    def test_direct_send_requests_submission_ack_like_orchestrate(self):
        self.client.result = {
            "type": "host:ack", "ok": True, "submitted": True,
            "effectState": "SUBMITTED",
        }
        result = self.call("direct-submit-ack", {
            "command": "send", "instance_id": "instance123",
            "to": "BCT_ROSTER", "text": "benign task",
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("SUBMITTED", result.evidence["host_state"])
        self.assertIs(self.client.calls[0]["extra"]["returnOnAck"], True)

    def test_direct_send_proven_pre_submit_failure_keeps_exact_error(self):
        self.client.result = {
            "type": "host:result", "ok": False, "submitted": False,
            "effectState": "NOT_APPLIED", "ambiguous": False,
            "error": "RELAY_EDITOR_TEXT_MISMATCH",
        }
        result = self.call("direct-pre-submit-error", {
            "command": "send", "instance_id": "instance123",
            "to": "BCT_ROSTER", "text": "benign task",
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual("NOT_APPLIED", result.evidence["host_state"])
        self.assertEqual("RELAY_EDITOR_TEXT_MISMATCH", result.evidence["error"])

    def test_direct_send_ambiguous_host_failure_does_not_release_claim(self):
        self.client.result = {
            "type": "host:result", "ok": False,
            "effectState": "UNKNOWN", "ambiguous": True,
            "error": "RELAY_SEND_BUTTON_CHANGED",
        }
        result = self.call("direct-ambiguous-error", {
            "command": "send", "instance_id": "instance123",
            "to": "BCT_ROSTER", "text": "benign task",
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        self.assertIn("RELAY_SEND_BUTTON_CHANGED", result.error)
        db = self.bct.store._connect()
        try:
            claim = db.execute("SELECT unresolved FROM resource_claims WHERE operation_id=?",
                               ("direct-ambiguous-error",)).fetchone()
            self.assertEqual(1, claim["unresolved"])
        finally:
            db.close()

    def test_direct_send_ack_without_submission_is_not_success(self):
        self.client.result = {"type": "host:ack", "ok": True,
                              "submitted": False, "effectState": "QUEUED"}
        result = self.call("direct-queued-ack", {
            "command": "send", "instance_id": "instance123",
            "to": "BCT_ROSTER", "text": "benign task",
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)

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
        self.client.results = [
            self._idle_rcc_state(),
            {"type": "host:result", "requestId": "reload-1", "ok": True,
             "reloading": True},
        ]
        first = self.call("reload-1", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        duplicate = self.call("reload-1", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(["state", "reload-extension"], [
            call["command"] for call in self.client.calls
        ])
        self.assertEqual("reload-1", self.client.calls[1]["extra"]["operationId"])

    def test_extension_reload_coexists_with_finished_unknown_effect_claim(self):
        wrong = self._new_chat_result("compose-before-reload")
        wrong["windowId"] = 99
        target_ref = self._fresh_window_target()
        original = self.call("compose-before-reload", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.client.results = [
            self._idle_rcc_state(),
            {"type": "host:result", "requestId": "reload-after-unknown",
             "ok": True, "reloading": True},
        ]
        reloaded = self.call("reload-after-unknown", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, reloaded.outcome)
        original_after = self.bct.store.get_operation_for(
            operation_id="compose-before-reload", work_id="rcc-work",
            principal_id="codex",
        )
        self.assertEqual(Outcome.UNKNOWN, original_after.outcome)
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("compose-before-reload",),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

    def _delivery_for_reload(self, *, state="SENT_WAITING"):
        manager = "11111111-1111-1111-1111-111111111111"
        worker = "22222222-2222-2222-2222-222222222222"
        ledger = DeliveryLedger(self.bct.store)
        ledger.create_or_get(
            delivery_id="reload-delivery-1", work_id="rcc-work",
            instance_id="instance123", manager_conversation_key=manager,
            worker_conversation_key=worker, request_sha256="a" * 64,
        )
        ledger.observe(delivery_id="reload-delivery-1", work_id="rcc-work",
                       event=DeliveryEvent.WORKER_TURN_CONFIRMED)
        if state in {"REPLY_CAPTURED", "RETURNED"}:
            ledger.observe(delivery_id="reload-delivery-1", work_id="rcc-work",
                           event=DeliveryEvent.WORKER_REPLY_CAPTURED,
                           response_sha256="b" * 64, response_length=5)
        if state == "RETURNED":
            ledger.observe(delivery_id="reload-delivery-1", work_id="rcc-work",
                           event=DeliveryEvent.MANAGER_TURN_CONFIRMED)
        return manager, worker

    def test_extension_reload_allows_ordinary_generating_chat(self):
        busy = self._idle_rcc_state()
        busy["state"]["endpoints"] = [
            {"tabId": 10, "conversationKey": "33333333-3333-3333-3333-333333333333",
             "generating": True},
        ]
        self.client.results = [busy, {
            "type": "host:result", "requestId": "reload-ordinary",
            "ok": True, "reloading": True,
        }]
        applied = self.call("reload-ordinary", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, applied.outcome)
        self.assertEqual(["state", "reload-extension"],
                         [call["command"] for call in self.client.calls])

    def test_extension_reload_fences_active_worker_delivery_generation(self):
        _manager, worker = self._delivery_for_reload(state="SENT_WAITING")
        busy = self._idle_rcc_state()
        busy["state"]["endpoints"] = [
            {"tabId": 10, "conversationKey": worker, "generating": True},
        ]
        self.client.result = busy
        rejected = self.call("reload-worker-delivery-generating", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.FAILED, rejected.outcome)
        self.assertEqual("RCC_RELOAD_ACTIVE_DELIVERY_GENERATING", rejected.error)
        self.assertEqual(["state"], [call["command"] for call in self.client.calls])

    def test_extension_reload_fences_active_manager_return_generation(self):
        manager, _worker = self._delivery_for_reload(state="REPLY_CAPTURED")
        busy = self._idle_rcc_state()
        busy["state"]["endpoints"] = [
            {"tabId": 10, "conversationKey": manager, "generating": True},
        ]
        self.client.result = busy
        rejected = self.call("reload-manager-delivery-generating", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.FAILED, rejected.outcome)
        self.assertEqual("RCC_RELOAD_ACTIVE_DELIVERY_GENERATING", rejected.error)

    def test_extension_reload_does_not_block_ended_delivery_or_unrelated_chat(self):
        manager, worker = self._delivery_for_reload(state="RETURNED")
        busy = self._idle_rcc_state()
        busy["state"]["endpoints"] = [
            {"tabId": 10, "conversationKey": worker, "generating": True},
            {"tabId": 11, "conversationKey": manager, "generating": True},
        ]
        self.client.results = [busy, {
            "type": "host:result", "requestId": "reload-delivery-returned",
            "ok": True, "reloading": True,
        }]
        applied = self.call("reload-delivery-returned", {
            "command": "reload-extension", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, applied.outcome)


    def test_extension_reload_does_not_bypass_running_rcc_effect(self):
        target_ref = self._fresh_window_target()
        created, _ = self.bct.operations.begin(
            principal=self.principal, work_id="rcc-work",
            operation_id="compose-still-running", capability="relay_browser",
            arguments={
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "hello",
                "timeout_s": 120,
            },
        )
        self.assertTrue(created)
        with self.assertRaisesRegex(Exception, "RCC_MAINTENANCE_ACTIVE_EXECUTION"):
            self.call("reload-during-running-effect", {
                "command": "reload-extension", "instance_id": "instance123",
            })
        self.assertEqual(["state"], [call["command"] for call in self.client.calls])

    def test_active_exact_delivery_claim_blocks_maintenance_reload(self):
        created, _ = self.bct.operations.begin(
            principal=self.principal, work_id="rcc-work",
            operation_id="delivery-submit-reserved", capability="relay_browser",
            arguments={
                "command": "delivery-start", "instance_id": "instance123",
                "delivery_id": "delivery-reserved",
                "manager_conversation_key": "11111111-1111-1111-1111-111111111111",
                "worker_conversation_key": "22222222-2222-2222-2222-222222222222",
                "text": "bounded worker task",
            },
        )
        self.assertTrue(created)
        with self.assertRaisesRegex(Exception, "RCC_MAINTENANCE_ACTIVE_EXECUTION"):
            self.call("reload-during-delivery-reservation", {
                "command": "reload-extension", "instance_id": "instance123",
            })
        self.assertEqual([], self.client.calls)

    def test_exact_delivery_cannot_start_during_reserved_reload(self):
        created, _ = self.bct.operations.begin(
            principal=self.principal, work_id="rcc-work",
            operation_id="reload-maintenance-reserved", capability="relay_browser",
            arguments={"command": "reload-extension", "instance_id": "instance123"},
        )
        self.assertTrue(created)
        with self.assertRaisesRegex(Exception, "RCC_MAINTENANCE_IN_PROGRESS"):
            self.call("delivery-during-maintenance", {
                "command": "delivery-start", "instance_id": "instance123",
                "delivery_id": "delivery-during-maintenance",
                "manager_conversation_key": "11111111-1111-1111-1111-111111111111",
                "worker_conversation_key": "22222222-2222-2222-2222-222222222222",
                "text": "must not be submitted",
            })
        self.assertEqual([], self.client.calls)

    def test_rcc_effect_does_not_start_during_reserved_reload(self):
        created, _ = self.bct.operations.begin(
            principal=self.principal, work_id="rcc-work",
            operation_id="reload-reserved", capability="relay_browser",
            arguments={
                "command": "reload-extension", "instance_id": "instance123",
            },
        )
        self.assertTrue(created)
        target_ref = self._fresh_window_target()
        with self.assertRaisesRegex(Exception, "RCC_MAINTENANCE_IN_PROGRESS"):
            self.call("compose-during-reload", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "hello",
                "timeout_s": 120,
            })
        self.assertEqual(["state"], [call["command"] for call in self.client.calls])

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
    def _new_chat_result(operation_id: str, *, state: str = "RESULT_PERSISTED"):
        complete = state == "RESULT_PERSISTED"
        result = {
            "type": "host:result", "ok": complete,
            "command": "new-chat-send", "operationId": operation_id,
            "state": state,
            "effectState": "APPLIED_CONFIRMED" if complete else "UNKNOWN",
            "instanceId": "instance123", "sessionId": "session1",
            "tabId": 10, "windowId": 11,
            "conversationKey": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d" if complete else "",
            "textSha256": "b" * 64,
            "resultState": "RESULT_PERSISTED" if complete else "",
            "resultHash": "" if complete else "",
            "reply": "OK" if complete else "",
            "stageTiming": {"beganAt": 1, "completedAt": 2},
        }
        if complete:
            result["resultHash"] = hashlib.sha256(json.dumps([
                operation_id, "instance123", "session1", 10, 11,
                result["conversationKey"], result["textSha256"], result["reply"],
            ], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        return result

    def test_target_discovery_issues_opaque_window_and_tab_refs(self):
        self.client.target_state = self._target_state()
        discovered = self.call("target-discovery-1", {
            "command": "target-discover", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.APPLIED, discovered.outcome)
        targets = discovered.output["targets"]
        self.assertEqual({"tab", "window"}, {target["target_kind"] for target in targets})
        self.assertTrue(all(str(target["target_ref"]).startswith("rcc-target-v1.")
                            for target in targets))
        self.assertEqual(["state"], [call["command"] for call in self.client.calls])

    def test_create_and_send_rejects_raw_window_before_operation_claim(self):
        with self.assertRaisesRegex(PreconditionError, "RCC_LEGACY_NUMERIC_TARGET_REJECTED"):
            self.call("raw-window-rejected", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "window_id": 11, "text": "never send",
            })
        self.assertEqual([], self.client.calls)
        with self.assertRaises(KeyError):
            self.bct.store.get_operation_for(
                operation_id="raw-window-rejected", work_id="rcc-work", principal_id="codex",
            )

    def test_create_and_send_rejects_reference_after_session_rollover_before_claim(self):
        target_ref = self._fresh_window_target()
        self.client.target_state = self._target_state(session_id="session2")
        with self.assertRaisesRegex(PreconditionError, "RCC_TARGET_REFERENCE_SESSION_EXPIRED"):
            self.call("stale-target-rejected", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "never send",
            })
        self.assertEqual(["state"], [call["command"] for call in self.client.calls])
        with self.assertRaises(KeyError):
            self.bct.store.get_operation_for(
                operation_id="stale-target-rejected", work_id="rcc-work", principal_id="codex",
            )

    def test_create_and_send_rejects_reference_after_target_epoch_changes_before_claim(self):
        target_ref = self._fresh_window_target()
        self.client.target_state = self._target_state(tab_id=12, window_id=11)
        with self.assertRaisesRegex(PreconditionError, "RCC_TARGET_REFERENCE_EPOCH_EXPIRED"):
            self.call("epoch-target-rejected", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "never send",
            })
        self.assertEqual(["state"], [call["command"] for call in self.client.calls])

    def test_create_and_send_tab_returns_exact_terminal_result_in_one_call(self):
        self.client.result = self._new_chat_result("compose-tab")
        target_ref = self._fresh_window_target()
        first = self.call("compose-tab", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120})
        duplicate = self.call("compose-tab", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120})
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(["state", "new-chat-send", "state"], [c["command"] for c in self.client.calls])
        self.assertEqual("compose-tab", self.client.calls[1]["request_id"])
        self.assertEqual(11, self.client.calls[1]["extra"]["windowId"])
        self.assertEqual(118000, self.client.calls[1]["extra"]["responseTimeoutMs"])
        self.assertEqual("new-chat-send", first.evidence["rcc_command"])
        self.assertEqual("OK", first.output["result"]["reply"])

    def test_create_and_send_requires_exact_existing_window(self):
        target_ref = self._fresh_window_target()
        with self.assertRaisesRegex(PreconditionError, "RCC_COMPOSE_MODE_OR_TEXT_REQUIRED"):
            self.call("compose-window", {"command": "create-and-send",
                "instance_id": "instance123", "mode": "window", "text": "hello"})
        with self.assertRaisesRegex(PreconditionError, "RCC_TARGET_REFERENCE_REQUIRED"):
            self.call("compose-no-window", {"command": "create-and-send",
                "instance_id": "instance123", "mode": "tab", "text": "hello"})
        with self.assertRaisesRegex(PreconditionError, "RCC_LEGACY_NUMERIC_TARGET_REJECTED"):
            self.call("compose-legacy-window", {"command": "create-and-send",
                "instance_id": "instance123", "mode": "tab", "window_id": 11, "text": "hello"})
        with self.assertRaisesRegex(PreconditionError, "RCC_NEW_CHAT_TIMEOUT_TOO_SHORT"):
            self.call("compose-short-timeout", {"command": "create-and-send",
                "instance_id": "instance123", "mode": "tab", "target_ref": target_ref,
                "text": "hello", "timeout_s": 29})
        self.assertEqual([], self.client.calls)

    def test_create_and_send_unknown_keeps_claim_and_never_resends(self):
        self.client.result = self._new_chat_result("compose-unknown", state="SUBMIT_UNKNOWN")
        target_ref = self._fresh_window_target()
        result = self.call("compose-unknown",{
            "command":"create-and-send","instance_id":"instance123",
            "mode":"tab","target_ref":target_ref,"text":"hello"})
        duplicate = self.call("compose-unknown",{
            "command":"create-and-send","instance_id":"instance123",
            "mode":"tab","target_ref":target_ref,"text":"hello"})
        self.assertEqual(Outcome.UNKNOWN,result.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(1,sum(c["command"]=="new-chat-send" for c in self.client.calls))
        with self.assertRaisesRegex(Exception,"compose-unknown:FINISHED:UNKNOWN"):
            self.call("compose-blocked",{"command":"create-and-send",
                          "instance_id":"instance123","mode":"tab","target_ref":target_ref,"text":"hello"})

    def _legacy_missing_instance_claim(self, operation_id="legacy-create-window"):
        self.client.result = {"type": "host:result", "ok": False}
        original = self.call(operation_id, {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual("RCC_HOST_OUTCOME_UNVERIFIED:MISSING", original.error)
        return original

    @staticmethod
    def _idle_rcc_state():
        return {
            "type": "host:result", "ok": True,
            "state": {"instanceId": "instance123", "sessionId": "session-current",
                      "endpoints": []},
        }

    @staticmethod
    def _missing_rcc_result(operation_id="legacy-create-window"):
        return {
            "type": "host:result", "ok": True, "relayId": operation_id,
            "found": False, "completed": False, "pending": False,
            "result": None, "pendingStatus": None,
        }

    def test_create_and_send_retires_only_proven_idle_legacy_instance_claim(self):
        self._legacy_missing_instance_claim()
        target_ref = self._fresh_window_target()
        self.client.results = [
            self._idle_rcc_state(), self._missing_rcc_result(),
            self._new_chat_result("compose-after-idle-proof"),
        ]
        fresh = self.call("compose-after-idle-proof", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
        })
        self.assertEqual(Outcome.APPLIED, fresh.outcome)
        self.assertEqual(
            ["create-chat-window", "state", "state", "result", "new-chat-send"],
            [call["command"] for call in self.client.calls],
        )
        original = self.bct.store.get_operation_for(
            operation_id="legacy-create-window", work_id="rcc-work",
            principal_id="codex",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual("RCC_HOST_OUTCOME_UNVERIFIED:MISSING", original.error)
        db = self.bct.store._connect()
        try:
            old_claim = db.execute(
                "SELECT COUNT(*) FROM resource_claims "
                "WHERE operation_id=? AND unresolved=1",
                ("legacy-create-window",),
            ).fetchone()[0]
            event = db.execute(
                "SELECT kind,data_json FROM events WHERE subject_id=? "
                "ORDER BY event_id DESC LIMIT 1",
                ("legacy-create-window",),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(0, old_claim)
        self.assertEqual("RCC_CLAIM_RETIRED", event[0])
        self.assertTrue(json.loads(event[1])["original_effect_unchanged"])

    def test_create_and_send_does_not_retire_when_old_rcc_result_is_pending(self):
        self._legacy_missing_instance_claim()
        target_ref = self._fresh_window_target()
        pending = self._missing_rcc_result()
        pending.update({"pending": True, "pendingStatus": {"state": "QUEUED"}})
        self.client.results = [self._idle_rcc_state(), pending]
        with self.assertRaisesRegex(Exception, "legacy-create-window:FINISHED:UNKNOWN"):
            self.call("compose-after-pending-proof", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
            })
        self.assertEqual(
            ["create-chat-window", "state", "state", "result"],
            [call["command"] for call in self.client.calls],
        )
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("legacy-create-window",),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

    def test_create_and_send_does_not_retire_on_rcc_identity_mismatch(self):
        self._legacy_missing_instance_claim()
        target_ref = self._fresh_window_target()
        wrong_state = self._idle_rcc_state()
        wrong_state["state"]["instanceId"] = "different-instance"
        self.client.results = [wrong_state, self._missing_rcc_result()]
        with self.assertRaisesRegex(Exception, "legacy-create-window:FINISHED:UNKNOWN"):
            self.call("compose-after-wrong-instance", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
            })
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?",
                ("legacy-create-window",),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

    def test_create_and_send_does_not_inspect_non_missing_unknown_claim(self):
        self.client.result = {
            "type": "host:result", "ok": False, "error": "SOME_OTHER_UNKNOWN",
        }
        original = self.call("legacy-other-unknown", {
            "command": "create-chat-window", "instance_id": "instance123",
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertNotEqual("RCC_HOST_OUTCOME_UNVERIFIED:MISSING", original.error)
        prior_calls = len(self.client.calls)
        target_ref = self._fresh_window_target()
        with self.assertRaisesRegex(Exception, "legacy-other-unknown:FINISHED:UNKNOWN"):
            self.call("compose-after-other-unknown", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
            })
        # Target freshness is read before the inherited UNKNOWN claim fence is
        # evaluated.  It is read-only; no new-chat effect was dispatched.
        self.assertEqual(prior_calls + 1, len(self.client.calls))
        self.assertEqual("state", self.client.calls[-1]["command"])

    def test_create_and_send_terminal_identity_mismatch_stays_unknown(self):
        wrong = self._new_chat_result("compose-bad-identity")
        wrong["windowId"] = 99
        self.client.result = wrong
        target_ref = self._fresh_window_target()
        result = self.call("compose-bad-identity", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello"})
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        self.assertEqual(["state", "new-chat-send"], [c["command"] for c in self.client.calls])

    def _terminal_mismatch_original(self, operation_id="handoff-terminal-mismatch"):
        wrong = self._new_chat_result(operation_id)
        wrong["windowId"] = 99
        self.client.result = wrong
        original = self.call(operation_id, {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "window_id": 11, "text": "old request", "timeout_s": 120,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.assertEqual("RCC_NEW_CHAT_TERMINAL_EVIDENCE_MISMATCH", original.error)
        return operation_id

    def _successor_work(self, *, work_id="rcc-successor", principal=None):
        principal = principal or self.principal
        self.bct.create_work(
            work_id=work_id, request_summary="independent successor",
            roots=[str(self.root)], actions=["relay_browser"], principal=principal,
        )
        return principal

    def _call_successor(self, operation_id, arguments, *, work_id="rcc-successor", principal=None):
        return self.bct.operations.run(
            principal=principal or self.principal, work_id=work_id,
            operation_id=operation_id, capability="relay_browser", arguments=arguments,
        )

    def test_same_principal_successor_retires_exact_terminal_mismatch_claim_after_idle_proof(self):
        original_id = self._terminal_mismatch_original()
        self._successor_work()
        self.client.results = [
            self._idle_rcc_state(), self._missing_rcc_result(original_id),
            self._new_chat_result("successor-independent"),
        ]
        successor = self._call_successor("successor-independent", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "window_id": 11, "text": "new independent request", "timeout_s": 120,
            "predecessor_work_id": "rcc-work", "predecessor_operation_id": original_id,
        })
        self.assertEqual(Outcome.APPLIED, successor.outcome)
        self.assertEqual(
            ["new-chat-send", "state", "result", "new-chat-send"],
            [call["command"] for call in self.client.calls],
        )
        db = self.bct.store._connect()
        try:
            old_claim = db.execute(
                "SELECT COUNT(*) FROM resource_claims WHERE operation_id=? AND unresolved=1",
                (original_id,),
            ).fetchone()[0]
            original = db.execute(
                "SELECT outcome FROM operations WHERE operation_id=?", (original_id,)
            ).fetchone()[0]
            event = db.execute(
                "SELECT kind,data_json FROM events WHERE subject_id=? ORDER BY event_id DESC LIMIT 1",
                (original_id,),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(0, old_claim)
        self.assertEqual("UNKNOWN", original)
        self.assertEqual("RCC_CLAIM_RETIRED", event[0])
        audit = json.loads(event[1])
        self.assertEqual("successor-independent", audit["new_operation_id"])
        self.assertEqual("rcc-successor", audit["successor_work_id"])
        self.assertTrue(audit["same_principal_verified"])
        self.assertEqual("TERMINAL_OPERATION_RCC_NO_PENDING_RECORD_EFFECT_UNKNOWN", audit["reason"])
        self.assertTrue(audit["no_resend_original"])

    def test_terminal_mismatch_handoff_rejects_foreign_principal_without_probe_or_release(self):
        original_id = self._terminal_mismatch_original()
        foreign = Principal("foreign", "test", frozenset({"relay_browser"}))
        self._successor_work(principal=foreign)
        calls_before = len(self.client.calls)
        with self.assertRaisesRegex(Exception, "RESOURCE_ALREADY_CLAIMED:FOREIGN_WORK"):
            self._call_successor("foreign-independent", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "window_id": 11, "text": "new independent request", "timeout_s": 120,
                "predecessor_work_id": "rcc-work", "predecessor_operation_id": original_id,
            }, principal=foreign)
        self.assertEqual(calls_before, len(self.client.calls))
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?", (original_id,)
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

    def test_terminal_mismatch_handoff_keeps_claim_when_rcc_reports_pending(self):
        original_id = self._terminal_mismatch_original()
        self._successor_work()
        pending = self._missing_rcc_result(original_id)
        pending.update({"pending": True, "pendingStatus": {"state": "QUEUED"}})
        self.client.results = [self._idle_rcc_state(), pending]
        with self.assertRaisesRegex(Exception, "RESOURCE_ALREADY_CLAIMED:FOREIGN_WORK"):
            self._call_successor("successor-pending", {
                "command": "create-and-send", "instance_id": "instance123",
                "mode": "tab", "window_id": 11, "text": "new independent request", "timeout_s": 120,
                "predecessor_work_id": "rcc-work", "predecessor_operation_id": original_id,
            })
        self.assertEqual(
            ["new-chat-send", "state", "result"],
            [call["command"] for call in self.client.calls],
        )
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims WHERE operation_id=?", (original_id,)
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

    def test_new_chat_unknown_reconciles_exact_persisted_receipt_without_resend(self):
        wrong = self._new_chat_result("compose-reconcile")
        wrong["windowId"] = 99
        target_ref = self._fresh_window_target()
        original = self.call("compose-reconcile", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        receipt = self._new_chat_result("compose-reconcile")
        self.client.result = {
            "type": "host:result", "ok": True, "relayId": "compose-reconcile",
            "found": True, "completed": True, "pending": False,
            "result": receipt,
        }
        reconciled = self.call("compose-reconcile-readback", {
            "command": "reconcile-create-and-send", "instance_id": "instance123",
            "relay_id": "compose-reconcile",
        })
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        self.assertTrue(reconciled.evidence["no_resend"])
        self.assertEqual(receipt["resultHash"], reconciled.evidence["result_hash"])
        self.assertEqual(1, sum(
            call["command"] == "new-chat-send" for call in self.client.calls
        ))
        self.assertEqual("result", self.client.calls[-1]["command"])
        self.assertEqual("compose-reconcile", self.client.calls[-1]["text"])
        original_after = self.bct.store.get_operation_for(
            operation_id="compose-reconcile", work_id="rcc-work", principal_id="codex",
        )
        self.assertEqual(Outcome.UNKNOWN, original_after.outcome)
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims "
                "WHERE operation_id='compose-reconcile'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(0, unresolved)

    def test_new_chat_tampered_receipt_keeps_unknown_claim(self):
        wrong = self._new_chat_result("compose-tampered")
        wrong["windowId"] = 99
        target_ref = self._fresh_window_target()
        original = self.call("compose-tampered", {
            "command": "create-and-send", "instance_id": "instance123",
            "mode": "tab", "target_ref": target_ref, "text": "hello", "timeout_s": 120,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        receipt = self._new_chat_result("compose-tampered")
        receipt["reply"] = "tampered"
        self.client.result = {
            "type": "host:result", "ok": True, "relayId": "compose-tampered",
            "found": True, "completed": True, "pending": False,
            "result": receipt,
        }
        rejected = self.call("compose-tampered-readback", {
            "command": "reconcile-create-and-send", "instance_id": "instance123",
            "relay_id": "compose-tampered",
        })
        self.assertEqual(Outcome.FAILED, rejected.outcome)
        self.assertEqual("RCC_NEW_CHAT_RECEIPT_NOT_PROVEN", rejected.error)
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT unresolved FROM resource_claims "
                "WHERE operation_id='compose-tampered'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, unresolved)

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

    def test_terminal_rename_unknown_is_history_not_a_conversation_lock(self):
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
        third = self.call("unknown-duplicate-target", {
            "command": "rename-conversation", "instance_id": "instance123",
            "session_id": "original-session", "tab_id": 114,
            "conversation_key": "conv-abc", "title": "다시 변경",
        })
        self.assertEqual(Outcome.UNKNOWN, third.outcome)
        original = self.bct.store.get_operation_for(
            operation_id="unknown-first", work_id="rcc-work",
            principal_id="codex",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        db = self.bct.store._connect()
        try:
            claims = [tuple(x) for x in db.execute(
                "SELECT operation_id,resource_key FROM resource_claims "
                "WHERE unresolved=1 ORDER BY operation_id")]
        finally:
            db.close()
        self.assertEqual(
            {"unknown-duplicate-target", "unknown-other"},
            {item[0] for item in claims},
        )
        self.assertTrue(all(":rename:" in item[1] for item in claims))

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


    def test_direct_tab_result_read_scoped_to_successful_original(self):
        direct_id = "direct-tab-first-accepted"
        self.client.result = {
            "type": "host:result", "ok": True, "state": "SUBMITTED",
            "submitted": True, "ambiguous": False, "operationId": direct_id,
            "instanceId": "instance123", "sessionId": "a" * 32,
            "tabId": 10, "windowId": 11,
            "conversationKey": "6ad5b191-947c-83ee-8dae-b9c867af9026",
        }
        original = self.call(direct_id, {
            "command": "send-to-tab", "instance_id": "instance123",
            "session_id": "a" * 32, "tab_id": 10, "window_id": 11,
            "conversation_key": "", "text": "bounded isolated test",
        })
        self.assertEqual(Outcome.APPLIED, original.outcome)
        self.assertEqual("send-to-tab", original.evidence["command"])
        self.client.result = {
            "type": "host:result", "ok": True, "relayId": direct_id,
            "found": True, "completed": True, "pending": False,
            "result": {
                "id": direct_id, "ok": True,
                "reply": "BCT_DIRECT_TEST_20261019_OK",
                "resultState": "RESULT_PERSISTED",
            },
        }
        read = self.call("direct-tab-result-once", {
            "command": "result", "instance_id": "instance123",
            "relay_id": direct_id,
        })
        self.assertEqual(Outcome.APPLIED, read.outcome)
        self.assertEqual(
            "BCT_DIRECT_TEST_20261019_OK",
            read.output["result"]["result"]["reply"],
        )
        self.assertEqual("result", self.client.calls[-1]["command"])
        self.assertEqual(direct_id, self.client.calls[-1]["text"])
        self.assertTrue(self.call("direct-tab-result-once", {
            "command": "result", "instance_id": "instance123",
            "relay_id": direct_id,
        }).duplicate)

        with self.assertRaisesRegex(PreconditionError, "RCC_RESULT_INSTANCE_MISMATCH"):
            self.call("direct-tab-result-wrong-instance", {
                "command": "result", "instance_id": "otherinstance",
                "relay_id": direct_id,
            })
        self.call("direct-tab-unrelated-state", {
            "command": "state", "instance_id": "instance123",
        })
        with self.assertRaisesRegex(PreconditionError, "RCC_RESULT_ORIGINAL_SEND_REQUIRED"):
            self.call("direct-tab-result-nonsend-original", {
                "command": "result", "instance_id": "instance123",
                "relay_id": "direct-tab-unrelated-state",
            })

        self.bct.create_work(
            work_id="other-direct-tab-work", request_summary="strict owner",
            roots=[str(self.root)], actions=["relay_browser"],
            principal=self.principal,
        )
        with self.assertRaisesRegex(Exception, "OPERATION_RESULT_ACCESS_DENIED"):
            self.bct.operations.run(
                principal=self.principal, work_id="other-direct-tab-work",
                operation_id="direct-tab-cross-work-denied",
                capability="relay_browser",
                arguments={
                    "command": "result", "instance_id": "instance123",
                    "relay_id": direct_id,
                },
            )

    def test_direct_tab_result_read_rejects_not_applied_original(self):
        self.client.result = {
            "type": "host:result", "ok": False, "state": "NOT_APPLIED",
            "effectState": "NOT_APPLIED", "submitted": False,
            "ambiguous": False, "error": "DIRECT_TAB_IDENTITY_MISMATCH",
        }
        original = self.call("direct-tab-rejected", {
            "command": "send-to-tab", "instance_id": "instance123",
            "session_id": "a" * 32, "tab_id": 10, "window_id": 11,
            "conversation_key": "", "text": "bounded isolated test",
        })
        self.assertEqual(Outcome.NOT_APPLIED, original.outcome)
        with self.assertRaisesRegex(PreconditionError, "RCC_RESULT_ORIGINAL_SEND_REQUIRED"):
            self.call("direct-tab-no-result-on-rejection", {
                "command": "result", "instance_id": "instance123",
                "relay_id": "direct-tab-rejected",
            })

if __name__ == "__main__":
    unittest.main()
