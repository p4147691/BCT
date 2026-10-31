import unittest

from bct.delayed_send_message import (
    Watch, advance, advance_from_rcc, extract_next_instruction, InstructionError,
)


class DelayedSendMessageTests(unittest.TestCase):
    def setUp(self):
        self.watch = Watch("task-1", 1, "worker-uuid", "turn-1", "send-1")
        self.events = []

    def advance(self, response, *, complete=True, ready=True, turn="turn-1"):
        return advance(
            watch=self.watch, response_turn_id=turn, response_text=response,
            response_complete=complete, input_ready=ready,
            manager_conversation_key="manager-uuid",
            register_next_watch=lambda w: self.events.append(("watch", w)),
            send_message=lambda target, text, key: (
                self.events.append(("send", target, text, key)) or "receipt-2"
            ),
        )

    def test_rcc_observation_dispatches_only_exact_completed_turn(self):
        observed = {"conversation_key": "worker-uuid", "response_turn_id": "turn-1",
                    "response_text": "NEXT TASK — SELF\nContinue coding.",
                    "response_complete": True, "input_ready": True}
        def run(data):
            return advance_from_rcc(
                watch=self.watch, observation=data,
                manager_conversation_key="manager-uuid",
                register_next_watch=lambda w: self.events.append(("watch", w)),
                send_message=lambda target, body, key: (
                    self.events.append(("send", target, body, key)) or "receipt"),
            )
        self.assertEqual("WAITING_RESPONSE", run({**observed, "input_ready": False}).status)
        self.assertEqual("WAITING_EXPECTED_RESPONSE", run({**observed, "conversation_key": "other"}).status)
        self.assertFalse(self.events)
        self.assertEqual("SELF_SENT", run(observed).status)
        self.assertEqual(["watch", "send"], [x[0] for x in self.events])

    def test_self_reserves_next_watch_before_send(self):
        result = self.advance("Completed part 1.\nNEXT TASK — SELF\nFix remaining issue.")
        self.assertEqual("SELF_SENT", result.status)
        self.assertEqual(["watch", "send"], [x[0] for x in self.events])
        self.assertEqual(2, result.next_watch.generation)
        self.assertEqual("worker-uuid", self.events[1][1])
        self.assertEqual("Fix remaining issue.", self.events[1][2])

    def test_manager_return_ends_without_reservation(self):
        result = self.advance("Done.\nNEXT TASK — MANAGER\nCompleted and verified.")
        self.assertEqual("RETURNED_TO_MANAGER", result.status)
        self.assertEqual(["send"], [x[0] for x in self.events])
        self.assertEqual("manager-uuid", self.events[0][1])

    def test_incomplete_or_unready_does_not_send(self):
        for complete, ready in [(False, True), (True, False)]:
            self.assertEqual("WAITING_RESPONSE", self.advance(
                "NEXT TASK — SELF\nContinue.", complete=complete, ready=ready).status)
        self.assertFalse(self.events)

    def test_unrelated_turn_does_not_send(self):
        self.assertEqual("WAITING_EXPECTED_RESPONSE", self.advance(
            "NEXT TASK — SELF\nContinue.", turn="old-turn").status)
        self.assertFalse(self.events)

    def test_missing_ambiguous_or_empty_instruction_does_not_send(self):
        for body in ["Continue.", "NEXT TASK — SELF",
                     "NEXT TASK — SELF\nA\nNEXT TASK — MANAGER\nB"]:
            self.assertEqual("INSTRUCTION_UNAVAILABLE", self.advance(body).status)
        self.assertFalse(self.events)

    def test_exact_instruction_text_is_preserved(self):
        body = "NEXT TASK — SELF\n  Edit file X.\nRun focused test."
        result = self.advance(body)
        self.assertEqual("SELF_SENT", result.status)
        self.assertEqual("Edit file X.\nRun focused test.", self.events[1][2])


if __name__ == "__main__":
    unittest.main()
