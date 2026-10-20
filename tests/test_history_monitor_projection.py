import json
import sqlite3
import unittest
from contextlib import closing
from tests.test_history_readonly import HistoryReadOnlyTests
from bct.core.history_monitor_projection import history_view

class HistoryMonitorProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = HistoryReadOnlyTests("test_integrity")
        self.fixture.setUp()
        self.path = self.fixture.db
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
              INSERT INTO conversation_network_projects VALUES ('p1');
              INSERT INTO conversation_network_conversations VALUES ('c1','Group chat');
              INSERT INTO conversation_network_memberships VALUES ('p1','c1','ACTIVE');
            """)

    def tearDown(self):
        self.fixture.tearDown()

    def test_separates_current_and_historical(self):
        x=history_view(self.path,work_ids=['w1'],project_ids=['p1'])
        self.assertEqual(x['schema'],'BCT_MONITOR_HISTORY_VIEW_V1')
        self.assertEqual([r['node_id'] for r in x['current']['nodes']],['n2'])
        self.assertEqual([r['node_id'] for r in x['history']['nodes']],['n1'])
        self.assertEqual(x['history']['works'][0]['session_ids'],['s1'])
        self.assertEqual(x['history']['projects'][0]['conversation_keys'],['c1'])
        self.assertIsNone(x['history']['nodes'][0]['historical_name'])
        self.assertEqual(x['current']['nodes'][0]['live_presence'],'UNVERIFIED')
        self.assertFalse(x['full_history_verified'])

    def test_no_message_bodies_or_full_status(self):
        body=json.dumps(history_view(self.path,work_ids=['w1']))
        self.assertNotIn('digest1',body)
        self.assertNotIn('payload_json',body)
        self.assertNotIn('"FULL"',body)

    def test_rejects_live_name_and_unbounded_selections(self):
        with self.assertRaisesRegex(ValueError,'LIVE_DATABASE_FORBIDDEN'):
            history_view(r'D:\\BCT\\runtime\\state\\state.sqlite')
        with self.assertRaisesRegex(ValueError,'SELECTION_INVALID'):
            history_view(self.path,work_ids=['w']*13)
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):
            history_view(self.path,work_ids=['w1','w1'])

    def test_absent_work_is_not_empty_result(self):
        with self.assertRaises(KeyError):
            history_view(self.path,work_ids=['missing'])

if __name__=='__main__':
    unittest.main()
