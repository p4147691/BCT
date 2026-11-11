"""Atomic RCC new-chat receipt as exact Node Recovery inheritance proof."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bct.conversation_network import configure_conversation_scope, conversation_scope_directory
from bct.core.models import Work
from bct.core.store import Store
from bct.node_recovery import NodeRecoveryLedger, observe_node
from bct.send_delayed_message import DurableWatchLedger

OLD = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NEW = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
OTHER = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def node_view(key, *, missing=False):
    return {"current_nodes":{
        "observation":{"state":"FRESH"}, "observed_at":100,
        "items":[] if missing else [{
            "conversation_uuid":key,"status":"CONFIRMED",
            "tab_id":1,"window_id":2,"generating":False,
            "network_id":"project","roles":["Worker"],
            "connection":{"disconnected":False},
        }],
    }}


class AtomicReplacementReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/"state.sqlite")
        self.work=self.store.create_work(Work(
            "actual-work","restore original Worker",(tmp.name,),
            frozenset({"browser"}),"owner",
        ))
        self.ledger=NodeRecoveryLedger(self.store)
        configure_conversation_scope(
            self.store,conversation_key=OLD,display_name="Old Worker",
            scope_name="Test project",role_tags=["Worker"],
            node_memo="original task",assigned_task="task-1",
        )
        configure_conversation_scope(
            self.store,conversation_key=NEW,display_name="Candidate",
            role_tags=[],
        )
        self.ledger.check(
            work=self.work,case_id="auto-node-replace-1",task_id="",
            conversation_key=OLD,
            evidence=observe_node(node_view(OLD,missing=True),OLD),kind="CHECK",
        )
        self.ledger.pause(
            work=self.work,case_id="auto-node-replace-1",reason="explicit new chat required",
        )
        self.evidence=observe_node(node_view(NEW),NEW)
        self.opid="auto-node-newchat-001"

    def store_result(self, *, key=NEW,outcome="APPLIED",
                     result_state="RESULT_PERSISTED"):
        proof={"command":"create-and-send","rcc_command":"new-chat-send",
               "result_state":result_state,
               "conversation_key":key,"result_hash":"a"*64,
               "session_id":"b"*32,"instance_id":"c"*32,
               "tab_id":21,"window_id":11}
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.opid,self.work.work_id,"owner","requesthash","browser",
                 "new-chat","FINISHED",outcome,json.dumps(proof),"",
                 self.work.assignment_epoch,"policy-revision",1.0,1.0),
            )

    def test_verified_atomic_new_chat_result_can_commit_role_and_task(self):
        self.store_result()
        prepared=self.ledger.prepare_replace(
            work=self.work,case_id="auto-node-replace-1",
            successor_conversation_key=NEW,
            inheritance_task_id="auto-inherit-task-1",
            successor_evidence=self.evidence,
            atomic_inheritance_operation_id=self.opid,
        )
        self.assertEqual("REPLACEMENT_PREPARED",prepared["state"])
        result=self.ledger.commit_replace(
            work=self.work,case_id="auto-node-replace-1",
            successor_evidence=self.evidence,
        )
        self.assertEqual("REPLACED",result["state"])
        self.assertEqual(NEW,result["successor_conversation_key"])
        after=conversation_scope_directory(
            self.store,conversation_keys=[OLD,NEW],
        )
        self.assertIn("Worker",after[NEW]["role_tags"])
        self.assertEqual("original task",after[NEW]["node_memo"])
        self.assertEqual("task-1",after[NEW]["assigned_task"])
        self.assertTrue(self.ledger.commit_replace(
            work=self.work,case_id="auto-node-replace-1",
            successor_evidence=self.evidence,
        )["duplicate"])

    def test_wrong_uuid_rejected_before_any_role_effect(self):
        self.store_result(key=OTHER)
        with self.assertRaisesRegex(ValueError,"ATOMIC_RECEIPT_IDENTITY_INVALID"):
            self.ledger.prepare_replace(
                work=self.work,case_id="auto-node-replace-1",
                successor_conversation_key=NEW,
                inheritance_task_id="auto-inherit-task-1",
                successor_evidence=self.evidence,
                atomic_inheritance_operation_id=self.opid,
            )
        self.assertEqual("PAUSED",self.ledger.get(
            work=self.work,case_id="auto-node-replace-1")["state"])

    def test_unknown_effect_never_authorizes_replace(self):
        self.store_result(outcome="UNKNOWN")
        with self.assertRaisesRegex(ValueError,"ATOMIC_RECEIPT_NOT_APPLIED"):
            self.ledger.prepare_replace(
                work=self.work,case_id="auto-node-replace-1",
                successor_conversation_key=NEW,
                inheritance_task_id="auto-inherit-task-1",
                successor_evidence=self.evidence,
                atomic_inheritance_operation_id=self.opid,
            )

    def test_missing_response_never_authorizes_replace(self):
        self.store_result(result_state="SUBMITTED")
        with self.assertRaisesRegex(ValueError,"ATOMIC_RECEIPT_IDENTITY_INVALID"):
            self.ledger.prepare_replace(
                work=self.work,case_id="auto-node-replace-1",
                successor_conversation_key=NEW,
                inheritance_task_id="auto-inherit-task-1",
                successor_evidence=self.evidence,
                atomic_inheritance_operation_id=self.opid,
            )


if __name__ == "__main__":
    unittest.main()
