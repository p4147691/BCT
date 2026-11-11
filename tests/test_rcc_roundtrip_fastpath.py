import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from bct.send_delayed_message import SendDelayedMessageService

UUID = "6af349ab-5460-83e8-8085-a0ce2ba98b86"
SESSION = "a" * 32


class FastPathTest(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.request.return_value = {"ok": True, "conversationKey": UUID}
        self.feature = SimpleNamespace(client=self.client)
        self.service = object.__new__(SendDelayedMessageService)
        self.service.browser_feature = self.feature
        self.service._locate = Mock(return_value=(SESSION, 101, 202))
        self.target = {
            "instance_id": "instance-1",
            "conversation_key": UUID,
            "session_id": SESSION,
            "tab_id": 101,
            "window_id": 202,
        }

    def test_exact_target_skips_global_lookup_and_reports_timing(self):
        timings = []
        out = self.service.latest(
            instance_id="instance-1", conversation_key=UUID,
            verified_target=self.target, timing_sink=timings.append,
        )
        self.assertTrue(out["ok"])
        self.service._locate.assert_not_called()
        self.client.request.assert_called_once()
        self.assertEqual(self.client.request.call_args.kwargs["command"],
                         "read-latest-assistant")
        self.assertEqual(self.client.request.call_args.kwargs["extra"]["tabId"], 101)
        self.assertEqual(timings[0]["route"], "exact_target")
        self.assertEqual(timings[0]["direct_read_call_count"], 1)
        self.assertEqual(timings[0]["discovery_call_count"], 0)
        self.assertGreaterEqual(timings[0]["total_ms"], 0)

    def test_legacy_path_preserves_discovery(self):
        timings = []
        self.service.latest(instance_id="instance-1", conversation_key=UUID,
                            timing_sink=timings.append)
        self.service._locate.assert_called_once_with("instance-1", UUID)
        self.assertEqual(timings[0]["route"], "global_discovery")
        self.assertEqual(timings[0]["discovery_call_count"], None)

    def test_mismatched_receipt_fails_closed_without_request(self):
        for changes in ({"conversation_key": "wrong"},
                        {"session_id": ""},
                        {"tab_id": 0},
                        {"instance_id": "wrong"},
                        {"window_id": "not-an-int"}):
            with self.subTest(changes=changes):
                self.client.reset_mock()
                with self.assertRaises(ValueError):
                    self.service.latest(instance_id="instance-1",
                                        conversation_key=UUID,
                                        verified_target={**self.target, **changes})
                self.client.request.assert_not_called()

    def test_parallel_independent_read_only_targets(self):
        from threading import Barrier
        barrier = Barrier(2, timeout=2)
        def reply(**kwargs):
            barrier.wait()
            return {"ok": True, "tabId": kwargs["extra"]["tabId"]}
        self.client.request.side_effect = reply
        second_key = "11111111-2222-3333-4444-555555555555"
        second = {**self.target, "conversation_key": second_key, "tab_id": 103}
        outputs = self.service.latest_many([
            {"instance_id": "instance-1", "conversation_key": UUID,
             "verified_target": self.target},
            {"instance_id": "instance-1", "conversation_key": second_key,
             "verified_target": second},
        ], max_workers=2)
        self.assertEqual([x["tabId"] for x in outputs], [101, 103])
        self.assertEqual(self.client.request.call_count, 2)
        self.service._locate.assert_not_called()

    def test_parallel_duplicate_rejected_before_network(self):
        item = {"instance_id": "instance-1", "conversation_key": UUID,
                "verified_target": self.target}
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            self.service.latest_many([item, item])
        self.client.request.assert_not_called()

    def test_request_failure_still_emits_timing(self):
        self.client.request.side_effect = TimeoutError("rcc")
        timings = []
        with self.assertRaises(TimeoutError):
            self.service.latest(instance_id="instance-1", conversation_key=UUID,
                                verified_target=self.target, timing_sink=timings.append)
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["direct_read_call_count"], 1)


if __name__ == "__main__":
    unittest.main()
