from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import (
    ConflictError, FeatureRequest, Outcome, PreconditionError, Principal,
)
from bct.features.orchestration import OrchestrationFeature, _canonical, _hash
from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable


RESULT_START = "[BCT_ORCHESTRATION_RESULT_V1]"
RESULT_END = "[/BCT_ORCHESTRATION_RESULT_V1]"
ASSIGNMENT_START = "[BCT_ORCHESTRATION_ASSIGNMENT_V1]"
ASSIGNMENT_END = "[/BCT_ORCHESTRATION_ASSIGNMENT_V1]"


class FakeRelay:
    def __init__(self):
        self.instance_id = "instance123"
        self.session_id = "session123"
        self.bindings = {}
        self.calls = []
        self.results = {}
        self.fail_send_once = set()
        self.hide_results = False
        self.lose_send_response = False
        self.return_submit_ack = False
        self.confirmed_not_applied = set()
        self.defer_wake_once = set()
        self.unknown_wake_once = set()
        self.result_mutator = None
        self.recover_pending_enabled = False
        self.recover_pending_calls = 0
        self.endpoints = [
            self.endpoint(101, 10, "conversation-a", "Manager"),
            self.endpoint(102, 10, "conversation-a", "Manager duplicate"),
            self.endpoint(201, 20, "conversation-b", "Worker B"),
            self.endpoint(301, 30, "conversation-c", "Worker C"),
            self.endpoint(401, 40, "conversation-d", "Backup manager"),
        ]

    @staticmethod
    def endpoint(tab, window, key, title):
        return {
            "tabId": tab, "windowId": window, "conversationKey": key,
            "title": title, "url": f"https://chatgpt.com/c/{key}",
            "presence": "OPEN", "observedAt": 1000 + tab,
        }

    def request(
        self, *, instance_id, request_id, command, to="", text="",
        extra=None, timeout_s=30,
    ):
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
            return {
                "ok": True,
                "state": {
                    "instanceId": self.instance_id,
                    "sessionId": self.session_id,
                    "endpoints": self.endpoints,
                    "tabs": [],
                    "registrations": registrations,
                },
            }
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
        if command == "send-wakeback":
            binding = self.bindings[to]
            if extra.get("bindingReceiptId") != binding["bindingReceiptId"]:
                return {"ok": False, "effectState": "NOT_APPLIED"}
            if to in self.unknown_wake_once:
                self.unknown_wake_once.remove(to)
                raise RelayEffectUnknown("wake acknowledgement was lost")
            if to in self.defer_wake_once:
                self.defer_wake_once.remove(to)
                return {"type": "host:ack", "ok": True, "submitted": False,
                        "deferred": True, "effectState": "QUEUED"}
            return {"type": "host:ack", "ok": True, "submitted": True,
                    "deferred": False, "effectState": "SUBMITTED"}
        if command == "send":
            if to in self.fail_send_once:
                self.fail_send_once.remove(to)
                raise RelayUnavailable("relay unavailable before dispatch")
            if to in self.confirmed_not_applied:
                self.confirmed_not_applied.remove(to)
                return {
                    "type": "host:result", "ok": False,
                    "effectState": "NOT_APPLIED",
                    "error": "RCC_PRE_SUBMIT_LEASE_CONFLICT",
                }
            binding = self.bindings[to]
            if extra.get("bindingReceiptId") != binding["bindingReceiptId"]:
                return {"ok": False, "error": "TARGET_BINDING_RECEIPT_MISMATCH"}
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
                "status": "SUCCEEDED",
                "summary": f"completed by {to}",
            }, sort_keys=True) + RESULT_END
            stored = {
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
            self.results[request_id] = stored
            if self.lose_send_response:
                raise RelayEffectUnknown("response lost after dispatch")
            if self.return_submit_ack:
                return {
                    "type": "host:ack", "ok": True,
                    "submitted": True, "deferred": False,
                    "effectState": "SUBMITTED",
                }
            return {
                "ok": True, "reply": reply,
                "resultHash": "a" * 64,
            }
        if command == "recover-pending":
            self.recover_pending_calls += 1
            if not self.recover_pending_enabled or text not in self.results:
                return {"ok": False, "error": "RELAY_RECOVERY_RESULT_NOT_CAPTURE_ERROR"}
            self.result_mutator = None
            return {
                "ok": True, "relayId": text, "recovered": True,
                "persistedResult": True, "returnState": "NOT_REQUESTED",
                "receiverAckState": "NOT_REQUESTED",
            }
        if command == "result":
            stored = None if self.hide_results else self.results.get(text)
            if stored is not None and self.result_mutator is not None:
                stored = self.result_mutator(dict(stored))
            return {
                "ok": True, "found": stored is not None,
                "completed": stored is not None, "pending": False,
                "result": stored,
            }
        raise AssertionError(command)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["read","write","test","orchestrate"]\n'
            'approval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(
            state_path=self.root / "state.sqlite", policy_path=self.policy
        )
        self.owner = Principal(
            "owner", "test", frozenset({"read", "write", "test", "orchestrate"})
        )
        self.bct.create_work(
            work_id="work", request_summary="orchestration tests",
            roots=[str(self.root)], actions=["read", "write", "test", "orchestrate"],
            principal=self.owner,
        )
        self.relay = FakeRelay()
        self.bct.operations._features["orchestrate"] = OrchestrationFeature(
            self.bct.orchestration, self.relay
        )
        self.call("start", {
            "operation": "session-start", "session_id": "session",
            "objective": "complete a durable manager worker chain",
            "acceptance": {"result": "verified"},
        })
        self.call("sync", {
            "operation": "node-sync", "session_id": "session",
            "instance_id": self.relay.instance_id,
            "nodes": [
                {"conversation_key": "conversation-a", "node_id": "manager",
                 "name": "Manager", "role": "MANAGER", "relay_role": "BCT_MGR"},
                {"conversation_key": "conversation-b", "node_id": "worker-b",
                 "name": "Worker B", "role": "WORKER", "relay_role": "BCT_W1"},
                {"conversation_key": "conversation-c", "node_id": "worker-c",
                 "name": "Worker C", "role": "WORKER", "relay_role": "BCT_W2"},
                {"conversation_key": "conversation-d", "node_id": "backup",
                 "name": "Backup", "role": "MANAGER", "relay_role": "BCT_MGR2"},
            ],
        })
        self.call("manager", {
            "operation": "manager-takeover", "session_id": "session",
            "expected_manager_epoch": 0, "manager_node_id": "manager",
            "reason": "initial manager selection",
        })

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation_id, arguments):
        return self.bct.operations.run(
            principal=self.owner, work_id="work", operation_id=operation_id,
            capability="orchestrate", arguments=arguments,
        )

    def attachment(self, node_id):
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        return next(
            item for item in snapshot["attachments"]
            if item["node_id"] == node_id and item["active"] and item["relay_role"]
        )

    def test_trusted_worker_can_receive_project_scoped_write_work(self):
        worker = self.attachment("worker-b")
        result = self.call("write-assignment", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "write-assignment",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "edit one project file and report the test result",
            "actions": ["read", "write", "test"],
            "acceptance": {"tested": True},
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(
            ["read", "test", "write"],
            result.output["assignment"]["actions"],
        )

    def test_duplicate_tabs_map_to_one_node_and_immutable_attachments(self):
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        manager = [
            item for item in snapshot["attachments"]
            if item["node_id"] == "manager"
        ]
        self.assertEqual(2, len(manager))
        self.assertEqual({101, 102}, {item["tab_id"] for item in manager})
        self.assertEqual(1, sum(bool(item["relay_role"]) for item in manager))

    def test_node_sync_conflict_is_rejected_before_rcc_binding(self):
        self.call("preflight-start", {
            "operation": "session-start", "session_id": "preflight-session",
            "objective": "prove node-sync ownership before RCC mutation",
            "acceptance": {"no_partial_binding": True},
        })
        before = len([
            item for item in self.relay.calls
            if item["command"] == "conversation-bind"
        ])
        result = self.call("preflight-conflict", {
            "operation": "node-sync", "session_id": "preflight-session",
            "instance_id": self.relay.instance_id,
            "nodes": [{
                "conversation_key": "conversation-b",
                "node_id": "different-worker",
                "name": "Different worker",
                "role": "WORKER",
                "relay_role": "BCT_W1",
            }],
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        after = len([
            item for item in self.relay.calls
            if item["command"] == "conversation-bind"
        ])
        self.assertEqual(before, after)
        self.assertFalse(any(
            claim["operation_id"] == "preflight-conflict"
            for claim in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))

    def test_legacy_node_sync_unknown_restores_binding_before_claim_release(self):
        self.call("legacy-sync-start", {
            "operation": "session-start", "session_id": "legacy-sync-session",
            "objective": "recover one proven partial node-sync binding",
            "acceptance": {"exact_binding_restored": True},
        })
        expected = self.attachment("worker-b")
        validate = self.bct.orchestration.validate_sync_targets
        self.bct.orchestration.validate_sync_targets = lambda **_kwargs: None
        try:
            unknown = self.call("legacy-node-sync-unknown", {
                "operation": "node-sync", "session_id": "legacy-sync-session",
                "instance_id": self.relay.instance_id,
                "nodes": [{
                    "conversation_key": "conversation-b",
                    "node_id": "legacy-different-worker",
                    "name": "Legacy different worker",
                    "role": "WORKER",
                    "relay_role": "BCT_W1",
                }],
            })
        finally:
            self.bct.orchestration.validate_sync_targets = validate
        self.assertEqual(Outcome.UNKNOWN, unknown.outcome)
        self.assertNotEqual(
            expected["binding_receipt_id"],
            self.relay.bindings["BCT_W1"]["bindingReceiptId"],
        )
        self.assertTrue(any(
            claim["operation_id"] == "legacy-node-sync-unknown"
            for claim in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))

        recovered = self.call("legacy-node-sync-recovery", {
            "operation": "recover-node-sync",
            "session_id": "legacy-sync-session",
            "original_operation_id": "legacy-node-sync-unknown",
            "instance_id": self.relay.instance_id,
            "timeout_s": 5,
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        self.assertEqual(
            expected["binding_receipt_id"],
            self.relay.bindings["BCT_W1"]["bindingReceiptId"],
        )
        original = self.bct.store.get_operation_for(
            operation_id="legacy-node-sync-unknown",
            work_id="work", principal_id=self.owner.principal_id,
        )
        self.assertEqual(Outcome.FAILED, original.outcome)
        self.assertFalse(any(
            claim["operation_id"] == "legacy-node-sync-unknown"
            for claim in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))
        self.assertFalse(any(
            item["command"] == "send" and "legacy" in item["text"]
            for item in self.relay.calls
        ))

    def test_retired_rcc_blocks_only_new_assignment_and_replacement(self):
        work = self.bct.store.get_work("work")
        worker = self.attachment("worker-b")
        other = self.attachment("worker-c")
        kwargs = dict(
            work=work, session_id="session", assignment_id="old-before-retire",
            manager_epoch=1, worker_node_id="worker-b",
            attachment_id=worker["attachment_id"],
            request={"instruction": "existing task"}, roots=[str(self.root)],
            actions=["read"], acceptance={"result": True}, dependencies=[],
        )
        created, original = self.bct.orchestration.create_assignment(**kwargs)
        self.assertTrue(created)
        self.bct.orchestration.excluded_new_assignment_instances = frozenset(
            {self.relay.instance_id}
        )
        created_again, replay = self.bct.orchestration.create_assignment(**kwargs)
        self.assertFalse(created_again)
        self.assertEqual(original["assignment_id"], replay["assignment_id"])
        with self.assertRaisesRegex(ConflictError, "RCC_RETIRED_FOR_NEW_ASSIGNMENTS"):
            self.bct.orchestration.create_assignment(
                **(kwargs | {"assignment_id": "new-after-retire"})
            )
        self.bct.orchestration.complete_assignment(
            assignment_id="old-before-retire", generation=1, outcome="NOT_APPLIED",
            result={"pre_dispatch": True, "reason": "not sent"},
            result_message_id="result.retirement.test",
        )
        with self.assertRaisesRegex(ConflictError, "RCC_RETIRED_FOR_NEW_ASSIGNMENTS"):
            self.bct.orchestration.replace_worker(
                work=work, session_id="session",
                assignment_id="old-before-retire", manager_epoch=1,
                worker_node_id="worker-c", attachment_id=other["attachment_id"],
                reason="replacement forbidden on retired instance",
            )
        self.assertEqual(
            "NOT_APPLIED", self.bct.orchestration.snapshot(
                work=work, session_id="session"
            )["assignments"][0]["state"],
        )

    def test_retired_rcc_policy_loads_on_new_service_without_rewriting_existing(self):
        with self.policy.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n[orchestration]\n"
                'excluded_new_assignment_instance_ids=["instance123"]\n'
                'require_current_session_instance_ids=["instance456"]\n'
            )
        restarted = BCT(
            state_path=self.root / "state.sqlite", policy_path=self.policy
        )
        self.assertIn(
            "instance123", restarted.orchestration.excluded_new_assignment_instances
        )
        self.assertIn(
            "instance456", restarted.orchestration.require_current_session_instances
        )
        self.assertEqual(
            self.bct.orchestration.snapshot(
                work=self.bct.store.get_work("work"), session_id="session"
            )["session"]["session_id"],
            restarted.orchestration.snapshot(
                work=restarted.store.get_work("work"), session_id="session"
            )["session"]["session_id"],
        )

    def test_same_instance_reload_retires_old_session_and_routes_only_current(self):
        before = self.attachment("worker-b")
        self.relay.session_id = "session456"
        refreshed = self.call("sync-after-same-id-reload", {
            "operation": "node-sync", "session_id": "session",
            "instance_id": self.relay.instance_id,
            "nodes": [
                {"conversation_key": "conversation-a", "node_id": "manager",
                 "name": "Manager", "role": "MANAGER", "relay_role": "BCT_MGR"},
                {"conversation_key": "conversation-b", "node_id": "worker-b",
                 "name": "Worker B", "role": "WORKER", "relay_role": "BCT_W1"},
                {"conversation_key": "conversation-c", "node_id": "worker-c",
                 "name": "Worker C", "role": "WORKER", "relay_role": "BCT_W2"},
                {"conversation_key": "conversation-d", "node_id": "backup",
                 "name": "Backup", "role": "MANAGER", "relay_role": "BCT_MGR2"},
            ],
        })
        self.assertEqual(Outcome.APPLIED, refreshed.outcome)
        self.assertTrue(refreshed.output["superseded_session_attachments"])
        after = self.attachment("worker-b")
        self.assertEqual("session456", after["external_session_id"])
        self.assertNotEqual(before["attachment_id"], after["attachment_id"])
        db = self.bct.store._connect()
        try:
            current = db.execute(
                "SELECT external_session_id FROM orchestration_rcc_instance_sessions "
                "WHERE instance_id=?", (self.relay.instance_id,),
            ).fetchone()
            old = db.execute(
                "SELECT active FROM orchestration_attachments "
                "WHERE attachment_id=? AND generation=?",
                (before["attachment_id"], before["generation"]),
            ).fetchone()
            old_connection = db.execute(
                "SELECT active FROM connections WHERE connection_id=?",
                ("orch:" + before["attachment_id"],),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual("session456", current["external_session_id"])
        self.assertFalse(old["active"])
        self.assertFalse(old_connection["active"])
        created, assignment = self.bct.orchestration.create_assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="post-reload", manager_epoch=1,
            worker_node_id="worker-b", attachment_id=after["attachment_id"],
            request={"instruction": "continue after reload"},
            roots=[str(self.root)], actions=["read"],
            acceptance={"continued": True}, dependencies=[],
        )
        self.assertTrue(created)
        self.assertEqual("QUEUED", assignment["state"])

    def test_stale_session_attachment_cannot_receive_new_assignment(self):
        stale = self.bct.orchestration.sync_attachment(
            work=self.bct.store.get_work("work"), session_id="session",
            node_id="worker-b", name="Worker B stale", role="WORKER",
            attachment_id="att-stale-session", instance_id=self.relay.instance_id,
            external_session_id="superseded-session", tab_id=999, window_id=99,
            conversation_key="conversation-b",
            endpoint="https://chatgpt.com/c/conversation-b",
            relay_role="BCT_OLD", binding_receipt_id="RCB-OLDSESSION",
        )
        with self.assertRaisesRegex(ConflictError, "ATTACHMENT_SESSION_STALE"):
            self.bct.orchestration.create_assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="stale-session-assignment", manager_epoch=1,
                worker_node_id="worker-b", attachment_id=stale["attachment_id"],
                request={"instruction": "must not route to stale session"},
                roots=[str(self.root)], actions=["read"],
                acceptance={"blocked": True}, dependencies=[],
            )

    def test_policy_fenced_instance_requires_one_current_session_observation(self):
        worker = self.attachment("worker-b")
        with self.bct.store.transaction() as db:
            db.execute(
                "DELETE FROM orchestration_rcc_instance_sessions WHERE instance_id=?",
                (self.relay.instance_id,),
            )
        self.bct.orchestration.require_current_session_instances = frozenset(
            {self.relay.instance_id}
        )
        with self.assertRaisesRegex(ConflictError, "RCC_SESSION_NOT_OBSERVED"):
            self.bct.orchestration.create_assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="unobserved-current-session", manager_epoch=1,
                worker_node_id="worker-b", attachment_id=worker["attachment_id"],
                request={"instruction": "must wait for a current node sync"},
                roots=[str(self.root)], actions=["read"],
                acceptance={"blocked": True}, dependencies=[],
            )

    def test_scope_can_narrow_but_not_widen(self):
        worker = self.attachment("worker-b")
        result = self.call("dispatch-narrow", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "narrow",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "inspect the assigned evidence",
            "acceptance": {"summary": True},
            "roots": [str(self.root)], "actions": ["read"],
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        with self.assertRaises(PreconditionError):
            self.bct.orchestration.create_assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="widen", manager_epoch=1,
                worker_node_id="worker-b",
                attachment_id=worker["attachment_id"],
                request={"instruction": "outside"}, roots=["D:\\outside"],
                actions=["read"], acceptance={}, dependencies=[],
            )

    def test_takeover_is_independent_of_unrelated_unknown_claim(self):
        from tests.test_core import UnknownFeature

        self.bct.operations._features["write"] = UnknownFeature()
        unknown = self.bct.operations.run(
            principal=self.owner, work_id="work", operation_id="unknown-write",
            capability="write", arguments={"resource": "unrelated"},
        )
        self.assertEqual(Outcome.UNKNOWN, unknown.outcome)
        takeover = self.call("takeover", {
            "operation": "manager-takeover", "session_id": "session",
            "expected_manager_epoch": 1, "manager_node_id": "backup",
            "reason": "manager unavailable",
            "evidence": {"unrelated_unknown_preserved": True},
        })
        self.assertEqual(Outcome.APPLIED, takeover.outcome)
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        self.assertEqual(2, snapshot["session"]["manager_epoch"])
        self.assertEqual("owner", self.bct.store.get_work("work").owner_principal_id)
        with self.assertRaises(ConflictError):
            self.bct.orchestration.create_assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="stale", manager_epoch=1,
                worker_node_id="worker-b",
                attachment_id=self.attachment("worker-b")["attachment_id"],
                request={"instruction": "stale"}, roots=[str(self.root)],
                actions=["read"], acceptance={}, dependencies=[],
            )

    def test_chain_runs_two_workers_takes_over_manager_and_synthesizes(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        backup = self.attachment("backup")
        result = self.call("chain", {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {
                    "assignment_id": "task-b", "worker_node_id": "worker-b",
                    "attachment_id": worker_b["attachment_id"],
                    "instruction": "find one bottleneck", "acceptance": {"one": True},
                },
                {
                    "assignment_id": "task-c", "worker_node_id": "worker-c",
                    "attachment_id": worker_c["attachment_id"],
                    "instruction": "find one improvement", "acceptance": {"one": True},
                },
            ],
            "takeover": {
                "manager_node_id": "backup", "reason": "planned failover exercise",
                "evidence": {"old_manager": "intentionally replaced"},
            },
            "synthesis": {
                "assignment_id": "synthesis", "manager_node_id": "backup",
                "attachment_id": backup["attachment_id"],
                "instruction": "synthesize the worker results",
                "acceptance": {"combined": True},
            },
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        self.assertEqual("FINISHED", snapshot["session"]["state"])
        self.assertEqual("backup", snapshot["session"]["manager_node_id"])
        self.assertEqual(2, snapshot["session"]["manager_epoch"])
        self.assertEqual(
            {"task-b": "APPLIED", "task-c": "APPLIED", "synthesis": "APPLIED"},
            {item["assignment_id"]: item["state"] for item in snapshot["assignments"]},
        )
        sends = [item for item in self.relay.calls if item["command"] == "send"]
        self.assertEqual(3, len(sends))
        self.assertEqual(3, len({item["request_id"] for item in sends}))
        consumed = [
            item for item in snapshot["mailbox"]
            if item["kind"] == "RESULT" and item["consumed_at"] is not None
        ]
        self.assertEqual(2, len(consumed))

    def test_restart_returns_identical_persisted_result_without_rcc(self):
        worker = self.attachment("worker-b")
        result = self.call("restart-result", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "restart-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "produce a durable result",
            "acceptance": {"durable": True},
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        before = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        restarted = BCT(
            state_path=self.root / "state.sqlite", policy_path=self.policy
        )
        after = restarted.orchestration.snapshot(
            work=restarted.store.get_work("work"), session_id="session"
        )
        self.assertEqual(
            before["assignments"][0]["terminal_result"],
            after["assignments"][0]["terminal_result"],
        )

    def test_worker_replacement_requires_proven_not_applied_and_fences_late_result(self):
        work = self.bct.store.get_work("work")
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        _created, assignment = self.bct.orchestration.create_assignment(
            work=work, session_id="session", assignment_id="replace-task",
            manager_epoch=1, worker_node_id="worker-b",
            attachment_id=worker_b["attachment_id"],
            request={"instruction": "produce replaceable evidence"},
            roots=[str(self.root)], actions=["read"],
            acceptance={"replacement": True}, dependencies=[],
        )
        with self.assertRaises(ConflictError):
            self.bct.orchestration.replace_worker(
                work=work, session_id="session", assignment_id="replace-task",
                manager_epoch=1, worker_node_id="worker-c",
                attachment_id=worker_c["attachment_id"], reason="too early",
            )
        self.bct.orchestration.complete_assignment(
            assignment_id="replace-task", generation=1,
            outcome="NOT_APPLIED",
            result={"pre_dispatch": True, "error": "relay unavailable"},
            result_message_id="result.replace.not-applied",
        )
        result = self.call("replace-worker", {
            "operation": "worker-replace", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "replace-task",
            "worker_node_id": "worker-c",
            "attachment_id": worker_c["attachment_id"],
            "reason": "prior attempt proven not dispatched",
            "evidence": {"source": "delivery receipt"}, "timeout_s": 30,
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        current = self.bct.orchestration.snapshot(
            work=work, session_id="session"
        )["assignments"][0]
        self.assertEqual(2, current["current_generation"])
        self.assertEqual("APPLIED", current["state"])
        self.assertEqual("worker-c", current["attempts"][-1]["worker_node_id"])
        self.bct.orchestration.record_delivery(
            assignment_id="replace-task", generation=1,
            state="ACKNOWLEDGED", evidence={"late": True},
        )
        late = self.bct.orchestration.complete_assignment(
            assignment_id="replace-task", generation=1, outcome="APPLIED",
            result={"summary": "late old worker"},
            result_message_id="result.replace.late",
        )
        self.assertEqual(2, late["current_generation"])
        self.assertEqual(current["terminal_result"], late["terminal_result"])
        self.assertEqual("APPLIED", late["state"])

    def test_chain_automatically_replaces_worker_only_after_not_applied(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        manager = self.attachment("manager")
        self.relay.fail_send_once.add("BCT_W1")
        result = self.call("chain-replacement", {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {
                    "assignment_id": "replace-in-chain",
                    "worker_node_id": "worker-b",
                    "attachment_id": worker_b["attachment_id"],
                    "instruction": "inspect one safe diagnostic",
                    "acceptance": {"diagnostic": True},
                    "replacement": {
                        "worker_node_id": "worker-c",
                        "attachment_id": worker_c["attachment_id"],
                        "reason": "first relay proved unavailable before dispatch",
                    },
                },
                {
                    "assignment_id": "second-in-chain",
                    "worker_node_id": "worker-c",
                    "attachment_id": worker_c["attachment_id"],
                    "instruction": "inspect a second safe diagnostic",
                    "acceptance": {"diagnostic": True},
                },
            ],
            "synthesis": {
                "assignment_id": "replacement-synthesis",
                "manager_node_id": "manager",
                "attachment_id": manager["attachment_id"],
                "instruction": "combine the diagnostics",
                "acceptance": {"combined": True},
            },
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        replaced = next(
            item for item in snapshot["assignments"]
            if item["assignment_id"] == "replace-in-chain"
        )
        self.assertEqual(2, replaced["current_generation"])
        self.assertEqual("worker-c", replaced["attempts"][-1]["worker_node_id"])
        self.assertEqual("APPLIED", replaced["state"])

    def test_duplicate_dispatch_returns_receipt_without_second_send(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "one-delivery",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return one durable response",
            "acceptance": {"once": True},
        }
        first = self.call("dispatch-once", arguments)
        before = len([call for call in self.relay.calls if call["command"] == "send"])
        duplicate = self.call("dispatch-once", arguments)
        after = len([call for call in self.relay.calls if call["command"] == "send"])
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(before, after)

    def test_manager_wake_is_durable_exact_and_not_duplicated(self):
        worker = self.attachment("worker-b")
        dispatched = self.call("wake-source", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "wake-source-assignment",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "produce the durable result", "acceptance": {"ok": True},
        })
        self.assertEqual(Outcome.APPLIED, dispatched.outcome)
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        self.assertEqual(1, len(snapshot["manager_wakes"]))
        wake = snapshot["manager_wakes"][0]
        self.assertEqual("DELIVERED", wake["state"])
        self.assertEqual(1, wake["manager_epoch"])
        woke = self.call("wake-manager", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertEqual(Outcome.APPLIED, woke.outcome)
        self.assertEqual("DELIVERED", woke.output["event"]["state"])
        sent = [call for call in self.relay.calls if call["command"] == "send-wakeback"]
        self.assertEqual(1, len(sent))
        self.assertEqual("BCT_MGR", sent[0]["to"])
        self.assertEqual("BCT_MGR", sent[0]["extra"]["returnTo"])
        duplicate = self.call("wake-manager", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertEqual(Outcome.APPLIED, duplicate.outcome)
        self.assertEqual(1, len([call for call in self.relay.calls if call["command"] == "send-wakeback"]))

    def test_manager_wake_fails_closed_after_manager_takeover(self):
        worker = self.attachment("worker-b")
        self.relay.defer_wake_once.add("BCT_MGR")
        self.call("stale-wake-source", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "stale-wake-source-assignment",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "produce the durable result", "acceptance": {"ok": True},
        })
        wake = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )["manager_wakes"][0]
        self.assertEqual("PENDING", wake["state"])
        self.call("takeover-before-wake", {
            "operation": "manager-takeover", "session_id": "session",
            "expected_manager_epoch": 1, "manager_node_id": "backup",
            "reason": "prove old wake cannot redirect",
        })
        wakes = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )["manager_wakes"]
        self.assertEqual(["STALE", "PENDING"], [item["state"] for item in wakes])
        fresh = wakes[1]
        self.assertEqual(2, fresh["manager_epoch"])
        resumed = self.call("wake-backup-manager", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 2, "event_id": fresh["event_id"],
        })
        self.assertEqual(Outcome.APPLIED, resumed.outcome)
        self.assertEqual("DELIVERED", resumed.output["event"]["state"])
        stale = self.call("stale-wake", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertNotEqual(Outcome.APPLIED, stale.outcome)
        sent = [call for call in self.relay.calls if call["command"] == "send-wakeback"]
        self.assertEqual(2, len(sent))
        self.assertEqual(["BCT_MGR", "BCT_MGR2"], [item["to"] for item in sent])
        self.assertEqual(
            ["BCT_MGR", "BCT_MGR2"],
            [item["extra"]["returnTo"] for item in sent],
        )

    def test_deferred_manager_wake_stays_pending_for_exact_retry(self):
        worker = self.attachment("worker-b")
        self.relay.defer_wake_once.add("BCT_MGR")
        self.call("deferred-wake-source", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "deferred-wake-source-assignment",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "produce the durable result", "acceptance": {"ok": True},
        })
        wake = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )["manager_wakes"][0]
        self.assertEqual("PENDING", wake["state"])
        retry = self.call("deferred-wake-retry", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertEqual(Outcome.APPLIED, retry.outcome)
        self.assertEqual("DELIVERED", retry.output["event"]["state"])
        sent = [call for call in self.relay.calls if call["command"] == "send-wakeback"]
        self.assertEqual(2, len(sent))
        self.assertEqual(sent[0]["request_id"], sent[1]["request_id"])

    def test_ambiguous_manager_wake_is_quarantined_without_resend(self):
        worker = self.attachment("worker-b")
        self.relay.unknown_wake_once.add("BCT_MGR")
        self.call("unknown-wake-source", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "unknown-wake-source-assignment",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "produce the durable result", "acceptance": {"ok": True},
        })
        wake = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )["manager_wakes"][0]
        self.assertEqual("UNKNOWN", wake["state"])
        retry = self.call("unknown-wake-retry", {
            "operation": "manager-wake", "session_id": "session",
            "manager_epoch": 1, "event_id": wake["event_id"],
        })
        self.assertNotEqual(Outcome.APPLIED, retry.outcome)
        self.assertEqual(1, len([call for call in self.relay.calls if call["command"] == "send-wakeback"]))

    def test_unknown_receipt_inspection_is_exact_owned_read_only(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("inspect-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "inspect-target",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "produce one exact persistent reply",
            "acceptance": {"inspect": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        a = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="inspect-target",
        )
        delivery_id = a["attempts"][-1]["dispatch_operation_id"]
        self.assertIn(delivery_id, self.relay.results)
        sends_before = len([x for x in self.relay.calls if x["command"] == "send"])
        base = {"operation": "inspect-result-receipt", "session_id": "session",
                "assignment_id": "inspect-target",
                "original_operation_id": "inspect-original",
                "delivery_id": delivery_id}
        before = self.call("receipt-inspect-missing", base)
        self.assertEqual(Outcome.APPLIED, before.outcome)
        self.assertEqual("RESULT_NOT_CONFIRMED", before.output["observation"])
        self.relay.hide_results = False
        result = self.call("receipt-inspect-found", base)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("RESULT_CANDIDATE_FOUND", result.output["observation"])
        self.assertTrue(result.output["all_identity_checks_except_prompt"])
        self.assertEqual("UNVERIFIED", result.output["receipt_origin"])
        self.assertFalse(result.output["receipt_origin_attested"])
        self.assertEqual([], result.output["missing_fields"])
        self.assertEqual([], result.output["identity_mismatches"])
        self.assertFalse(result.output["historical_prompt_verified"])
        self.assertFalse(result.output["result_promoted"])
        self.assertNotIn("reply", str(result.output))
        self.assertEqual(sends_before, len(
            [x for x in self.relay.calls if x["command"] == "send"]
        ))
        original_after = self.bct.store.get_operation_for(
            operation_id="inspect-original", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.UNKNOWN, original_after.outcome)
        self.assertEqual("UNKNOWN", self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="inspect-target",
        )["state"])
        incorrect = dict(base, delivery_id="another-delivery")
        denied = self.call("receipt-inspect-other-delivery", incorrect)
        self.assertEqual(Outcome.NOT_APPLIED, denied.outcome)
        self.assertEqual(sends_before, len(
            [x for x in self.relay.calls if x["command"] == "send"]
        ))
        wrong_owner = dict(base, original_operation_id="not-the-original")
        rejected = self.call("receipt-inspect-other-origin", wrong_owner)
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome)

    def test_unknown_receipt_inspection_reports_binding_mismatch_without_promoting(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("inspect-mismatch-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "inspect-mismatch",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "produce a receipt to independently inspect",
            "acceptance": {"inspect": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        a = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="inspect-mismatch",
        )
        delivery_id = a["attempts"][-1]["dispatch_operation_id"]
        self.relay.hide_results = False
        self.relay.result_mutator = lambda value: {
            **value, "targetBindingReceipt": "tampered"
        }
        result = self.call("receipt-inspect-mismatch", {
            "operation": "inspect-result-receipt", "session_id": "session",
            "assignment_id": "inspect-mismatch",
            "original_operation_id": "inspect-mismatch-original",
            "delivery_id": delivery_id,
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("IDENTITY_MISMATCH", result.output["observation"])
        self.assertFalse(result.output["checks"]["binding_receipt"])
        self.assertIn("binding_receipt", result.output["identity_mismatches"])
        self.assertEqual([], result.output["missing_fields"])
        self.assertFalse(result.output["all_identity_checks_except_prompt"])
        self.assertFalse(result.output["result_promoted"])

    def test_inspector_rejects_legacy_result_cache_as_incomplete_receipt(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("inspect-legacy-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "inspect-legacy",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return one original result", "acceptance": {"inspect": True},
            "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        assignment = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="inspect-legacy",
        )
        delivery_id = assignment["attempts"][-1]["dispatch_operation_id"]
        self.relay.hide_results = False

        # The historical general results cache could contain a valid
        # fingerprint but omit eight proof fields present in durable receipts.
        self.relay.result_mutator = lambda value: {
            key: value[key] for key in
            ("id", "ok", "reply", "fingerprint", "tabId", "conversationKey")
            if key in value
        }
        before_sends = len([
            call for call in self.relay.calls if call["command"] == "send"
        ])
        inspected = self.call("inspect-legacy-candidate", {
            "operation": "inspect-result-receipt", "session_id": "session",
            "assignment_id": "inspect-legacy",
            "original_operation_id": "inspect-legacy-original",
            "delivery_id": delivery_id,
        })
        self.assertEqual(Outcome.APPLIED, inspected.outcome)
        self.assertEqual("RECEIPT_INCOMPLETE", inspected.output["observation"])
        self.assertTrue(inspected.output["result_candidate_found"])
        self.assertFalse(inspected.output["receipt_origin_attested"])
        self.assertEqual("UNVERIFIED", inspected.output["receipt_origin"])
        self.assertEqual({
            "ambiguous", "attachmentGeneration", "instanceId", "messageHash",
            "resultHash", "resultState", "sessionId", "targetBindingReceipt",
        }, set(inspected.output["missing_fields"]))
        self.assertEqual([], inspected.output["identity_mismatches"])
        self.assertFalse(inspected.output["result_promoted"])
        self.assertNotIn("reply", str(inspected.output))
        self.assertEqual(before_sends, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))
        self.assertEqual(Outcome.UNKNOWN, self.bct.store.get_operation_for(
            operation_id="inspect-legacy-original",
            work_id="work", principal_id="owner",
        ).outcome)

    def test_inspector_incomplete_structural_proof_is_not_identity_mismatch(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("inspect-broken-proof-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "inspect-broken-proof",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return exact proof", "acceptance": {"inspect": True},
            "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        assignment = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="inspect-broken-proof",
        )
        delivery_id = assignment["attempts"][-1]["dispatch_operation_id"]
        self.relay.hide_results = False
        self.relay.result_mutator = lambda value: {
            **value, "resultHash": "not-a-valid-hash",
        }
        inspected = self.call("inspect-broken-proof-candidate", {
            "operation": "inspect-result-receipt", "session_id": "session",
            "assignment_id": "inspect-broken-proof",
            "original_operation_id": "inspect-broken-proof-original",
            "delivery_id": delivery_id,
        })
        self.assertEqual(Outcome.APPLIED, inspected.outcome)
        self.assertEqual("RECEIPT_INCOMPLETE", inspected.output["observation"])
        self.assertEqual([], inspected.output["missing_fields"])
        self.assertIn("resultHash", inspected.output["invalid_proof_fields"])
        self.assertFalse(inspected.output["result_promoted"])

    def test_inspection_foreign_work_missing_assignment_and_attachment_reject_without_unknown(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("access-inspect-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "access-inspect-target",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "produce one uncertain receipt for access checks",
            "acceptance": {"inspect": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        a = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="access-inspect-target",
        )
        delivery_id = a["attempts"][-1]["dispatch_operation_id"]
        base = {
            "operation": "inspect-result-receipt", "session_id": "session",
            "assignment_id": "access-inspect-target",
            "original_operation_id": "access-inspect-original",
            "delivery_id": delivery_id,
        }
        self.bct.create_work(
            work_id="foreign-work", request_summary="separate work fixture",
            roots=[str(self.root)], actions=["orchestrate"], principal=self.owner,
        )
        rejected_foreign = self.bct.operations.run(
            principal=self.owner, work_id="foreign-work",
            operation_id="access-foreign-inspector", capability="orchestrate",
            arguments=base,
        )
        self.assertEqual(Outcome.NOT_APPLIED, rejected_foreign.outcome)
        rejected_missing = self.call(
            "access-missing-assignment",
            {**base, "assignment_id": "not-an-assignment"},
        )
        self.assertEqual(Outcome.NOT_APPLIED, rejected_missing.outcome)
        rejected_other = self.call(
            "access-foreign-original",
            {**base, "original_operation_id": "not-the-original"},
        )
        self.assertEqual(Outcome.NOT_APPLIED, rejected_other.outcome)
        with self.bct.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_session_nodes SET active=0 "
                "WHERE session_id=? AND node_id=?",
                ("session", "worker-b"),
            )
        rejected_attachment = self.call("access-missing-attachment", base)
        self.assertEqual(Outcome.NOT_APPLIED, rejected_attachment.outcome)
        claimed = {
            x["operation_id"] for x in
            self.bct.store.monitor_snapshot()["unresolved_claims"]
        }
        for operation_id in (
            "access-foreign-inspector", "access-missing-assignment",
            "access-foreign-original", "access-missing-attachment",
        ):
            self.assertNotIn(operation_id, claimed)
        self.assertIn("access-inspect-original", claimed)

    def test_inspection_mismatched_fingerprint_is_diagnostic_not_success(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("inspect-fingerprint-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "inspect-fingerprint",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return a receipt with immutable target identity",
            "acceptance": {"inspect": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        a = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="inspect-fingerprint",
        )
        delivery_id = a["attempts"][-1]["dispatch_operation_id"]
        self.relay.hide_results = False

        def corrupted_fingerprint(value):
            parts = json.loads(value["fingerprint"])
            parts[6] = "incorrect-instance"
            return {**value, "fingerprint": json.dumps(
                parts, ensure_ascii=False, separators=(",", ":")
            )}

        self.relay.result_mutator = corrupted_fingerprint
        sends_before = len([x for x in self.relay.calls if x["command"] == "send"])
        observed = self.call("inspect-fingerprint-mismatched-result", {
            "operation": "inspect-result-receipt", "session_id": "session",
            "assignment_id": "inspect-fingerprint",
            "original_operation_id": "inspect-fingerprint-original",
            "delivery_id": delivery_id,
        })
        self.assertEqual(Outcome.APPLIED, observed.outcome)
        self.assertEqual("IDENTITY_MISMATCH", observed.output["observation"])
        self.assertTrue(observed.output["checks"]["fingerprint_structure"])
        self.assertFalse(
            observed.output["checks"]["fingerprint_identity_except_prompt"]
        )
        self.assertTrue(observed.output["checks"]["instance_id"])
        self.assertFalse(observed.output["all_identity_checks_except_prompt"])
        self.assertFalse(observed.output["result_promoted"])
        self.assertEqual(sends_before, len([
            x for x in self.relay.calls if x["command"] == "send"
        ]))
        self.assertEqual(
            Outcome.UNKNOWN,
            self.bct.store.get_operation_for(
                operation_id="inspect-fingerprint-original", work_id="work",
                principal_id="owner",
            ).outcome,
        )

    def test_immediate_reply_is_not_durable_receipt_and_later_reconciles(self):
        # RCC has an exact result, but its durable readback is temporarily
        # unavailable; the immediate reply has no attested receipt metadata.
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        original = self.call("immediate-but-unconfirmed", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "immediate-late-receipt",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return a result after readback reconnects",
            "acceptance": {"recover": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        assignment = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="immediate-late-receipt",
        )
        self.assertEqual(
            "ORCHESTRATION_RESULT_NOT_CONFIRMED",
            assignment["terminal_result"]["error"],
        )
        sends_before = len([
            x for x in self.relay.calls if x["command"] == "send"
        ])
        self.relay.hide_results = False
        recovered = self.call("immediate-late-reconcile", {
            "operation": "reconcile", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "immediate-late-receipt",
            "original_operation_id": "immediate-but-unconfirmed",
            "timeout_s": 2,
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        self.assertEqual(sends_before, len([
            x for x in self.relay.calls if x["command"] == "send"
        ]))
        self.assertEqual(
            Outcome.UNKNOWN,
            self.bct.store.get_operation_for(
                operation_id="immediate-but-unconfirmed",
                work_id="work", principal_id="owner",
            ).outcome,
        )

    def test_exact_result_reconciles_unknown_without_resend(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        self.relay.lose_send_response = True
        unknown = self.call("lost-dispatch", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "lost-result",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return a durable result despite response loss",
            "acceptance": {"reconciled": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, unknown.outcome)
        sends_before = len([
            call for call in self.relay.calls if call["command"] == "send"
        ])
        self.relay.hide_results = False
        self.relay.lose_send_response = False
        with self.assertRaises(ConflictError):
            self.call("blocked-same-conversation", {
                "operation": "dispatch", "session_id": "session",
                "manager_epoch": 1, "assignment_id": "must-be-quarantined",
                "worker_node_id": "worker-b",
                "attachment_id": worker["attachment_id"],
                "instruction": "must not bypass unknown quarantine",
                "acceptance": {"never": True},
            })
        reconciled = self.call("reconcile-lost-dispatch", {
            "operation": "reconcile", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "lost-result",
            "original_operation_id": "lost-dispatch", "timeout_s": 2,
        })
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))
        original = self.bct.store.get_operation_for(
            operation_id="lost-dispatch", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        assignment = next(
            item for item in snapshot["assignments"]
            if item["assignment_id"] == "lost-result"
        )
        self.assertEqual("APPLIED", assignment["state"])
        # This original fixture is LEGACY_RETURN_V1; its reconciliation
        # must not silently create new Schema 2-style Manager notifications.
        self.assertFalse([
            wake for wake in snapshot["manager_wakes"]
            if wake["assignment_id"] == "lost-result"
        ])

    def _prepare_schema2_lost_worker_result(self, suffix: str):
        # This fixture turns the already-created test session into Schema 2
        # without changing any LIVE/legacy session.
        with self.bct.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_sessions SET "
                "wake_receipt_mode='RCC_RESULT_POLL_V1' "
                "WHERE session_id='session'"
            )
        self.bct.orchestration.manager_wake_receipt_v2_enabled = True
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        self.relay.lose_send_response = True
        original_id = "lost-" + suffix
        assignment_id = "recovered-" + suffix
        original = self.call(original_id, {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": assignment_id,
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return one isolated durable result",
            "acceptance": {"test": suffix}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        self.relay.hide_results = False
        self.relay.lose_send_response = False
        return original_id, assignment_id

    def test_schema2_reconciliation_records_single_manager_wake(self):
        original_id, assignment_id = self._prepare_schema2_lost_worker_result(
            "wake-on-reconcile"
        )
        sends_before = len([
            c for c in self.relay.calls if c["command"] == "send"
        ])
        reconciled = self.call("resolve-schema2", {
            "operation": "reconcile", "session_id": "session",
            "assignment_id": assignment_id,
            "manager_epoch": 1,
            "original_operation_id": original_id, "timeout_s": 3,
        })
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        snap = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session",
        )
        self.assertEqual(1, len([
            x for x in snap["manager_wakes"]
            if x["assignment_id"] == assignment_id
        ]))
        self.assertEqual("DELIVERED", snap["manager_wakes"][0]["state"])
        self.assertEqual("RCC_RESULT_POLL_V1",
                         snap["manager_wakes"][0]["receipt_mode"])
        self.assertEqual(sends_before, len([
            c for c in self.relay.calls if c["command"] == "send"
        ]))
        # Re-read existing terminal proof: no new Wake and no second send.
        again = self.call("backfill-already-present", {
            "operation": "recover-reconciled-wake",
            "session_id": "session", "manager_epoch": 1,
            "assignment_id": assignment_id,
        })
        self.assertEqual(Outcome.APPLIED, again.outcome)
        self.assertFalse(again.evidence["wake_created"])
        self.assertEqual(1, len([
            x for x in self.bct.orchestration.snapshot(
                work=self.bct.store.get_work("work"), session_id="session",
            )["manager_wakes"] if x["assignment_id"] == assignment_id
        ]))

    def test_schema2_backfill_existing_reconciliation_without_worker_resend(self):
        original_id, assignment_id = self._prepare_schema2_lost_worker_result(
            "old-reconciled-missing-wake"
        )
        # Simulate the OLD implementation: exact RESULT imported, but no Wake.
        original_method = self.bct.orchestration._record_manager_wake
        self.bct.orchestration._record_manager_wake = lambda *args, **kw: None
        try:
            reconciled = self.call("old-import", {
                "operation": "reconcile", "session_id": "session",
                "manager_epoch": 1, "assignment_id": assignment_id,
                "original_operation_id": original_id, "timeout_s": 3,
            })
        finally:
            self.bct.orchestration._record_manager_wake = original_method
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        self.assertFalse(self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session",
        )["manager_wakes"])
        sends_before = len([
            c for c in self.relay.calls if c["command"] == "send"
        ])
        recovered = self.call("recover-old-wake", {
            "operation": "recover-reconciled-wake",
            "session_id": "session", "manager_epoch": 1,
            "assignment_id": assignment_id,
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        self.assertTrue(recovered.evidence["wake_created"])
        self.assertEqual("DELIVERED", recovered.evidence["wake_state"])
        self.assertEqual(sends_before, len([
            c for c in self.relay.calls if c["command"] == "send"
        ]))
        retried = self.call("recover-old-wake-again", {
            "operation": "recover-reconciled-wake",
            "session_id": "session", "manager_epoch": 1,
            "assignment_id": assignment_id,
        })
        self.assertEqual(Outcome.APPLIED, retried.outcome)
        self.assertFalse(retried.evidence["wake_created"])
        self.assertEqual(1, len([
            x for x in self.bct.orchestration.snapshot(
                work=self.bct.store.get_work("work"), session_id="session",
            )["manager_wakes"] if x["assignment_id"] == assignment_id
        ]))

    def test_unknown_conversation_quarantine_is_global_across_rcc_instances(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        self.relay.lose_send_response = True
        unknown = self.call("cross-instance-unknown", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "cross-instance-first",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "leave an ambiguous external effect",
            "acceptance": {"once": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, unknown.outcome)
        second = self.bct.orchestration.sync_attachment(
            work=self.bct.store.get_work("work"), session_id="session",
            node_id="worker-b", name="Worker B alternate instance", role="WORKER",
            attachment_id="att-cross-instance", instance_id="instance999",
            external_session_id="session999", tab_id=999, window_id=99,
            conversation_key="conversation-b",
            endpoint="https://chatgpt.com/c/conversation-b", relay_role="BCT_W9",
            binding_receipt_id="RCB-ZZZZZZZZZZZZ",
        )
        self.bct.orchestration.activate_instance_session(
            work=self.bct.store.get_work("work"), session_id="session",
            instance_id="instance999", external_session_id="session999",
        )
        with self.assertRaisesRegex(
            ConflictError, "ORCHESTRATION_CONVERSATION_QUARANTINED:UNKNOWN"
        ):
            self.bct.orchestration.create_assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="cross-instance-second", manager_epoch=1,
                worker_node_id="worker-b", attachment_id=second["attachment_id"],
                request={"instruction": "must not replay via another RCC instance"},
                roots=[str(self.root)], actions=["read"],
                acceptance={"never": True}, dependencies=[],
            )

    def test_incomplete_rcc_receipt_never_applies_worker_result(self):
        worker = self.attachment("worker-b")
        self.relay.result_mutator = lambda value: {
            key: item for key, item in value.items() if key != "fingerprint"
        }
        result = self.call("bad-receipt", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "bad-receipt-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return a result whose transport receipt is incomplete",
            "acceptance": {"strict": True},
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        assignment = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="bad-receipt-task",
        )
        self.assertEqual("UNKNOWN", assignment["state"])
        self.assertEqual(
            "ORCHESTRATION_RCC_FINGERPRINT_MISMATCH",
            assignment["terminal_result"]["error"],
        )
        self.assertTrue(any(
            claim["operation_id"] == "bad-receipt"
            for claim in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))

    def test_recoverable_rcc_capture_failure_uses_result_only_recovery(self):
        worker = self.attachment("worker-b")
        self.relay.return_submit_ack = True
        self.relay.recover_pending_enabled = True
        self.relay.result_mutator = lambda value: {
            **value,
            "ok": False,
            "reply": "",
            "error": "net::ERR_ABORTED",
            "failureEvidence": {
                "phase": "FINAL_DOM_VALIDATION",
                "networkError": "net::ERR_ABORTED",
                "domError": "RELAY_FINAL_DOM_NOT_READY:ROUTE_TURN_NOT_RESOLVED",
                "networkSignal": "FAILED",
            },
        }
        result = self.call("recover-capture", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "recover-capture-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "recover an exact final DOM result without resending",
            "acceptance": {"result_only_recovery": True},
        })
        self.assertEqual(
            Outcome.APPLIED, result.outcome,
            (result, self.relay.recover_pending_calls, self.relay.calls),
        )
        self.assertEqual(1, self.relay.recover_pending_calls)
        self.assertEqual(
            1,
            len([call for call in self.relay.calls if call["command"] == "send"]),
        )

    def test_ambiguous_receipt_must_be_explicit_boolean_false(self):
        worker = self.attachment("worker-b")
        self.relay.result_mutator = lambda value: {
            **value, "ambiguous": 0,
        }
        result = self.call("non-boolean-ambiguous", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "ambiguous-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return a receipt with a non-boolean ambiguity field",
            "acceptance": {"strict": True},
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        assignment = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="ambiguous-task",
        )
        self.assertEqual("UNKNOWN", assignment["state"])

    def test_invalid_result_envelope_after_dispatch_stays_unknown(self):
        worker = self.attachment("worker-b")
        self.relay.result_mutator = lambda value: {
            **value, "reply": RESULT_START + "not-json" + RESULT_END,
        }
        result = self.call("invalid-result-envelope", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "invalid-result-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return a malformed result envelope",
            "acceptance": {"strict": True},
        })
        self.assertEqual(Outcome.UNKNOWN, result.outcome)
        assignment = self.bct.orchestration.assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="invalid-result-task",
        )
        self.assertEqual("UNKNOWN", assignment["state"])
        self.assertEqual(
            "ORCHESTRATION_RESULT_JSON_INVALID",
            assignment["terminal_result"]["error"],
        )

    def test_reconcile_rejects_untrusted_receipt_without_releasing_original(self):
        worker = self.attachment("worker-b")
        self.relay.hide_results = True
        self.relay.lose_send_response = True
        dispatched = self.call("untrusted-reconcile-original", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "untrusted-reconcile-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "persist a result for strict reconciliation",
            "acceptance": {"strict": True}, "timeout_s": 5,
        })
        self.assertEqual(Outcome.UNKNOWN, dispatched.outcome)
        self.relay.hide_results = False
        self.relay.lose_send_response = False
        self.relay.result_mutator = lambda value: {
            key: item for key, item in value.items() if key != "ambiguous"
        }
        rejected = self.call("reject-untrusted-reconcile", {
            "operation": "reconcile", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "untrusted-reconcile-task",
            "original_operation_id": "untrusted-reconcile-original",
            "timeout_s": 2,
        })
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome)
        original_claims = [
            claim for claim in self.bct.store.monitor_snapshot()["unresolved_claims"]
            if claim["operation_id"] == "untrusted-reconcile-original"
        ]
        self.assertTrue(original_claims)

        self.relay.result_mutator = None
        accepted = self.call("accept-trusted-reconcile", {
            "operation": "reconcile", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "untrusted-reconcile-task",
            "original_operation_id": "untrusted-reconcile-original",
            "timeout_s": 2,
        })
        self.assertEqual(Outcome.APPLIED, accepted.outcome)

    def test_chain_skips_synthesis_until_unknown_worker_is_reconciled(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        manager = self.attachment("manager")
        first_delivery = "orch.send." + _hash(
            _canonical(["session", "deferred-first", 1]), 32
        )
        self.relay.result_mutator = lambda value: (
            {key: item for key, item in value.items() if key != "ambiguous"}
            if value["id"] == first_delivery else value
        )
        chain = self.call("deferred-synthesis-chain", {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {"assignment_id": "deferred-first", "worker_node_id": "worker-b",
                 "attachment_id": worker_b["attachment_id"],
                 "instruction": "produce the first durable result",
                 "acceptance": {"first": True}},
                {"assignment_id": "deferred-second", "worker_node_id": "worker-c",
                 "attachment_id": worker_c["attachment_id"],
                 "instruction": "produce the second durable result",
                 "acceptance": {"second": True}},
            ],
            "synthesis": {
                "assignment_id": "deferred-synthesis", "manager_node_id": "manager",
                "attachment_id": manager["attachment_id"],
                "instruction": "synthesize only trusted worker results",
                "acceptance": {"combined": True},
            },
        })
        self.assertEqual(Outcome.UNKNOWN, chain.outcome)
        self.assertEqual(
            ["BCT_W1", "BCT_W2"],
            [call["to"] for call in self.relay.calls if call["command"] == "send"],
        )
        with self.assertRaises(KeyError):
            self.bct.orchestration.assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="deferred-synthesis",
            )

        self.relay.result_mutator = None
        resumed = self.call("resume-deferred-synthesis", {
            "operation": "chain-resume", "session_id": "session",
            "manager_epoch": 1,
            "original_operation_id": "deferred-synthesis-chain",
        })
        self.assertEqual(Outcome.APPLIED, resumed.outcome)
        self.assertEqual(
            ["BCT_W1", "BCT_W2", "BCT_MGR"],
            [call["to"] for call in self.relay.calls if call["command"] == "send"],
        )
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        synthesis = next(
            item for item in snapshot["assignments"]
            if item["assignment_id"] == "deferred-synthesis"
        )
        self.assertEqual("APPLIED", synthesis["state"])
        consumed = [
            item for item in snapshot["mailbox"]
            if item["kind"] == "RESULT" and item["consumed_at"] is not None
        ]
        self.assertEqual(2, len(consumed))

    def test_reconcile_recovers_running_operation_after_worker_loss(self):
        worker = self.attachment("worker-b")
        dispatch_arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "running-loss",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "persist a result before the operation worker disappears",
            "acceptance": {"recovered": True},
        }
        created, original = self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="running-original",
            capability="orchestrate", arguments=dispatch_arguments,
        )
        self.assertTrue(created)
        self.assertEqual("RUNNING", original.state.value)
        _created, assignment = self.bct.orchestration.create_assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="running-loss", manager_epoch=1,
            worker_node_id="worker-b", attachment_id=worker["attachment_id"],
            request={"instruction": dispatch_arguments["instruction"]},
            roots=[str(self.root)], actions=["read"],
            acceptance=dispatch_arguments["acceptance"], dependencies=[],
        )
        generation = 1
        nonce = _hash(_canonical([
            "running-loss", generation, assignment["request_digest"]
        ]), 32)
        prompt = OrchestrationFeature._result_envelope(
            session_id="session", assignment_id="running-loss",
            generation=generation, manager_epoch=1,
            request_digest=assignment["request_digest"], result_nonce=nonce,
            instruction=dispatch_arguments["instruction"],
            acceptance=dispatch_arguments["acceptance"],
            roots=assignment["roots"], actions=assignment["actions"], dependencies=[],
        )
        delivery_id = "orch.send." + _hash(
            _canonical(["session", "running-loss", generation]), 32
        )
        message_id = "msg." + _hash(
            _canonical(["session", "running-loss", generation, "dispatch"]), 32
        )
        self.bct.orchestration.reserve_dispatch(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="running-loss", manager_epoch=1,
            message_id=message_id, dispatch_operation_id=delivery_id,
            payload={
                "request_digest": assignment["request_digest"],
                "result_nonce": nonce, "attachment_id": worker["attachment_id"],
                "attachment_generation": worker["generation"],
            },
        )
        self.relay.request(
            instance_id=worker["instance_id"], request_id=delivery_id,
            command="send", to=worker["relay_role"], text=prompt,
            extra={
                "fromNode": "BCT_MANAGER",
                "messageHash": assignment["request_digest"],
                "bindingReceiptId": worker["binding_receipt_id"],
                "expectedInstanceId": worker["instance_id"],
                "expectedSessionId": worker["external_session_id"],
                "expectedTabId": worker["tab_id"],
                "expectedConversationKey": worker["conversation_key"],
                "attachmentGeneration": worker["generation"],
            }, timeout_s=30,
        )
        sends_before = len([
            call for call in self.relay.calls if call["command"] == "send"
        ])
        reconciled = self.call("reconcile-running", {
            "operation": "reconcile", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "running-loss",
            "original_operation_id": "running-original", "timeout_s": 2,
        })
        self.assertEqual(Outcome.APPLIED, reconciled.outcome)
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))
        original = self.bct.store.get_operation_for(
            operation_id="running-original", work_id="work", principal_id="owner"
        )
        self.assertEqual("FINISHED", original.state.value)
        self.assertEqual(Outcome.APPLIED, original.outcome)

    def test_chain_resume_continues_after_first_durable_result_without_replay(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        manager = self.attachment("manager")
        chain_arguments = {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {"assignment_id": "resume-first", "worker_node_id": "worker-b",
                 "attachment_id": worker_b["attachment_id"],
                 "instruction": "persist the first result",
                 "acceptance": {"first": True}},
                {"assignment_id": "resume-second", "worker_node_id": "worker-c",
                 "attachment_id": worker_c["attachment_id"],
                 "instruction": "continue with the second result",
                 "acceptance": {"second": True}},
            ],
            "synthesis": {
                "assignment_id": "resume-synthesis", "manager_node_id": "manager",
                "attachment_id": manager["attachment_id"],
                "instruction": "synthesize resumed results",
                "acceptance": {"combined": True},
            },
        }
        created, _original = self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="running-chain",
            capability="orchestrate", arguments=chain_arguments,
        )
        self.assertTrue(created)
        work = self.bct.store.get_work("work")
        self.bct.orchestration.record_chain_plan(
            work=work, session_id="session", operation_id="running-chain",
            plan={
                "tasks": chain_arguments["tasks"],
                "synthesis": chain_arguments["synthesis"],
                "takeover": None, "timeout_s": 30,
            },
        )
        feature = self.bct.operations._features["orchestrate"]
        prepared = feature.prepare(work=work, arguments=chain_arguments)
        first = feature._dispatch(
            request=prepared, work=work,
            values={
                **chain_arguments["tasks"][0], "session_id": "session",
                "manager_epoch": 1, "timeout_s": 30,
            },
        )
        self.assertEqual("APPLIED", first["state"])
        sends_before = len([
            call for call in self.relay.calls if call["command"] == "send"
        ])
        resumed = self.call("resume-chain-operation", {
            "operation": "chain-resume", "session_id": "session",
            "manager_epoch": 1, "original_operation_id": "running-chain",
        })
        self.assertEqual(Outcome.APPLIED, resumed.outcome)
        sends = [call for call in self.relay.calls if call["command"] == "send"]
        self.assertEqual(sends_before + 2, len(sends))
        first_delivery = "orch.send." + _hash(
            _canonical(["session", "resume-first", 1]), 32
        )
        self.assertEqual(1, sum(
            call["request_id"] == first_delivery for call in sends
        ))
        original = self.bct.store.get_operation_for(
            operation_id="running-chain", work_id="work", principal_id="owner"
        )
        self.assertEqual("FINISHED", original.state.value)
        self.assertEqual(Outcome.APPLIED, original.outcome)

    def test_takeover_adopts_queued_attempt_before_dispatch(self):
        worker = self.attachment("worker-b")
        self.bct.orchestration.create_assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="queued-before-takeover", manager_epoch=1,
            worker_node_id="worker-b", attachment_id=worker["attachment_id"],
            request={"instruction": "continue after manager replacement"},
            # Exercise equivalent Windows path spellings (hosted runners can
            # expose temp roots through an 8.3 alias while Work stores long form).
            roots=[str(self.root / "scope-alias" / "..")],
            actions=["read"], acceptance={"done": True},
            dependencies=[],
        )
        self.call("takeover-queued", {
            "operation": "manager-takeover", "session_id": "session",
            "expected_manager_epoch": 1, "manager_node_id": "backup",
            "reason": "original manager unavailable before dispatch",
        })
        result = self.call("dispatch-adopted", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 2, "assignment_id": "queued-before-takeover",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "continue after manager replacement",
            "acceptance": {"done": True},
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)

    def test_recover_not_dispatched_releases_running_operation_without_plan(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "never-started",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "must never be sent", "acceptance": {"safe": True},
        }
        created, _ = self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="lost-before-feature",
            capability="orchestrate", arguments=arguments,
        )
        self.assertTrue(created)
        recovered = self.call("recover-lost-before-feature", {
            "operation": "recover-not-dispatched", "session_id": "session",
            "original_operation_id": "lost-before-feature",
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        original = self.bct.store.get_operation_for(
            operation_id="lost-before-feature", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.NOT_APPLIED, original.outcome)
        self.assertFalse(any(
            item["operation_id"] == "lost-before-feature"
            for item in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))

    def test_recover_not_dispatched_accepts_exact_queued_assignment(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "queued-crash",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "queued only", "acceptance": {"safe": True},
        }
        self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="queued-original",
            capability="orchestrate", arguments=arguments,
        )
        self.bct.orchestration.create_assignment(
            work=self.bct.store.get_work("work"), session_id="session",
            assignment_id="queued-crash", manager_epoch=1,
            worker_node_id="worker-b", attachment_id=worker["attachment_id"],
            request={"instruction": "queued only",
                     "_outer_operation_id": "queued-original"}, roots=[str(self.root)],
            actions=["read"], acceptance={"safe": True}, dependencies=[],
        )
        recovered = self.call("recover-queued-original", {
            "operation": "recover-not-dispatched", "session_id": "session",
            "original_operation_id": "queued-original",
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        original = self.bct.store.get_operation_for(
            operation_id="queued-original", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.NOT_APPLIED, original.outcome)
        sends_before = len([call for call in self.relay.calls if call["command"] == "send"])
        continued = self.call("queued-continuation", arguments)
        self.assertEqual(Outcome.APPLIED, continued.outcome)
        self.assertEqual(sends_before + 1, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))

    def test_invalid_timeout_never_reserves_or_creates_assignment(self):
        worker = self.attachment("worker-b")
        sends_before = len([call for call in self.relay.calls if call["command"] == "send"])
        result = self.call("invalid-timeout", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "invalid-timeout-task",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "must not reserve", "acceptance": {"safe": True},
            "timeout_s": 1,
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        with self.assertRaises(KeyError):
            self.bct.orchestration.assignment(
                work=self.bct.store.get_work("work"), session_id="session",
                assignment_id="invalid-timeout-task",
            )
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))

    def test_recovery_fence_prevents_late_worker_send(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "fenced-queued",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "must stay fenced", "acceptance": {"safe": True},
        }
        self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="fenced-original",
            capability="orchestrate", arguments=arguments,
        )
        work = self.bct.store.get_work("work")
        _created, assignment = self.bct.orchestration.create_assignment(
            work=work, session_id="session", assignment_id="fenced-queued",
            manager_epoch=1, worker_node_id="worker-b",
            attachment_id=worker["attachment_id"],
            request={"instruction": "must stay fenced",
                     "_outer_operation_id": "fenced-original"},
            roots=[str(self.root)], actions=["read"],
            acceptance={"safe": True}, dependencies=[],
        )
        recovered = self.call("fence-recovery", {
            "operation": "recover-not-dispatched", "session_id": "session",
            "original_operation_id": "fenced-original",
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        sends_before = len([call for call in self.relay.calls if call["command"] == "send"])
        with self.assertRaises(ConflictError):
            self.bct.operations._features["orchestrate"]._dispatch_assignment(
                work=work, assignment=assignment, manager_epoch=1, timeout_s=30,
            )
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))

    def test_recover_not_dispatched_accepts_stale_attachment_terminal(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "stale-terminal",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "never routed", "acceptance": {"safe": True},
        }
        self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="stale-original",
            capability="orchestrate", arguments=arguments,
        )
        work = self.bct.store.get_work("work")
        self.bct.orchestration.create_assignment(
            work=work, session_id="session", assignment_id="stale-terminal",
            manager_epoch=1, worker_node_id="worker-b",
            attachment_id=worker["attachment_id"],
            request={"instruction": "never routed",
                     "_outer_operation_id": "stale-original"},
            roots=[str(self.root)], actions=["read"],
            acceptance={"safe": True}, dependencies=[],
        )
        self.bct.orchestration.reconcile_observed_attachments(
            work=work, session_id="session", instance_id=worker["instance_id"],
            active_attachment_ids=[
                item["attachment_id"] for item in
                self.bct.orchestration.snapshot(work=work, session_id="session")["attachments"]
                if item["active"] and item["attachment_id"] != worker["attachment_id"]
            ],
        )
        attachment, terminal = self.bct.orchestration.resolve_dispatch_attachment(
            work=work, session_id="session", assignment_id="stale-terminal",
            manager_epoch=1,
        )
        self.assertIsNone(attachment)
        self.assertEqual("NOT_APPLIED", terminal["state"])
        recovered = self.call("recover-stale-terminal", {
            "operation": "recover-not-dispatched", "session_id": "session",
            "original_operation_id": "stale-original",
        })
        self.assertEqual(Outcome.APPLIED, recovered.outcome)
        original = self.bct.store.get_operation_for(
            operation_id="stale-original", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.NOT_APPLIED, original.outcome)

    def test_reconcile_recovers_confirmed_unavailable_terminal_without_resend(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "unavailable-terminal",
            "worker_node_id": "worker-b", "attachment_id": worker["attachment_id"],
            "instruction": "confirmed unavailable", "acceptance": {"safe": True},
            "timeout_s": 30,
        }
        self.bct.operations.begin(
            principal=self.owner, work_id="work",
            operation_id="unavailable-original", capability="orchestrate",
            arguments=arguments,
        )
        work = self.bct.store.get_work("work")
        feature = self.bct.operations._features["orchestrate"]
        prepared = feature.prepare(work=work, arguments=arguments)
        prepared = FeatureRequest(
            prepared.capability, prepared.target, prepared.arguments,
            prepared.resources, prepared.preconditions, "unavailable-original",
        )
        self.relay.fail_send_once.add(worker["relay_role"])
        terminal = feature._dispatch(
            request=prepared, work=work, values=arguments,
        )
        self.assertEqual("NOT_APPLIED", terminal["state"])
        self.assertTrue(terminal["terminal_result"]["pre_dispatch"])
        sends_before = len([call for call in self.relay.calls if call["command"] == "send"])
        reconciled = self.call("unavailable-resolver", {
            "operation": "reconcile", "session_id": "session", "manager_epoch": 1,
            "assignment_id": "unavailable-terminal",
            "original_operation_id": "unavailable-original", "timeout_s": 1,
        })
        self.assertEqual(Outcome.NOT_APPLIED, reconciled.outcome)
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))
        original = self.bct.store.get_operation_for(
            operation_id="unavailable-original", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.NOT_APPLIED, original.outcome)

    def test_standalone_reconcile_cannot_release_partial_chain_claims(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        manager = self.attachment("manager")
        arguments = {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {"assignment_id": "chain-one", "worker_node_id": "worker-b",
                 "attachment_id": worker_b["attachment_id"], "instruction": "one",
                 "acceptance": {"one": True}},
                {"assignment_id": "chain-two", "worker_node_id": "worker-c",
                 "attachment_id": worker_c["attachment_id"], "instruction": "two",
                 "acceptance": {"two": True}},
            ],
            "synthesis": {"assignment_id": "chain-final", "manager_node_id": "manager",
                          "attachment_id": manager["attachment_id"],
                          "instruction": "combine", "acceptance": {"all": True}},
        }
        self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="chain-original",
            capability="orchestrate", arguments=arguments,
        )
        work = self.bct.store.get_work("work")
        self.bct.orchestration.record_chain_plan(
            work=work, session_id="session", operation_id="chain-original",
            plan={"tasks": arguments["tasks"], "synthesis": arguments["synthesis"],
                  "takeover": None, "timeout_s": 30},
        )
        prepared = self.bct.operations._features["orchestrate"].prepare(
            work=work, arguments=arguments
        )
        self.bct.operations._features["orchestrate"]._dispatch(
            request=prepared, work=work,
            values={**arguments["tasks"][0], "session_id": "session",
                    "manager_epoch": 1, "timeout_s": 30},
        )
        rejected = self.call("bad-partial-chain-reconcile", {
            "operation": "reconcile", "session_id": "session", "manager_epoch": 1,
            "assignment_id": "chain-one",
            "original_operation_id": "chain-original", "timeout_s": 1,
        })
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome)
        self.assertIn("ORCHESTRATION_CHAIN_REQUIRES_RESUME", rejected.error or "")
        self.assertTrue(any(
            item["operation_id"] == "chain-original"
            for item in self.bct.store.monitor_snapshot()["unresolved_claims"]
        ))

    def test_chain_resume_recovers_terminal_session_after_outer_receipt_loss(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        manager = self.attachment("manager")
        arguments = {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {"assignment_id": "terminal-one", "worker_node_id": "worker-b",
                 "attachment_id": worker_b["attachment_id"], "instruction": "one",
                 "acceptance": {"one": True}},
                {"assignment_id": "terminal-two", "worker_node_id": "worker-c",
                 "attachment_id": worker_c["attachment_id"], "instruction": "two",
                 "acceptance": {"two": True}},
            ],
            "synthesis": {
                "assignment_id": "terminal-final", "manager_node_id": "manager",
                "attachment_id": manager["attachment_id"], "instruction": "combine",
                "acceptance": {"all": True},
            },
        }
        self.bct.operations.begin(
            principal=self.owner, work_id="work", operation_id="terminal-original",
            capability="orchestrate", arguments=arguments,
        )
        work = self.bct.store.get_work("work")
        self.bct.orchestration.record_chain_plan(
            work=work, session_id="session", operation_id="terminal-original",
            plan={"tasks": arguments["tasks"], "synthesis": arguments["synthesis"],
                  "takeover": None, "timeout_s": 30},
        )
        feature = self.bct.operations._features["orchestrate"]
        request = feature.prepare(work=work, arguments=arguments)
        completed = feature._chain(
            request, work, resume_original_operation_id="terminal-original"
        )
        self.assertEqual("FINISHED", completed["session"]["state"])
        sends_before = len([call for call in self.relay.calls if call["command"] == "send"])
        resumed = self.call("terminal-resolver", {
            "operation": "chain-resume", "session_id": "session",
            "manager_epoch": 1, "original_operation_id": "terminal-original",
        })
        self.assertEqual(Outcome.APPLIED, resumed.outcome)
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))
        original = self.bct.store.get_operation_for(
            operation_id="terminal-original", work_id="work", principal_id="owner"
        )
        self.assertEqual(Outcome.APPLIED, original.outcome)

    def test_exact_chain_run_restart_adopts_terminal_session_without_resend(self):
        worker_b = self.attachment("worker-b")
        worker_c = self.attachment("worker-c")
        manager = self.attachment("manager")
        arguments = {
            "operation": "chain-run", "session_id": "session",
            "manager_epoch": 1, "timeout_s": 30,
            "tasks": [
                {"assignment_id": "restart-terminal-one",
                 "worker_node_id": "worker-b",
                 "attachment_id": worker_b["attachment_id"],
                 "instruction": "one", "acceptance": {"one": True}},
                {"assignment_id": "restart-terminal-two",
                 "worker_node_id": "worker-c",
                 "attachment_id": worker_c["attachment_id"],
                 "instruction": "two", "acceptance": {"two": True}},
            ],
            "synthesis": {
                "assignment_id": "restart-terminal-final",
                "manager_node_id": "manager",
                "attachment_id": manager["attachment_id"],
                "instruction": "combine", "acceptance": {"all": True},
            },
        }
        completed = self.call("restart-terminal-chain", arguments)
        self.assertEqual(Outcome.APPLIED, completed.outcome)
        sends_before = len([
            call for call in self.relay.calls if call["command"] == "send"
        ])
        # Model a hard crash after session commit and before outer receipt commit.
        with self.bct.store.transaction() as db:
            db.execute(
                "UPDATE operations SET state='RUNNING',outcome=NULL,error=NULL "
                "WHERE operation_id='restart-terminal-chain'"
            )
            db.execute(
                "UPDATE resource_claims SET unresolved=1 "
                "WHERE operation_id='restart-terminal-chain'"
            )
        resumed = self.bct.operations.resume(
            principal=self.owner, work_id="work",
            operation_id="restart-terminal-chain",
            capability="orchestrate", arguments=arguments,
        )
        self.assertEqual(Outcome.APPLIED, resumed.outcome)
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))

    def test_exact_dispatch_restart_reconciles_late_unknown_result(self):
        worker = self.attachment("worker-b")
        arguments = {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "restart-late-result",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "persist before restart",
            "acceptance": {"late": True}, "timeout_s": 5,
        }
        self.relay.lose_send_response = True
        self.relay.hide_results = True
        unknown = self.call("restart-late-dispatch", arguments)
        self.assertEqual(Outcome.UNKNOWN, unknown.outcome)
        sends_before = len([
            call for call in self.relay.calls if call["command"] == "send"
        ])
        self.relay.lose_send_response = False
        self.relay.hide_results = False
        with self.bct.store.transaction() as db:
            db.execute(
                "UPDATE operations SET state='RUNNING',outcome=NULL,error=NULL "
                "WHERE operation_id='restart-late-dispatch'"
            )
        resumed = self.bct.operations.resume(
            principal=self.owner, work_id="work",
            operation_id="restart-late-dispatch",
            capability="orchestrate", arguments=arguments,
        )
        self.assertEqual(Outcome.APPLIED, resumed.outcome)
        self.assertEqual(sends_before, len([
            call for call in self.relay.calls if call["command"] == "send"
        ]))

    def test_node_sync_rotates_stale_session_attachment(self):
        self.relay.session_id = "session456"
        result = self.call("sync-after-rcc-restart", {
            "operation": "node-sync", "session_id": "session",
            "instance_id": self.relay.instance_id,
            "nodes": [
                {"conversation_key": "conversation-b", "node_id": "worker-b",
                 "name": "Worker B", "role": "WORKER", "relay_role": "BCT_W1"},
            ],
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        rows = [
            item for item in snapshot["attachments"]
            if item["node_id"] == "worker-b" and item["tab_id"] == 201
        ]
        self.assertEqual(2, len(rows))
        self.assertEqual(1, sum(bool(item["active"]) for item in rows))

    def test_complete_observation_deactivates_omitted_attachments_and_connections(self):
        work = self.bct.store.get_work("work")
        selected = self.attachment("worker-b")
        omitted = self.attachment("worker-c")
        stale = self.bct.orchestration.reconcile_observed_attachments(
            work=work, session_id="session", instance_id=self.relay.instance_id,
            active_attachment_ids=[selected["attachment_id"]],
        )
        stale_ids = {item["attachment_id"] for item in stale}
        self.assertNotIn(selected["attachment_id"], stale_ids)
        self.assertIn(omitted["attachment_id"], stale_ids)

        snapshot = self.bct.orchestration.snapshot(
            work=work, session_id="session"
        )
        selected_after = next(
            item for item in snapshot["attachments"]
            if item["attachment_id"] == selected["attachment_id"]
            and item["generation"] == selected["generation"]
        )
        self.assertTrue(selected_after["active"])
        for attachment_id in stale_ids:
            active = [
                item for item in snapshot["attachments"]
                if item["attachment_id"] == attachment_id and item["active"]
            ]
            self.assertEqual([], active)
            connection = self.bct.store.get_connection("orch:" + attachment_id)
            self.assertFalse(connection["active"])

    def test_stale_pre_dispatch_attachment_is_not_applied_and_replaceable(self):
        work = self.bct.store.get_work("work")
        stale_worker = self.attachment("worker-b")
        replacement_worker = self.attachment("worker-c")
        self.bct.orchestration.create_assignment(
            work=work, session_id="session", assignment_id="stale-before-send",
            manager_epoch=1, worker_node_id="worker-b",
            attachment_id=stale_worker["attachment_id"],
            request={"instruction": "must not use a stale attachment"},
            roots=[str(self.root)], actions=["read"], acceptance={"done": True},
            dependencies=[],
        )
        self.bct.orchestration.reconcile_observed_attachments(
            work=work, session_id="session", instance_id=self.relay.instance_id,
            active_attachment_ids=[replacement_worker["attachment_id"]],
        )

        with self.assertRaisesRegex(
            PreconditionError, "ORCHESTRATION_ATTACHMENT_NOT_ROUTABLE"
        ):
            self.bct.orchestration.reserve_dispatch(
                work=work, session_id="session",
                assignment_id="stale-before-send", manager_epoch=1,
                message_id="msg.stale-before-send",
                dispatch_operation_id="orch.send.stale-before-send",
                payload={"must_not_dispatch": True},
            )
        failed = self.bct.orchestration.assignment(
            work=work, session_id="session", assignment_id="stale-before-send"
        )
        self.assertEqual("NOT_APPLIED", failed["state"])
        self.assertEqual("NOT_APPLIED", failed["attempts"][-1]["state"])
        self.assertTrue(failed["terminal_result"]["pre_dispatch"])
        self.assertEqual(
            "ORCHESTRATION_ATTACHMENT_NOT_ROUTABLE",
            failed["terminal_result"]["error"],
        )
        self.assertIsNone(failed["attempts"][-1]["dispatch_operation_id"])

        repeated_attachment, repeated = (
            self.bct.orchestration.resolve_dispatch_attachment(
                work=work, session_id="session",
                assignment_id="stale-before-send", manager_epoch=1,
            )
        )
        self.assertIsNone(repeated_attachment)
        self.assertEqual(failed["terminal_result"], repeated["terminal_result"])

        replaced = self.bct.orchestration.replace_worker(
            work=work, session_id="session", assignment_id="stale-before-send",
            manager_epoch=1, worker_node_id="worker-c",
            attachment_id=replacement_worker["attachment_id"],
            reason="the prior attachment disappeared before dispatch",
            evidence={"source": "complete RCC observation"},
        )
        self.assertEqual("stale-before-send", replaced["assignment_id"])
        self.assertEqual(2, replaced["current_generation"])
        self.assertEqual("QUEUED", replaced["state"])
        self.assertEqual("worker-c", replaced["attempts"][-1]["worker_node_id"])

    def test_cancelled_session_rejects_new_dispatch(self):
        cancelled = self.call("cancel", {
            "operation": "cancel", "session_id": "session",
            "manager_epoch": 1, "reason": "explicit cancellation test",
        })
        self.assertEqual(Outcome.APPLIED, cancelled.outcome)
        worker = self.attachment("worker-b")
        rejected = self.call("dispatch-after-cancel", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "must-not-run",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "must not dispatch",
            "acceptance": {"never": True},
        })
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome)
        self.assertFalse(any(
            call["command"] == "send" and "must not dispatch" in call["text"]
            for call in self.relay.calls
        ))


    def test_confirmed_pre_submit_failure_is_not_unknown(self):
        worker = self.attachment("worker-b")
        self.relay.confirmed_not_applied.add("BCT_W1")
        result = self.call("confirmed-not-applied", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "confirmed-not-applied-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "inspect one bounded input",
            "acceptance": {"read_only": True},
            "timeout_s": 5,
        })
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        current = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )["assignments"][0]
        self.assertEqual("NOT_APPLIED", current["state"])
        self.assertTrue(current["terminal_result"]["pre_dispatch"])
        self.assertFalse(any(
            call["command"] == "result" for call in self.relay.calls
        ))

    def test_submit_ack_is_persisted_before_result_readback(self):
        worker = self.attachment("worker-b")
        self.relay.return_submit_ack = True
        result = self.call("ack-then-result", {
            "operation": "dispatch", "session_id": "session",
            "manager_epoch": 1, "assignment_id": "ack-task",
            "worker_node_id": "worker-b",
            "attachment_id": worker["attachment_id"],
            "instruction": "return one exact result",
            "acceptance": {"read_only": True},
            "timeout_s": 5,
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        send = next(call for call in self.relay.calls if call["command"] == "send")
        self.assertIs(True, send["extra"]["returnOnAck"])
        snapshot = self.bct.orchestration.snapshot(
            work=self.bct.store.get_work("work"), session_id="session"
        )
        ack = [item for item in snapshot["mailbox"] if item["kind"] == "ACK"]
        self.assertEqual(1, len(ack))
        self.assertIsNotNone(ack[0]["delivered_at"])


if __name__ == "__main__":
    unittest.main()
