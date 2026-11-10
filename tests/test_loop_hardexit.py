"""Actual isolated subprocess hard-exit durability for Loop SELF intents."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore,LoopStateError
from bct.loop_self_outbox import LoopSelfOutbox

OWNER="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class LoopHardExitTests(unittest.TestCase):
    def test_outbox_reservation_survives_process_hard_exit(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.sqlite"
            store=Store(path)
            store.create_work(Work(
                work_id="w",request_summary="hard exit test",
                roots=(root,),actions=frozenset({"browser"}),
                owner_principal_id="test",
            ))
            LoopStore(store).start(
                work_id="w",direction_id="d",task_id="t",
                owner=OWNER,plan_text="single step",now=100,
            )
            out=LoopSelfOutbox(store)
            message=out.queue(work_id="w",epoch=1,step=0,owner=OWNER,
                              message="do next",now=110)
            script=(
                "import os,sys;"
                "from bct.core.store import Store;"
                "from bct.loop_self_outbox import LoopSelfOutbox;"
                f"s=Store({str(path)!r});"
                f"LoopSelfOutbox(s).reserve(work_id='w',epoch=1,step=0,"
                f"owner={OWNER!r},now=111);"
                "os._exit(17)"
            )
            env=os.environ.copy()
            repo=str(Path(__file__).resolve().parents[1]/"src")
            env["PYTHONPATH"]=repo+os.pathsep+env.get("PYTHONPATH","")
            child=subprocess.run(
                [sys.executable,"-c",script],env=env,
                capture_output=True,text=True,timeout=15,
            )
            self.assertEqual(child.returncode,17,child.stderr)
            reopened=LoopSelfOutbox(Store(path))
            row=reopened.get(work_id="w",epoch=1,step=0)
            self.assertEqual(row["operation_id"],message["operation_id"])
            self.assertEqual(row["state"],"UNCERTAIN")
            with self.assertRaisesRegex(LoopStateError,"LOOP_SELF_ALREADY_DISPATCHED"):
                reopened.reserve(work_id="w",epoch=1,step=0,
                                 owner=OWNER,now=112)
            unknown=reopened.reconcile(work_id="w",epoch=1,step=0,
                                       principal_id="test",now=113)
            self.assertEqual(unknown["state"],"UNKNOWN")
            self.assertEqual(len(reopened.list_uncertain()),1)


if __name__=="__main__":
    unittest.main()
