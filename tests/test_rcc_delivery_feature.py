from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from bct.core.models import ConfirmedFailure, Outcome, UnknownEffectError, Work
from bct.core.store import Store
from bct.features.rcc import RelayBrowserFeature
from bct.integrations.rcc import RelayUnavailable


class FakeDeliveryHost:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        delivery_id = kwargs["extra"]["deliveryId"]
        if kwargs["command"] == "delivery-start":
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "SENT_WAITING", "workerTabId": 11,
                    "workerWindowId": 22}
        if kwargs["command"] == "delivery-status":
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "REPLY_CAPTURED",
                    "responseSha256": hashlib.sha256(b"reply").hexdigest(),
                    "responseLength": 5}
        return {"ok": True, "deliveryId": delivery_id,
                "state": "RETURNED", "managerTabId": 33,
                "managerWindowId": 44}


class DeliveryFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.work = self.store.create_work(Work(
            "work", "thin relay", (self.temp.name,),
            frozenset({"relay_browser"}), "owner",
        ))
        self.host = FakeDeliveryHost()
        self.feature = RelayBrowserFeature(self.host, store=self.store)
        self.base = {
            "instance_id": "6174664e1c1b4e6db1d4729c841db3c9",
            "delivery_id": "delivery-001",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def execute(self, arguments, operation_id):
        request = self.feature.prepare(work=self.work, arguments=arguments)
        return self.feature.execute(replace(request, operation_id=operation_id))

    def test_one_delivery_id_drives_one_exact_roundtrip(self) -> None:
        result = self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "원문 그대로 한 번",
        }, "outer-start")
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("SENT_WAITING", result.evidence["delivery_state"])
        result = self.execute({**self.base, "command": "delivery-status"}, "outer-status")
        self.assertEqual("REPLY_CAPTURED", result.evidence["delivery_state"])
        result = self.execute({**self.base, "command": "delivery-return"}, "outer-return")
        self.assertEqual("RETURNED", result.evidence["delivery_state"])
        self.assertEqual(
            ["delivery-start", "delivery-status", "delivery-return"],
            [call["command"] for call in self.host.calls],
        )
        self.assertTrue(all(
            call["extra"]["deliveryId"] == "delivery-001" for call in self.host.calls
        ))

    def test_duplicate_start_does_not_resend(self) -> None:
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "same",
        }
        self.execute(args, "outer-start-1")
        replay = self.execute(args, "outer-start-2")
        self.assertTrue(replay.evidence["replayed"])
        self.assertEqual(1, len(self.host.calls))

    def test_status_transport_failure_is_retryable_but_return_failure_is_review(self) -> None:
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "same",
        }
        self.execute(args, "outer-start")

        class Down:
            def request(self, **_kwargs):
                raise RelayUnavailable("down")

        self.feature.client = Down()
        with self.assertRaisesRegex(ConfirmedFailure, "RCC_DELIVERY_STATUS_UNAVAILABLE"):
            self.execute({**self.base, "command": "delivery-status"}, "outer-status")
        self.assertEqual(
            "SENT_WAITING",
            self.feature.delivery_ledger.get_for_work(
                delivery_id="delivery-001", work_id=self.work.work_id,
            )["state"],
        )

        self.feature.client = self.host
        self.execute({**self.base, "command": "delivery-status"}, "outer-status-2")
        self.feature.client = Down()
        with self.assertRaisesRegex(UnknownEffectError, "RCC_DELIVERY_TRANSPORT_UNKNOWN"):
            self.execute({**self.base, "command": "delivery-return"}, "outer-return")
        self.assertEqual(
            "NEEDS_REVIEW",
            self.feature.delivery_ledger.get_for_work(
                delivery_id="delivery-001", work_id=self.work.work_id,
            )["state"],
        )


if __name__ == "__main__":
    unittest.main()
