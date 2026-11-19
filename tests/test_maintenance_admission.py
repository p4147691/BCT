from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from bct_maintenance.admission import admission_fence, assert_quiescent, history_digest
from bct_maintenance.errors import PreconditionError


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'state').mkdir()
        self.db = sqlite3.connect(self.root / 'state/state.sqlite', isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript('''
          CREATE TABLE operations(operation_id TEXT, capability TEXT, state TEXT,
                                  created_at REAL, updated_at REAL);
          CREATE TABLE resource_claims(resource_key TEXT,operation_id TEXT,unresolved INT);
          CREATE TABLE background_jobs(operation_id TEXT);
          CREATE TABLE orchestration_durable_leases(expires_at REAL);
          CREATE TABLE orchestration_dispatch_outbox(state TEXT);
          INSERT INTO operations VALUES('old','execute','RUNNING',10,10);
          INSERT INTO resource_claims VALUES('resource','old',1);
        ''')

    def test_old_synchronous_receipt_requires_exact_pin_and_remains_unchanged(self):
        pin = history_digest(self.db)
        with self.assertRaises(PreconditionError):
            assert_quiescent(self.db)
        with patch('bct_maintenance.admission.psutil.boot_time', return_value=20):
            evidence = assert_quiescent(self.db, pin)
        self.assertEqual(evidence['retained_operations'], 1)
        self.assertEqual(history_digest(self.db), pin)
        self.assertEqual(self.db.execute('select state from operations').fetchone()[0], 'RUNNING')

    def test_current_boot_work_or_durable_job_cannot_be_waived_by_pin(self):
        pin = history_digest(self.db)
        with patch('bct_maintenance.admission.psutil.boot_time', return_value=5):
            with self.assertRaises(PreconditionError):
                assert_quiescent(self.db, pin)
        self.db.execute("insert into background_jobs values('old')")
        with self.assertRaises(PreconditionError):
            assert_quiescent(self.db, pin)

    def test_unknown_history_is_retained_but_runtime_effect_still_blocks(self):
        self.db.execute("update operations set state='FINISHED',capability='browser'")
        pin = history_digest(self.db)
        self.assertEqual(assert_quiescent(self.db, pin)['retained_claims'], 1)
        self.db.execute("update operations set capability='deploy'")
        with self.assertRaises(PreconditionError):
            assert_quiescent(self.db, history_digest(self.db))

    def test_changed_history_and_live_dispatch_block(self):
        pin = history_digest(self.db)
        self.db.execute('update operations set updated_at=11')
        with self.assertRaises(PreconditionError):
            assert_quiescent(self.db, pin)
        pin = history_digest(self.db)
        self.db.execute('insert into orchestration_durable_leases values(?)', (time.time()+60,))
        with self.assertRaisesRegex(PreconditionError, 'IN_FLIGHT_DISPATCH'):
            assert_quiescent(self.db, pin)
        self.db.execute('delete from orchestration_durable_leases')
        self.db.execute("insert into orchestration_dispatch_outbox values('DISPATCHING')")
        with self.assertRaisesRegex(PreconditionError, 'IN_FLIGHT_DISPATCH'):
            assert_quiescent(self.db, pin)

    def test_legacy_fence_blocks_second_writer_and_rolls_back(self):
        pin = history_digest(self.db)
        with admission_fence(self.root):
            with closing(sqlite3.connect(self.root / 'state/state.sqlite', timeout=0.01)) as other:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    other.execute('BEGIN IMMEDIATE')
        self.db.execute('BEGIN IMMEDIATE')
        self.db.rollback()
        self.assertEqual(history_digest(self.db), pin)
