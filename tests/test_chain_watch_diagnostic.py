import json
import tempfile
import unittest
from pathlib import Path
from bct.core.store import Store
from bct.send_delayed_message import DurableWatchLedger, SendDelayedMessageService, Watch


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

    def test_later_exact_terminal_source_retires_unrecoverable_watch(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root) / "state.sqlite"))
            baseline = {
                "responseTurnCount": 4, "generating": False,
                "responseTurnKey": "assistant-4", "responseSha256": "a" * 64,
            }
            ledger.prearm_task(
                task_id="old-chain", work_id="work", principal_id="owner",
                assignment_epoch=1, instance_id="instance",
                conversation_key="worker", manager_conversation_key="manager",
                manager_instance_id="instance", baseline=baseline,
                registration_receipt="arm-old",
                planned_send_operation_id="send-old",
                planned_send_text="old instruction",
            )
            saved = ledger.get("old-chain", 1)
            row = dict(saved)
            row["context"] = json.loads(row.pop("context_json"))
            previous_terminal = {
                "ok": True, "responseTurnCount": 4,
                "responseTurnKey": "assistant-4", "responseSha256": "a" * 64,
                "latestUserTurnKey": "previous-user",
                "latestUserSha256": "e" * 64,
                "responseSourceUserTurnKey": "previous-user",
                "responseSourceUserSha256": "e" * 64,
                "latestUserTextOccurrenceCount": 1,
                "responseSourceUserTextOccurrenceCount": 1,
                "terminal": True, "inputReady": True, "generating": False,
            }
            service = SendDelayedMessageService.__new__(SendDelayedMessageService)
            service.ledger = ledger
            service.latest = lambda **kwargs: previous_terminal
            self.assertEqual({}, service._response_for(row))
            self.assertEqual("WATCHING", ledger.get("old-chain", 1)["state"])
            later = {
                "ok": True, "responseTurnCount": 6,
                "responseTurnKey": "assistant-6", "responseSha256": "d" * 64,
                "latestUserTurnKey": "user-6", "latestUserSha256": "c" * 64,
                "responseSourceUserTurnKey": "user-6",
                "responseSourceUserSha256": "c" * 64,
                "latestUserTextOccurrenceCount": 1,
                "responseSourceUserTextOccurrenceCount": 1,
                "terminal": True, "inputReady": True, "generating": False,
            }
            service.latest = lambda **kwargs: later
            self.assertEqual({}, service._response_for(row))
            retired = ledger.get("old-chain", 1)
            self.assertEqual("SUPERSEDED", retired["state"])
            context = json.loads(retired["context_json"])
            self.assertEqual("SOURCE_SUPERSEDED", context["watch_terminal_reason"])
            self.assertNotIn("watch_diagnostic_reason", context)
            self.assertEqual([], ledger.watching())

    def test_in_progress_different_source_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root) / "state.sqlite"))
            baseline = {
                "responseTurnCount": 4, "generating": False,
                "responseTurnKey": "assistant-4", "responseSha256": "a" * 64,
            }
            ledger.prearm_task(
                task_id="active-chain", work_id="work", principal_id="owner",
                assignment_epoch=1, instance_id="instance",
                conversation_key="worker", manager_conversation_key="manager",
                manager_instance_id="instance", baseline=baseline,
                registration_receipt="arm-active",
                planned_send_operation_id="send-active",
                planned_send_text="active instruction",
            )
            saved = ledger.get("active-chain", 1)
            row = dict(saved)
            row["context"] = json.loads(row.pop("context_json"))
            service = SendDelayedMessageService.__new__(SendDelayedMessageService)
            service.ledger = ledger
            service.latest = lambda **kwargs: {
                "ok": True, "responseTurnCount": 5,
                "responseTurnKey": "assistant-5", "responseSha256": "d" * 64,
                "latestUserTurnKey": "user-5", "latestUserSha256": "c" * 64,
                "responseSourceUserTurnKey": "user-5",
                "responseSourceUserSha256": "c" * 64,
                "latestUserTextOccurrenceCount": 1,
                "responseSourceUserTextOccurrenceCount": 1,
                "terminal": False, "inputReady": False, "generating": True,
            }
            self.assertEqual({}, service._response_for(row))
            active = ledger.get("active-chain", 1)
            self.assertEqual("WATCHING", active["state"])
            self.assertEqual(
                "SOURCE_PROVENANCE_MISMATCH",
                json.loads(active["context_json"])["watch_diagnostic_reason"],
            )


if __name__ == "__main__":
    unittest.main()
