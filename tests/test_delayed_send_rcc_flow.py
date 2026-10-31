from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.service import BCT
from bct.core.models import Principal, Outcome
from bct.features.rcc import RelayBrowserFeature
from bct.delayed_send_message import DelayedSendService, _rcc_submitted_text_sha256

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

    def reply(self, conversation, body):
        _, count = self.responses[conversation]
        self.responses[conversation] = (body, count + 1)

    def request(self, *, instance_id, request_id, command, to="", text="",
                extra=None, timeout_s=30, before_write=None):
        assert instance_id == INSTANCE
        extra = extra or {}
        if command == "state":
            return {"ok": True, "state": {
                "instanceId": INSTANCE, "sessionId": SESSION,
                "tabs": [
                    {"tabId": 10, "windowId": 11, "url": "https://chatgpt.com/c/" + WORKER},
                    {"tabId": 12, "windowId": 11, "url": "https://chatgpt.com/c/" + MANAGER},
                ],
            }}
        if command == "read-latest-assistant":
            key = extra["conversationKey"]
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
                "responseSourceUserTurnKey": latest_user_key if count else "",
                "responseSourceUserSha256": latest_user_sha if count else "",
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
            self.sent.append((extra["conversationKey"], text, request_id))
            return {
                "type": "host:result", "ok": True, "state": "SUBMITTED",
                "submitted": True, "operationId": request_id,
                "instanceId": instance_id, "sessionId": extra["sessionId"],
                "tabId": extra["tabId"], "windowId": extra["windowId"],
            }
        raise AssertionError(f"Unexpected RCC command: {command}")


class DelayedSendRccFlowTests(unittest.TestCase):
    def test_worker_prearm_self_then_manager_live_path_with_exact_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            browser = RelayBrowserFeature(rcc, store=bct.store)
            bct.operations._features["relay_browser"] = browser
            principal = Principal("tester", "test", frozenset({"relay_browser"}))
            work = bct.create_work(
                work_id="task-run-work", request_summary="SELF→MANAGER task",
                roots=[str(root)], actions=["relay_browser"], principal=principal,
            )
            service = DelayedSendService(
                store=bct.store, relay_feature=browser, operations=bct.operations,
            )
            # The worker calls the public Delayed Send operation BEFORE writing.
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="task-prearm-1", capability="relay_browser",
                arguments={"command": "delayed-send-message",
                           "task_id": "task-1", "instance_id": INSTANCE,
                           "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            self.assertEqual(1, armed.output["generation"])
            rcc.reply(WORKER, "Implemented stage one.\nNEXT TASK — SELF\nFinish the remaining code.")
            first = service.poll_once()
            self.assertEqual("SELF_SENT", first["events"][0]["status"])
            self.assertEqual(1, len(rcc.sent))
            self.assertEqual(WORKER, rcc.sent[0][0])
            self.assertIn("Finish the remaining code.", rcc.sent[0][1])
            self.assertIn("Delayed Send Message", rcc.sent[0][1])
            self.assertEqual("RESERVED", service.ledger.get("task-1", 2)["state"])
            import json
            reserved = json.loads(service.ledger.get("task-1", 2)["context_json"])
            self.assertEqual(rcc.sent[0][2], reserved["source_send_operation_id"])
            self.assertEqual(_rcc_submitted_text_sha256(rcc.sent[0][1]),
                             reserved["source_send_sha256"])
            # The next message asks B to prearm the same Task ID again.
            rearmed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="task-prearm-2", capability="relay_browser",
                arguments={"command": "delayed-send-message", "task_id": "task-1"},
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
