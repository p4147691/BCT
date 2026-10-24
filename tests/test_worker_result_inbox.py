import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from bct.worker_result_inbox import WorkerResultInbox

class Inbox(unittest.TestCase):
 def test_full_recovery_ack_and_busy_coalescing(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"inbox.sqlite"
   with sqlite3.connect(p) as c:WorkerResultInbox.install(c)
   c.close()
   box=WorkerResultInbox(p)
   for n,text,state in [(1,"결과 전문 🦊","VERIFIED"),(2,"UNKNOWN 결과 🔎","UNKNOWN")]:
    kw=dict(delivery_id=f"d{n}",work_id="w",manager_uuid="manager",worker_uuid="worker",result_text=text,
            result_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),capture_state=state)
    self.assertEqual(box.ingest(**kw),"STORED")
    self.assertEqual(box.ingest(**kw),"DUPLICATE")
   self.assertEqual(box.coalesced_wake("manager")["pending_count"],2)
   original=box.pending_all(manager_uuid="manager",limit=1)
   self.assertEqual(len(original),2)
   self.assertEqual(original[0]["result_text"],"결과 전문 🦊")
   self.assertEqual(box.pending_all(manager_uuid="manager"),original)
   self.assertEqual(box.decide(delivery_id="d1",manager_uuid="manager",decision="COMPLETE",receipt_id="ack-1",
      reason="verified",observed_sha=original[0]["result_sha256"]),"DECIDED")
   self.assertEqual(box.coalesced_wake("manager")["delivery_ids"],["d2"])
   self.assertEqual(box.decide(delivery_id="d2",manager_uuid="manager",decision="DEFER",receipt_id="ack-2",
      reason="read-only reconcile; no resend",observed_sha=original[1]["result_sha256"]),"DECIDED")
   self.assertEqual(box.coalesced_wake("manager")["pending_count"],0)
   with sqlite3.connect(p) as c:
    self.assertEqual(c.execute("select count(*) from worker_result_inbox").fetchone()[0],2)
   c.close()
 def test_unknown_not_automatically_acknowledged(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"db.sqlite"
   with sqlite3.connect(p) as c:WorkerResultInbox.install(c)
   c.close()
   b=WorkerResultInbox(p)
   text="미확정"
   b.ingest(delivery_id="x",work_id="w",manager_uuid="m",worker_uuid="w",result_text=text,
     result_sha256=hashlib.sha256(text.encode()).hexdigest(),capture_state="UNKNOWN")
   self.assertEqual(b.pending_all(manager_uuid="m")[0]["decision"],None)
   with self.assertRaises(ValueError):b.decide(delivery_id="x",manager_uuid="m",decision="COMPLETE",receipt_id="r",reason="none",observed_sha="bad")
 def test_five_busy_results_one_wake_partial_ack_and_recovery(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/"five.sqlite"
   with sqlite3.connect(p) as conn:WorkerResultInbox.install(conn)
   conn.close()
   inbox=WorkerResultInbox(p)
   for i in range(5):
    content=("결과 %d 🦊 "%i)+("긴 원문 "+"가"*4000)
    digest=hashlib.sha256(content.encode("utf-8")).hexdigest()
    self.assertEqual(inbox.ingest(delivery_id=f"d{i}",work_id="work",
      manager_uuid="manager",worker_uuid=f"worker{i}",result_text=content,
      result_sha256=digest),"STORED")
   self.assertEqual(inbox.wake_signal(manager_uuid="manager"),{
     "signal":"RESULTS_PENDING","wake_count":1,"pending_count":5,"effect":"NONE_NO_SEND"})
   metadata={f"d{i}":{"priority":i,"summary":f"검토 항목 {i}"} for i in range(5)}
   listing=inbox.pending_summaries(manager_uuid="manager",priority_by_delivery=metadata)
   self.assertEqual([x["delivery_id"] for x in listing],["d4","d3","d2","d1","d0"])
   self.assertTrue(all("긴 원문" not in str(x) for x in listing))
   self.assertEqual(len({x["result_sha256"] for x in listing}),5)
   for item in listing[:2]:
    self.assertEqual(inbox.decide(delivery_id=item["delivery_id"],manager_uuid="manager",
       decision="DEFER",receipt_id="decision-"+item["delivery_id"],reason="추가 검토",
       observed_sha=item["result_sha256"]),"DECIDED")
   self.assertEqual(inbox.wake_signal(manager_uuid="manager")["pending_count"],3)
   self.assertEqual(len(inbox.pending_all(manager_uuid="manager",limit=2)),3)
   with sqlite3.connect(p) as conn:
    self.assertEqual(conn.execute("SELECT COUNT(*) FROM worker_result_inbox").fetchone()[0],5)
   conn.close()

if __name__=="__main__":unittest.main()
