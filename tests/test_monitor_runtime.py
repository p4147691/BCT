from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.monitor_runtime import build_monitor_state


class MonitorRuntimeTests(unittest.TestCase):
    def test_snapshot_is_bounded_and_omits_operation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "state.sqlite")
            store.create_work(Work(
                "monitor-work", "monitor test", (str(root),), frozenset({"read"}), "owner"
            ))
            state = build_monitor_state(
                store=store,
                service_state={"ready": True, "release_sha": "1" * 40, "pid": 123},
                data_root=root / "data",
            )
            self.assertEqual(1, state["schema"])
            self.assertEqual(1, state["counts"]["works"])
            self.assertEqual("UNCONFIGURED", state["decision"]["state"])
            self.assertNotIn("roots", state["works"][0])
            self.assertEqual([], state["operations"])


if __name__ == "__main__":
    unittest.main()
