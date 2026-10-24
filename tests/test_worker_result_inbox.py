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
if __name__=="__main__":unittest.main()
