"""Acceptance, requester binding and exactly-once result transport, no LIVE effects."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore, LoopStateError
from bct.loop_result import LoopResultLedger, LoopResultDispatcher
from bct.loop_supervisor_handoff import LoopReviewLedger
from bct.send_delayed_message import SendDelayedMessageService, _rcc_submitted_text_sha256
from test_loop_self_dispatch import OWNER, snapshot

REQUESTER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SUPERVISOR = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class LoopResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/"db.sqlite")
        self.store.create_work(Work(work_id="w", request_summary="single Loop",
            roots=(self.tmp.name,), actions=frozenset({"browser"}), owner_principal_id="p"))
        self.loop = LoopStore(self.store)
        self.loop.start(work_id="w", direction_id="d", task_id="t", owner=OWNER, plan_text="verified plan", now=100)
        self.ledger = LoopResultLedger(self.store)
        self.calls, self.receipts = [], {}
        self.outcome, self.crash, self.wrong_proof = "APPLIED", False, False
        def run(**kw):
            self.calls.append(kw)
            if self.crash:
                raise RuntimeError("crash after reservation")
            args = kw["arguments"]
            receipt = SimpleNamespace(state=SimpleNamespace(value="FINISHED"),
                outcome=SimpleNamespace(value=self.outcome), evidence={
                    "command":"send-to-tab", "host_request_id":kw["operation_id"],
                    "instance_id":args["instance_id"],
                    "conversation_key":OWNER if self.wrong_proof else args["conversation_key"],
                    "source_message_sha256":_rcc_submitted_text_sha256(args["text"])})
            self.receipts[kw["operation_id"]] = receipt
            return receipt
        def get_receipt(**kw):
            self.assertEqual(kw["work_id"], "w")
            self.assertEqual(kw["principal_id"], "p")
            return self.receipts[kw["operation_id"]]
        self.store.get_operation_for = get_receipt
        self.dispatcher = LoopResultDispatcher(self.store, SimpleNamespace(run=run))
        p = patch("bct.loop_result.NodeRecoveryLedger.assert_send_allowed")
        p.start(); self.addCleanup(p.stop)

    def bind(self, target=None):
        return self.ledger.configure(work_id="w", owner=OWNER,
            requester_ref="original-dot-request:42", conversation_key=target,
            snapshot=snapshot(owner=target) if target else None)

    def accept(self):
        # Composed review tests below verify the independent-acceptance gate;
        # this fixture isolates the transaction-owned result block.
        with self.store.transaction() as db:
            loop = db.execute("SELECT * FROM loop_recipe_runs WHERE work_id='w'").fetchone()
            LoopResultLedger.record_acceptance(db, loop=loop,
                review={"supervisor":SUPERVISOR,"candidate_sha":"a"*40,"task_id":"review-t","operation_id":"review-op"},
                context={"decision":{"response_sha256":"b"*64,"payload":"Independent verification passed."}},
                return_operation_id="return-op", now=110)
        return self.ledger.get("w")

    def dispatch(self, **kwargs):
        return self.dispatcher.run_once(snapshot=snapshot(owner=REQUESTER, **kwargs))

    def test_no_requester_route_means_durable_result_not_an_invented_send(self):
        row = self.accept()
        self.assertEqual(row["state"], "READY_FOR_REQUESTER")
        self.assertEqual(row["result"]["acceptance"], "ACCEPTED")
        self.assertEqual(row["result"]["user_notification"], "UNVERIFIED")
        self.assertIsNone(row["conversation_key"])
        self.dispatch()
        self.assertEqual(self.calls, [])
        self.assertEqual(LoopResultLedger(self.store).get("w"), row)

    def test_pull_requester_ref_is_not_treated_as_browser_identity(self):
        self.bind()
        row = self.accept()
        self.assertEqual(row["requester_ref"], "original-dot-request:42")
        self.assertEqual(row["state"], "READY_FOR_REQUESTER")
        self.assertEqual(self.ledger.pending(), [])
        with self.assertRaisesRegex(LoopStateError, "BINDING_CONFLICT"):
            self.bind(REQUESTER)

    def test_explicit_exact_delivery_is_not_user_notification(self):
        self.bind(REQUESTER)
        row = self.accept()
        result = self.dispatch()
        self.assertEqual(result[0]["state"], "DELIVERED_TO_CONVERSATION")
        for _ in range(3):
            self.dispatch()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["operation_id"], row["operation_id"])
        self.assertEqual(self.calls[0]["arguments"]["conversation_key"], REQUESTER)
        self.assertEqual(self.ledger.get("w")["result"]["user_notification"], "UNVERIFIED")

    def test_unknown_missing_receipt_and_restart_never_replay(self):
        self.bind(REQUESTER); self.accept(); self.crash = True
        self.dispatch()
        operation_id = self.calls[0]["operation_id"]
        self.dispatcher = LoopResultDispatcher(self.store, SimpleNamespace(run=lambda **kw: self.fail("replay")))
        for _ in range(3):
            self.dispatch()
        row = self.ledger.get("w")
        self.assertEqual(row["state"], "UNKNOWN")
        self.assertEqual(row["operation_id"], operation_id)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(LoopStateError, "BINDING_CONFLICT"):
            self.ledger.configure(work_id="w",owner=OWNER,requester_ref="different")

    def test_unknown_settles_only_from_same_original_verified_receipt(self):
        self.bind(REQUESTER); self.accept(); self.outcome = "UNKNOWN"
        self.dispatch()
        row = self.ledger.get("w")
        self.assertEqual(row["state"], "UNKNOWN")
        self.receipts[row["operation_id"]].outcome.value = "APPLIED"
        self.dispatch()
        self.assertEqual(self.ledger.get("w")["state"], "DELIVERED_TO_CONVERSATION")
        self.assertEqual(len(self.calls), 1)

    def test_applied_with_wrong_identity_does_not_prove_delivery(self):
        self.bind(REQUESTER); self.accept(); self.wrong_proof = True
        self.dispatch(); self.dispatch()
        row = self.ledger.get("w")
        self.assertEqual(row["state"], "UNKNOWN")
        self.assertEqual(row["last_error"], "LOOP_RESULT_DELIVERY_PROOF_MISMATCH")
        self.assertEqual(len(self.calls), 1)

    def test_not_applied_is_not_automatically_retried(self):
        self.bind(REQUESTER); self.accept(); self.outcome = "NOT_APPLIED"
        self.dispatch(); self.dispatch()
        self.assertEqual(self.ledger.get("w")["state"], "NOT_APPLIED")
        self.assertEqual(len(self.calls), 1)

    def test_unfresh_busy_disconnected_identity_cannot_send(self):
        self.bind(REQUESTER); self.accept()
        for params in ({"fresh":False}, {"generating":True}, {"disconnected":True}):
            self.dispatch(**params)
            self.assertEqual(self.ledger.get("w")["state"], "PENDING")
        wrong = snapshot(owner=REQUESTER)
        wrong["rcc"]["instances"][0]["tabs"][0]["conversation_key"] = OWNER
        self.dispatcher.run_once(snapshot=wrong)
        self.assertEqual(self.calls, [])

    def test_owner_and_supervisor_are_not_requester_delivery_targets(self):
        with self.assertRaisesRegex(LoopStateError, "SELF_RETURN_FORBIDDEN"):
            self.bind(OWNER)
        LoopReviewLedger(self.store)
        with self.store.transaction() as db:
            db.execute("INSERT INTO loop_review_handoffs(work_id,owner,supervisor,instruction,state,task_id,operation_id,updated_at) VALUES(?,?,?,'review','CONFIGURED','rt','ro',100)", ("w",OWNER,SUPERVISOR))
        with self.assertRaisesRegex(LoopStateError, "SELF_RETURN_FORBIDDEN"):
            self.bind(SUPERVISOR)

    def test_owner_change_before_reservation_prevents_self_return(self):
        self.bind(REQUESTER); self.accept()
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_runs SET owner=? WHERE work_id='w'", (REQUESTER,))
        self.dispatch()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ledger.get("w")["state"], "PENDING")

    def test_production_recovery_dispatches_report_without_active_loop_work(self):
        import ast
        import time
        from bct.status_views import status_view
        from unittest.mock import Mock
        self.bind(REQUESTER); self.accept()
        with self.store.transaction() as db:
            db.execute("UPDATE loop_recipe_runs SET state='COMPLETED' WHERE work_id='w'")
        stop = SimpleNamespace(done=False)
        stop.is_set = lambda: stop.done
        stop.wait = lambda _: setattr(stop, "done", True)
        state = {"loop_recipe_recovery": {"runs":0}}
        operations = self.dispatcher.operations
        operations._features = {"browser":Mock()}
        source = Path(__file__).resolve().parents[1]/"src/bct/runtime_server.py"
        body = next(n for n in ast.walk(ast.parse(source.read_text()))
                    if isinstance(n, ast.FunctionDef) and n.name == "loop_recipe_recovery_loop")
        namespace = dict(__package__="bct",__name__="bct.runtime_server",
            bct=SimpleNamespace(store=self.store,operations=operations), recovery_stop=stop,
            state=state,time=time,runtime_root=Path(self.tmp.name),status_view=status_view,
            build_monitor_state=lambda **_: snapshot(owner=REQUESTER),
            SendDelayedMessageService=SendDelayedMessageService,
            status_snapshot=lambda: snapshot(owner=REQUESTER))
        exec(compile(ast.Module(body=[body],type_ignores=[]),str(source),"exec"),namespace)
        namespace["loop_recipe_recovery_loop"]()
        self.assertIsNone(state["loop_recipe_recovery"].get("last_error"), state)
        self.assertEqual(state["loop_recipe_recovery"]["last_result_reports"][0]["state"], "DELIVERED_TO_CONVERSATION")
        self.assertEqual(len(self.calls), 1)

    def test_legacy_accepted_result_may_bind_once_without_changing_payload(self):
        original = self.accept()
        row = self.bind(REQUESTER)
        self.assertEqual(row["state"], "PENDING")
        self.assertEqual(row["result"], original["result"])
        self.assertEqual(row["message_sha256"], original["message_sha256"])
        self.assertEqual(row["operation_id"], original["operation_id"])
        self.dispatch()
        self.assertEqual(len(self.calls), 1)
