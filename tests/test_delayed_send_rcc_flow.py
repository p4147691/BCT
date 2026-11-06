from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.service import BCT
from bct.chain_direction import ChainDirectionLedger
from bct.chain_execution_plan import ChainExecutionPlanLedger
from bct.core.models import Principal, Outcome
from bct.features.rcc import BrowserFeature
from bct.send_delayed_message import (
    SendDelayedMessageService, _rcc_submitted_text_sha256,
    _self_prearm_guidance,
)

INSTANCE = "instance123"
SESSION = "a" * 32
WORKER = "6ae54613-5be8-83ee-9c47-1486efa232d8"
MANAGER = "6ae467d4-6d64-83e8-9b3e-c8c8aeb91bb3"


class SimulatedRcc:
    """Contract-compatible fake RCC for the full Task B SELF→MANAGER cycle."""
    def __init__(self):
        self.sent = []
        self.manual_user_text = "Initial manual work request"
        self.visible_count_override = None
        self.responses = {WORKER: ("", 0), MANAGER: ("", 0)}
        self.locations = {
            WORKER: {"tabId": 10, "windowId": 11, "index": 0},
            MANAGER: {"tabId": 12, "windowId": 11, "index": 1},
        }

    def reply(self, conversation, body):
        _, count = self.responses[conversation]
        self.responses[conversation] = (body, count + 1)

    def move(self, conversation, *, window_id, index):
        self.locations[conversation] = {
            **self.locations[conversation], "windowId": window_id, "index": index,
        }

    def request(self, *, instance_id, request_id, command, to="", text="",
                extra=None, timeout_s=30, before_write=None):
        assert instance_id == INSTANCE
        extra = extra or {}
        if command == "state":
            return {"ok": True, "state": {
                "instanceId": INSTANCE, "sessionId": SESSION,
                "tabs": [
                    {**self.locations[WORKER], "url": "https://chatgpt.com/c/" + WORKER},
                    {**self.locations[MANAGER], "url": "https://chatgpt.com/c/" + MANAGER},
                ],
            }}
        if command == "read-latest-assistant":
            key = extra["conversationKey"]
            location = self.locations[key]
            assert extra["tabId"] == location["tabId"]
            assert extra["windowId"] == location["windowId"]
            body, count = self.responses[key]
            latest_send = next((text for target,text,_ in reversed(self.sent)
                                if target == key), "")
            latest_user_key = "trusted-user-send-1" if latest_send else "manual-user-turn-1"
            latest_user_sha = _rcc_submitted_text_sha256(
                latest_send if latest_send else self.manual_user_text
            )
            return {
                "latestUserTurnKey": latest_user_key,
                "latestUserSha256": latest_user_sha,
                "latestUserTextOccurrenceCount": 1,
                "responseSourceUserTextOccurrenceCount": 1,
                "responseSourceUserTurnKey": ("manual-user-turn-1" if count == 1
                    else latest_user_key) if count else "",
                "responseSourceUserSha256": (_rcc_submitted_text_sha256(
                    self.manual_user_text) if count == 1 else latest_user_sha)
                    if count else "",
                "ok": True, "conversationKey": key,
                "responseTurnCount": (self.visible_count_override
                                      if self.visible_count_override is not None else count),
                "responseTurnKey": f"assistant-{count}" if count else "",
                "responseText": body,
                "responseSha256": hashlib.sha256(body.encode()).hexdigest() if body else "",
                "observationState": "TERMINAL" if count else "EMPTY",
                "terminal": bool(count), "generating": False,
                "inputReady": bool(count),
            }
        if command == "send-to-tab":
            location = self.locations[extra["conversationKey"]]
            assert extra["tabId"] == location["tabId"]
            assert extra["windowId"] == location["windowId"]
            self.sent.append((extra["conversationKey"], text, request_id))
            return {
                "type": "host:result", "ok": True, "state": "SUBMITTED",
                "submitted": True, "operationId": request_id,
                "instanceId": instance_id, "sessionId": extra["sessionId"],
                "tabId": extra["tabId"], "windowId": extra["windowId"],
            }
        raise AssertionError(f"Unexpected RCC command: {command}")


class SelfPrearmGuidanceTests(unittest.TestCase):
    def test_names_exact_public_command_without_rediscovering_target(self):
        text = _self_prearm_guidance(work_id="work-1", task_id="task-1")
        self.assertIn(
            'bct_send_delayed_message(work_id="work-1", task_id="task-1")',
            text,
        )
        self.assertIn("대상·창·탭을 다시 고르지 않습니다", text)
        self.assertIn("범용 execute capability", text)


class DelayedSendRccFlowTests(unittest.TestCase):
    def test_verified_prearm_before_send_handles_fast_completed_reply(self):
        # Regression: real 2026-11-01 tests armed AFTER an already-terminal
        # response. A planned, exact BCT send must be reserved BEFORE sending.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            policy=root/"bct.toml"
            policy.write_text('[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                              encoding="utf-8")
            bct=BCT(state_path=root/"state.sqlite",policy_path=policy)
            rcc=SimulatedRcc()
            feature=BrowserFeature(rcc,store=bct.store)
            bct.operations._features["browser"]=feature
            principal=Principal("tester","test",frozenset({"browser"}))
            work=bct.create_work(work_id="prearmed-test",request_summary="one exact send",
                                 roots=[str(root)],actions=["browser"],principal=principal)
            service=SendDelayedMessageService(store=bct.store,browser_feature=feature,
                                       operations=bct.operations)
            rcc.reply(WORKER,"Previous already finished assistant response.")
            # The already finished user/assistant pair cannot be falsely armed.
            late=bct.operations.run(principal=principal,work_id=work.work_id,
                 operation_id="late-old-answer",capability="browser",
                 arguments={"command":"send-delayed-message","task_id":"late-task",
                            "instance_id":INSTANCE,"conversation_key":WORKER,
                            "manager_conversation_key":MANAGER})
            self.assertEqual(Outcome.NOT_APPLIED,late.outcome)
            self.assertEqual("DELAYED_PREARM_RESPONSE_ALREADY_TERMINAL",
                             late.evidence["code"])
            self.assertIsNone(service.ledger.get("late-task",1))
            prompt="Complete exactly this task. NEXT TASK — MANAGER"
            send_id="verified-exact-planned-send-01"
            planned=bct.operations.run(principal=principal,work_id=work.work_id,
                 operation_id="planned-prearm-first",capability="browser",
                 arguments={"command":"send-delayed-message","task_id":"planned-task",
                            "instance_id":INSTANCE,"conversation_key":WORKER,
                            "manager_conversation_key":MANAGER,
                            "planned_send_operation_id":send_id,
                            "planned_send_text":prompt,
                            "execution_path":"DIRECTION_DECLARED",
                            "chain_direction_id":"direction-e2e"})
            self.assertEqual(Outcome.APPLIED,planned.outcome,planned.as_dict())
            self.assertEqual("WATCHING",service.ledger.get("planned-task",1)["state"])
            import json
            provenance = json.loads(service.ledger.get("planned-task",1)["context_json"])
            self.assertEqual("DIRECTION_DECLARED", provenance["execution_path"])
            self.assertEqual("direction-e2e", provenance["chain_direction_id"])
            # No BCT send receipt yet -> no dispatch of the previous answer.
            self.assertEqual([],service.poll_once()["events"])
            send=bct.operations.run(principal=principal,work_id=work.work_id,
                operation_id=send_id,capability="browser",
                arguments={"command":"send-message","instance_id":INSTANCE,
                           "session_id":SESSION,"tab_id":10,"window_id":11,
                           "conversation_key":WORKER,"text":prompt})
            self.assertEqual(Outcome.APPLIED,send.outcome,send.as_dict())
            self.assertEqual(WORKER,send.evidence["conversation_key"])
            self.assertEqual(_rcc_submitted_text_sha256(prompt),
                             send.evidence["source_message_sha256"])
            # User prompt is now visible; earlier completed answer remains.
            self.assertEqual([],service.poll_once()["events"])
            # The real response may complete before the next polling cycle.
            # ChatGPT commonly keeps a short continuation body on the marker
            # line.  This remains an explicit, unambiguous MANAGER branch.
            rcc.reply(WORKER,"NEXT TASK — MANAGER: PLANNED_SEND_E2E_OK")
            # A tab may be reordered or attached to a different Chrome window
            # while the durable watch is active. The watch and return path
            # reacquire both conversations by unique conversation identity.
            rcc.move(WORKER, window_id=22, index=3)
            rcc.move(MANAGER, window_id=23, index=0)
            polled=service.poll_once()
            self.assertEqual("RETURNED_TO_MANAGER",polled["events"][0]["status"])
            self.assertEqual(MANAGER,rcc.sent[-1][0])
            self.assertEqual("PLANNED_SEND_E2E_OK",rcc.sent[-1][1])
            self.assertEqual("RETURNED_TO_MANAGER",
                             service.ledger.get("planned-task",1)["state"])
            self.assertEqual([],service.poll_once()["events"])
            # The same already-applied send receipt cannot be reused as a new
            # planned prearm even if a matching Assistant answer is terminal.
            reused=bct.operations.run(principal=principal,work_id=work.work_id,
                operation_id="stale-planned-reuse",capability="browser",
                arguments={"command":"send-delayed-message","task_id":"stale-reuse-task",
                           "instance_id":INSTANCE,"conversation_key":WORKER,
                           "manager_conversation_key":MANAGER,
                           "planned_send_operation_id":send_id,
                           "planned_send_text":prompt})
            self.assertEqual(Outcome.NOT_APPLIED,reused.outcome)
            self.assertEqual("DELAYED_PLANNED_SEND_OPERATION_ALREADY_EXISTS",
                             reused.evidence["code"])
            self.assertIsNone(service.ledger.get("stale-reuse-task",1))

    def test_worker_prearm_self_then_manager_live_path_with_exact_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            browser = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = browser
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="task-run-work", request_summary="SELF→MANAGER task",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=browser, operations=bct.operations,
            )
            # The worker calls the public Delayed Send operation BEFORE writing.
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="task-prearm-1", capability="browser",
                arguments={"command": "send-delayed-message",
                           "task_id": "task-1", "instance_id": INSTANCE,
                           "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            self.assertEqual(1, armed.output["generation"])
            # B records its concrete plan after A's direction has started.
            # The next SELF delivery must carry that exact plan back to B,
            # without creating another Chain or using task_run.
            directions = ChainDirectionLedger(bct.store)
            directions.save(
                direction_id="direction-1", work_id=work.work_id,
                source_kind="USER", decision="NEW_TASK",
                direction_text="Complete the bounded Worker task safely.",
            )
            directions.plan_chain(
                direction_id="direction-1", work_id=work.work_id,
                task_id="task-1", operation_id="chain-1",
                instruction_text="Complete the bounded Worker task safely.",
            )
            directions.mark_chain_started(
                direction_id="direction-1", work_id=work.work_id,
                task_id="task-1", operation_id="chain-1",
            )
            plan_text = "Inspect the remaining code, make the bounded fix, then verify E2E."
            ChainExecutionPlanLedger(bct.store).save(
                plan_id="plan-1", work_id=work.work_id,
                direction_id="direction-1", task_id="task-1",
                generation=1, plan_text=plan_text,
            )
            rcc.reply(WORKER, "Implemented stage one.\nNEXT TASK — SELF\nFinish the remaining code.")
            first = service.poll_once()
            self.assertEqual("SELF_SENT", first["events"][0]["status"])
            self.assertEqual(1, len(rcc.sent))
            self.assertEqual(WORKER, rcc.sent[0][0])
            self.assertIn("Finish the remaining code.", rcc.sent[0][1])
            self.assertIn(plan_text, rcc.sent[0][1])
            self.assertIn("plan_id=plan-1", rcc.sent[0][1])
            self.assertIn("bct_send_delayed_message", rcc.sent[0][1])
            self.assertIn("범용 execute capability", rcc.sent[0][1])
            self.assertEqual("RESERVED", service.ledger.get("task-1", 2)["state"])
            import json
            reserved = json.loads(service.ledger.get("task-1", 2)["context_json"])
            self.assertEqual(rcc.sent[0][2], reserved["source_send_operation_id"])
            self.assertEqual(_rcc_submitted_text_sha256(rcc.sent[0][1]),
                             reserved["source_send_sha256"])
            # The next message asks B to prearm the same Task ID again.
            rearmed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="task-prearm-2", capability="browser",
                arguments={"command": "send-delayed-message", "task_id": "task-1"},
            )
            self.assertEqual(Outcome.APPLIED, rearmed.outcome, rearmed.as_dict())
            self.assertEqual(2, rearmed.output["generation"])
            rcc.reply(WORKER, "Final stage done.\nNEXT TASK — MANAGER\nFinished, report complete.")
            # DOM may render fewer assistant nodes than at prearm; trusted SELF
            # source receipt + exact user pair still identify this response.
            rcc.visible_count_override = 0
            second = service.poll_once()
            self.assertEqual("RETURNED_TO_MANAGER", second["events"][0]["status"])
            self.assertEqual(2, len(rcc.sent))
            self.assertEqual(MANAGER, rcc.sent[1][0])
            self.assertEqual("Finished, report complete.", rcc.sent[1][1])
            self.assertEqual("RETURNED_TO_MANAGER", service.ledger.get("task-1", 2)["state"])
            self.assertEqual([], service.poll_once()["events"])
            self.assertEqual([], bct.store.claim_diagnostics())


if __name__ == "__main__":
    unittest.main()
