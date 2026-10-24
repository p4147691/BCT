import hashlib,sqlite3,tempfile,unittest
from pathlib import Path
from bct.worker_result_inbox import WorkerResultInbox
from bct.worker_result_recovery import WorkerResultRecovery
class RecoveryTests(unittest.TestCase):
 def test_busy_idle_duplicate_restart_and_partial_ack(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/"same_inbox.sqlite"
   with sqlite3.connect(p) as db: WorkerResultInbox.install(db)
   db.close()
   box=WorkerResultInbox(p); bindings={}
   for i in range(5):
    did=f"d{i}";text=f"한글 🧭 결과 원문 {i}"*200
    box.ingest(delivery_id=did,work_id="w",manager_uuid="m",worker_uuid=f"worker{i}",
      result_text=text,result_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
    bindings[did]=dict(delivery_id=did,work_id="w",manager_uuid="m",worker_uuid=f"worker{i}",manager_epoch=3)
   fake=[]
   rec=WorkerResultRecovery(box)
   self.assertEqual(rec.run_once(manager_uuid="m",manager_epoch=3,idle=False,bindings=bindings,fake_dispatch=fake.append)["state"],"BUSY_QUEUED")
   self.assertEqual(fake,[])
   self.assertEqual(rec.run_once(manager_uuid="m",manager_epoch=3,idle=True,bindings=bindings,fake_dispatch=fake.append)["state"],"PLANNED_NO_SEND")
   self.assertEqual(len(fake),1)
   self.assertNotIn("result_text",str(fake))
   again=WorkerResultRecovery(WorkerResultInbox(p))
   self.assertEqual(again.run_once(manager_uuid="m",manager_epoch=3,idle=True,bindings=bindings,fake_dispatch=fake.append)["state"],"ALREADY_PLANNED")
   self.assertEqual(len(fake),1)
   for did in ("d0","d1"):
    row=box.pending_all(manager_uuid="m")[0]
    self.assertEqual(row["delivery_id"],did)
    box.decide(delivery_id=did,manager_uuid="m",decision="DEFER",receipt_id=did,reason="검토",observed_sha=row["result_sha256"])
   self.assertEqual(len(again.inbox.pending_all(manager_uuid="m")),3)
 def test_unknown_and_binding_mismatch_never_plan(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/"db.sqlite"
   with sqlite3.connect(p) as db:WorkerResultInbox.install(db)
   db.close()
   box=WorkerResultInbox(p);text="미확정 🔎"
   box.ingest(delivery_id="d",work_id="w",manager_uuid="m",worker_uuid="worker",
      result_text=text,result_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),capture_state="UNKNOWN")
   rec=WorkerResultRecovery(box)
   binding={"d":dict(delivery_id="d",work_id="w",manager_uuid="m",worker_uuid="worker",manager_epoch=1)}
   self.assertEqual(rec.run_once(manager_uuid="m",manager_epoch=1,idle=True,bindings=binding)["state"],"ESCALATE_UNKNOWN")
   self.assertEqual(rec.run_once(manager_uuid="m",manager_epoch=2,idle=True,bindings=binding)["state"],"ESCALATE_BINDING_MISMATCH")
 def test_core_entrypoint_fails_closed_without_binding(self):
  from bct.delivery_continuation_recovery import DeliveryContinuationRecovery
  from bct.worker_result_recovery import WorkerResultRecovery
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/"db.sqlite"
   with sqlite3.connect(p) as db:WorkerResultInbox.install(db)
   db.close()
   b=WorkerResultInbox(p);text="작업 완료 🧭"
   b.ingest(delivery_id="d",work_id="w",manager_uuid="m",worker_uuid="x",
     result_text=text,result_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
   core=DeliveryContinuationRecovery(None,None)
   self.assertEqual(core.plan_worker_result_inbox(inbox=b,manager_uuid="m",
     manager_epoch=1,idle=True,verified_bindings={})["state"],"ESCALATE_BINDING_MISMATCH")

if __name__=="__main__": unittest.main()
