from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.core.delivery_ledger import DeliveryLedger
from bct.core.delivery_state import DeliveryEvent
from bct.core.models import FeatureRequest, FeatureResult, Outcome, Work
from bct.core.store import Store
from bct.delivery_continuation_recovery import DeliveryContinuationRecovery


MANAGER = "6adbfb63-ddb0-83ee-8a42-dcdb8e56874c"
WORKER = "6adbfb66-57dc-83e8-b321-0bfe59aa013f"


class FakeRelayFeature:
    def __init__(self, ledger: DeliveryLedger):
        self.ledger = ledger
        self.calls: list[str] = []

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        return FeatureRequest(
            "relay_browser", arguments["instance_id"], dict(arguments),
            ("delivery:" + arguments["delivery_id"],), {},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        command = request.arguments["command"]
        delivery_id = request.arguments["delivery_id"]
        work_id = "work"
        self.calls.append(command)
        if command == "delivery-status":
            row = self.ledger.observe(
                delivery_id=delivery_id, work_id=work_id,
                event=DeliveryEvent.WORKER_REPLY_CAPTURED,
                response_sha256=hashlib.sha256(b"worker result").hexdigest(),
                response_length=13,
            )
        elif command == "delivery-manager-status":
            row = self.ledger.observe(
                delivery_id=delivery_id, work_id=work_id,
                event=DeliveryEvent.MANAGER_TURN_RECONCILED,
                observation={"manager_return_reconciled": True},
            )
        else:
            row = self.ledger.observe(
                delivery_id=delivery_id, work_id=work_id,
                event=DeliveryEvent.MANAGER_TURN_CONFIRMED,
            )
        return FeatureResult(
            Outcome.APPLIED, {"delivery_state": row["state"]}, output={"delivery": row},
        )


class DeliveryContinuationRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "state.sqlite")
        self.work = self.store.create_work(Work(
            "work", "wake continuity", (temporary.name,),
            frozenset({"relay_browser"}), "owner",
        ))
        self.ledger = DeliveryLedger(self.store)
        self.feature = FakeRelayFeature(self.ledger)
        self.recovery = DeliveryContinuationRecovery(self.store, self.feature)

    def create(self, delivery_id: str, mode: str) -> None:
        self.ledger.create_or_get(
            delivery_id=delivery_id, work_id=self.work.work_id,
            instance_id="6174664e1c1b4e6db1d4729c841db3c9",
            manager_conversation_key=MANAGER,
            worker_conversation_key=WORKER,
            request_sha256=hashlib.sha256(delivery_id.encode()).hexdigest(),
            scope_id="network.test", original_task="return this result",
            continuation_mode=mode,
        )
        self.ledger.observe(
            delivery_id=delivery_id, work_id=self.work.work_id,
            event=DeliveryEvent.WORKER_TURN_CONFIRMED,
        )

    def test_auto_return_advances_same_delivery_without_new_dispatch(self):
        self.create("auto-1", "auto_return")
        result = self.recovery.run_once()
        self.assertEqual({"captured": 1, "returned": 1}, {
            "captured": result["captured"], "returned": result["returned"],
        })
        self.assertEqual(["delivery-status", "delivery-return"], self.feature.calls)
        self.assertEqual("RETURNED", self.ledger.get_for_work(
            delivery_id="auto-1", work_id=self.work.work_id,
        )["state"])
        self.assertEqual(0, self.recovery.run_once()["checked"])

    def test_manual_delivery_is_never_touched(self):
        self.create("manual-1", "manual")
        result = self.recovery.run_once()
        self.assertEqual(0, result["checked"])
        self.assertEqual([], self.feature.calls)
        self.assertEqual("SENT_WAITING", self.ledger.get_for_work(
            delivery_id="manual-1", work_id=self.work.work_id,
        )["state"])

    def test_return_unknown_with_exact_effect_is_reconciled_not_blocked(self):
        self.create("auto-reconcile", "auto_return")
        self.ledger.observe(
            delivery_id="auto-reconcile", work_id=self.work.work_id,
            event=DeliveryEvent.WORKER_REPLY_CAPTURED,
            response_sha256=hashlib.sha256(b"worker result").hexdigest(),
            response_length=13,
        )
        self.ledger.observe(
            delivery_id="auto-reconcile", work_id=self.work.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
            observation={
                "host_state": "REPLY_CAPTURED",
                "error_code": "RCC_DELIVERY_EFFECT_UNKNOWN",
            },
        )
        result = self.recovery.run_once()
        self.assertEqual(1, result["checked"])
        self.assertEqual(1, result["returned"])
        self.assertEqual(["delivery-manager-status"], self.feature.calls)
        row = self.ledger.get_for_work(
            delivery_id="auto-reconcile", work_id=self.work.work_id,
        )
        self.assertEqual("RETURNED", row["state"])
        self.assertTrue(row["observation"]["manager_return_reconciled"])

    def test_completed_work_is_never_touched(self):
        self.create("finished-1", "auto_return")
        with self.store.transaction() as db:
            db.execute("UPDATE works SET state='FINISHED' WHERE work_id='work'")
        self.assertEqual(0, self.recovery.run_once()["checked"])
        self.assertEqual([], self.feature.calls)


if __name__ == "__main__":
    unittest.main()
