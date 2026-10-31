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
                    "response_complete":True,"input_ready":True,
                    "response_turn_key":"rcc-turn-1",
                    "response_sha256":"digest-1"},
                send_message=lambda target,body,key: (
                    sent.append((target,body,key)) or "send-2"))
            result=runner.poll_once(self.watch,manager_conversation_key="manager-uuid")
            self.assertEqual("SELF_SENT",result.status)
            self.assertEqual("worker-uuid",sent[0][0])
            self.assertEqual("RESERVED",ledger.get("task-1",2)["state"])
            self.assertEqual("SELF_SENT",ledger.get("task-1",1)["state"])
            self.assertEqual("rcc-turn-1", __import__("json").loads(ledger.get("task-1",1)["context_json"])["observed_response_turn_key"])
            self.assertEqual("WAITING_WATCH",runner.poll_once(
                self.watch,manager_conversation_key="manager-uuid").status)
            self.assertEqual(1,len(sent))

    def test_real_rcc_terminal_payload_mapping(self):
        body = "NEXT TASK — SELF\\nContinue."
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        payload = {"ok": True, "conversationKey": "worker-uuid",
                   "responseText": body, "responseSha256": digest,
                   "responseTurnKey":"rcc-turn-1",
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
                        "responseText":body,"responseTurnKey":"rcc-turn-1",
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

    def test_missing_or_wrong_turn_key_never_dispatches(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root)/"state.sqlite"))
            ledger.reserve(Watch("task-1",1,"worker-uuid","",""))
            ledger.bind(Watch("task-1",1,"worker-uuid","",""),
                        send_receipt="send-1",response_turn_id="turn-1")
            sent = []
            observation = {
                "conversation_key":"worker-uuid","response_turn_id":"turn-1",
                "response_text":"NEXT TASK — MANAGER\nOnly current result.",
                "response_complete":True,"input_ready":True,
                "response_sha256":"sha-current"}
            current = dict(observation)
            runner = DelayedSendRunner(ledger, read_response=lambda _:current,
                send_message=lambda *args:sent.append(args) or "receipt")
            for change in ({"response_turn_key":""},
                           {"response_turn_key":"current","response_complete":False},
                           {"response_turn_key":"current","input_ready":False},
                           {"response_turn_key":"current","conversation_key":"other"}):
                current = {**observation, **change}
                self.assertNotEqual("RETURNED_TO_MANAGER",
                    runner.poll_once(self.watch,manager_conversation_key="manager-uuid").status)
            self.assertFalse(sent)
            current = {**observation,"response_turn_key":"current"}
            self.assertEqual("RETURNED_TO_MANAGER",
                runner.poll_once(self.watch,manager_conversation_key="manager-uuid").status)
            self.assertEqual(("manager-uuid","Only current result."),sent[0][:2])

    def test_self_generations_bind_independent_rcc_keys(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root)/"state.sqlite"))
            first = Watch("task-1",1,"worker-uuid","turn-1","send-1")
            ledger.prearm(first)
            sent = []
            def sender(target, body, key):
                sent.append((target,body,key))
                return "receipt-" + str(len(sent))
            runner = DelayedSendRunner(ledger,read_response=lambda w:{
                "conversation_key":"worker-uuid",
                "response_turn_id":w.response_turn_id,
                "response_turn_key":"rcc-key-"+str(w.generation),
                "response_sha256":"sha-"+str(w.generation),
                "response_text":("NEXT TASK — SELF\nContinue." if w.generation==1
                                 else "NEXT TASK — MANAGER\nFinal."),
                "response_complete":True,"input_ready":True},
                send_message=sender)
            self.assertEqual("SELF_SENT",runner.poll_once(first,manager_conversation_key="manager-uuid").status)
            second = ledger.bind(Watch("task-1",2,"worker-uuid","",""),
                                 send_receipt="receipt-1",response_turn_id="turn-2")
            self.assertEqual("RETURNED_TO_MANAGER",
                runner.poll_once(second,manager_conversation_key="manager-uuid").status)
            import json
            self.assertEqual("rcc-key-1",json.loads(ledger.get("task-1",1)["context_json"])["observed_response_turn_key"])
            self.assertEqual("rcc-key-2",json.loads(ledger.get("task-1",2)["context_json"])["observed_response_turn_key"])
            self.assertEqual("manager-uuid",sent[-1][0])

    def test_initial_manual_prearm_requires_exact_rcc_user_proof(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root) / "state.sqlite"))
            source = {"responseTurnCount": 2, "generating": True,
                      "responseTurnKey": "old-response", "responseSha256": "a" * 64}
            kwargs = dict(task_id="manual-proof-task",work_id="work",
                          principal_id="owner",assignment_epoch=1,
                          instance_id="instance",conversation_key="worker",
                          manager_conversation_key="manager",
                          manager_instance_id="instance",registration_receipt="prearm")
            for incomplete in (
                source,
                {**source,"latestUserTurnKey":"fallback-turn-1",
                 "latestUserSha256":"b"*64},
                {**source,"latestUserTurnKey":"actual-user",
                 "latestUserSha256":"not-a-sha"},
            ):
                with self.assertRaisesRegex(ValueError,"DELAYED_SOURCE_USER_PROOF_REQUIRED"):
                    ledger.prearm_task(**kwargs,baseline=incomplete)
                self.assertIsNone(ledger.get("manual-proof-task",1))
            verified = {**source,"latestUserTurnKey":"actual-user",
                        "latestUserSha256":"b"*64}
            result = ledger.prearm_task(**kwargs,baseline=verified)
            self.assertEqual("WATCHING",result["state"])
            import json
            context = json.loads(ledger.get("manual-proof-task",1)["context_json"])
            self.assertEqual("RCC_PREARM_USER_TURN",context["source_proof_kind"])
            self.assertEqual("actual-user",context["source_user_turn_key"])

    def test_cancel_exact_watching_generation_and_idempotent_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = DurableWatchLedger(Store(Path(root)/"state.sqlite"))
            baseline={"responseTurnCount":1,"generating":False,
                      "responseTurnKey":"old","responseSha256":"a"*64,
                      "latestUserTurnKey":"trusted-manual-user",
                      "latestUserSha256":"b"*64}
            ledger.prearm_task(task_id="task-cancel",work_id="work-owner",
                principal_id="principal-owner",assignment_epoch=1,
                instance_id="instance",conversation_key="worker",
                manager_conversation_key="manager",manager_instance_id="instance",
                baseline=baseline,registration_receipt="receipt")
            with self.assertRaisesRegex(ValueError,"OWNER_MISMATCH"):
                ledger.cancel_task(task_id="task-cancel",generation=1,
                    work_id="foreign",principal_id="principal-owner",assignment_epoch=1)
            with self.assertRaisesRegex(ValueError,"NOT_FOUND"):
                ledger.cancel_task(task_id="task-cancel",generation=2,
                    work_id="work-owner",principal_id="principal-owner",assignment_epoch=1)
            self.assertEqual("WATCHING",ledger.get("task-cancel",1)["state"])
            args={"task_id":"task-cancel","generation":1,"work_id":"work-owner",
                  "principal_id":"principal-owner","assignment_epoch":1}
            self.assertFalse(ledger.cancel_task(**args)["already_cancelled"])
            self.assertEqual("CANCELLED",ledger.get("task-cancel",1)["state"])
            self.assertTrue(DurableWatchLedger(ledger.store).cancel_task(**args)["already_cancelled"])
            self.assertEqual([],ledger.watching())
            with self.assertRaisesRegex(ValueError,"OWNER_MISMATCH"):
                ledger.cancel_task(task_id="task-cancel",generation=1,
                    work_id="work-owner",principal_id="principal-owner",assignment_epoch=2)

    def test_response_count_decrease_requires_exact_source_user_pairing(self):
        from bct.delayed_send_message import DelayedSendService
        body = "NEXT TASK — MANAGER\\nExact current result."
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        source_key = "trusted-user-turn-A"
        source_sha = "b" * 64
        baseline = {
            "baseline_count": 6, "baseline_generating": True,
            "baseline_sha": "a" * 64, "baseline_key": "old-assistant",
            "work_id": "work-owner", "principal_id": "principal-owner",
            "source_user_turn_key": source_key,
            "source_user_sha256": source_sha,
            "source_send_operation_id": "trusted-self-op",
            "source_send_sha256": source_sha,
            "instance_id": "instance", "conversation_key": "worker-uuid",
        }
        payload = {
            "ok": True, "conversationKey": "worker-uuid",
            "responseTurnCount": 5, "responseTurnKey": "new-assistant",
            "responseSha256": digest, "responseText": body,
            "observationState": "TERMINAL", "terminal": True,
            "generating": False, "inputReady": True,
            "latestUserTurnKey": source_key, "latestUserSha256": source_sha,
            "responseSourceUserTurnKey": source_key,
            "responseSourceUserSha256": source_sha,
        }
        service = DelayedSendService.__new__(DelayedSendService)
        from types import SimpleNamespace
        from bct.core.models import Outcome
        class ReceiptStore:
            valid = True
            def get_operation_for(self, **kwargs):
                if not self.valid:
                    raise KeyError("SOURCE_RECEIPT_MISSING")
                return SimpleNamespace(
                    state=SimpleNamespace(value="FINISHED"),
                    outcome=Outcome.APPLIED,
                    evidence={"command":"send-to-tab",
                              "host_request_id":"trusted-self-op",
                              "instance_id":"instance"})
        service.store = ReceiptStore()
        service.latest = lambda **kwargs: payload
        row = {"task_id": "task", "generation": 2,
               "conversation_key": "worker-uuid",
               "response_turn_id": "task:task:2",
               "context": baseline}
        result = service._response_for(row)
        self.assertEqual("new-assistant", result["response_turn_key"])
        self.assertEqual(body, result["response_text"])
        for change in (
            {"responseSourceUserTurnKey": "unrelated"},
            {"responseSourceUserSha256": "c" * 64},
            {"latestUserTurnKey": "other"},
            {"responseTurnKey": "old-assistant"},
            {"terminal": False},
            {"inputReady": False},
            {"generating": True},
            {"conversationKey": "other"},
        ):
            service.latest = lambda data={**payload, **change}, **kwargs: data
            self.assertEqual({}, service._response_for(row), change)
        service.latest = lambda **kwargs: {**payload, "responseTurnCount": 5}
        self.assertEqual({}, service._response_for(
            {**row, "context": {**baseline, "source_user_turn_key": ""}}))
        self.assertEqual({}, service._response_for(
            {**row, "context": {**baseline, "source_user_turn_key": "fallback-turn-3"}}))
        self.assertEqual({}, service._response_for(
            {**row, "context": {**baseline, "source_send_operation_id": ""}}))
        self.assertEqual({}, service._response_for(
            {**row, "context": {**baseline, "source_send_sha256": "c" * 64}}))
        service.store.valid = False
        self.assertEqual({},service._response_for(row))

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
