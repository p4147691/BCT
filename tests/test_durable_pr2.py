import tempfile
import threading
import unittest
from pathlib import Path

from bct.core.store import Store
from bct.core.models import ConflictError, Work
from bct.core.orchestration import _digest,_canonical,OrchestrationService
from bct.core.durable_pr2 import (acquire_lease,renew_lease,create_wake,commit_and_enqueue,
                                  reserve_delivery,record_attempt,acknowledge_delivery,recovery_snapshot,reserve_wake,record_wake)

class PR2Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.s=Store(Path(self.t.name)/"fixture.db")
        with self.s.transaction() as db:
            db.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?)",("w","test","[]","[]","o",1,"ACTIVE"))
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",("m","manager","MANAGER","G",1,1))
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",("worker","worker","WORKER","G",1,1))
            db.execute("INSERT INTO orchestration_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("s","w",1,"test","[]","[]","{}",1,"m",2,"ACTIVE","{}",1.,1.))
            db.execute("INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("att",1,"worker","test","inst","ext",1,1,"conv","endpoint","WORKER",None,1,1.))
            for name,state in (("consumer","PENDING"),("result","APPLIED"),("next","PENDING")):
                db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (name,"s",2,"req","{}","[]","[]","{}",state,1,
                            _canonical({"message":"result"}) if name=="result" else "{}",1.,1.))
            db.execute("INSERT INTO orchestration_assignment_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ("result",1,2,"worker","att",1,"APPLIED",None,None,1.,1.))
            db.execute("INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("r","s","result",1,"RESULT","worker",None,_digest({"message":"result"}),
                        _canonical({"message":"result"}),1.,None,None))
        self.lease=acquire_lease(self.s,session_id="s",manager_node_id="m",expected_epoch=2,ttl_s=1000,now=100.)
    def args(self):
        return dict(session_id="s",consumer_assignment_id="consumer",manager_epoch=2,
                    lease_token=self.lease["token"],decision_id="decision",request_digest="req",
                    decision={"next":"next"},results=[("r",_digest({"message":"result"}))],
                    actions=[{"delivery_id":"stable-id","target_node_id":"worker","attachment_id":"att",
                              "attachment_generation":1,"assignment_id":"next",
                              "assignment_generation":1,"payload":{"command":"test"}}],now=101.)
    def count(self,table):
        db=self.s._connect()
        try:return db.execute("SELECT count(*) FROM "+table).fetchone()[0]
        finally:db.close()
    def test_atomic_idempotent_reopen_and_ack(self):
        self.assertFalse(commit_and_enqueue(self.s,**self.args())["idempotent"])
        self.assertTrue(commit_and_enqueue(self.s,**self.args())["idempotent"])
        restarted=Store(self.s.path)
        self.assertEqual(["stable-id"], recovery_snapshot(restarted,session_id="s")["resendable"])
        r=reserve_delivery(restarted,delivery_id="stable-id",epoch=2,token=self.lease["token"],now=102.)
        record_attempt(restarted,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                       reservation_token=r["reservation_token"],phase="SEND_STARTED",now=103.)
        record_attempt(restarted,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                       reservation_token=r["reservation_token"],phase="DELIVERED",now=104.)
        self.assertTrue(acknowledge_delivery(restarted,delivery_id="stable-id",target_node_id="worker",
                        attachment_id="att",attachment_generation=1,ack_digest="ack",epoch=2,token=self.lease["token"],now=105.))
        self.assertFalse(acknowledge_delivery(restarted,delivery_id="stable-id",target_node_id="worker",
                        attachment_id="att",attachment_generation=1,ack_digest="ack",epoch=2,token=self.lease["token"],now=105.))
        self.assertEqual([],recovery_snapshot(Store(self.s.path),session_id="s")["resendable"])
    def test_bad_target_rolls_back_decision_and_receipt(self):
        args=self.args();args["actions"][0]["attachment_generation"]=99
        with self.assertRaises(ConflictError):commit_and_enqueue(self.s,**args)
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))
        self.assertEqual(0,self.count("orchestration_consumption_receipts"))
    def test_timeout_unknown_no_retry(self):
        commit_and_enqueue(self.s,**self.args())
        r=reserve_delivery(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],now=102.)
        kw=dict(delivery_id="stable-id",epoch=2,token=self.lease["token"],reservation_token=r["reservation_token"])
        record_attempt(self.s,**kw,phase="SEND_STARTED",now=103.)
        record_attempt(self.s,**kw,phase="UNKNOWN",now=104.)
        with self.assertRaises(ConflictError):
            reserve_delivery(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],now=105.)
        self.assertEqual([],recovery_snapshot(Store(self.s.path),session_id="s")["resendable"])
    def test_target_rotation_before_reserve_and_send_fails_closed(self):
        commit_and_enqueue(self.s,**self.args())
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='att'")
        with self.assertRaises(ConflictError):
            reserve_delivery(self.s,delivery_id="stable-id",epoch=2,
                             token=self.lease["token"],now=102.)
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=1 WHERE attachment_id='att'")
        reservation=reserve_delivery(self.s,delivery_id="stable-id",epoch=2,
                                     token=self.lease["token"],now=103.)
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_attachments SET active=0 WHERE attachment_id='att'")
        with self.assertRaises(ConflictError):
            record_attempt(self.s,delivery_id="stable-id",epoch=2,
                           token=self.lease["token"],reservation_token=reservation["reservation_token"],
                           phase="SEND_STARTED",now=104.)

    def test_pre_send_abort_can_requeue(self):
        commit_and_enqueue(self.s,**self.args())
        r=reserve_delivery(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],now=102.)
        record_attempt(self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                       reservation_token=r["reservation_token"],phase="PRE_SEND_ABORT",now=103.)
        self.assertEqual(["stable-id"],recovery_snapshot(self.s,session_id="s")["resendable"])

    def test_confirmed_not_applied_is_terminal_from_reserved_and_dispatching(self):
        arguments=self.args()
        arguments["actions"]=[
            {**arguments["actions"][0],"delivery_id":"not-applied-reserved"},
            {**arguments["actions"][0],"delivery_id":"not-applied-dispatching"},
        ]
        commit_and_enqueue(self.s,**arguments)
        for send_started in (False, True):
            with self.subTest(send_started=send_started):
                delivery_id=("not-applied-dispatching" if send_started
                             else "not-applied-reserved")
                reservation=reserve_delivery(self.s,delivery_id=delivery_id,epoch=2,
                                             token=self.lease["token"],now=102.)
                values=dict(delivery_id=delivery_id,epoch=2,token=self.lease["token"],
                            reservation_token=reservation["reservation_token"])
                if send_started:
                    record_attempt(self.s,**values,phase="SEND_STARTED",now=103.)
                record_attempt(self.s,**values,phase="CONFIRMED_NOT_APPLIED",now=104.)
                rows={row["delivery_id"]:row for row in
                      recovery_snapshot(self.s,session_id="s")["deliveries"]}
                self.assertEqual("NOT_APPLIED",rows[delivery_id]["state"])
                self.assertNotIn(delivery_id,recovery_snapshot(
                    self.s,session_id="s")["resendable"])

    def test_delivery_operations_join_caller_transaction(self):
        commit_and_enqueue(self.s,**self.args())
        with self.assertRaises(RuntimeError):
            with self.s.transaction() as db:
                reservation=reserve_delivery(
                    self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                    now=102.,_db=db,
                )
                record_attempt(
                    self.s,delivery_id="stable-id",epoch=2,token=self.lease["token"],
                    reservation_token=reservation["reservation_token"],
                    phase="SEND_STARTED",now=103.,_db=db,
                )
                raise RuntimeError("rollback")
        snapshot=recovery_snapshot(self.s,session_id="s")
        self.assertEqual("PENDING",snapshot["deliveries"][0]["state"])

    def test_stale_foreign_token_and_ack(self):
        commit_and_enqueue(self.s,**self.args())
        for token in ("wrong","",None):
            with self.assertRaises((ConflictError,ValueError,TypeError)):
                reserve_delivery(self.s,delivery_id="stable-id",epoch=2,token=token,now=102.)
        with self.assertRaises(ConflictError):
            acknowledge_delivery(self.s,delivery_id="stable-id",target_node_id="other",
                                 attachment_id="att",attachment_generation=1,ack_digest="ack",epoch=2,token=self.lease["token"],now=105.)
    def test_expired_takeover_fences_old_manager(self):
        with self.assertRaises(ConflictError):
            acquire_lease(self.s,session_id="s",manager_node_id="m",expected_epoch=2,
                          ttl_s=100,now=1200.)
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=3 WHERE session_id='s'")
        new=acquire_lease(self.s,session_id="s",manager_node_id="m",expected_epoch=3,ttl_s=100,
                          now=1200.)
        self.assertEqual(3,new["epoch"])
        with self.assertRaises(ConflictError):
            commit_and_enqueue(self.s,**self.args())
        with self.assertRaises(ConflictError):
            renew_lease(self.s,session_id="s",epoch=2,token=self.lease["token"],ttl_s=100,now=1201.)
    def test_takeover_recovers_only_pending_no_resend_unknown(self):
        commit_and_enqueue(self.s,**self.args())
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=3 WHERE session_id='s'")
        new=acquire_lease(self.s,session_id="s",manager_node_id="m",expected_epoch=3,
                          ttl_s=100,now=1200.)
        with self.assertRaises(ConflictError):
            reserve_delivery(self.s,delivery_id="stable-id",epoch=2,
                             token=self.lease["token"],now=1201.)
        row=reserve_delivery(Store(self.s.path),delivery_id="stable-id",epoch=3,
                             token=new["token"],now=1201.)
        self.assertEqual("stable-id",row["delivery_id"])

    def test_malformed_and_foreign_generation_fails_closed(self):
        arguments=self.args()
        for field,wrong in (("assignment_generation",0),("attachment_generation",0),
                            ("target_node_id","other"),("assignment_id","foreign")):
            modified=self.args()
            modified["actions"][0][field]=wrong
            with self.subTest(field=field),self.assertRaises((ValueError,ConflictError)):
                commit_and_enqueue(self.s,**modified)
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))

    def test_duplicate_delivery_id_conflict_is_atomic(self):
        args=self.args()
        args["actions"].append({**args["actions"][0]})
        with self.assertRaises(Exception):
            commit_and_enqueue(self.s,**args)
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))
        self.assertEqual(0,self.count("orchestration_dispatch_outbox"))

    def test_expiry_requires_external_takeover_and_preserves_session(self):
        with self.assertRaises(ConflictError):
            acquire_lease(self.s,session_id="s",manager_node_id="m",
                          expected_epoch=2,ttl_s=100,now=1200.)
        with self.s.transaction() as db:
            session=db.execute("SELECT manager_epoch FROM orchestration_sessions WHERE session_id='s'").fetchone()
            self.assertEqual(2,session[0])
            self.assertEqual(0,db.execute("SELECT count(*) FROM orchestration_manager_epochs").fetchone()[0])

    def test_sql_insert_failure_rolls_back_decision_and_outbox(self):
        with self.s.transaction() as db:
            db.execute("CREATE TRIGGER abort_outbox BEFORE INSERT ON orchestration_dispatch_outbox "
                       "BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(Exception):
            commit_and_enqueue(self.s,**self.args())
        for table in ("orchestration_consumption_decisions","orchestration_consumption_receipts",
                      "orchestration_dispatch_outbox"):
            self.assertEqual(0,self.count(table))

    def test_old_owner_cannot_ack_after_takeover(self):
        commit_and_enqueue(self.s,**self.args())
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=3 WHERE session_id='s'")
        acquire_lease(self.s,session_id="s",manager_node_id="m",expected_epoch=3,ttl_s=100,
                      now=1200.)
        with self.assertRaises(ConflictError):
            acknowledge_delivery(self.s,delivery_id="stable-id",target_node_id="worker",
                         attachment_id="att",attachment_generation=1,ack_digest="ack",
                         epoch=2,token=self.lease["token"],now=1201.)

    def test_wake_idempotence_and_mismatch(self):
        args=dict(wake_id="wake",session_id="s",assignment_id="result",generation=1,
                  result_message_id="r",result_digest=_digest({"message":"result"}))
        self.assertTrue(create_wake(self.s,**args))
        self.assertFalse(create_wake(self.s,**args))
        with self.assertRaises(ConflictError):
            create_wake(self.s,**{**args,"result_digest":"spoof"})
    def test_wake_lifecycle_and_unknown_fail_closed(self):
        args=dict(wake_id="wake",session_id="s",assignment_id="result",generation=1,
                  result_message_id="r",result_digest=_digest({"message":"result"}))
        create_wake(self.s,**args)
        res=reserve_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],now=102.)
        self.assertTrue(record_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],
                                    reservation_token=res["reservation_token"],outcome="UNKNOWN",now=103.))
        with self.assertRaises(ConflictError):
            reserve_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],now=104.)
        self.assertEqual("UNKNOWN",recovery_snapshot(Store(self.s.path),session_id="s")["wakes"][0]["state"])

    def test_wake_ack_and_pre_send_abort(self):
        args=dict(wake_id="wake",session_id="s",assignment_id="result",generation=1,
                  result_message_id="r",result_digest=_digest({"message":"result"}))
        create_wake(self.s,**args)
        r=reserve_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],now=102.)
        kw=dict(wake_id="wake",epoch=2,token=self.lease["token"],reservation_token=r["reservation_token"])
        record_wake(self.s,**kw,outcome="PRE_SEND_ABORT",now=103.)
        r=reserve_wake(self.s,wake_id="wake",epoch=2,token=self.lease["token"],now=104.)
        kw["reservation_token"]=r["reservation_token"]
        record_wake(self.s,**kw,outcome="DELIVERED",now=105.)
        self.assertTrue(record_wake(self.s,**kw,outcome="ACKNOWLEDGED",now=106.))
        self.assertFalse(record_wake(self.s,**kw,outcome="ACKNOWLEDGED",now=107.))

    def test_two_connections_lease_race(self):
        outcome=[]
        gate=threading.Barrier(2)
        def work():
            gate.wait()
            try:
                acquire_lease(Store(self.s.path),session_id="s",manager_node_id="m",
                              expected_epoch=3,ttl_s=50,now=1200.)
                outcome.append("won")
            except ConflictError: outcome.append("lost")
        with self.s.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=3 WHERE session_id='s'")
        x=threading.Thread(target=work);y=threading.Thread(target=work)
        x.start();y.start();x.join();y.join()
        self.assertCountEqual(["won","lost"],outcome)
    def _real_takeover(self, *, current_time):
        # Construct a genuine orchestration history, manager attachments,
        # old pending wake and a proven-unsent queued assignment in temp SQLite.
        with self.s.transaction() as db:
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                       ("new-manager","new","MANAGER","G",1,1))
            for node,att,instance in (("m","manager-old","manager-instance-old"),
                                      ("new-manager","manager-new","manager-instance-new")):
                db.execute("INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                           ("s",node,"MANAGER",1))
                db.execute("INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (att,1,node,"rcc",instance,"manager-session",17,18,
                            "manager-conversation","endpoint","MANAGER",None,1,1.))
                db.execute("INSERT INTO connections VALUES(?,?,?,?,?,?,?)",
                           ("orch:"+att,node,"rcc","{}", "endpoint",1,1))
            db.execute("INSERT INTO orchestration_manager_epochs VALUES(?,?,?,?,?,?,?)",
                       ("s",2,"m","ORIGINAL","{}",1.,None))
            db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("queued","s",2,"request","{}","[]","[]","{}","QUEUED",
                        1,"{}",1.,1.))
            db.execute("INSERT INTO orchestration_assignment_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ("queued",1,2,"worker","att",1,"QUEUED",None,None,1.,1.))
            row=db.execute("SELECT * FROM orchestration_assignments WHERE assignment_id='result'").fetchone()
            old=OrchestrationService(self.s)._record_manager_wake(
                db,session_id="s",assignment=row,generation=1,result_message_id="r",
                result_digest=_digest({"message":"result"}),now=1.)
            self.assertEqual("PENDING",old["state"])
            old_event=old["event_id"]
        create_wake(self.s,wake_id="durable-wake",session_id="s",assignment_id="result",
                    generation=1,result_message_id="r",result_digest=_digest({"message":"result"}))
        commit_and_enqueue(self.s,**self.args())
        work=Work("w","test",tuple(),frozenset(),"o",1,"ACTIVE")
        session=OrchestrationService(self.s).takeover_manager(
            work=work,session_id="s",expected_epoch=2,manager_node_id="new-manager",
            reason="isolated fixture takeover")
        self.assertEqual(3,session["manager_epoch"])
        self.assertEqual(2,session["plan_revision"])
        new=acquire_lease(Store(self.s.path),session_id="s",manager_node_id="new-manager",
                          expected_epoch=3,ttl_s=100,now=current_time)
        self.assertEqual(3,new["epoch"])
        self.assertNotEqual(self.lease["token"],new["token"])
        with self.s.transaction() as db:
            history=db.execute("SELECT epoch,manager_node_id,ended_at FROM orchestration_manager_epochs WHERE session_id='s' ORDER BY epoch").fetchall()
            self.assertEqual([2,3],[x["epoch"] for x in history])
            self.assertIsNotNone(history[0]["ended_at"])
            self.assertEqual("new-manager",history[1]["manager_node_id"])
            self.assertIsNone(history[1]["ended_at"])
            wakes=db.execute("SELECT manager_epoch,state,manager_node_id FROM orchestration_manager_wakes WHERE session_id='s' ORDER BY manager_epoch").fetchall()
            self.assertEqual([(2,"STALE","m"),(3,"PENDING","new-manager")],
                             [(x["manager_epoch"],x["state"],x["manager_node_id"]) for x in wakes])
            attempt=db.execute("SELECT manager_epoch,state,dispatch_operation_id FROM orchestration_assignment_attempts WHERE assignment_id='queued'").fetchone()
            self.assertEqual((3,"QUEUED",None),tuple(attempt))
            reconciliation=db.execute("SELECT decision,manager_epoch FROM orchestration_reconciliations WHERE assignment_id='queued'").fetchone()
            self.assertEqual(("ADOPT_QUEUED_NOT_DISPATCHED",3),tuple(reconciliation))
            events={x[0] for x in db.execute("SELECT kind FROM events")}
            self.assertTrue({"ORCHESTRATION_MANAGER_WAKE_STALE","ORCHESTRATION_MANAGER_WAKE_RECORDED",
                             "ORCHESTRATION_MANAGER_TAKEOVER"}.issubset(events))
            receipt=db.execute("SELECT revoked_epoch,successor_epoch,reason,token_digest FROM orchestration_durable_lease_revocations WHERE session_id='s'").fetchone()
            self.assertEqual((2,3,"SUPERSEDED_BY_SESSION_EPOCH"),tuple(receipt)[:3])
            self.assertNotEqual(self.lease["token"],receipt["token_digest"])
        with self.assertRaises(ConflictError):
            renew_lease(self.s,session_id="s",epoch=2,token=self.lease["token"],ttl_s=20,now=current_time+1)
        with self.assertRaises(ConflictError):
            reserve_wake(self.s,wake_id="durable-wake",epoch=2,token=self.lease["token"],now=current_time+1)
        with self.assertRaises(ConflictError):
            reserve_delivery(self.s,delivery_id="stable-id",epoch=2,
                             token=self.lease["token"],now=current_time+1)
        with self.assertRaises(ConflictError):
            acknowledge_delivery(self.s,delivery_id="stable-id",target_node_id="worker",
                         attachment_id="att",attachment_generation=1,ack_digest="ack",
                         epoch=2,token=self.lease["token"],now=current_time+1)
        return new

    def test_real_takeover_supersedes_active_lease(self):
        # Existing lease expires_at=1100; takeover at 200 is before expiry.
        self._real_takeover(current_time=200.)
        self.assertEqual(1,self.count("orchestration_durable_lease_revocations"))

    def test_real_takeover_supersedes_expired_lease(self):
        self._real_takeover(current_time=1200.)
        self.assertEqual(1,self.count("orchestration_durable_lease_revocations"))

    def test_legacy_consumed_unchanged(self):
        commit_and_enqueue(self.s,**self.args())
        db=self.s._connect()
        try:self.assertIsNone(db.execute("SELECT consumed_at FROM orchestration_mailbox WHERE message_id='r'").fetchone()[0])
        finally:db.close()

if __name__=="__main__":unittest.main()
