import json
import tempfile
import unittest
from pathlib import Path
from bct.core.store import Store
from bct.delayed_send_message import DurableWatchLedger, Watch


class ChainWatchDiagnosticTests(unittest.TestCase):
    def test_bounded_diagnostic_preserves_watch_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root) / "state.sqlite"))
            watch = Watch("diag-task", 1, "worker-uuid", "turn-1", "send-1")
            ledger.prearm(watch)
            row = {"task_id": "diag-task", "generation": 1}
            self.assertTrue(ledger.record_watch_diagnostic(row, "SOURCE_PROVENANCE_MISMATCH"))
            self.assertTrue(ledger.record_watch_diagnostic(row, "SOURCE_PROVENANCE_MISMATCH"))
            saved = ledger.get("diag-task", 1)
            self.assertEqual("WATCHING", saved["state"])
            ctx = json.loads(saved["context_json"])
            self.assertEqual("SOURCE_PROVENANCE_MISMATCH", ctx["watch_diagnostic_reason"])
            self.assertFalse(ledger.record_watch_diagnostic(row, "arbitrary user content"))
            self.assertEqual(ctx, json.loads(ledger.get("diag-task", 1)["context_json"]))


if __name__ == "__main__":
    unittest.main()
