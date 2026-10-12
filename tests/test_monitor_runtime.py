from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.monitor_runtime import build_monitor_state
from bct.service_runtime import ProcessIdentity, atomic_json


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

    def test_decision_ownership_uses_service_creation_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            identity = ProcessIdentity(42, r"C:\Python\python.exe", "creation-1", "f" * 64)
            atomic_json(data / "decision-endpoint.json", {
                "owner": "BCT",
                "runtime": "laya",
                "mode": "recommend_shadow",
                "model_name": "model",
                "generation": 3,
                "warmed_up": True,
                "process": identity.as_dict(),
            })
            with patch("bct.monitor_runtime.process_identity", return_value=identity):
                state = build_monitor_state(
                    store=Store(root / "state.sqlite"),
                    service_state={"ready": True, "release_sha": "1" * 40, "pid": 7},
                    data_root=data,
                )
            self.assertEqual("RUNNING", state["decision"]["state"])
            self.assertTrue(state["decision"]["owned"])


if __name__ == "__main__":
    unittest.main()
