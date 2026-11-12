"""Public LOOP round trips using the real durable Watch and Operation stores."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bct.core.models import Outcome, Work
from bct.core.store import Store
from bct.loop_recipe_contracts import LoopContractError
from bct.loop_turns import LoopTurnRunner, LoopTurns
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
        self.service = None

    def run(self, *, principal, work_id, operation_id, capability, arguments, expected_assignment_epoch):
        self.calls.append((operation_id, arguments))
        work = self.store.get_work(work_id)
        if work.assignment_epoch != expected_assignment_epoch:
            raise AssertionError("operation epoch differs from Loop")
        created, receipt = self.store.begin_operation(
            operation_id=operation_id, work=work, principal_id=principal.principal_id,
            request_digest=operation_id, capability=capability,
            target=arguments["conversation_key"], resources=(), policy_revision="test",
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
            self.sends[arguments["conversation_key"]] = arguments["text"]
            outcome = self.next_outcome
            evidence = {
                "command": "send-to-tab", "host_request_id": operation_id,
                "instance_id": arguments["instance_id"],
                "conversation_key": arguments["conversation_key"],
                "source_message_sha256": _rcc_submitted_text_sha256(arguments["text"]),
            }
        return self.store.finish_operation(operation_id=operation_id, outcome=outcome,
                                           evidence=evidence, error=None, release_claims=True)

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
