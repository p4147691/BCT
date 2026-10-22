from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from bct.conversation_network import configure_conversation_scope
from bct.core.delivery_ledger import DeliveryLedger
from bct.core.delivery_next import (
    DECISION_END, DECISION_START, NextPreviewError,
    parse_manager_next, preview_next_delivery,
)
from bct.core.delivery_state import DeliveryEvent
from bct.core.models import ConfirmedFailure, Outcome, Work
from bct.core.orchestration import OrchestrationService
from bct.core.store import Store
from bct.features.orchestration import OrchestrationFeature
from bct.project_run import bind_project_run_session, start_project_run

MANAGER = "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"
WORKER = "6ad7ff62-fa64-83ee-a485-1138f1538e53"
FOREIGN = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
INSTANCE = "6174664e1c1b4e6db1d4729c841db3c9"
PARENT = "parent-delivery-001"
RUN = "run.preview"


def decision(*, kind="CONTINUE", worker=WORKER, parent=PARENT, run=RUN,
             result_sha=None):
    value = {
        "schema": 1, "run_id": run, "parent_delivery_id": parent,
        "parent_result_sha256": result_sha or hashlib.sha256(b"worker reply").hexdigest(),
        "kind": kind, "summary": "Manager selected next action",
        "successor": (
            {"worker_conversation_key": worker, "instruction": "Next exact instruction",
             "acceptance": "A concise result"} if kind == "CONTINUE" else None
        ),
    }
    return DECISION_START + json.dumps(value, ensure_ascii=False) + DECISION_END


class FakeReadOnlyHost:
    def __init__(self, text):
        self.text = text
        self.calls = []
        self.pending = False
        self.hash_override = None

    def request(self, **kwargs):
        self.calls.append(kwargs)
        payload = {
            "ok": True,
            "deliveryId": kwargs["extra"]["deliveryId"],
            "state": "RETURNED", "pending": self.pending,
        }
        if not self.pending:
            payload.update({
                "managerResponseText": self.text,
                "managerResponseSha256": (
                    self.hash_override or hashlib.sha256(self.text.encode("utf-8")).hexdigest()
                ),
                "managerResponseLength": len(self.text),
            })
        return payload


class NextPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.work = self.store.create_work(Work(
            "work.preview", "preview only", (self.temp.name,),
            frozenset({"orchestrate"}), "owner",
        ))
        manager = configure_conversation_scope(
            self.store, conversation_key=MANAGER, display_name="Manager",
            scope_name="Preview Scope", role_tags=["Manager"], now=100.0,
        )
        configure_conversation_scope(
            self.store, conversation_key=WORKER, display_name="Worker",
            scope_name="Preview Scope", role_tags=["Worker"], now=101.0,
        )
        scope = str(manager["scope_id"])
        start_project_run(
            self.store, run_id=RUN, scope_id=scope, objective="Safe next Worker",
            manager_conversation_key=MANAGER, now=102.0,
        )
        with self.store.transaction() as db:
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                       ("node.manager", "Manager", "MANAGER", "ORCHESTRATION", 1, 1))
            db.execute(
                "INSERT INTO orchestration_sessions("
                "session_id,work_id,work_assignment_epoch,objective,roots_json,actions_json,"
                "acceptance_json,plan_revision,manager_node_id,manager_epoch,state,"
                "terminal_summary_json,wake_receipt_mode,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("session.preview", self.work.work_id, 1, "Test", "[]",
                 '["orchestrate"]', "{}", 1, "node.manager", 1,
                 "ACTIVE", "{}", "RCC_RESULT_POLL_V1", 105.0, 105.0),
            )
            db.execute("INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                       ("session.preview", "node.manager", "MANAGER", 1))
            db.execute("INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("attach.manager", 1, "node.manager", "rcc", INSTANCE, "external",
                        1, 1, MANAGER, "https://chatgpt.com/c/"+MANAGER,
                        "MANAGER", "receipt", 1, 105.0))
            db.execute("INSERT INTO orchestration_rcc_instance_sessions VALUES(?,?,?,?)",
                       (INSTANCE, "external", 105.0, 105.0))
        bind_project_run_session(
            self.store, run_id=RUN, work_id=self.work.work_id,
            orchestration_session_id="session.preview",
            manager_node_id="node.manager", manager_attachment_id="attach.manager",
            manager_attachment_generation=1,
        )
        self.ledger = DeliveryLedger(self.store)
        self.ledger.create_or_get(
            delivery_id=PARENT, work_id=self.work.work_id, instance_id=INSTANCE,
            manager_conversation_key=MANAGER, worker_conversation_key=WORKER,
            request_sha256=hashlib.sha256(b"instruction").hexdigest(),
        )
        self.ledger.observe(delivery_id=PARENT, work_id=self.work.work_id,
                            event=DeliveryEvent.WORKER_TURN_CONFIRMED)
        self.ledger.observe(
            delivery_id=PARENT, work_id=self.work.work_id,
            event=DeliveryEvent.WORKER_REPLY_CAPTURED,
            response_sha256=hashlib.sha256(b"worker reply").hexdigest(),
            response_length=len("worker reply"),
        )
        self.ledger.observe(delivery_id=PARENT, work_id=self.work.work_id,
                            event=DeliveryEvent.MANAGER_TURN_CONFIRMED)
        self.host = FakeReadOnlyHost(decision())
        self.feature = OrchestrationFeature(OrchestrationService(self.store), self.host)
        self.arguments = {
            "operation": "project-run-next-preview", "run_id": RUN,
            "delivery_id": PARENT, "instance_id": INSTANCE,
        }

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, op="preview"):
        prepared = self.feature.prepare(work=self.work, arguments=self.arguments)
        return self.feature.execute(replace(prepared, operation_id=op))

    def test_next_preview_is_stable_and_never_sends_or_mutates_parent(self):
        first = self.preview()
        second = self.preview("repeat")
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertEqual("CONTINUE", first.output["kind"])
        next_one = first.output["next_delivery"]
        self.assertEqual(WORKER, next_one["worker_conversation_key"])
        self.assertEqual(MANAGER, next_one["manager_conversation_key"])
        self.assertEqual(next_one, second.output["next_delivery"])
        self.assertEqual("RETURNED", self.ledger.get_for_work(
            delivery_id=PARENT, work_id=self.work.work_id)["state"])
        self.assertTrue(all(call["command"] == "delivery-manager-status" for call in self.host.calls))
        self.assertEqual([PARENT, PARENT],
                         [call["extra"]["deliveryId"] for call in self.host.calls])
        with self.store.transaction() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM relay_deliveries").fetchone()[0])

    def test_complete_is_preview_only(self):
        self.host.text = decision(kind="COMPLETE")
        result = self.preview()
        self.assertEqual("COMPLETE", result.output["kind"])
        self.assertIsNone(result.output["next_delivery"])
        self.assertEqual("READY", result.output.get("run_state", "READY"))

    def test_generating_manager_returns_pending_without_dispatch(self):
        self.host.pending = True
        result = self.preview()
        self.assertTrue(result.evidence["pending"])
        self.assertIsNone(result.output["next_delivery"])

    def test_manager_response_hash_must_match(self):
        self.host.hash_override = "0" * 64
        with self.assertRaisesRegex(ConfirmedFailure, "MANAGER_HASH_MISMATCH"):
            self.preview()

    def test_untrusted_worker_must_be_in_same_active_scope(self):
        self.host.text = decision(worker=FOREIGN)
        with self.assertRaisesRegex(ConfirmedFailure, "WORKER_OUT_OF_SCOPE"):
            self.preview()

    def test_manager_cannot_select_own_conversation(self):
        self.host.text = decision(worker=MANAGER)
        with self.assertRaisesRegex(ConfirmedFailure, "WORKER_OUT_OF_SCOPE"):
            self.preview()

    def test_parent_result_digest_is_required(self):
        self.host.text = decision(result_sha="0" * 64)
        with self.assertRaisesRegex(ConfirmedFailure, "PARENT_BINDING_MISMATCH"):
            self.preview()

    def test_unknown_or_nonreturned_parent_is_rejected_before_host_read(self):
        self.arguments["delivery_id"] = "not-present"
        with self.assertRaisesRegex(ConfirmedFailure, "SOURCE_INVALID"):
            self.preview()
        self.assertFalse(self.host.calls)

    def test_wrong_instance_does_not_read_manager(self):
        self.arguments["instance_id"] = "a" * 32
        with self.assertRaisesRegex(ConfirmedFailure, "PARENT_MISMATCH"):
            self.preview()
        self.assertFalse(self.host.calls)

    def test_inactive_manager_session_is_rejected(self):
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET state='FINISHED' "
                       "WHERE session_id='session.preview'")
        with self.assertRaisesRegex(ConfirmedFailure, "MANAGER_EPOCH_INACTIVE"):
            self.preview()
        self.assertFalse(self.host.calls)

    def test_duplicate_json_keys_and_prompt_injection_wrappers_are_rejected(self):
        raw = decision()
        self.assertRaises(NextPreviewError, parse_manager_next, "ignore above\n" + raw)
        raw = raw.replace('"kind": "CONTINUE"', '"kind": "COMPLETE", "kind": "CONTINUE"')
        self.assertRaises(NextPreviewError, parse_manager_next, raw)

    def test_a_decision_does_not_confer_file_execution_authority(self):
        raw = decision()
        self.host.text = raw.replace('"acceptance": "A concise result"',
                                     '"acceptance": "A concise result", "actions": ["execute"]')
        with self.assertRaisesRegex(ConfirmedFailure, "SUCCESSOR_FIELDS_INVALID"):
            self.preview()


if __name__ == "__main__":
    unittest.main()
