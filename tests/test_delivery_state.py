from __future__ import annotations

import unittest
import hashlib
import tempfile
from pathlib import Path

from bct.core.delivery_ledger import DeliveryLedger
from bct.core.delivery_state import (
    DeliveryEvent,
    DeliveryState,
    DeliveryTransitionError,
    advance_delivery_state,
)
from bct.core.models import ConflictError, Work
from bct.core.store import Store


class DeliveryStateTests(unittest.TestCase):
    def test_happy_path_is_one_ordered_roundtrip(self) -> None:
        state = DeliveryState.NOT_SENT
        state = advance_delivery_state(state, DeliveryEvent.WORKER_TURN_CONFIRMED)
        self.assertEqual(state, DeliveryState.SENT_WAITING)
        state = advance_delivery_state(state, DeliveryEvent.WORKER_REPLY_CAPTURED)
        self.assertEqual(state, DeliveryState.REPLY_CAPTURED)
        state = advance_delivery_state(state, DeliveryEvent.MANAGER_TURN_CONFIRMED)
        self.assertEqual(state, DeliveryState.RETURNED)

    def test_busy_target_waits_without_crossing_submission_boundary(self) -> None:
        state = advance_delivery_state(
            DeliveryState.NOT_SENT, DeliveryEvent.TARGET_QUEUED,
        )
        self.assertEqual(state, DeliveryState.WAITING_TARGET)
        self.assertNotIn(state, {
            DeliveryState.SENT_WAITING, DeliveryState.NOT_APPLIED,
            DeliveryState.NEEDS_REVIEW,
        })
        state = advance_delivery_state(
            state, DeliveryEvent.WORKER_TURN_CONFIRMED,
        )
        self.assertEqual(state, DeliveryState.SENT_WAITING)

    def test_busy_policy_can_reject_before_submit(self) -> None:
        state = advance_delivery_state(
            DeliveryState.NOT_SENT, DeliveryEvent.TARGET_QUEUED,
        )
        state = advance_delivery_state(
            state, DeliveryEvent.PRE_SUBMIT_REJECTED,
        )
        self.assertEqual(state, DeliveryState.NOT_APPLIED)

    def test_same_observation_is_idempotent(self) -> None:
        self.assertEqual(
            advance_delivery_state(
                DeliveryState.SENT_WAITING,
                DeliveryEvent.WORKER_TURN_CONFIRMED,
            ),
            DeliveryState.SENT_WAITING,
        )

    def test_pre_submit_rejection_is_terminal_not_applied(self) -> None:
        state = advance_delivery_state(
            DeliveryState.NOT_SENT, DeliveryEvent.PRE_SUBMIT_REJECTED,
        )
        self.assertEqual(state, DeliveryState.NOT_APPLIED)
        with self.assertRaisesRegex(
            DeliveryTransitionError, "DELIVERY_TERMINAL_STATE_IMMUTABLE",
        ):
            advance_delivery_state(state, DeliveryEvent.WORKER_TURN_CONFIRMED)

    def test_ambiguous_boundary_never_becomes_success_or_retry(self) -> None:
        for state in (
            DeliveryState.NOT_SENT,
            DeliveryState.WAITING_TARGET,
            DeliveryState.SENT_WAITING,
            DeliveryState.REPLY_CAPTURED,
        ):
            with self.subTest(state=state):
                terminal = advance_delivery_state(
                    state, DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
                )
                self.assertEqual(terminal, DeliveryState.NEEDS_REVIEW)
                with self.assertRaisesRegex(
                    DeliveryTransitionError,
                    "DELIVERY_TERMINAL_STATE_IMMUTABLE",
                ):
                    advance_delivery_state(
                        terminal, DeliveryEvent.WORKER_TURN_CONFIRMED,
                    )

    def test_skipped_and_backward_transitions_are_rejected(self) -> None:
        invalid = (
            (DeliveryState.NOT_SENT, DeliveryEvent.WORKER_REPLY_CAPTURED),
            (DeliveryState.NOT_SENT, DeliveryEvent.MANAGER_TURN_CONFIRMED),
            (DeliveryState.SENT_WAITING, DeliveryEvent.MANAGER_TURN_CONFIRMED),
            (DeliveryState.REPLY_CAPTURED, DeliveryEvent.WORKER_TURN_CONFIRMED),
        )
        for state, event in invalid:
            with self.subTest(state=state, event=event):
                with self.assertRaisesRegex(
                    DeliveryTransitionError, "DELIVERY_TRANSITION_INVALID",
                ):
                    advance_delivery_state(state, event)

    def test_confirmed_worker_failure_only_follows_confirmed_send(self) -> None:
        with self.assertRaisesRegex(
            DeliveryTransitionError, "DELIVERY_TRANSITION_INVALID",
        ):
            advance_delivery_state(
                DeliveryState.NOT_SENT, DeliveryEvent.WORKER_TURN_FAILED,
            )
        self.assertEqual(
            advance_delivery_state(
                DeliveryState.SENT_WAITING,
                DeliveryEvent.WORKER_TURN_FAILED,
            ),
            DeliveryState.FAILED,
        )


class DeliveryLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.work = self.store.create_work(Work(
            "delivery-work", "thin relay", (self.temp.name,),
            frozenset({"relay_browser"}), "owner",
        ))
        self.ledger = DeliveryLedger(self.store)
        self.identity = dict(
            delivery_id="delivery-001", work_id=self.work.work_id,
            instance_id="6174664e1c1b4e6db1d4729c841db3c9",
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key="6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            request_sha256=hashlib.sha256(b"one exact message").hexdigest(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_one_row_covers_the_whole_roundtrip(self) -> None:
        created, row = self.ledger.create_or_get(**self.identity)
        self.assertTrue(created)
        self.assertEqual("NOT_SENT", row["state"])
        row = self.ledger.observe(
            delivery_id="delivery-001", work_id=self.work.work_id,
            event=DeliveryEvent.WORKER_TURN_CONFIRMED,
            observation={"rcc_session_id": "session-1", "untrusted": "drop"},
        )
        self.assertEqual("SENT_WAITING", row["state"])
        self.assertEqual({"rcc_session_id": "session-1"}, row["observation"])
        response_hash = hashlib.sha256(b"worker reply").hexdigest()
        row = self.ledger.observe(
            delivery_id="delivery-001", work_id=self.work.work_id,
            event=DeliveryEvent.WORKER_REPLY_CAPTURED,
            response_sha256=response_hash, response_length=12,
        )
        self.assertEqual("REPLY_CAPTURED", row["state"])
        row = self.ledger.observe(
            delivery_id="delivery-001", work_id=self.work.work_id,
            event=DeliveryEvent.MANAGER_TURN_CONFIRMED,
        )
        self.assertEqual("RETURNED", row["state"])
        self.assertEqual(response_hash, row["response_sha256"])

    def test_same_id_is_idempotent_but_identity_is_immutable(self) -> None:
        self.ledger.create_or_get(**self.identity)
        created, _row = self.ledger.create_or_get(**self.identity)
        self.assertFalse(created)
        with self.assertRaisesRegex(ConflictError, "DELIVERY_ID_REUSE_MISMATCH"):
            self.ledger.create_or_get(**{
                **self.identity,
                "request_sha256": hashlib.sha256(b"different").hexdigest(),
            })


if __name__ == "__main__":
    unittest.main()
