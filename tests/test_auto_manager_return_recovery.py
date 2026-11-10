"""Automatic Manager return delivery under Core crash and uncertain RCC effects."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.chain_manager_recovery import ChainManagerRecoveryLedger
from bct.core.models import Principal, Outcome
from bct.core.store import Store
from bct.features.rcc import BrowserFeature
from bct.integrations.rcc import RelayEffectUnknown
from bct.send_delayed_message import SendDelayedMessageService
from bct.service import BCT
from tests.test_delayed_send_rcc_flow import (
    SimulatedRcc, INSTANCE, SESSION, WORKER, MANAGER, SUPERVISOR,
)


class EmptyManagerReturnLedgerTests(unittest.TestCase):
    def test_uninitialized_core_has_no_phantom_return_and_no_schema_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.sqlite")
            before = self._tables(store)
            recovery = ChainManagerRecoveryLedger(store, initialize=False)
            self.assertEqual([], recovery.pending_manager_deliveries())
            self.assertEqual(before, self._tables(store))
            self.assertNotIn("chain_manager_return_checkpoints", before)

    @staticmethod
    def _tables(store):
        with store._readonly() as db:
            return {str(row["name"]) for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}


class AutoManagerReturnRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        policy = root / "bct.toml"
        policy.write_text(chr(10).join([
            "[policy]", 'normal_actions=["browser"]',
            "approval_actions=[]", "",
        ]), encoding="utf-8")
        self.bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
        self.rcc = SimulatedRcc()
        self.rcc.manager_disconnected = True
        self.rcc.supervisor_disconnected = True
        self.browser = BrowserFeature(self.rcc, store=self.bct.store)
        self.bct.operations._features["browser"] = self.browser
        self.principal = Principal("tester", "test", frozenset({"browser"}))
        self.work = self.bct.create_work(
            work_id="automatic-return-work",
            request_summary="Recover every completed Manager return without rerunning B",
            roots=[str(root)], actions=["browser"], principal=self.principal,
        )
        self.service = SendDelayedMessageService(
            store=self.bct.store, browser_feature=self.browser,
            operations=self.bct.operations,
        )
        self.ledger = ChainManagerRecoveryLedger(self.bct.store)
        self.rcc.reply(WORKER, "Baseline unrelated previous response.")
        prompt = "Complete this original Worker task."
        self.assertEqual(
            Outcome.APPLIED,
            self.bct.operations.run(
                principal=self.principal, work_id=self.work.work_id,
                operation_id="auto-recovery-arm", capability="browser",
                arguments={
                    "command": "send-delayed-message",
                    "task_id": "auto-return-task",
                    "instance_id": INSTANCE, "conversation_key": WORKER,
                    "manager_conversation_key": MANAGER,
                    "manager_instance_id": INSTANCE,
                    "supervisor_conversation_key": SUPERVISOR,
                    "supervisor_instance_id": INSTANCE,
                    "planned_send_operation_id": "auto-original-send",
                    "planned_send_text": prompt,
                    "execution_path": "DIRECTION_DECLARED",
                    "chain_direction_id": "original-direction",
                },
            ).outcome,
        )
        self.assertEqual(
            Outcome.APPLIED,
            self.bct.operations.run(
                principal=self.principal, work_id=self.work.work_id,
                operation_id="auto-original-send", capability="browser",
                arguments={
                    "command": "send-message",
                    "instance_id": INSTANCE, "session_id": SESSION,
                    "tab_id": 10, "window_id": 11,
                    "conversation_key": WORKER, "text": prompt,
                },
            ).outcome,
        )
        self.rcc.reply(WORKER, chr(10).join([
            "Final completed task result.",
            "NEXT TASK — MANAGER: Accept exact completed original Worker result.",
        ]))
        events = self.service.poll_once()["events"]
        self.assertEqual("MANAGER_RECOVERY_PENDING", events[0]["status"])
        self.assertEqual("PENDING", self.pending()["delivery_state"])
        self.assertEqual(1, len(self.rcc.sent))

    def pending(self):
        return self.ledger.get(task_id="auto-return-task", generation=1)

    def test_many_saved_returns_are_fairly_delivered_without_duplication(self):
        for index in range(6):
            task_id = "z-return-%02d" % index
            with self.bct.store.transaction() as db:
                db.execute(
                    "INSERT INTO delayed_send_watches "
                    "(task_id,generation,conversation_key,response_turn_id,"
                    "source_send_receipt,state,context_json) "
                    "SELECT ?,generation,conversation_key,response_turn_id,"
                    "source_send_receipt,'MANAGER_RECOVERY_PENDING',context_json "
                    "FROM delayed_send_watches WHERE task_id='auto-return-task'",
                    (task_id,),
                )
            self.ledger.record_pending(
                task_id=task_id, generation=1, work_id=self.work.work_id,
                direction_id="original-direction",
                worker_conversation_key=WORKER,
                manager_conversation_key=MANAGER,
                supervisor_conversation_key=SUPERVISOR,
                response_turn_key="stored-turn-%02d" % index,
                response_sha256="a" * 64,
                return_payload="Original completed result %d" % index,
            )
        self.rcc.manager_disconnected = False
        for _ in range(10):
            self.service.poll_once(limit=2)
        self.assertEqual(8, len(self.rcc.sent))
        self.assertEqual(7, len([
            row for row in self.rcc.sent if row[0] == MANAGER
        ]))
        for index in range(6):
            self.assertEqual(
                "RETURNED_TO_MANAGER",
                self.ledger.get(task_id="z-return-%02d" % index, generation=1)["delivery_state"],
            )
        self.assertEqual("RETURNED_TO_MANAGER", self.pending()["delivery_state"])
        self.service.poll_once(limit=2)
        self.assertEqual(8, len(self.rcc.sent))

    def test_generating_manager_is_not_sent_recovery_prompt_until_idle(self):
        self.rcc.manager_disconnected = False
        self.rcc.manager_generating = True
        self.service.poll_once()
        self.assertEqual("PENDING", self.pending()["delivery_state"])
        self.assertEqual(1, len(self.rcc.sent))
        self.rcc.manager_generating = False
        result = self.service.poll_once()
        self.assertEqual("MANAGER_RETURN_AUTODELIVERED", result["events"][-1]["status"])
        self.assertEqual("RETURNED_TO_MANAGER", self.pending()["delivery_state"])
        self.assertEqual(2, len(self.rcc.sent))
        self.service.poll_once()
        self.assertEqual(2, len(self.rcc.sent))

    def test_crash_after_browser_applied_before_checkpoint_finalization(self):
        self.rcc.manager_disconnected = False
        with patch.object(
            ChainManagerRecoveryLedger, "finish_pending_manager_delivery",
            side_effect=RuntimeError("simulated_core_hard_kill_after_submit"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated_core"):
                self.service.poll_once()
        self.assertEqual("DELIVERING", self.pending()["delivery_state"])
        self.assertEqual(2, len(self.rcc.sent))
        # New Core service resumes the same preclaimed operation_id.
        restarted = SendDelayedMessageService(
            store=self.bct.store, browser_feature=self.browser,
            operations=self.bct.operations,
        )
        events = restarted.poll_once()["events"]
        self.assertEqual("MANAGER_RETURN_AUTODELIVERED", events[-1]["status"])
        self.assertEqual("RETURNED_TO_MANAGER", self.pending()["delivery_state"])
        self.assertEqual(2, len(self.rcc.sent))
        restarted.poll_once()
        self.assertEqual(2, len(self.rcc.sent))

    def test_external_effect_unknown_never_replays_original_delivery(self):
        self.rcc.manager_disconnected = False
        original = self.rcc.request
        injected = []
        def uncertain_after_effect(**kwargs):
            command = kwargs.get("command")
            extra = kwargs.get("extra") or {}
            if (command in {"send-to-tab", "rcc_send_message_to_tab"}
                    and extra.get("conversationKey") == MANAGER and not injected):
                injected.append(True)
                original(**kwargs)
                raise RelayEffectUnknown("lost host acknowledgement after real submit")
            return original(**kwargs)
        with patch.object(self.rcc, "request", side_effect=uncertain_after_effect):
            result = self.service.poll_once()
        self.assertEqual(1, len(injected))
        self.assertEqual("MANAGER_RETURN_UNKNOWN", result["events"][-1]["status"])
        self.assertEqual("UNKNOWN", self.pending()["delivery_state"])
        self.assertEqual(2, len(self.rcc.sent))
        self.service.poll_once()
        self.assertEqual(2, len(self.rcc.sent))


if __name__ == "__main__":
    unittest.main()
