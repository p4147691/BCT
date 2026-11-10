"""Small facade smoke tests using the canonical BCT Store."""
import tempfile
import unittest
from pathlib import Path
from bct.core.store import Store
from bct.loop_runtime import LoopLedger


class FacadeTests(unittest.TestCase):
    def test_loop_runtime_alias_uses_canonical_store(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"ledger.sqlite")
            store.get_work=lambda work_id: object()
            result=LoopLedger(store).start(
                work_id="facade-work",direction_id="dir",task_id="task",
                owner="node-a",plan_text="plan",now=100,
            )
            self.assertEqual(result["state"],"LOOP_STARTED")


if __name__=="__main__":
    unittest.main()
