import sqlite3
import tempfile
import unittest
from pathlib import Path
from bct.recovery_card import build_card
from bct.recovery_supervisor import capability_manifest
from bct.recovery_succession import collect_succession, SuccessorLedger

class SuccessionIntegration(unittest.TestCase):
 def test_successor_b_preserves_complete_and_queries_unknown_without_resend(self):
  with tempfile.TemporaryDirectory() as folder:
   db=Path(folder)/"bct.sqlite"
   with sqlite3.connect(db) as c:
    c.executescript("""CREATE TABLE works(work_id TEXT,state TEXT,request_summary TEXT);
       CREATE TABLE operations(operation_id TEXT,work_id TEXT,capability TEXT,state TEXT,outcome TEXT);
       CREATE TABLE github_run_inbox(subscription_id TEXT,conclusion TEXT,state TEXT);
       CREATE TABLE github_run_inbox_recipients(subscription_id TEXT,work_id TEXT);
       INSERT INTO works VALUES('A','ACTIVE','작업 복구 🧭');
       INSERT INTO operations VALUES('o1','A','read','FINISHED','APPLIED');
       INSERT INTO github_run_inbox VALUES('inbox1','success','FINISHED');
       INSERT INTO github_run_inbox_recipients VALUES('inbox1','A');""")
   c.close()
   cards=[]
   for state in ["COMPLETE","UNKNOWN"]:
    card=build_card(predecessor={"work_id":"A","conversation":"감독관 A"},
      observations={"worktree":"isolation"},verified_evidence={"worktree":"fixture"},
      protected_resources=["main","RCC"],next_minimal_step="상태 확인")
    card["task_state"]=state
    card["result_sha256"]="a"*64 if state=="COMPLETE" else None
    card["card_sha256"]=state+"-"+card["card_sha256"]
    cards.append(card)
   manifest=capability_manifest(successor="일반 노드 B",scope="A",
     available_tools={"bct_status"},expressly_allowed=set())
   pkg=collect_succession(db,"A",cards,manifest)
   self.assertEqual(pkg["inbox_receipts"][0]["subscription_id"],"inbox1")
   self.assertEqual(pkg["cards"][0]["next_minimal_step"],"PRESERVE_VERIFIED_RESULT")
   self.assertEqual(pkg["cards"][1]["next_minimal_step"],"READ_ONLY_STATUS_RECONCILIATION_NO_RESEND")
   ledger=SuccessorLedger(Path(folder)/"succession.sqlite")
   self.assertEqual(ledger.assign(pkg,"B")["state"],"ASSIGNED_PREPARED")
   self.assertEqual(ledger.assign(pkg,"B")["state"],"DUPLICATE")
   self.assertEqual(ledger.assign(pkg,"C")["state"],"CONFLICT_OTHER_SUCCESSOR")
   ack=ledger.acknowledge(pkg,"B")
   self.assertEqual(ack,ledger.acknowledge(pkg,"B"))
   self.assertIn("UNKNOWN",ack)
   self.assertEqual(ack["next_minimal_step"],"RECONCILE_UNCERTAIN_TASKS")
   self.assertIn("복구",str(pkg))
   self.assertEqual(pkg["effect"],"NONE_READ_ONLY")
if __name__=="__main__":unittest.main()
