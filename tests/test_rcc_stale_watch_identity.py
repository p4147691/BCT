"""Exact UUID watch can recover an observed moved/reconnected tab, without send."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from bct.send_delayed_message import SendDelayedMessageService

UUID = "6af349ab-5460-83e8-8085-a0ce2ba98b86"
SESSION_OLD = "a" * 32
SESSION_NEW = "b" * 32


class StaleWatchTests(unittest.TestCase):
    def setUp(self):
        self.svc = object.__new__(SendDelayedMessageService)
        self.client = Mock()
        self.svc.browser_feature = SimpleNamespace(client=self.client)
        self.svc.ledger = Mock()
        self.row = {
            "task_id": "watch-1", "generation": 1, "conversation_key": UUID,
            "context": {"instance_id": "instance-1", "watched_session_id": SESSION_OLD,
                        "watched_tab_id": 101, "watched_window_id": 201},
        }

    def test_exact_same_uuid_moved_tab_is_rebound_only_after_explicit_mismatch(self):
        reads = []
        def request(**kwargs):
            reads.append(kwargs)
            extra = kwargs["extra"]
            if extra["tabId"] == 101:
                return {"ok": False, "observationState": "NOT_APPLIED",
                        "error": "READ_LATEST_ASSISTANT_IDENTITY_MISMATCH"}
            return {"ok": False, "conversationKey": UUID, "error": "READ_LATEST_ASSISTANT_UNAVAILABLE"}
        self.client.request.side_effect = request
        self.svc._locate = Mock(return_value=(SESSION_NEW, 102, 202))
        self.assertEqual(self.svc._response_for(self.row), {})
        self.assertEqual([x["extra"]["tabId"] for x in reads], [101, 102])
        self.svc._locate.assert_called_once_with("instance-1", UUID)
        self.assertEqual(self.svc._response_for(self.row), {})
        self.assertEqual([x["extra"]["tabId"] for x in reads], [101, 102, 102])
        self.assertEqual(self.client.request.call_count, 3)

    def test_reconnected_session_is_relocated_by_same_uuid(self):
        seen = []
        def request(**kwargs):
            seen.append(kwargs["extra"]["sessionId"])
            if kwargs["extra"]["sessionId"] == SESSION_OLD:
                return {"ok": False, "error": "TAB_GROUP_SESSION_ID_MISMATCH"}
            return {"ok": False, "error": "READ_LATEST_ASSISTANT_UNAVAILABLE"}
        self.client.request.side_effect = request
        self.svc._locate = Mock(return_value=(SESSION_NEW, 101, 201))
        self.assertEqual(self.svc._response_for(self.row), {})
        self.assertEqual(seen, [SESSION_OLD, SESSION_NEW])
        self.svc._locate.assert_called_once_with("instance-1", UUID)

    def test_generic_unavailable_does_not_trigger_global_discovery(self):
        self.client.request.return_value = {
            "ok": False, "error": "READ_LATEST_ASSISTANT_UNAVAILABLE",
        }
        self.svc._locate = Mock()
        self.assertEqual(self.svc._response_for(self.row), {})
        self.svc._locate.assert_not_called()
        self.client.request.assert_called_once()

    def test_timeout_does_not_trigger_discovery_or_retry(self):
        self.client.request.side_effect = TimeoutError("transport")
        self.svc._locate = Mock()
        with self.assertRaises(TimeoutError):
            self.svc._response_for(self.row)
        self.svc._locate.assert_not_called()
        self.assertEqual(self.client.request.call_count, 1)

    def test_unverified_or_ambiguous_new_target_does_not_fall_back_to_other_uuid(self):
        self.client.request.return_value = {
            "ok": False, "observationState": "NOT_APPLIED",
            "error": "READ_LATEST_ASSISTANT_IDENTITY_MISMATCH",
        }
        self.svc._locate = Mock(side_effect=ValueError("DELAYED_TARGET_NOT_EXACT"))
        self.assertEqual(self.svc._response_for(self.row), {})
        self.assertEqual(self.client.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
