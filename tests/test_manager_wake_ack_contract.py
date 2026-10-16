from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import ConflictError, Outcome, Principal
from bct.features.orchestration import OrchestrationFeature
from bct.integrations.rcc import RelayEffectUnknown


ASSIGNMENT_START = "[BCT_ORCHESTRATION_ASSIGNMENT_V1]"
ASSIGNMENT_END = "[/BCT_ORCHESTRATION_ASSIGNMENT_V1]"
RESULT_START = "[BCT_ORCHESTRATION_RESULT_V1]"
RESULT_END = "[/BCT_ORCHESTRATION_RESULT_V1]"
WAKE_V1_START = "[BCT_ORCHESTRATION_MANAGER_WAKE_V1]"
WAKE_V1_END = "[/BCT_ORCHESTRATION_MANAGER_WAKE_V1]"
WAKE_V2_START = "[BCT_ORCHESTRATION_MANAGER_WAKE_V2]"
WAKE_V2_END = "[/BCT_ORCHESTRATION_MANAGER_WAKE_V2]"


class WakeRelay:
    def __init__(self):
        self.instance_id = "instance123"
        self.session_id = "session123"
        self.bindings: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.results: dict[str, dict] = {}
        self.wake_outcomes: list[str] = []
        self.endpoints = [
            self.endpoint(101, "conversation-a", "Manager"),
            self.endpoint(201, "conversation-b", "Worker"),
            self.endpoint(301, "conversation-c", "Backup manager"),
        ]

    @staticmethod
    def endpoint(tab: int, key: str, title: str) -> dict:
        return {
            "tabId": tab, "windowId": tab, "conversationKey": key,
            "title": title, "url": f"https://chatgpt.com/c/{key}",
            "presence": "OPEN", "observedAt": 1000 + tab,
        }

    def request(
        self, *, instance_id, request_id, command, to="", text="",
        extra=None, timeout_s=30,
    ):
        del timeout_s
        extra = dict(extra or {})
        self.calls.append({
            "instance_id": instance_id, "request_id": request_id,
            "command": command, "to": to, "text": text, "extra": extra,
        })
        if command == "state":
            registrations = {
                role: {
                    key: value for key, value in binding.items()
                    if key != "instanceId"
                } | {"transportInstanceId": binding["instanceId"]}
                for role, binding in self.bindings.items()
            }
            return {"ok": True, "state": {
                "instanceId": self.instance_id, "sessionId": self.session_id,
                "endpoints": self.endpoints, "tabs": [],
                "registrations": registrations,
            }}
        if command == "conversation-bind":
            binding = {
                "logicalNode": to,
                "conversationKey": extra["conversationKey"],
                "instanceId": instance_id,
                "sessionId": extra["sessionId"],
                "tabId": extra["tabId"],
                "bindingReceiptId": extra["bindingReceiptId"],
            }
            self.bindings[to] = dict(binding)
            return {"ok": True, "binding": binding}
        if command == "send":
            start = text.index(ASSIGNMENT_START) + len(ASSIGNMENT_START)
            end = text.index(ASSIGNMENT_END, start)
            assignment = json.loads(text[start:end])
            reply = RESULT_START + json.dumps({
                "schema": 1,
                "session_id": assignment["session_id"],
                "assignment_id": assignment["assignment_id"],
                "assignment_generation": assignment["assignment_generation"],
                "request_digest": assignment["request_digest"],
                "result_nonce": assignment["result_nonce"],
                "status": "SUCCEEDED", "summary": "completed",
            }, sort_keys=True) + RESULT_END
            self.results[request_id] = {
                "id": request_id, "reply": reply, "resultHash": "a" * 64,
                "ok": True, "ambiguous": False,
                "resultState": "RESULT_PERSISTED",
                "messageHash": extra.get("messageHash", ""),
                "targetBindingReceipt": extra.get("bindingReceiptId", ""),
                "instanceId": extra.get("expectedInstanceId", ""),
                "sessionId": extra.get("expectedSessionId", ""),
                "tabId": extra.get("expectedTabId"),
                "conversationKey": extra.get("expectedConversationKey", ""),
                "attachmentGeneration": extra.get("attachmentGeneration"),
                "fingerprint": json.dumps([
                    to, text, False, "", extra.get("bindingReceiptId", ""),
                    extra.get("messageHash", ""),
                    extra.get("expectedInstanceId", ""),
                    extra.get("expectedSessionId", ""),
                    extra.get("expectedTabId", 0),
                    extra.get("expectedConversationKey", ""),
                    extra.get("attachmentGeneration", 0),
                ], ensure_ascii=False, separators=(",", ":")),
            }
            return {"ok": True, "reply": reply, "resultHash": "a" * 64}
        if command == "result":
            stored = self.results.get(text)
            return {
                "ok": True, "found": stored is not None,
                "completed": stored is not None, "pending": False,
                "result": stored,
            }
        if command == "send-wakeback":
            outcome = self.wake_outcomes.pop(0) if self.wake_outcomes else "DELIVERED"
            if outcome == "UNKNOWN":
                raise RelayEffectUnknown("wake response lost")
            if outcome == "PENDING":
                return {
                    "type": "host:ack", "ok": True, "submitted": False,
                    "deferred": True, "effectState": "QUEUED",
                }
            return {
                "type": "host:ack", "ok": True, "submitted": True,
                "deferred": False, "effectState": "SUBMITTED",
            }
        raise AssertionError(command)


class ManagerWakeAckContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["read","write","orchestrate"]\n'
            'approval_actions=[]\n', encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.owner = Principal(
            "owner", "test", frozenset({"read", "write", "orchestrate"})
        )
        self.bct.create_work(
            work_id="work", request_summary="manager wake receipt contract",
            roots=[str(self.root)], actions=["read", "write", "orchestrate"],
            principal=self.owner,
        )
        self.relay = WakeRelay()
        self.bct.operations._features["orchestrate"] = OrchestrationFeature(
            self.bct.orchestration, self.relay
        )
        self.call("start", {
            "operation": "session-start", "session_id": "session",
            "objective": "prove receipt-only manager wake fencing",
            "acceptance": {"atomic": True},
        })
        self.call("sync", {
            "operation": "node-sync", "session_id": "session",
            "instance_id": self.relay.instance_id,
            "nodes": [
                {"conversation_key": "conversation-a", "node_id": "manager",
                 "name": "Manager", "role": "MANAGER", "relay_role": "BCT_MGR"},
                {"conversation_key": "conversation-b", "node_id": "worker",
                 "name": "Worker", "role": "WORKER", "relay_role": "BCT_W1"},
                {"conversation_key": "conversation-c", "node_id": "backup",
                 "name": "Backup", "role": "MANAGER", "relay_role": "BCT_MGR2"},
            ],
        })
        self.call("manager", {
            "operation": "manager-takeover", "session_id": "session",
            "expected_manager_epoch": 0, "manager_node_id": "manager",
            "reason": "initial manager",
        })

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation_id: str, arguments: dict):
        return self.bct.operations.run(
            principal=self.owner, work_id="work", operation_id=operation_id,
            capability="orchestrate", arguments=arguments,
        )

    def attachment(self, node_id: str) -> dict:
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        return next(
            item for item in snapshot["attachments"]
            if item["node_id"] == node_id and item["active"] and item["relay_role"]
        )

    def dispatch(self, operation_id: str = "dispatch"):
        worker = self.attachment("worker")
        result = self.call(operation_id, {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": operation_id + "-assignment",
            "worker_node_id": "worker", "attachment_id": worker["attachment_id"],
            "instruction": "return one durable result", "acceptance": {"ok": True},
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        return result

    def wake_calls(self) -> list[dict]:
        return [call for call in self.relay.calls if call["command"] == "send-wakeback"]

    @staticmethod
    def envelope(call: dict) -> dict:
        text = call["text"]
        if WAKE_V2_START in text:
            start, end = WAKE_V2_START, WAKE_V2_END
        else:
            start, end = WAKE_V1_START, WAKE_V1_END
        return json.loads(text.split(start, 1)[1].split(end, 1)[0])

    def first_wake(self) -> dict:
        return self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )["manager_wakes"][0]

    def test_new_wake_is_receipt_only_and_submit_is_not_manager_ack(self):
        result = self.dispatch()
        call = self.wake_calls()[0]
        envelope = self.envelope(call)
        wake = self.first_wake()
        self.assertEqual(2, envelope["schema"])
        self.assertEqual("RCC_RESULT_POLL_V1", envelope["receipt_mode"])
        self.assertNotIn("consume_capability", envelope)
        self.assertEqual("", call["extra"]["returnTo"])
        self.assertTrue(call["extra"]["returnOnAck"])
        self.assertEqual("DELIVERED", wake["state"])
        self.assertEqual(2, wake["envelope_schema"])
        self.assertEqual("RCC_RESULT_POLL_V1", wake["receipt_mode"])
        self.assertIsNone(wake["acknowledged_at"])
        self.assertNotIn("consume_capability", json.dumps(result.output))

    def test_confirmed_non_submit_reuses_exact_delivery_and_envelope(self):
        self.relay.wake_outcomes.extend(["PENDING", "DELIVERED"])
        self.dispatch()
        first = self.wake_calls()[0]
        wake = self.first_wake()
        self.assertEqual("PENDING", wake["state"])
        retried = self.call("retry-wake", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertEqual(Outcome.APPLIED, retried.outcome)
        second = self.wake_calls()[1]
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(first["text"], second["text"])
        self.assertEqual("", second["extra"]["returnTo"])

    def test_legacy_schema_one_retry_keeps_original_return_path(self):
        self.relay.wake_outcomes.append("PENDING")
        self.dispatch()
        wake = self.first_wake()
        with self.bct.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_manager_wakes SET envelope_schema=1,"
                "receipt_mode='LEGACY_RETURN_V1' WHERE event_id=?",
                (wake["event_id"],),
            )
        self.relay.wake_outcomes.append("DELIVERED")
        self.call("legacy-retry", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        call = self.wake_calls()[-1]
        envelope = self.envelope(call)
        self.assertEqual(1, envelope["schema"])
        self.assertNotIn("attachment_id", envelope)
        self.assertEqual("BCT_MGR", call["extra"]["returnTo"])
        expected_id = "orch.wake." + hashlib.sha256(
            wake["event_id"].encode("utf-8")
        ).hexdigest()[:32]
        self.assertEqual(expected_id, call["request_id"])

    def test_unknown_wake_is_never_resent(self):
        self.relay.wake_outcomes.append("UNKNOWN")
        self.dispatch()
        wake = self.first_wake()
        self.assertEqual("UNKNOWN", wake["state"])
        retried = self.call("unknown-retry", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertNotEqual(Outcome.APPLIED, retried.outcome)
        self.assertEqual(1, len(self.wake_calls()))

    def test_unknown_schema_and_mode_fail_closed_before_resend(self):
        self.relay.wake_outcomes.append("PENDING")
        self.dispatch()
        wake = self.first_wake()
        for schema, mode in ((3, "RCC_RESULT_POLL_V1"), (2, "UNKNOWN")):
            with self.subTest(schema=schema, mode=mode):
                with self.bct.store.transaction() as db:
                    db.execute(
                        "UPDATE orchestration_manager_wakes SET envelope_schema=?,"
                        "receipt_mode=? WHERE event_id=?",
                        (schema, mode, wake["event_id"]),
                    )
                with self.assertRaises(ConflictError):
                    self.bct.orchestration.claim_manager_wake(
                        work=self.bct.store.get_work("work"), session_id="session",
                        event_id=wake["event_id"], manager_epoch=1,
                        delivery_id=wake["delivery_id"],
                    )
        self.assertEqual(1, len(self.wake_calls()))

    def test_stale_work_object_after_handoff_cannot_claim(self):
        self.relay.wake_outcomes.append("PENDING")
        self.dispatch()
        wake = self.first_wake()
        stale = self.bct.store.get_work("work")
        self.bct.store.handoff_work(
            work_id="work", old_principal_id="owner",
            new_principal_id="next-owner", expected_epoch=1,
        )
        with self.assertRaises(ConflictError):
            self.bct.orchestration.claim_manager_wake(
                work=stale, session_id="session", event_id=wake["event_id"],
                manager_epoch=1, delivery_id=wake["delivery_id"],
            )

    def test_upgrade_defaults_existing_wakes_to_schema_one_without_backfill(self):
        db = self.bct.store._connect()
        try:
            self.assertEqual([], db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='orchestration_manager_wake_capabilities'"
            ).fetchall())
            columns = {
                row["name"]: row for row in db.execute(
                    "PRAGMA table_info(orchestration_manager_wakes)"
                ).fetchall()
            }
        finally:
            db.close()
        self.assertEqual("1", str(columns["envelope_schema"]["dflt_value"]))
        self.assertIn("LEGACY_RETURN_V1", columns["receipt_mode"]["dflt_value"])

    def test_legacy_schema_migration_preserves_acknowledged_at(self):
        self.dispatch()
        wake = self.first_wake()
        with self.bct.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_manager_wakes SET acknowledged_at=123.0 "
                "WHERE event_id=?", (wake["event_id"],),
            )
            db.execute(
                "ALTER TABLE orchestration_manager_wakes DROP COLUMN receipt_mode"
            )
            db.execute(
                "ALTER TABLE orchestration_manager_wakes DROP COLUMN envelope_schema"
            )
        reopened = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        row = reopened.orchestration.snapshot(
            work=reopened.store.get_work("work"), session_id="session"
        )["manager_wakes"][0]
        self.assertEqual(123.0, row["acknowledged_at"])
        self.assertEqual(1, row["envelope_schema"])
        self.assertEqual("LEGACY_RETURN_V1", row["receipt_mode"])


if __name__ == "__main__":
    unittest.main()
