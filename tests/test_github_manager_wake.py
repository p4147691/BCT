import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from bct.github_manager_wake import GithubManagerWake


class StoreFixture:
    def __init__(self, path):
        self.path = path
        import contextlib
        self.contextlib = contextlib
    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db
    def transaction(self):
        @self.contextlib.contextmanager
        def tx():
            db = self._connect()
            try:
                yield db
                db.commit()
            finally:
                db.close()
        return tx()


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StoreFixture(str(Path(self.tmp.name)/"fixture.sqlite"))
        with self.store.transaction() as db:
            db.executescript("""
              CREATE TABLE github_run_inbox(subscription_id TEXT, state TEXT, updated_at REAL);
              CREATE TABLE github_run_inbox_recipients(subscription_id TEXT,node_id TEXT,
                notify_manager INTEGER,unread INTEGER);
            """)
            for i in range(3):
                db.execute("INSERT INTO github_run_inbox VALUES(?,?,?)",(str(i),"SUCCESS",i))
                db.execute("INSERT INTO github_run_inbox_recipients VALUES(?,?,1,1)",
                           (str(i),"manager"))
        self.co = GithubManagerWake(self.store)
        self.kw = dict(manager_node_id="manager",manager_epoch=3,
                       conversation_uuid="uuid",idle=True)

    def test_busy_then_coalesced_idle_and_single_submission(self):
        self.assertIsNone(self.co.plan(**{**self.kw,"idle":False}))
        plan = self.co.plan(**self.kw)
        self.assertEqual(len(plan.subscription_ids),3)
        count = []
        def relay(target,text,token):
            count.append((target,text,token))
            return dict(ok=True,delivery_id=token,exact_turn_confirmed=True)
        fence=lambda node,epoch,uuid: self.assertEqual((node,epoch,uuid),("manager",3,"uuid"))
        self.assertEqual(self.co.dispatch(plan,assert_manager_epoch=fence,existing_relay=relay),"SUBMITTED")
        self.assertEqual(self.co.dispatch(plan,assert_manager_epoch=fence,existing_relay=relay),"SUBMITTED")
        self.assertEqual(len(count),1)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT SUM(unread) FROM github_run_inbox_recipients").fetchone()[0],3)

    def test_unknown_never_resends(self):
        plan=self.co.plan(**self.kw)
        calls=[]
        def broken(*args):
            calls.append(1)
            raise TimeoutError("ambiguous")
        self.assertEqual(self.co.dispatch(plan,assert_manager_epoch=lambda *args:None,
                                          existing_relay=broken),"UNKNOWN")
        self.assertEqual(self.co.dispatch(plan,assert_manager_epoch=lambda *args:None,
                                          existing_relay=broken),"UNKNOWN")
        self.assertEqual(len(calls),1)

    def test_epoch_gate_blocks_before_transport(self):
        plan=self.co.plan(**self.kw)
        def reject(*args):raise PermissionError("stale epoch")
        with self.assertRaises(PermissionError):
            self.co.dispatch(plan,assert_manager_epoch=reject,existing_relay=lambda *a:None)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='github_manager_wake_attempts'").fetchone()[0],0)

    def test_distinct_batches_and_inbox_untouched(self):
        a=self.co.plan(**self.kw)
        with self.store.transaction() as db:
            db.execute("INSERT INTO github_run_inbox VALUES('4','SUCCESS',4)")
            db.execute("INSERT INTO github_run_inbox_recipients VALUES('4','manager',1,1)")
        b=self.co.plan(**self.kw)
        self.assertNotEqual(a.token,b.token)
        self.assertEqual(len(b.subscription_ids),4)


class RecoveryAdapterTests(WakeTests):
    def test_restart_rediscovers_pending_and_coalesces(self):
        from bct.github_manager_wake import GithubWakeRecoveryAdapter
        busy = lambda: [dict(node_id="manager",epoch=3,conversation_uuid="uuid",idle=False)]
        self.assertEqual(GithubWakeRecoveryAdapter(self.store,busy).run_once()["busy"],1)
        count = []
        def fake(*args):
            count.append(args)
            return dict(ok=True,delivery_id=args[2],exact_turn_confirmed=True)
        provider = lambda: [dict(node_id="manager",epoch=3,conversation_uuid="uuid",idle=True)]
        fence = lambda *args: self.assertEqual(args,("manager",3,"uuid"))
        a=GithubWakeRecoveryAdapter(self.store,provider,fake,fence)
        self.assertEqual(a.run_once()["submitted"],1)
        # Fresh coordinator instance on the same SQLite represents restart.
        b=GithubWakeRecoveryAdapter(self.store,provider,fake,fence)
        self.assertEqual(b.run_once()["submitted"],1)
        self.assertEqual(len(count),1)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT SUM(unread) FROM github_run_inbox_recipients").fetchone()[0],3)

    def test_epoch_mismatch_before_wake(self):
        from bct.github_manager_wake import GithubWakeRecoveryAdapter
        def bad(*_): raise PermissionError("epoch mismatch")
        provider=lambda:[dict(node_id="manager",epoch=3,conversation_uuid="uuid",idle=True)]
        with self.assertRaises(PermissionError):
            GithubWakeRecoveryAdapter(self.store,provider,lambda *x:None,bad).run_once()

if __name__=="__main__":
    unittest.main()
