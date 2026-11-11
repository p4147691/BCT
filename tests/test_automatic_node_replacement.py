"""Core automatic new-chat recovery from precise RCC identity and BCT receipts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.automatic_node_replacement import AutomaticNodeReplacement
from bct.chain_manager_recovery import ChainManagerRecoveryLedger
from bct.conversation_network import (
    configure_conversation_scope,conversation_scope_directory,
)
from bct.core.models import Work,Outcome,OperationState,OperationResult
from bct.core.store import Store
from bct.node_recovery import NodeRecoveryLedger,observe_node
from bct.send_delayed_message import DurableWatchLedger

A="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
S="cccccccc-cccc-cccc-cccc-cccccccccccc"
SUCCESSOR="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
INSTANCE="f"*32
SESSION="a"*32


class FakeOps:
    def __init__(self,store,work,fixture):
        self.store=store
        self.work=work
        self.fixture=fixture
        self.sends=0
        self.discoveries=0
        self.effect="APPLIED"

    def run(self, *, principal,work_id,operation_id,capability,arguments):
        assert work_id==self.work.work_id and capability=="browser"
        assert principal.principal_id==self.work.owner_principal_id
        cmd=arguments["command"]
        if cmd=="target-discover":
            self.discoveries+=1
            if self.fixture.ready_after_discover:
                self.fixture.original_ready=True
            return OperationResult(
                operation_id=operation_id,state=OperationState.FINISHED,
                outcome=Outcome.APPLIED,evidence={},
                output={"targets":[{
                    "target_ref":"rcc-target-v1.fake",
                    "target_kind":"window","window_id":11,
                }]},
            )
        if cmd!="create-and-send":
            raise AssertionError("unexpected command "+cmd)
        assert arguments["mode"]=="tab"
        assert arguments["instance_id"]==INSTANCE
        assert "Original work_id" in arguments["text"]
        self.sends+=1
        outcome=self.effect
        evidence={
            "command":"create-and-send",
            "rcc_command":"new-chat-send",
            "operation_id":operation_id,"instance_id":INSTANCE,
            "session_id":SESSION,"tab_id":21,"window_id":11,
            "conversation_key":SUCCESSOR,
            "result_hash":"a"*64,
            "result_state":"RESULT_PERSISTED",
        }
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id,work_id,principal.principal_id,"requesthash",
                 "browser","create-and-send","FINISHED",outcome,
                 json.dumps(evidence),"",self.work.assignment_epoch,"test",1.0,1.0),
            )
        if outcome=="APPLIED":
            self.fixture.created=True
        return self.store.get_operation_for(
            operation_id=operation_id,work_id=work_id,
            principal_id=principal.principal_id,
        )


class AutoNewChatTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.store=Store(Path(t.name)/"state.sqlite")
        self.work=self.store.create_work(Work(
            "original-work","Keep previous task",(t.name,),
            frozenset({"browser"}),"owner",
        ))
        DurableWatchLedger(self.store)
        self.created=False
        self.successor_observable=True
        self.original_ready=False
        self.ready_after_discover=False
        self.original_roles=["Worker"]
        self.original=B
        self.orig_scope=configure_conversation_scope(
            self.store,conversation_key=self.original,display_name="B",
            scope_name="Project",role_tags=self.original_roles,
            node_memo="original memo",assigned_task="original-task",
        )
        ctx=json.dumps({
            "work_id":self.work.work_id,
            "manager_conversation_key":A,
            "manager_instance_id":INSTANCE,
            "supervisor_conversation_key":S,
            "supervisor_instance_id":INSTANCE,
            "instance_id":INSTANCE,
        })
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches "
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES('original-task',1,?,'original-turn','original-send',"
                "'WATCHING',?)",(B,ctx),
            )
        self.ledger=NodeRecoveryLedger(self.store)
        self.case="auto-node-case-1"
        self.auto=AutomaticNodeReplacement(
            bct=SimpleNamespace(
                store=self.store,
                operations=FakeOps(self.store,self.work,self),
            ),
            status_provider=self.snapshot,
        )
        self.explicit_failure()

    def snapshot(self):
        rows=[{
            "conversation_uuid":self.original,"status":"CONFIRMED",
            "tab_id":10,"window_id":11,"generating":False,
            "roles":self.original_roles,
            "connection":{"disconnected":False},
            "telemetry":{"user_attention":(
                {} if self.original_ready else {"kind":"NEW_CHAT_REQUIRED"}
            )},
        }]
        tabs=[{
            "conversation_key":self.original,"presence":"OPEN",
            "tab_id":10,"window_id":11,
            "connection":{"disconnected":False},
            "telemetry":{"user_attention":(
                {} if self.original_ready else {"kind":"NEW_CHAT_REQUIRED"}
            )},
            "conversation_scope":{
                "scope_id":self.orig_scope["scope_id"],
                "scope_name":"Project","role_tags":self.original_roles,
            },
        }]
        if self.created and self.successor_observable:
            known=conversation_scope_directory(
                self.store,conversation_keys=[SUCCESSOR],
            ).get(SUCCESSOR) or {}
            with self.store._readonly() as db:
                registered = db.execute(
                    "SELECT 1 FROM conversation_network_conversations "
                    "WHERE conversation_key=?", (SUCCESSOR,),
                ).fetchone() is not None
            rows.append({
                "conversation_uuid":SUCCESSOR,
                "status":"CONFIRMED" if registered else "TEMPORARY",
                "tab_id":21,"window_id":11,"generating":False,
                "connection":{"disconnected":False},
                "telemetry":{},
            })
            tabs.append({
                "conversation_key":SUCCESSOR,"presence":"OPEN",
                "tab_id":21,"window_id":11,
                "connection":{"disconnected":False},
                "conversation_scope":{
                    "scope_id":known.get("scope_id") or "",
                    "scope_name":known.get("scope_name") or "",
                    "role_tags":known.get("role_tags") or [],
                }
            })
        return {"monitor":{
            "current_nodes":{
                "observation":{"state":"FRESH"},"observed_at":100,
                "items":rows,
            },
            "rcc":{"instances":[{
                "instance_id":INSTANCE,"session_id":SESSION,
                "state":"OPEN","cached":False,"tabs":tabs,
            }]},
        }}

    def explicit_failure(self):
        view={"current_nodes":{
            "observation":{"state":"FRESH"},"observed_at":100,
            "items":[{
                "conversation_uuid":self.original,"status":"CONFIRMED",
                "tab_id":10,"window_id":11,
                "generating":False,
                "connection":{"disconnected":False},
                "telemetry":{"user_attention":{"kind":"NEW_CHAT_REQUIRED"}},
            }],
        }}
        for kind in ("CHECK","RECHECK"):
            self.ledger.check(
                work=self.work,case_id=self.case,
                task_id="original-task",conversation_key=self.original,
                evidence=observe_node(view,self.original),kind=kind,
            )
        self.ledger.mark_automatic_observation(
            work=self.work,case_id=self.case,
            state="RECOVERY_NEEDED",reason="NODE_NEW_CHAT_REQUIRED",
        )

    def promote_original_role(self, role):
        self.original_roles=[role]
        configure_conversation_scope(
            self.store,conversation_key=self.original,display_name=role,
            scope_name="" if role=="Supervisor" else "Project",
            role_tags=[role],
        )

    def seed_other_watch_and_return(self, *, manager, supervisor):
        ctx=json.dumps({
            "work_id":self.work.work_id,
            "manager_conversation_key":manager,
            "manager_instance_id":INSTANCE,
            "supervisor_conversation_key":supervisor,
            "supervisor_instance_id":INSTANCE,
        })
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches "
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES('other-task',1,?,'other-turn','sent-other','WATCHING',?)",
                (S,ctx),
            )
        ChainManagerRecoveryLedger(self.store).record_pending(
            task_id="other-task",generation=1,work_id=self.work.work_id,
            direction_id="original-direction",worker_conversation_key=S,
            manager_conversation_key=manager,
            supervisor_conversation_key=supervisor,
            response_turn_key="other-turn",response_sha256="f"*64,
            return_payload="Completed and safely stored",
        )

    def test_manager_auto_replace_moves_epoch_scoped_watches_and_returns(self):
        self.promote_original_role("Manager")
        with self.store.transaction() as db:
            row=db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id='original-task'",
            ).fetchone()
            ctx=json.loads(row["context_json"])
            ctx["manager_conversation_key"]=B
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? "
                "WHERE task_id='original-task'",(json.dumps(ctx),),
            )
        self.seed_other_watch_and_return(manager=B,supervisor=S)
        result=self.auto.run_once()
        self.assertEqual("REPLACED",result["events"][0]["status"],result)
        binding=result["events"][0]["manager_binding_recovery"]
        self.assertEqual(2,binding["updated_watches"])
        self.assertEqual(1,binding["rebound_checkpoints"])
        self.assertTrue(binding["atomic"])
        with self.store._readonly() as db:
            other=db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id='other-task'",
            ).fetchone()
        self.assertEqual(
            SUCCESSOR,json.loads(other["context_json"])["manager_conversation_key"],
        )
        self.assertEqual(SUCCESSOR,ChainManagerRecoveryLedger(self.store).get(
            task_id="other-task",generation=1,
        )["active_manager_conversation_key"])

    def add_supervisor_work(self, *, owner="owner", name="additional-work"):
        extra=self.store.create_work(Work(
            name, "A different conversation network, same global S",
            self.work.roots,frozenset({"browser"}),owner,
        ))
        ctx=json.dumps({
            "work_id":extra.work_id,
            "manager_conversation_key":A,
            "manager_instance_id":INSTANCE,
            "supervisor_conversation_key":B,
            "supervisor_instance_id":INSTANCE,
        })
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO delayed_send_watches "
                "(task_id,generation,conversation_key,response_turn_id,"
                "source_send_receipt,state,context_json) "
                "VALUES(?,1,?,'other-work-turn','other-work-send','WATCHING',?)",
                (name+"-task",S,ctx),
            )
        ChainManagerRecoveryLedger(self.store).record_pending(
            task_id=name+"-task",generation=1,work_id=extra.work_id,
            direction_id="original-direction",worker_conversation_key=S,
            manager_conversation_key=A,supervisor_conversation_key=B,
            response_turn_key="other-work-turn",response_sha256="b"*64,
            return_payload="Completed on other Work",
        )
        return extra

    def test_global_supervisor_rebinds_other_same_owner_work_atomically(self):
        self.promote_original_role("Supervisor")
        self.seed_other_watch_and_return(manager=A,supervisor=B)
        self.add_supervisor_work()
        result=self.auto.run_once()
        self.assertEqual("REPLACED",result["events"][0]["status"],result)
        changed=result["events"][0]["supervisor_binding_recovery"]
        self.assertCountEqual(
            [self.work.work_id,"additional-work"],
            changed["affected_works"],
        )
        self.assertEqual(2,changed["updated_watches"])
        self.assertEqual(2,changed["updated_returns"])
        with self.store._readonly() as db:
            other=db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id='additional-work-task'",
            ).fetchone()
        self.assertEqual(
            SUCCESSOR,json.loads(other["context_json"])["supervisor_conversation_key"],
        )

    def test_global_supervisor_cannot_silently_mutate_another_owners_work(self):
        self.promote_original_role("Supervisor")
        self.add_supervisor_work(owner="other-principal",name="foreign-work")
        result=self.auto.run_once()
        self.assertEqual("RECONCILE_REQUIRED",result["events"][0]["status"])
        # Preparation is durable, while the conflicted cross-Work transfer
        # transaction rolled back without a partial role/binding change.
        self.assertEqual("REPLACEMENT_PREPARED",self.ledger.get(
            work=self.work,case_id=self.case,
        )["state"])
        with self.store._readonly() as db:
            foreign=db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id='foreign-work-task'",
            ).fetchone()
        self.assertEqual(
            B,json.loads(foreign["context_json"])["supervisor_conversation_key"],
        )
        # This is a scoped owner conflict, not permission to repeat
        # the exact already successful external new-chat Operation.
        self.assertEqual(1,self.auto.bct.operations.sends)
        self.auto.run_once()
        self.assertEqual(1,self.auto.bct.operations.sends)

    def test_global_supervisor_auto_replace_moves_work_return_bindings(self):
        self.promote_original_role("Supervisor")
        self.seed_other_watch_and_return(manager=A,supervisor=B)
        with self.store.transaction() as db:
            row=db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id='original-task'",
            ).fetchone()
            ctx=json.loads(row["context_json"])
            ctx["supervisor_conversation_key"]=B
            db.execute(
                "UPDATE delayed_send_watches SET context_json=? "
                "WHERE task_id='original-task'",(json.dumps(ctx),),
            )
        result=self.auto.run_once()
        self.assertEqual("REPLACED",result["events"][0]["status"],result)
        binding=result["events"][0]["supervisor_binding_recovery"]
        self.assertEqual(2,binding["updated_watches"])
        self.assertEqual(1,binding["updated_returns"])
        self.assertTrue(binding["atomic"])
        with self.store._readonly() as db:
            other=db.execute(
                "SELECT context_json FROM delayed_send_watches "
                "WHERE task_id='other-task'",
            ).fetchone()
        self.assertEqual(
            SUCCESSOR,json.loads(other["context_json"])["supervisor_conversation_key"],
        )
        checkpoint = ChainManagerRecoveryLedger(self.store).get(
            task_id="other-task",generation=1,
        )
        self.assertEqual(B, checkpoint["supervisor_conversation_key"])
        self.assertEqual(SUCCESSOR, checkpoint["active_supervisor_conversation_key"])

    def test_one_atomic_new_chat_restores_previous_role_and_task(self):
        result=self.auto.run_once()
        self.assertEqual("REPLACED",result["events"][0]["status"],result)
        self.assertEqual(1,self.auto.bct.operations.sends)
        self.assertEqual(1,self.auto.bct.operations.discoveries)
        self.assertEqual("REPLACED",self.ledger.get(
            work=self.work,case_id=self.case,
        )["state"])
        new=conversation_scope_directory(
            self.store,conversation_keys=[SUCCESSOR],
        )[SUCCESSOR]
        self.assertIn("Worker",new["role_tags"])
        self.assertEqual("original memo",new["node_memo"])
        self.assertEqual("original-task",new["assigned_task"])
        with self.store._readonly() as db:
            self.assertEqual("CANCELLED", db.execute(
                "SELECT state FROM delayed_send_watches WHERE task_id='original-task'"
            ).fetchone()["state"])
        self.assertEqual([],self.auto.run_once()["events"])
        self.assertEqual(1,self.auto.bct.operations.sends)

    def test_original_recovers_between_discovery_and_submit_without_new_chat(self):
        self.ready_after_discover=True
        result=self.auto.run_once()
        self.assertEqual("RECOVERED_ORIGINAL",result["events"][0]["status"],result)
        self.assertEqual(0,self.auto.bct.operations.sends)
        self.assertEqual(1,self.auto.bct.operations.discoveries)
        self.assertEqual("RECOVERED",self.ledger.get(
            work=self.work,case_id=self.case,
        )["state"])
        with self.store._readonly() as db:
            self.assertEqual("WATCHING",db.execute(
                "SELECT state FROM delayed_send_watches WHERE task_id='original-task'"
            ).fetchone()["state"])

    def test_reboot_after_applied_before_successor_uuid_observed(self):
        self.successor_observable=False
        first=self.auto.run_once()
        self.assertEqual("WAIT_VERIFIED_CREATED_UUID",first["events"][0]["status"],first)
        self.assertEqual(1,self.auto.bct.operations.sends)
        self.successor_observable=True
        restarted=AutomaticNodeReplacement(
            bct=self.auto.bct,status_provider=self.snapshot,
        )
        result=restarted.run_once()
        self.assertEqual("REPLACED",result["events"][0]["status"],result)
        self.assertEqual(1,self.auto.bct.operations.sends)
        self.assertEqual(1,self.auto.bct.operations.discoveries)

    def test_previous_unknown_worker_effect_blocks_unrelated_new_chat(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE delayed_send_watches SET state='UNKNOWN' "
                "WHERE task_id='original-task'",
            )
        result=self.auto.run_once()
        self.assertEqual(
            "ORIGINAL_EXTERNAL_EFFECT_UNKNOWN",result["events"][0]["status"],
        )
        self.assertEqual(0,self.auto.bct.operations.sends)
        self.assertEqual("RECOVERY_NEEDED",self.ledger.get(
            work=self.work,case_id=self.case,
        )["state"])

    def test_unknown_new_chat_cannot_be_cancelled_as_if_never_sent(self):
        self.auto.bct.operations.effect="UNKNOWN"
        self.assertEqual(
            "NEW_CHAT_UNKNOWN",self.auto.run_once()["events"][0]["status"],
        )
        self.original_ready=True
        result=self.auto.run_once()
        self.assertEqual("DUAL_NODE_EFFECT_RECONCILE_REQUIRED",
                         result["events"][0]["status"])
        self.assertEqual(1,self.auto.bct.operations.sends)

    def test_effect_unknown_keeps_exact_intent_and_does_not_retry(self):
        self.auto.bct.operations.effect="UNKNOWN"
        first=self.auto.run_once()
        self.assertEqual("NEW_CHAT_UNKNOWN",first["events"][0]["status"],first)
        self.assertEqual("PAUSED",self.ledger.get(
            work=self.work,case_id=self.case,
        )["state"])
        later=self.auto.run_once()
        self.assertEqual("NEW_CHAT_UNKNOWN",later["events"][0]["status"],later)
        self.assertEqual(1,self.auto.bct.operations.sends)
        self.assertFalse(self.created)

    def test_no_positive_new_chat_required_never_creates(self):
        with self.store.transaction() as db:
            rows=list(db.execute(
                "SELECT sequence,evidence_json FROM node_recovery_checks WHERE case_id=?",
                (self.case,),
            ))
            for row in rows:
                data=json.loads(row["evidence_json"])
                data["reason"]="NODE_CONNECTION_DISCONNECTED"
                db.execute(
                    "UPDATE node_recovery_checks SET evidence_json=? "
                    "WHERE case_id=? AND sequence=?",
                    (json.dumps(data),self.case,row["sequence"]),
                )
        result=self.auto.run_once()
        self.assertEqual("EXACT_NEW_CHAT_NOT_CONFIRMED",result["events"][0]["status"])
        self.assertEqual(0,self.auto.bct.operations.sends)


if __name__=="__main__":
    unittest.main()
