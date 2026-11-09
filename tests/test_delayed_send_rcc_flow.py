from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bct.service import BCT
from bct.chain_direction import ChainDirectionLedger
from bct.chain_execution_plan import ChainExecutionPlanLedger
from bct.chain_manager_recovery import ChainManagerRecoveryLedger
from bct.chain_worker_provision import ChainWorkerProvisionRecipe
from bct.core.models import Principal, Outcome
from bct.features.rcc import BrowserFeature
from bct.mcp_server import build_mcp
from bct.send_delayed_message import (
    SendDelayedMessageService, _rcc_submitted_text_sha256,
    _self_prearm_guidance,
)

INSTANCE = "instance123"
SESSION = "a" * 32
WORKER = "6ae54613-5be8-83ee-9c47-1486efa232d8"
MANAGER = "6ae467d4-6d64-83e8-9b3e-c8c8aeb91bb3"
SUPERVISOR = "8ce76835-7df0-85aa-be69-36a8cfc454fa"
SUCCESSOR = "7be65724-6cf9-84ff-ad58-2597fab343e9"


class SimulatedRcc:
    """Contract-compatible fake RCC for the full Task B SELF→MANAGER cycle."""
    def __init__(self):
        self.sent = []
        self.attention = ""
        self.created = None
        self.create_count = 0
        self.new_chat_send_outcomes = []
        self.reconcile_terminal = False
        self.reconcile_send = None
        self.manual_user_text = "Initial manual work request"
        self.visible_count_override = None
        self.worker_detached = False
        self.manager_disconnected = False
        self.responses = {WORKER: ("", 0), MANAGER: ("", 0), SUPERVISOR: ("", 0)}
        self.locations = {
            WORKER: {"tabId": 10, "windowId": 11, "index": 0},
            MANAGER: {"tabId": 12, "windowId": 11, "index": 1},
            SUPERVISOR: {"tabId": 13, "windowId": 11, "index": 2},
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
        command = {
            "rcc_get_extension_state": "state",
            "rcc_create_chat_tab": "create-chat-tab",
            "rcc_move_tab_to_window": "move-tab",
            "rcc_get_latest_assistant_message": "read-latest-assistant",
            "rcc_send_message_to_tab": "send-to-tab",
            "rcc_send_message_to_created_tab": "send-to-created-tab",
            "rcc_get_operation_result": "result",
        }.get(command, command)
        extra = extra or {}
        if command == "state":
            tabs = [
                {**self.locations[WORKER], "url": "https://chatgpt.com/c/" + WORKER},
                {**self.locations[MANAGER], "url": "https://chatgpt.com/c/" + MANAGER},
                {**self.locations[SUPERVISOR], "url": "https://chatgpt.com/c/" + SUPERVISOR},
            ]
            if self.created:
                tabs.append({**self.created, "url": self.created.get("url", "https://chatgpt.com/")})
            return {"ok": True, "state": {
                "instanceId": INSTANCE, "sessionId": SESSION,
                "tabs": tabs,
                "endpoints": [
                    {**self.locations[WORKER],
                     "conversationKey": "" if self.worker_detached else WORKER,
                     "generating": False, "connection": {"disconnected": False},
                     "telemetry": {"user_attention": (
                         {"kind": self.attention, "label": self.attention}
                         if self.attention else None)}},
                    {**self.locations[MANAGER], "conversationKey": MANAGER,
                     "generating": False, "connection": {
                         "disconnected": self.manager_disconnected},
                     "telemetry": {"user_attention": None}},
                    {**self.locations[SUPERVISOR], "conversationKey": SUPERVISOR,
                     "generating": False, "connection": {"disconnected": False},
                     "telemetry": {"user_attention": None}},
                ],
            }}
        if command == "create-chat-tab":
            self.create_count += 1
            self.created = {"tabId": 20, "windowId": extra.get("windowId", 11), "index": 2}
            return {"ok": True, "requestId": request_id,
                    "tabId": self.created["tabId"], "windowId": self.created["windowId"]}
        if command == "move-tab":
            assert self.created and extra["tabId"] == self.created["tabId"]
            self.created.update({"windowId": extra["targetWindowId"],
                                 "index": extra["index"]})
            for key, location in list(self.locations.items()):
                if location["tabId"] == extra["tabId"]:
                    self.locations[key] = dict(self.created)
            return {"ok": True, "requestId": request_id, "state": "APPLIED",
                    "tabId": extra["tabId"], "windowId": extra["targetWindowId"],
                    "index": extra["index"]}
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
                "responseSourceUserTurnKey": ("manual-user-turn-1" if count == 1 and key != SUCCESSOR
                    else latest_user_key) if count else "",
                "responseSourceUserSha256": (_rcc_submitted_text_sha256(
                    self.manual_user_text) if count == 1 and key != SUCCESSOR else latest_user_sha)
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
        if command == "send-to-created-tab":
            assert self.created and extra["tabId"] == self.created["tabId"]
            if self.new_chat_send_outcomes:
                outcome = self.new_chat_send_outcomes.pop(0)
                if outcome == "NOT_APPLIED":
                    return {"type": "host:result", "ok": False,
                            "state": "NOT_APPLIED", "error": "SEND_REJECTED"}
                if outcome == "UNKNOWN":
                    return {"type": "host:result", "ok": False,
                            "state": "SUBMIT_UNKNOWN"}
                if outcome == "UNKNOWN_APPLIED":
                    self.created["url"] = "https://chatgpt.com/c/" + SUCCESSOR
                    self.locations[SUCCESSOR] = dict(self.created)
                    self.responses[SUCCESSOR] = ("", 0)
                    self.sent.append((SUCCESSOR, text, request_id))
                    self.reconcile_send = {
                        "id": request_id,
                        "create_id": extra["createOperationId"],
                        "session_id": extra["sessionId"],
                        "tab_id": extra["tabId"],
                        "window_id": extra["windowId"],
                        "text": text,
                    }
                    return {"type": "host:result", "ok": False,
                            "state": "SUBMIT_UNKNOWN"}
            self.created["url"] = "https://chatgpt.com/c/" + SUCCESSOR
            self.locations[SUCCESSOR] = dict(self.created)
            self.responses[SUCCESSOR] = ("", 0)
            self.sent.append((SUCCESSOR, text, request_id))
            return {"type": "host:result", "ok": True, "state": "SUBMITTED",
                    "submitted": True, "operationId": request_id,
                    "conversationKey": SUCCESSOR, "instanceId": instance_id,
                    "sessionId": extra["sessionId"], "tabId": extra["tabId"],
                    "windowId": extra["windowId"]}
        if command == "result":
            if not self.reconcile_terminal or not self.reconcile_send:
                return {"type": "host:result", "ok": True, "relayId": text,
                        "found": False, "completed": False, "pending": True}
            sent = self.reconcile_send
            fingerprint = json.dumps([
                sent["create_id"], INSTANCE, sent["session_id"], sent["tab_id"],
                sent["window_id"], sent["text"],
            ], separators=(",", ":"))
            return {"type": "host:result", "ok": True, "relayId": text,
                    "found": True, "completed": True, "pending": False,
                    "result": {"id": sent["id"], "ok": True, "ambiguous": False,
                               "tabId": sent["tab_id"],
                               "conversationKey": SUCCESSOR,
                               "resultState": "RESULT_PERSISTED",
                               "fingerprint": fingerprint}}
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

    def test_exact_watched_tab_detach_records_recovery_needed_without_new_chat(self):
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
                work_id="detached-worker-work", request_summary="restart detached Worker",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=browser, operations=bct.operations,
            )
            prompt = "Long running task with explicit continuation."
            send_id = "detached-worker-send"
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="detached-worker-arm", capability="browser",
                arguments={"command": "send-delayed-message",
                           "task_id": "detached-worker-task",
                           "instance_id": INSTANCE,
                           "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER,
                           "planned_send_operation_id": send_id,
                           "planned_send_text": prompt,
                           "watched_session_id": SESSION,
                           "watched_tab_id": 10,
                           "watched_window_id": 11},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome, armed.as_dict())
            sent = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id=send_id, capability="browser",
                arguments={"command": "send-message", "instance_id": INSTANCE,
                           "session_id": SESSION, "tab_id": 10, "window_id": 11,
                           "conversation_key": WORKER, "text": prompt},
            )
            self.assertEqual(Outcome.APPLIED, sent.outcome, sent.as_dict())
            rcc.worker_detached = True
            self.assertEqual([], service.poll_once()["events"])
            second = service.poll_once()
            self.assertEqual("RECOVERY_NEEDED", second["events"][0]["status"])
            self.assertEqual("NEW_CHAT_REQUIRED", second["events"][0]["kind"])
            self.assertEqual(0, rcc.create_count)
            watched = service.ledger.get("detached-worker-task", 1)
            self.assertEqual("WATCHING", watched["state"])
            self.assertEqual(MANAGER, json.loads(watched["context_json"])["recovery_needed"]["reported_manager_conversation_key"])
class DelayedSendRccFlowTests(unittest.TestCase):
    def test_disconnected_manager_return_is_checkpointed_and_collected_by_supervisor(self):
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
                work_id="manager-recovery-work",
                request_summary="preserve a Manager return during A recovery",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=browser, operations=bct.operations,
            )
            rcc.reply(WORKER, "Earlier completed response before this exact Direction.")
            prompt = "Complete this exact bounded task."
            send_id = "manager-recovery-source-send"
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="manager-recovery-arm", capability="browser",
                arguments={
                    "command": "send-delayed-message",
                    "task_id": "manager-recovery-task",
                    "instance_id": INSTANCE,
                    "conversation_key": WORKER,
                    "manager_conversation_key": MANAGER,
                    "manager_instance_id": INSTANCE,
                    "supervisor_conversation_key": SUPERVISOR,
                    "supervisor_instance_id": INSTANCE,
                    "planned_send_operation_id": send_id,
                    "planned_send_text": prompt,
                    "execution_path": "DIRECTION_DECLARED",
                    "chain_direction_id": "manager-recovery-direction",
                },
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome, armed.as_dict())
            sent = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id=send_id, capability="browser",
                arguments={
                    "command": "send-message", "instance_id": INSTANCE,
                    "session_id": SESSION, "tab_id": 10, "window_id": 11,
                    "conversation_key": WORKER, "text": prompt,
                },
            )
            self.assertEqual(Outcome.APPLIED, sent.outcome, sent.as_dict())
            rcc.reply(
                WORKER,
                "Done.\nNEXT TASK — MANAGER\nPreserve this exact completion report.",
            )
            rcc.manager_disconnected = True
            outcome = service.poll_once()
            self.assertEqual(
                "COLLECTED_BY_SUPERVISOR", outcome["events"][0]["status"]
            )
            self.assertEqual(SUPERVISOR, rcc.sent[-1][0])
            self.assertIn("DO NOT ACT AS MANAGER", rcc.sent[-1][1])
            checkpoint = ChainManagerRecoveryLedger(bct.store).get(
                task_id="manager-recovery-task", generation=1,
            )
            self.assertEqual("COLLECTED_BY_SUPERVISOR", checkpoint["delivery_state"])
            self.assertEqual(SUPERVISOR, checkpoint["destination_conversation_key"])
            self.assertTrue(checkpoint["return_payload"].endswith(
                "Preserve this exact completion report."
            ))
            inbox = ChainManagerRecoveryLedger(bct.store).inbox(
                work_id=work.work_id,
                report_target_conversation_key=SUPERVISOR,
            )
            self.assertEqual(1, len(inbox))
            recovery = ChainManagerRecoveryLedger(bct.store)
            self.assertEqual(1, recovery.rebind_active_manager(
                work_id=work.work_id,
                manager_conversation_key=SUCCESSOR,
                succession_proofs=[{
                    "transfer_id": "transfer-1",
                    "predecessor_conversation_key": MANAGER,
                    "successor_conversation_key": SUCCESSOR,
                }],
            ))
            acknowledged = recovery.acknowledge(
                work_id=work.work_id, task_id="manager-recovery-task",
                generation=1, manager_conversation_key=SUCCESSOR,
            )
            self.assertEqual(SUCCESSOR, acknowledged["acknowledged_by"])
            self.assertGreater(acknowledged["acknowledged_at"], 0)

    def test_chain_worker_provision_recipe_replays_without_duplicate_tab_or_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser","conversation_network_update"]\n'
                'approval_actions=[]\n', encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            feature = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = feature
            principal = Principal(
                "tester", "test", frozenset({"browser", "conversation_network_update"}),
            )
            work = bct.create_work(
                work_id="worker-provision-work", request_summary="parallel child Worker",
                roots=[str(root)], actions=["browser", "conversation_network_update"],
                principal=principal,
            )
            direction = {
                "direction_id": "parent-direction", "work_id": work.work_id,
                "source_kind": "USER", "source_task_id": "", "source_generation": 0,
                "source_result_sha256": "", "direction_text": "Complete the parent goal.",
            }
            def status_provider():
                tabs = [
                    {"tab_id": value["tabId"], "window_id": value["windowId"],
                     "conversation_key": key}
                    for key, value in rcc.locations.items()
                ]
                if rcc.created and SUCCESSOR not in rcc.locations:
                    tabs.append({"tab_id": rcc.created["tabId"],
                                 "window_id": rcc.created["windowId"],
                                 "conversation_key": ""})
                return {"monitor": {"rcc": {"instances": [{
                    "instance_id": INSTANCE, "session_id": SESSION,
                    "state": "OPEN", "cached": False, "tabs": tabs,
                }]}}}
            recipe = ChainWorkerProvisionRecipe(
                bct=bct, principal=principal, status_provider=status_provider,
            )
            request = {
                "preparation_id": "parallel-lint-fix", "command": "create-chat-tab",
                "instance_id": INSTANCE, "window_id": 11,
                "instruction": "Fix the independent lint regression.",
                "display_name": "Lint Worker", "scope_name": "Project",
                "role_tags": ["Worker"],
                "arrange": {"target_window_id": 21, "index": 0},
            }
            first = recipe.run(
                direction=direction, assessment={"manager_conversation_key": MANAGER},
                work=work, task_id="lint-child", worker_preparation=request,
            )
            self.assertEqual("STARTED", first["status"], first)
            self.assertEqual(SUCCESSOR, first["conversation_key"])
            self.assertEqual(21, first["attachment"]["window_id"])
            self.assertEqual(11, rcc.locations[MANAGER]["windowId"])
            self.assertEqual(11, rcc.locations[WORKER]["windowId"])
            second = recipe.run(
                direction=direction, assessment={"manager_conversation_key": MANAGER},
                work=work, task_id="lint-child", worker_preparation=request,
            )
            self.assertEqual("STARTED", second["status"], second)
            self.assertEqual(1, rcc.create_count)
            self.assertEqual(1, len([item for item in rcc.sent if item[0] == SUCCESSOR]))

    def test_created_chat_receipts_bind_zero_baseline_and_capture_fast_first_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            feature = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = feature
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="created-worker-work", request_summary="prepare exact new Worker",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            prompt = "Handle the independent child task and report to Manager."
            created = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="created-worker-tab", capability="browser",
                arguments={"command": "create-chat-tab", "instance_id": INSTANCE,
                           "window_id": 11},
            )
            self.assertEqual(Outcome.APPLIED, created.outcome, created.as_dict())
            sent = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="created-worker-send", capability="browser",
                arguments={"command": "send-message", "instance_id": INSTANCE,
                           "session_id": SESSION, "tab_id": 20, "window_id": 11,
                           "conversation_key": "", "create_operation_id": "created-worker-tab",
                           "text": prompt},
            )
            self.assertEqual(Outcome.APPLIED, sent.outcome, sent.as_dict())
            self.assertEqual(SUCCESSOR, sent.evidence["conversation_key"])
            # Prove the bootstrap baseline does not miss a response which is
            # already terminal when the newly assigned UUID is bound.
            rcc.reply(SUCCESSOR, "NEXT TASK — MANAGER: CHILD_TASK_COMPLETE")
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="created-worker-watch", capability="browser",
                arguments={"command": "send-delayed-message", "task_id": "created-child-task",
                           "instance_id": INSTANCE, "conversation_key": SUCCESSOR,
                           "manager_conversation_key": MANAGER,
                           "manager_instance_id": INSTANCE,
                           "planned_send_operation_id": "created-worker-send",
                           "planned_send_text": prompt,
                           "bootstrap_create_operation_id": "created-worker-tab",
                           "watched_session_id": SESSION, "watched_tab_id": 20,
                           "watched_window_id": 11},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome, armed.as_dict())
            watch = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            ).ledger.get("created-child-task", 1)
            self.assertEqual("WATCHING", watch["state"])
            self.assertEqual(0, json.loads(watch["context_json"])["baseline_count"])

    def test_explicit_worker_stop_signal_records_recovery_needed_without_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            feature = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = feature
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="auto-restart-work", request_summary="restart stopped Worker",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            )
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="auto-restart-prearm", capability="browser",
                arguments={"command": "send-delayed-message", "task_id": "restart-task",
                           "instance_id": INSTANCE, "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            rcc.attention = "RETRY_REQUIRED"
            self.assertEqual([], service.poll_once()["events"])
            second = service.poll_once()
            self.assertEqual("RECOVERY_NEEDED", second["events"][0]["status"])
            self.assertEqual("RETRY_REQUIRED", second["events"][0]["kind"])
            self.assertEqual("WATCHING", service.ledger.get("restart-task", 1)["state"])
            self.assertIsNone(service.ledger.get("restart-task", 2))
            self.assertEqual([], rcc.sent)

    def test_new_chat_required_records_recovery_needed_without_metadata_transfer(self):
        from bct.conversation_network import upsert_conversation, configure_conversation_scope
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            feature = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = feature
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="new-chat-restart-work", request_summary="replace stopped Worker",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            upsert_conversation(bct.store, conversation_key=WORKER, display_name="Worker")
            configure_conversation_scope(
                bct.store, conversation_key=WORKER, display_name="Worker",
                scope_name="Restart network",
                role_tags=["Worker"], assigned_task="restart-task",
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            )
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="new-chat-prearm", capability="browser",
                arguments={"command": "send-delayed-message", "task_id": "replace-task",
                           "instance_id": INSTANCE, "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            rcc.attention = "NEW_CHAT_REQUIRED"
            self.assertEqual([], service.poll_once()["events"])
            result = service.poll_once()["events"][0]
            self.assertEqual("RECOVERY_NEEDED", result["status"])
            self.assertEqual("NEW_CHAT_REQUIRED", result["kind"])
            self.assertEqual("WATCHING", service.ledger.get("replace-task", 1)["state"])
            self.assertIsNone(service.ledger.get("replace-task", 2))
            with bct.store._readonly() as db:
                active = db.execute(
                    "SELECT conversation_key FROM conversation_network_memberships "
                    "WHERE activity='ACTIVE'"
                ).fetchall()
            self.assertEqual([WORKER], [row["conversation_key"] for row in active])

    def test_new_chat_required_never_creates_or_retries_a_tab_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            rcc.new_chat_send_outcomes = ["NOT_APPLIED"]
            feature = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = feature
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="retry-created-chat-work", request_summary="retry created Chat",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            )
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="retry-created-chat-prearm", capability="browser",
                arguments={"command": "send-delayed-message", "task_id": "retry-created-chat",
                           "instance_id": INSTANCE, "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            rcc.attention = "NEW_CHAT_REQUIRED"
            service.poll_once()
            first = service.poll_once()["events"][0]
            self.assertEqual("RECOVERY_NEEDED", first["status"])
            self.assertEqual(0, rcc.create_count)
            self.assertEqual([], rcc.sent)
            self.assertEqual([], service.poll_once()["events"])

    def test_unknown_new_chat_signal_never_creates_a_chat_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            rcc.new_chat_send_outcomes = ["UNKNOWN"]
            feature = BrowserFeature(rcc, store=bct.store)
            feature.result_readback_timeout_s = 0.01
            bct.operations._features["browser"] = feature
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="unknown-created-chat-work", request_summary="unknown created Chat",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            )
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="unknown-created-chat-prearm", capability="browser",
                arguments={"command": "send-delayed-message", "task_id": "unknown-created-chat",
                           "instance_id": INSTANCE, "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            rcc.attention = "NEW_CHAT_REQUIRED"
            service.poll_once()
            result = service.poll_once()["events"][0]
            self.assertEqual("RECOVERY_NEEDED", result["status"])
            self.assertEqual("WATCHING", service.ledger.get("unknown-created-chat", 1)["state"])
            self.assertEqual([], service.poll_once()["events"])
            self.assertEqual(0, rcc.create_count)
            self.assertEqual([], rcc.sent)

    def test_applied_unknown_new_chat_signal_is_reported_without_any_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n',
                encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            rcc.new_chat_send_outcomes = ["UNKNOWN_APPLIED"]
            feature = BrowserFeature(rcc, store=bct.store)
            feature.result_readback_timeout_s = 0.01
            bct.operations._features["browser"] = feature
            principal = Principal("tester", "test", frozenset({"browser"}))
            work = bct.create_work(
                work_id="reconcile-created-chat-work",
                request_summary="reconcile created Chat send",
                roots=[str(root)], actions=["browser"], principal=principal,
            )
            service = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            )
            armed = bct.operations.run(
                principal=principal, work_id=work.work_id,
                operation_id="reconcile-created-chat-prearm", capability="browser",
                arguments={"command": "send-delayed-message",
                           "task_id": "reconcile-created-chat",
                           "instance_id": INSTANCE, "conversation_key": WORKER,
                           "manager_conversation_key": MANAGER},
            )
            self.assertEqual(Outcome.APPLIED, armed.outcome)
            rcc.attention = "NEW_CHAT_REQUIRED"
            service.poll_once()
            first = service.poll_once()["events"][0]
            self.assertEqual("RECOVERY_NEEDED", first["status"])
            self.assertEqual(0, rcc.create_count)
            self.assertEqual([], rcc.sent)
            watched = service.ledger.get("reconcile-created-chat", 1)
            self.assertEqual("WATCHING", watched["state"])
            self.assertEqual("NEW_CHAT_REQUIRED", json.loads(
                watched["context_json"])["recovery_needed"]["kind"])

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
            self.assertIn("PLAN_MISSING", rcc.sent[-1][1])
            self.assertTrue(rcc.sent[-1][1].endswith("PLANNED_SEND_E2E_OK"))
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
                           "manager_conversation_key": MANAGER,
                           "execution_path": "DIRECTION_DECLARED",
                           "chain_direction_id": "direction-1"},
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
            revised_plan_text = (
                "Inspect the remaining code, repair the discovered edge case, then verify E2E."
            )
            ChainExecutionPlanLedger(bct.store).update(
                plan_id="plan-1", plan_text=revised_plan_text,
                update_reason="The initial inspection found one additional bounded repair.",
            )
            rcc.reply(WORKER, "Implemented stage one.\nNEXT TASK — SELF\nFinish the remaining code.")
            first = service.poll_once()
            self.assertEqual("SELF_SENT", first["events"][0]["status"])
            self.assertEqual(1, len(rcc.sent))
            self.assertEqual(WORKER, rcc.sent[0][0])
            self.assertIn("Finish the remaining code.", rcc.sent[0][1])
            self.assertIn(revised_plan_text, rcc.sent[0][1])
            self.assertNotIn(plan_text, rcc.sent[0][1])
            self.assertIn("plan_id=plan-1", rcc.sent[0][1])
            self.assertIn("PROGRESS: <completed>/<total>", rcc.sent[0][1])
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
            rcc.reply(
                WORKER,
                "Final stage done.\nPLAN REVISION: 1\n"
                "PROGRESS: 3/3 — final stage complete; report to A\n"
                "NEXT TASK — MANAGER\nFinished, report complete.",
            )
            # DOM may render fewer assistant nodes than at prearm; trusted SELF
            # source receipt + exact user pair still identify this response.
            rcc.visible_count_override = 0
            second = service.poll_once()
            self.assertEqual("RETURNED_TO_MANAGER", second["events"][0]["status"])
            self.assertEqual(2, len(rcc.sent))
            self.assertEqual(MANAGER, rcc.sent[1][0])
            self.assertEqual("Finished, report complete.", rcc.sent[1][1])
            observed = ChainExecutionPlanLedger(bct.store).get_latest_execute_plan_check(
                work_id=work.work_id, direction_id="direction-1", task_id="task-1",
            )
            self.assertEqual(2, observed["generation"])
            self.assertEqual("plan-1", observed["plan_id"])
            self.assertEqual(1, observed["reported_revision"])
            self.assertEqual((3, 3), (observed["completed_steps"], observed["total_steps"]))
            self.assertEqual((), observed["issues"])
            self.assertEqual("RETURNED_TO_MANAGER", service.ledger.get("task-1", 2)["state"])
            self.assertEqual([], service.poll_once()["events"])
            self.assertEqual([], bct.store.claim_diagnostics())


class ChainWorkerProvisionPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_chain_recipe_provisions_saved_worker_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "bct.toml"
            policy.write_text(
                '[policy]\nnormal_actions=["browser","conversation_network_update"]\n'
                'approval_actions=[]\n', encoding="utf-8",
            )
            bct = BCT(state_path=root / "state.sqlite", policy_path=policy)
            rcc = SimulatedRcc()
            feature = BrowserFeature(rcc, store=bct.store)
            bct.operations._features["browser"] = feature
            principal = Principal(
                "bct-mcp-local", "test",
                frozenset({"browser", "conversation_network_update"}),
            )
            work = bct.create_work(
                work_id="public-worker-provision", request_summary="public Chain Worker",
                roots=[str(root)], actions=["browser", "conversation_network_update"],
                principal=principal,
            )
            preparation = {
                "preparation_id": "public-child", "command": "create-chat-tab",
                "instance_id": INSTANCE, "window_id": 11,
                "instruction": "Handle the independent public child task.",
                "display_name": "Public Worker", "scope_name": "Project",
                "role_tags": ["Worker"], "arrange": None,
            }
            ChainDirectionLedger(bct.store).save(
                direction_id="public-parent", work_id=work.work_id,
                source_kind="USER", decision="NEW_TASK",
                direction_text="Complete the public parent task.", source_text="User request",
                assessment={
                    "answers": {}, "manager_conversation_key": MANAGER,
                    "supervisor_conversation_key": WORKER,
                    "network_name": "Project", "targets": [], "network_updates": [],
                    "worker_preparations": [preparation],
                },
            )
            def status_provider():
                tabs = [{"tab_id": value["tabId"], "window_id": value["windowId"],
                         "conversation_key": key} for key, value in rcc.locations.items()]
                if rcc.created and SUCCESSOR not in rcc.locations:
                    tabs.append({"tab_id": rcc.created["tabId"],
                                 "window_id": rcc.created["windowId"],
                                 "conversation_key": ""})
                return {"monitor": {"rcc": {"instances": [{
                    "instance_id": INSTANCE, "session_id": SESSION,
                    "state": "OPEN", "cached": False, "tabs": tabs,
                }]}}}
            mcp = build_mcp(bct, compact_catalogue=True, status_provider=status_provider)
            _, result = await mcp.call_tool("bct_chain_recipe", {
                "action": "provision_worker", "work_id": work.work_id,
                "direction_id": "public-parent", "task_id": "public-child-task",
                "worker_preparation_id": "public-child",
            })
            self.assertEqual("STARTED", result["status"], result)
            self.assertEqual(SUCCESSOR, result["conversation_key"])
            self.assertEqual(1, rcc.create_count)
            rcc.reply(SUCCESSOR, "NEXT TASK — MANAGER: PUBLIC_CHILD_COMPLETE")
            returned = SendDelayedMessageService(
                store=bct.store, browser_feature=feature, operations=bct.operations,
            ).poll_once()
            self.assertEqual("RETURNED_TO_MANAGER", returned["events"][0]["status"])
            self.assertEqual(MANAGER, rcc.sent[-1][0])
            self.assertIn("PUBLIC_CHILD_COMPLETE", rcc.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
