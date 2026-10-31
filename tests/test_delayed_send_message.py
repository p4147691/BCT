import unittest
import hashlib
import tempfile
from pathlib import Path
from bct.core.store import Store

from bct.delayed_send_message import (
    Watch, advance, advance_from_rcc, extract_next_instruction, InstructionError, DurableWatchLedger, DelayedSendRunner, normalize_rcc_latest_assistant, RccLatestAssistantReader,
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

    def test_durable_watch_survives_ledger_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"state.sqlite")
            ledger=DurableWatchLedger(store)
            next_watch=Watch("task-1",2,"worker-uuid","","")
            self.assertTrue(ledger.reserve(next_watch))
            self.assertFalse(DurableWatchLedger(store).reserve(next_watch))
            bound=ledger.bind(next_watch,send_receipt="receipt-2",
                              response_turn_id="turn-2")
            self.assertEqual("turn-2",bound.response_turn_id)
            self.assertEqual("WATCHING",DurableWatchLedger(store).get("task-1",2)["state"])

    def test_runner_reads_and_sends_using_durable_watch(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=DurableWatchLedger(Store(Path(root)/"state.sqlite"))
            ledger.reserve(Watch("task-1",1,"worker-uuid","",""))
            ledger.bind(Watch("task-1",1,"worker-uuid","",""),
                        send_receipt="send-1",response_turn_id="turn-1")
            sent=[]
            runner=DelayedSendRunner(
                ledger,
                read_response=lambda watch: {
                    "conversation_key":"worker-uuid","response_turn_id":"turn-1",
                    "response_text":"NEXT TASK — SELF\nContinue implementation.",
                    "response_complete":True,"input_ready":True},
                send_message=lambda target,body,key: (
                    sent.append((target,body,key)) or "send-2"))
            result=runner.poll_once(self.watch,manager_conversation_key="manager-uuid")
            self.assertEqual("SELF_SENT",result.status)
            self.assertEqual("worker-uuid",sent[0][0])
            self.assertEqual("RESERVED",ledger.get("task-1",2)["state"])
            self.assertEqual("SELF_SENT",ledger.get("task-1",1)["state"])
            self.assertEqual("WAITING_WATCH",runner.poll_once(
                self.watch,manager_conversation_key="manager-uuid").status)
            self.assertEqual(1,len(sent))

    def test_real_rcc_terminal_payload_mapping(self):
        body = "NEXT TASK — SELF\\nContinue."
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        payload = {"ok": True, "conversationKey": "worker-uuid",
                   "responseText": body, "responseSha256": digest,
                   "observationState": "TERMINAL", "terminal": True,
                   "generating": False, "inputReady": True}
        observation = normalize_rcc_latest_assistant(
            payload, conversation_key="worker-uuid",
            expected_response_sha256="0"*64, response_turn_id="turn-1",
            input_ready=True)
        self.assertTrue(observation["response_complete"])
        self.assertTrue(observation["input_ready"])
        self.assertEqual({}, normalize_rcc_latest_assistant(
            payload, conversation_key="worker-uuid",
            expected_response_sha256=digest, response_turn_id="turn-1",
            input_ready=True))
        self.assertEqual({}, normalize_rcc_latest_assistant(
            {**payload, "responseSha256":"0"*64},
            conversation_key="worker-uuid",
            expected_response_sha256="1"*64, response_turn_id="turn-1",
            input_ready=True))

    def test_rcc_reader_uses_exact_target_and_completion(self):
        class Client:
            calls = []
            def request(self, **kwargs):
                self.calls.append(kwargs)
                body = "NEXT TASK — SELF\\nContinue."
                return {"ok":True,"conversationKey":"worker-uuid",
                        "responseText":body,
                        "responseSha256":hashlib.sha256(body.encode()).hexdigest(),
                        "observationState":"TERMINAL","terminal":True,
                        "generating":False,"inputReady":True}
        client=Client()
        reader=RccLatestAssistantReader(
            client,instance_id="instance123",session_id="a"*32,
            tab_id=10,window_id=11,conversation_key="worker-uuid",
            baseline_response_sha256="0"*64,input_ready=lambda:True)
        result=reader(self.watch)
        self.assertTrue(result["response_complete"])
        self.assertEqual("read-latest-assistant",client.calls[0]["command"])
        self.assertEqual(10,client.calls[0]["extra"]["tabId"])

    def test_worker_prearms_before_task_and_reuses_same_reservation(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=DurableWatchLedger(Store(Path(root)/"state.sqlite"))
            self.assertTrue(ledger.prearm(self.watch))
            self.assertFalse(ledger.prearm(self.watch))
            self.assertEqual("WATCHING",ledger.get("task-1",1)["state"])

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
