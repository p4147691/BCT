import unittest
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing
from bct.core.history_readonly import connect,historical_nodes,timeline,integrity,current_nodes,work_history

class HistoryReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"fixture.sqlite"
        with closing(sqlite3.connect(self.db)) as d:
            d.executescript("""
            CREATE TABLE nodes(node_id TEXT,name TEXT,role TEXT,active INTEGER,revision INTEGER);
            CREATE TABLE connections(connection_id TEXT,node_id TEXT,active INTEGER);
            CREATE TABLE works(work_id TEXT);
            CREATE TABLE orchestration_sessions(session_id TEXT,work_id TEXT,state TEXT,created_at REAL);
            CREATE TABLE orchestration_session_nodes(node_id TEXT,session_id TEXT,session_role TEXT);
            CREATE TABLE orchestration_assignments(assignment_id TEXT,session_id TEXT,created_at REAL);
            CREATE TABLE orchestration_mailbox(message_id TEXT,session_id TEXT,kind TEXT,created_at REAL);
            CREATE TABLE orchestration_consumption_decisions(decision_id TEXT,session_id TEXT,created_at REAL);
            CREATE TABLE orchestration_consumption_receipts(result_message_id TEXT,session_id TEXT,created_at REAL);
            CREATE TABLE orchestration_manager_wakes(event_id TEXT,session_id TEXT,created_at REAL);
            INSERT INTO nodes VALUES('n1','Previous worker','WORKER',0,1);
            INSERT INTO nodes VALUES('n2','Current worker','WORKER',1,1);
            INSERT INTO works VALUES('w1');
            INSERT INTO orchestration_sessions VALUES('s1','w1','FINISHED',1.0);
            INSERT INTO orchestration_session_nodes VALUES('n1','s1','WORKER');
            INSERT INTO orchestration_assignments VALUES('a1','s1',2.0);
            INSERT INTO orchestration_mailbox VALUES('r1','s1','RESULT',3.0);
            """)
    def tearDown(self):
        self.tmp.cleanup()
    def test_node_past_participation_survives_inactive(self):
        n=historical_nodes(self.db)[0]
        self.assertEqual(n["active"],0)
        self.assertEqual(n["sessions"][0]["work_id"],"w1")
        self.assertEqual(n["historical_identity_coverage"],"CURRENT_IDENTITY_ONLY")
    def test_timeline_explicitly_nonfull(self):
        t=timeline(self.db,"s1")
        self.assertFalse(t["full_history_verified"])
        self.assertEqual([e["kind"] for e in t["timeline"]],["ASSIGNMENT","RESULT"])
    def test_missing_session(self):
        with self.assertRaises(KeyError):timeline(self.db,"missing")
    def test_readonly_disallows_write(self):
        with closing(connect(self.db)) as d:
            with self.assertRaises(sqlite3.OperationalError):
                d.execute("INSERT INTO nodes VALUES('n2','x','WORKER',1,1)")
    def test_current_nodes_does_not_infer_availability(self):
        n=current_nodes(self.db)
        self.assertEqual([x['node_id'] for x in n],['n2'])
        self.assertEqual(n[0]['live_presence'],'UNVERIFIED_REQUIRES_RCC')
    def test_work_history_isolated(self):
        w=work_history(self.db,'w1')
        self.assertEqual(len(w['sessions']),1)
        self.assertFalse(w['full_history_verified'])
    def test_integrity(self):
        r=integrity(self.db)
        self.assertEqual(r["integrity"],["ok"])
        self.assertEqual(r["foreign_key_errors"],[])
