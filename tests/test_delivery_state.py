from __future__ import annotations

import unittest

from bct.core.delivery_state import (
    DeliveryEvent,
    DeliveryState,
    DeliveryTransitionError,
    advance_delivery_state,
)


class DeliveryStateTests(unittest.TestCase):
    def test_happy_path_is_one_ordered_roundtrip(self) -> None:
        state = DeliveryState.NOT_SENT
        state = advance_delivery_state(state, DeliveryEvent.WORKER_TURN_CONFIRMED)
        self.assertEqual(state, DeliveryState.SENT_WAITING)
        state = advance_delivery_state(state, DeliveryEvent.WORKER_REPLY_CAPTURED)
        self.assertEqual(state, DeliveryState.REPLY_CAPTURED)
        state = advance_delivery_state(state, DeliveryEvent.MANAGER_TURN_CONFIRMED)
        self.assertEqual(state, DeliveryState.RETURNED)

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


if __name__ == "__main__":
    unittest.main()
