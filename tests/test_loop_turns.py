"""Public LOOP round trips using the real durable Watch and Operation stores."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bct.core.models import Outcome, Work
from bct.core.store import Store
from bct.loop_recipe_contracts import LoopContractError
from bct.loop_turns import LoopTurnRunner, LoopTurns, _UNCONFIRMED_SEND
from bct.send_delayed_message import SendDelayedMessageService, _rcc_submitted_text_sha256
from test_loop_self_dispatch import OWNER, snapshot


SUPERVISOR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PLAN = dict(remaining="requirement", steps="edit", verification="test", reason="current turn")


class FakeRccOperations:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.sends = {}
        self.next_outcome = Outcome.APPLIED
        self.next_error = None
        self.service = None

    def run(self, *, principal, work_id, operation_id, capability, arguments, expected_assignment_epoch):
        self.calls.append((operation_id, arguments))
        work = self.store.get_work(work_id)
        if work.assignment_epoch != expected_assignment_epoch:
            raise AssertionError("operation epoch differs from Loop")
        sending = arguments["command"] != "send-delayed-message"
        uncertain = sending and self.next_error == _UNCONFIRMED_SEND
        instance = arguments["instance_id"]
        created, receipt = self.store.begin_operation(
            operation_id=operation_id, work=work, principal_id=principal.principal_id,
            request_digest=operation_id, capability=capability,
            target=instance if uncertain else arguments["conversation_key"],
            resources=(f"rcc-instance:{instance}:direct-tab:{arguments['tab_id']}",) if uncertain else (),
            policy_revision="test",
        )
        if not created:
            return receipt
        if arguments["command"] == "send-delayed-message":
            conversation = arguments["conversation_key"]
            baseline = {"responseTurnCount": 0}
            if not arguments.get("planned_send_operation_id"):
                baseline.update(generating=True, latestUserTurnKey="user-first",
                                latestUserSha256=_rcc_submitted_text_sha256("original"))
            self.service.ledger.prearm_task(
                task_id=arguments["task_id"], work_id=work_id, principal_id=principal.principal_id,
                assignment_epoch=work.assignment_epoch, instance_id=arguments["instance_id"],
                conversation_key=conversation, manager_conversation_key=conversation,
                manager_instance_id=arguments["instance_id"], baseline=baseline,
                registration_receipt=operation_id, execution_path="LOOP",
                planned_send_operation_id=arguments.get("planned_send_operation_id", ""),
                planned_send_text=arguments.get("planned_send_text", ""),
                watched_session_id=arguments["watched_session_id"],
                watched_tab_id=arguments["watched_tab_id"],
                watched_window_id=arguments["watched_window_id"],
            )
            outcome = Outcome.APPLIED
            evidence = {"command": "send-delayed-message"}
        else:
            self.assert_watch_before_send(arguments["conversation_key"], operation_id)
            self.store.record_effect_stage(operation_id=operation_id, stage="DISPATCH_INTENT")
            self.sends[arguments["conversation_key"]] = arguments["text"]
            outcome = self.next_outcome
            evidence = {
                "command": "send-to-tab", "host_request_id": operation_id,
                "instance_id": arguments["instance_id"],
                "conversation_key": arguments["conversation_key"],
                "source_message_sha256": _rcc_submitted_text_sha256(arguments["text"]),
            }
        return self.store.finish_operation(operation_id=operation_id, outcome=outcome,
                                           evidence=evidence, error=self.next_error if uncertain else None,
                                           release_claims=not uncertain)

    def assert_watch_before_send(self, conversation, operation_id):
        with self.store._readonly() as db:
            row = db.execute("""SELECT 1 FROM delayed_send_watches WHERE state='WATCHING'
                AND conversation_key=? AND json_extract(context_json,'$.source_send_operation_id')=?""",
                             (conversation, operation_id)).fetchone()
        if row is None:
            raise AssertionError("send before Watch")


class LoopTurnTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "test.sqlite")
        self.work = Work("work", "request", (), frozenset({"browser"}), "owner")
        self.store.create_work(self.work)
        self.turns = LoopTurns(self.store, initialize=True)
        self.ops = FakeRccOperations(self.store)
        self.service = SendDelayedMessageService(
            store=self.store, browser_feature=SimpleNamespace(), operations=self.ops,
        )
        self.ops.service = self.service
        self.responses = {}
        self.service.latest = lambda **arguments: self.responses.get(arguments["conversation_key"], {})
        self.service._activity_for = lambda _watch: {}
        self.turns.start(work=self.work, loop_id="loop", task_id="task",
                         context=("original", "direction", OWNER, SUPERVISOR, "network"),
                         overall_plan="overall", conditions={"criterion": "criterion description"})
        with self.store.transaction() as db:
            db.execute("INSERT INTO conversation_network_projects VALUES('network','Loop',1,0,0)")
            db.execute("""INSERT INTO conversation_network_conversations
                (conversation_key,display_name,created_at,updated_at) VALUES(?,'Manager',0,0)""", (OWNER,))
            db.execute("INSERT INTO conversation_network_memberships VALUES('network',?,'ACTIVE',0,0)", (OWNER,))
        self.runner = self.make_runner()
        self.turns.arm("loop", OWNER)
        self.prepare(OWNER)

    def make_runner(self):
        return LoopTurnRunner(self.service, LoopTurns(self.store), lambda: snapshot(owner=self.target))

    def prepare(self, conversation):
        self.target = conversation
        self.assertEqual(self.runner.run_once()[0]["state"], "WATCHING")
        self.assertEqual(self.service.ledger.watching(), [])

    def decision(self, number, conversation, route, **fields):
        self.turns.save_plan("loop", number, conversation, plan_id=f"plan-{number}",
                             expected_revision=0, plan=PLAN)
        self.turns.decide("loop", number, conversation, decision={
            "route": route, "result": "observed result", "next_instruction": "read and verify", **fields,
        })

    def reply(self, number, conversation):
        text = f"assistant response {number}"
        user_key = "user-first" if number == 1 else f"user-{number}"
        user_sha = _rcc_submitted_text_sha256(self.ops.sends.get(conversation, "original"))
        self.responses[conversation] = {
            "ok": True, "conversationKey": conversation, "responseTurnCount": 1,
            "generating": False, "terminal": True, "inputReady": True,
            "observationState": "TERMINAL",
            "latestUserTurnKey": user_key, "responseSourceUserTurnKey": user_key,
            "latestUserSha256": user_sha, "responseSourceUserSha256": user_sha,
            "latestUserTextOccurrenceCount": 1, "responseSourceUserTextOccurrenceCount": 1,
            "responseTurnKey": f"assistant-{number}", "responseText": text,
            "responseSha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        self.assertEqual(self.runner.run_once()[0]["state"], "OBSERVED")

    def test_new_prepared_start_preserves_observed_watch_without_a_decision(self):
        self.reply(1, OWNER)
        old = self.turns.status("loop")
        self.assertEqual(old["objective"]["run_state"], "BLOCKED")
        new = dict(work=self.work, loop_id="new-loop", task_id="new-task",
                   context=("new", "direction", OWNER, SUPERVISOR, "new-network"),
                   overall_plan="overall", conditions={"criterion": "result"})
        with self.assertRaisesRegex(LoopContractError, "LOOP_MANAGER_PROJECT_OR_TASK_ALREADY_BOUND"):
            self.turns.start(**new)
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET decision_json='{}' WHERE loop_id='loop'")
        with self.assertRaisesRegex(LoopContractError, "LOOP_MANAGER_PROJECT_OR_TASK_ALREADY_BOUND"):
            self.turns.start(**new, replace_observed_first_watch=True)
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET decision_json=NULL WHERE loop_id='loop'")
        self.turns.start(**new, replace_observed_first_watch=True)
        saved = self.turns.status("loop")
        self.assertEqual(saved["objective"]["run_state"], "SUPERSEDED")
        self.assertIsNone(saved["objective"]["completion"])
        self.assertEqual(saved["turn"], old["turn"])
        self.assertEqual(saved["receipts"], old["receipts"])
        self.assertEqual(self.turns.previous_manager_scope(self.work, OWNER), "network")
        with self.assertRaisesRegex(LoopContractError, "LOOP_RUN_SUPERSEDED"):
            self.turns.resume("loop", 1, OWNER, "resume old turn")
        self.assertEqual(len(self.ops.calls), 1)

    def test_initial_watch_registers_before_fallback_and_never_sends(self):
        self.reply(1, OWNER)
        context = ("original", "direction", OWNER, SUPERVISOR, "new-network")
        self.turns.start(work=self.work, loop_id="new-loop", task_id="new-task",
                         context=context, overall_plan="overall",
                         conditions={"criterion": "result"}, replace_observed_first_watch=True)
        with self.store.transaction() as db:
            db.execute("INSERT INTO conversation_network_projects VALUES('new-network','New Loop',1,0,0)")
            db.execute("UPDATE conversation_network_memberships SET activity='EXCLUDED' WHERE project_id='network'")
            db.execute("INSERT INTO conversation_network_memberships VALUES('new-network',?,'ACTIVE',0,0)", (OWNER,))
        self.turns.arm("new-loop", OWNER, recovery_delay=30)
        self.assertEqual(self.turns.due(), [])
        target = dict(conversation_key=OWNER, instance_id="a"*32, session_id="b"*32,
                      tab_id=2, window_id=3)
        self.assertEqual(self.runner.register_initial_watch("new-loop", target), "WATCHING")
        status = self.turns.status("new-loop")
        self.assertEqual(status["turn"]["state"], "WATCHING")
        self.assertEqual(status["receipts"][status["turn"]["watch_operation_id"]]["outcome"], "APPLIED")
        self.assertEqual([args["command"] for _, args in self.ops.calls], ["send-delayed-message"] * 2)

    def test_new_start_preserves_a_late_first_watch_receipt(self):
        row = self.turns.due()[0]
        with self.store.transaction() as db:
            db.execute("DELETE FROM delayed_send_watches WHERE task_id=?", (row["watch_id"],))
            db.execute("""UPDATE operations SET outcome='NOT_APPLIED',
                       error='DELAYED_PREARM_RESPONSE_ALREADY_TERMINAL' WHERE operation_id=?""",
                       (row["watch_operation_id"],))
        self.turns.update(row, "BLOCKED")
        old = self.turns.status("loop")
        self.turns.start(work=self.work, loop_id="new-loop", task_id="new-task",
                         context=("new", "direction", OWNER, SUPERVISOR, "new-network"),
                         overall_plan="overall", conditions={"criterion": "result"},
                         replace_observed_first_watch=True)
        saved = self.turns.status("loop")
        self.assertEqual(saved["objective"]["run_state"], "SUPERSEDED")
        self.assertEqual(saved["turn"], old["turn"])
        self.assertEqual(saved["receipts"], old["receipts"])

    def test_partial_progress_and_supervisor_rework_then_complete(self):
        self.assertEqual(len(self.ops.calls), 1)
        self.turns.save_plan("loop", 1, OWNER, plan_id="plan-1", expected_revision=0, plan=PLAN)
        self.turns.record_progress("loop", 1, OWNER, plan_id="plan-1", revision=1,
                                   progress={"completed": 3, "total": 3, "evidence": "detail checked"})
        self.turns.decide("loop", 1, OWNER, decision={
            "route": "continue", "result": "detail complete, overall incomplete",
            "next_instruction": "check remaining conditions",
        })
        self.reply(1, OWNER)
        self.runner = self.make_runner()
        self.prepare(OWNER)
        self.assertEqual(self.turns.status("loop")["progress"]["completed"], 3)
        self.assertEqual(self.turns.status("loop")["objective"]["instruction_text"], "original")
        self.assertEqual(self.turns.status("loop")["previous_turn"]["response_turn_key"], "assistant-1")
        self.decision(2, OWNER, "handoff")
        self.reply(2, OWNER)
        self.prepare(SUPERVISOR)
        self.decision(3, SUPERVISOR, "return")
        self.reply(3, SUPERVISOR)
        self.prepare(OWNER)
        self.decision(4, OWNER, "handoff")
        self.reply(4, OWNER)
        self.prepare(SUPERVISOR)
        self.decision(5, SUPERVISOR, "return")
        self.reply(5, SUPERVISOR)
        self.prepare(OWNER)
        self.turns.save_plan("loop", 6, OWNER, plan_id="plan-4", expected_revision=1, plan=PLAN)
        with self.assertRaisesRegex(LoopContractError, "LOOP_COMPLETION_EVIDENCE_INCOMPLETE"):
            self.turns.decide("loop", 6, OWNER, decision={"route": "complete", "result": "partial"})
        self.turns.decide("loop", 6, OWNER, decision={
            "route": "complete", "result": "all verified",
            "condition_evidence": {"criterion": "verified in this turn"},
        })
        self.assertIsNone(self.turns.status("loop")["objective"]["completion"])
        self.reply(6, OWNER)
        objective = self.turns.status("loop")["objective"]
        self.assertEqual(objective["run_state"], "COMPLETED")
        self.assertEqual(objective["completion"]["receipt"]["response_turn_key"], "assistant-6")
        self.assertEqual(self.runner.run_once(), [])

    def test_saved_supervisor_return_needs_the_exact_completed_user_turn(self):
        self.decision(1, OWNER, "handoff")
        self.reply(1, OWNER)
        self.prepare(SUPERVISOR)
        self.decision(2, SUPERVISOR, "return")
        original = self.turns.status("loop")["turn"]
        source_sha = _rcc_submitted_text_sha256(self.ops.sends[SUPERVISOR])
        read = {"ok": True, "conversationKey": SUPERVISOR, "responseTurnCount": 1,
                "generating": False, "latestUserTurnKey": "new-user",
                "latestUserSha256": source_sha, "latestUserTextOccurrenceCount": 1,
                "responseSourceUserTurnKey": "previous-user",
                "responseSourceUserTextOccurrenceCount": 1}
        self.responses[SUPERVISOR] = read
        self.assertEqual(self.runner.run_turn(self.turns.due(4)[0]), "WATCHING")
        read.update(completedLatestUserTurnKey="new-turn", latestUserSha256="f" * 64)
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE state='WATCHING'")
        self.assertEqual(self.runner.run_once()[0]["state"], "WATCHING")
        read.update(latestUserSha256=source_sha, latestUserTextOccurrenceCount=2)
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE state='WATCHING'")
        self.assertEqual(self.runner.run_once()[0]["state"], "WATCHING")
        read["latestUserTextOccurrenceCount"] = 1
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE state='WATCHING'")
        self.runner = self.make_runner()
        self.assertEqual(self.runner.run_once()[0]["state"], "OBSERVED")
        status = self.turns.status("loop")
        self.assertEqual(status["turn"]["conversation_key"], OWNER)
        self.assertEqual(status["supervisor_return_evidence"]["watch_operation_id"],
                         original["watch_operation_id"])
        self.assertEqual(status["supervisor_return_evidence"]["send_operation_id"],
                         original["send_operation_id"])
        self.assertEqual(sum(op == original["send_operation_id"] for op, _ in self.ops.calls), 1)
        self.prepare(OWNER)
        self.decision(3, OWNER, "complete", condition_evidence={"criterion": "verified"})
        self.reply(3, OWNER)
        self.assertEqual(self.turns.status("loop")["objective"]["run_state"], "COMPLETED")

    def test_unknown_exact_send_uses_original_watch_and_never_replays(self):
        self.decision(1, OWNER, "handoff")
        self.reply(1, OWNER)
        self.target = SUPERVISOR
        self.ops.next_outcome = Outcome.UNKNOWN
        self.ops.next_error = _UNCONFIRMED_SEND
        self.assertEqual(self.runner.run_once()[0]["state"], "SEND_RECEIPT_PENDING_OR_HELD")
        row = self.turns.status("loop")["turn"]
        binding = self.service.ledger.get(row["watch_id"], 1)
        context = json.loads(binding["context_json"])
        read = {"ok": True, "conversationKey": SUPERVISOR,
                "tabId": context["watched_tab_id"], "windowId": context["watched_window_id"],
                "latestUserTurnKey": "user-2", "latestUserSha256": context["source_send_sha256"],
                "latestUserTextOccurrenceCount": 2, "observedAt": int(time.time() * 1000) + 1}
        self.responses[SUPERVISOR] = read
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE turn=2")
        self.assertEqual(self.runner.run_once()[0]["state"], "SEND_RECEIPT_PENDING_OR_HELD")
        read["latestUserTextOccurrenceCount"] = 1
        read["tabId"] += 1
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE turn=2")
        self.assertEqual(self.runner.run_once()[0]["state"], "SEND_RECEIPT_PENDING_OR_HELD")
        read["tabId"] -= 1
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE turn=2")
        self.runner = self.make_runner()
        self.assertEqual(self.runner.run_once()[0]["state"], "WATCHING")
        receipt = self.turns.status("loop")["receipts"][row["send_operation_id"]]
        self.assertEqual(receipt["outcome"], "UNKNOWN")
        self.assertEqual(receipt["reconciliation"]["source_user_turn_key"], "user-2")
        self.assertEqual(sum(op == row["send_operation_id"] for op, _ in self.ops.calls), 1)
        with self.store._readonly() as db:
            self.assertEqual(db.execute("SELECT unresolved FROM resource_claims WHERE operation_id=?",
                                        (row["send_operation_id"],)).fetchone()[0], 0)
        self.decision(2, SUPERVISOR, "return")
        text = "exact supervisor reply"
        read.update(responseTurnCount=1, generating=False, terminal=True, inputReady=True,
                    observationState="TERMINAL", responseSourceUserTurnKey="user-2",
                    responseSourceUserSha256=context["source_send_sha256"],
                    responseSourceUserTextOccurrenceCount=1, responseTurnKey="assistant-2",
                    responseText=text, responseSha256=hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(self.runner.run_once()[0]["state"], "OBSERVED")
        self.assertEqual(self.turns.status("loop")["turn"]["conversation_key"], OWNER)
        self.ops.next_outcome = Outcome.APPLIED
        self.ops.next_error = None
        self.prepare(OWNER)
        self.decision(3, OWNER, "complete", condition_evidence={"criterion": "verified"})
        self.reply(3, OWNER)
        self.assertEqual(self.turns.status("loop")["objective"]["run_state"], "COMPLETED")

    def test_direct_manager_watch_requires_original_user_instruction(self):
        row = self.turns.due()[0]
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_v2_contexts SET instruction_text='different input'")
            db.execute("UPDATE loop_recipe_turns SET state='PREPARING' WHERE watch_id=?", (row["watch_id"],))
        result = self.runner.run_once()
        self.assertEqual(result[0]["state"], "LOOP_INITIAL_USER_INSTRUCTION_MISMATCH")
        self.assertEqual(self.turns.status("loop")["objective"]["run_state"], "BLOCKED")
        self.assertEqual(len(self.ops.calls), 1)

    def test_restart_before_send_reuses_prearmed_watch(self):
        self.decision(1, OWNER, "continue")
        self.reply(1, OWNER)
        execute = self.runner._execute

        def crash_before_send(work, operation_id, arguments, *, epoch):
            if arguments["command"] == "send-message":
                raise RuntimeError("exit before send reservation")
            return execute(work, operation_id, arguments, epoch=epoch)

        with patch.object(self.runner, "_execute", side_effect=crash_before_send):
            with self.assertRaisesRegex(RuntimeError, "exit before send reservation"):
                self.runner.run_turn(self.turns.due()[0])
        self.runner = self.make_runner()
        self.prepare(OWNER)
        self.assertEqual([call[1]["command"] for call in self.ops.calls],
                         ["send-delayed-message", "send-delayed-message", "send-message"])

    def test_restart_after_send_reuses_operations(self):
        self.decision(1, OWNER, "continue")
        self.reply(1, OWNER)
        with patch.object(self.runner.turns, "update", side_effect=RuntimeError("hard exit")):
            with self.assertRaisesRegex(RuntimeError, "hard exit"):
                self.runner.run_turn(self.turns.due()[0])
        self.runner = self.make_runner()
        self.prepare(OWNER)
        self.assertEqual(len(self.ops.calls), 3)

    def test_unknown_is_reconciled_only_from_original_receipt(self):
        self.decision(1, OWNER, "continue")
        self.reply(1, OWNER)
        self.ops.next_outcome = Outcome.UNKNOWN
        self.assertEqual(self.runner.run_once()[0]["state"], "SEND_RECEIPT_PENDING_OR_HELD")
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE state='PREPARING'")
        self.runner = self.make_runner()
        self.assertEqual(self.runner.run_once()[0]["state"], "SEND_RECEIPT_PENDING_OR_HELD")
        self.assertEqual(len(self.ops.calls), 3)

    def test_stopped_tab_records_check_recheck_without_replaying_send(self):
        self.runner.snapshot = lambda: snapshot(owner=OWNER, disconnected=True)
        self.service._activity_for = lambda _watch: {
            "kind": "CONNECTION_DISCONNECTED", "session_id": "b" * 32,
            "tab_id": 2, "window_id": 3,
        }

        def poll():
            with self.store.transaction() as db:
                db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE state='WATCHING'")
            self.assertEqual(self.runner.run_once()[0]["state"], "WATCHING")

        poll()  # One stop observation is not enough to open a recovery case.
        self.assertIsNone(self.turns.status("loop")["node_recovery"])
        poll()  # Repeated exact RCC stop signal records CHECK.
        recovery = self.turns.status("loop")["node_recovery"]
        self.assertEqual(recovery["latest_check"]["kind"], "CHECK")
        self.assertEqual(recovery["latest_check"]["evidence"]["reason"],
                         "NODE_CONNECTION_DISCONNECTED")
        self.runner = self.make_runner()  # Core runner recreation keeps the case.
        self.runner.snapshot = lambda: snapshot(owner=OWNER, disconnected=True)
        with self.store.transaction() as db:
            db.execute("UPDATE node_recovery_checks SET created_at=0 WHERE case_id=?",
                       (recovery["case_id"],))
        poll()  # Persistent failure records RECHECK, without sending again.
        recovery = self.turns.status("loop")["node_recovery"]
        self.assertEqual(recovery["latest_check"]["kind"], "RECHECK")
        self.assertEqual(len(self.ops.calls), 1)
        self.assertEqual(self.turns.status("loop")["turn"]["state"], "WATCHING")

        self.service._activity_for = lambda _watch: {}
        self.decision(1, OWNER, "continue")
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_turns SET due_at=0 WHERE state='WATCHING'")
        self.reply(1, OWNER)  # The original Watch can still complete safely.
