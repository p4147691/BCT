"""Isolated PR1 consumption tests; all data lives in temporary SQLite files."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.consumption import commit_consumption_decision
from bct.core.models import ConflictError
from bct.core.store import Store
from bct.core.orchestration import _canonical, _digest


class ConsumptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "isolated.db")
        with self.store.transaction() as db:
            db.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                       ("w", "test", "[]", "[]", "owner", 1, "ACTIVE"))
            db.execute("INSERT INTO orchestration_sessions "
                       "(session_id,work_id,work_assignment_epoch,objective,roots_json,actions_json,"
                       "acceptance_json,plan_revision,manager_node_id,manager_epoch,state,"
                       "terminal_summary_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("s", "w", 1, "test", "[]", "[]", "{}", 1, None, 2,
                        "ACTIVE", "{}", 1.0, 1.0))
            for name in ("c1", "c2"):
                db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (name, "s", 2, "r", "{}", "[]", "[]", "{}", "PENDING",
                            1, "{}", 1.0, 1.0))
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                       ("worker", "worker", "WORKER", "ORCHESTRATION", 1, 1))
            db.execute("INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("attach", 1, "worker", "rcc", "test-instance", "test-session",
                        12, 11, "conversation", "endpoint", "WORKER", None, 1, 1.0))
            for message_id in ("r1", "r2"):
                db.execute("INSERT INTO orchestration_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (message_id, "s", 2, "request", "{}", "[]", "[]", "{}",
                            "APPLIED", 1, _canonical({"message": message_id}), 1.0, 1.0))
                db.execute("INSERT INTO orchestration_assignment_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (message_id, 1, 2, "worker", "attach", 1, "APPLIED",
                            None, None, 1.0, 1.0))
                db.execute("INSERT INTO orchestration_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (message_id, "s", message_id, 1, "RESULT", "worker", None,
                            _digest({"message": message_id}),
                            _canonical({"message": message_id}), 1.0, None, None))

    def run_commit(self, *, consumer="c1", decision_id="d1", digest="request",
                   epoch=2, results=None, decision=None):
        return commit_consumption_decision(
            self.store, session_id="s", consumer_assignment_id=consumer,
            manager_epoch=epoch, decision_id=decision_id, request_digest=digest,
            decision={"action": "continue"} if decision is None else decision,
            results=[("r1", _digest({"message": "r1"}))] if results is None else results,
        )

    def count(self, table):
        db = self.store._connect()
        try:
            return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        finally:
            db.close()


    def make_reconciled_result(self, message_id="r1"):
        # Versioned Schema 2 receipt from one already reconciled UNKNOWN dispatch.
        result = {"message": message_id, "reconciled": True}
        digest = _digest(result)
        original_id = "original-dispatch-" + message_id
        proof_id = "result." + hashlib.sha256(
            f"{original_id}:{message_id}:1".encode("utf-8")
        ).hexdigest()[:32]
        evidence = {
            "original_operation_id": original_id,
            "result_message_id": message_id,
            "result_digest": digest,
        }
        with self.store.transaction() as db:
            # Valid fixture foreign keys make the tampering reach the BCT
            # provenance checks instead of aborting inside SQLite.
            db.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                       ("foreign", "other work", "[]", "[]", "owner", 1, "ACTIVE"))
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                       ("other", "other", "WORKER", "ORCHESTRATION", 1, 1))
            db.execute("UPDATE orchestration_sessions SET wake_receipt_mode="
                       "'RCC_RESULT_POLL_V1' WHERE session_id='s'")
            db.execute("UPDATE orchestration_mailbox SET kind='RECONCILED_RESULT',"
                       "message_digest=?,payload_json=? WHERE message_id=?",
                       (digest, _canonical(result), message_id))
            db.execute("UPDATE orchestration_assignments SET terminal_result_json=? "
                       "WHERE assignment_id=?", (_canonical(result), message_id))
            db.execute("INSERT INTO operations "
                       "(operation_id,work_id,principal_id,request_digest,capability,"
                       "target,state,outcome,evidence_json,error,assignment_epoch,"
                       "policy_revision,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (original_id, "w", "owner", "original-request", "orchestrate",
                        "s", "FINISHED", "UNKNOWN",
                        _canonical({"operation": "dispatch", "session_id": "s",
                                    "assignment_id": message_id}), None, 1,
                        "fixture", 1.0, 1.0))
            db.execute("INSERT INTO resource_claims "
                       "(resource_key,operation_id,work_id,assignment_epoch,unresolved) "
                       "VALUES(?,?,?,?,?)",
                       ("orchestration-run:s:" + message_id,
                        original_id, "w", 1, 0))
            db.execute("INSERT INTO orchestration_reconciliations "
                       "(decision_id,session_id,assignment_id,generation,manager_epoch,"
                       "decision,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (proof_id, "s", message_id, 1, 2,
                        "IMPORT_EXACT_RCC_RESULT", _canonical(evidence), 1.0))
        return message_id, digest

    def test_first_commit_and_exact_idempotency(self):
        self.assertFalse(self.run_commit()["idempotent"])
        self.assertTrue(self.run_commit()["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_independent_consumers_same_result(self):
        self.run_commit()
        self.run_commit(consumer="c2", decision_id="d2")
        self.assertEqual(2, self.count("orchestration_consumption_receipts"))

    def test_digest_and_decision_conflict(self):
        self.run_commit()
        for arguments in ({"digest": "changed"}, {"decision": {"action": "stop"}},
                          {"results": [("r1", "different")]}):
            with self.subTest(arguments=arguments), self.assertRaises(ConflictError):
                self.run_commit(**arguments)
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_stale_epoch(self):
        with self.assertRaises(ConflictError):
            self.run_commit(epoch=1)
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_multiple_results_all_or_nothing(self):
        with self.assertRaises(ConflictError):
            self.run_commit(results=[("r1", _digest({"message": "r1"})), ("r2", "wrong")])
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(2, self.run_commit(results=[
            ("r1", _digest({"message": "r1"})), ("r2", _digest({"message": "r2"}))])["results"])

    def test_exception_rolls_back(self):
        # Patch only the PR1-owned clock binding, never the global time module.
        with patch("bct.core.consumption._current_time", side_effect=RuntimeError("fault")):
            with self.assertRaises(RuntimeError):
                self.run_commit()
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_legacy_not_promoted_or_modified(self):
        db = self.store._connect()
        try:
            before = db.execute("SELECT consumed_at FROM orchestration_mailbox WHERE message_id='r1'").fetchone()[0]
        finally:
            db.close()
        self.assertIsNone(before)
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.run_commit()
        db = self.store._connect()
        try:
            after = db.execute("SELECT consumed_at FROM orchestration_mailbox WHERE message_id='r1'").fetchone()[0]
        finally:
            db.close()
        self.assertIsNone(after)

    def test_sql_failure_after_decision_insert_rolls_back_everything(self):
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON "
                       "orchestration_consumption_receipts BEGIN "
                       "SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(Exception):
            self.run_commit()
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_restart_restores_saved_result_and_next_action_intent(self):
        # This fixture simulates a manager restart, not browser delivery.
        persisted = Store(self.store.path)
        receipt = commit_consumption_decision(
            persisted, session_id="s", consumer_assignment_id="c1",
            manager_epoch=2, decision_id="next-action-1", request_digest="request-1",
            decision={"next_assignment": "c2", "action": "prepare"},
            results=[("r1", _digest({"message": "r1"}))],
        )
        self.assertFalse(receipt["idempotent"])
        del persisted
        recovered = Store(self.store.path)
        with recovered.transaction() as db:
            result = db.execute("SELECT message_digest,consumed_at FROM orchestration_mailbox "
                                "WHERE message_id='r1'").fetchone()
            decision = db.execute("SELECT decision_json FROM orchestration_consumption_decisions "
                                  "WHERE decision_id='next-action-1'").fetchone()
            receipts = db.execute("SELECT COUNT(*) FROM orchestration_consumption_receipts "
                                  "WHERE decision_id='next-action-1'").fetchone()[0]
        self.assertEqual(_digest({"message": "r1"}), result["message_digest"])
        self.assertIsNone(result["consumed_at"])
        self.assertEqual('{"action":"prepare","next_assignment":"c2"}', decision["decision_json"])
        self.assertEqual(1, receipts)
        replay = commit_consumption_decision(
            recovered, session_id="s", consumer_assignment_id="c1",
            manager_epoch=2, decision_id="next-action-1", request_digest="request-1",
            decision={"next_assignment": "c2", "action": "prepare"},
            results=[("r1", _digest({"message": "r1"}))],
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_manager_takeover_fences_old_epoch_without_losing_result(self):
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_sessions SET manager_epoch=3 WHERE session_id='s'")
        recovered = Store(self.store.path)
        with self.assertRaises(ConflictError):
            commit_consumption_decision(
                recovered, session_id="s", consumer_assignment_id="c1",
                manager_epoch=2, decision_id="old-manager", request_digest="request",
                decision={"action": "prepare"}, results=[("r1", _digest({"message": "r1"}))])
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        fresh = commit_consumption_decision(
            recovered, session_id="s", consumer_assignment_id="c1",
            manager_epoch=3, decision_id="new-manager", request_digest="request",
            decision={"action": "prepare"}, results=[("r1", _digest({"message": "r1"}))])
        self.assertFalse(fresh["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))

    def test_source_provenance_missing_mismatched_and_late_fails_closed(self):
        cases = [
            ("assignment_id", None),
            ("assignment_id", "c1"),
            ("assignment_generation", None),
            ("assignment_generation", 2),
            ("sender_node_id", None),
            ("sender_node_id", "other-worker"),
            ("kind", "LATE_RESULT"),
        ]
        for field, altered in cases:
            with self.subTest(field=field, altered=altered):
                with self.store.transaction() as db:
                    previous = db.execute(
                        "SELECT " + field + " FROM orchestration_mailbox WHERE message_id='r1'"
                    ).fetchone()[0]
                    db.execute("UPDATE orchestration_mailbox SET " + field + "=? "
                               "WHERE message_id='r1'", (altered,))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit()
                    self.assertEqual(0, self.count("orchestration_consumption_decisions"))
                finally:
                    with self.store.transaction() as db:
                        db.execute("UPDATE orchestration_mailbox SET " + field + "=? "
                                   "WHERE message_id='r1'", (previous,))

    def test_foreign_session_source_assignment_fails_closed(self):
        with self.store.transaction() as db:
            db.execute("INSERT INTO orchestration_sessions "
                       "(session_id,work_id,work_assignment_epoch,objective,roots_json,actions_json,"
                       "acceptance_json,plan_revision,manager_node_id,manager_epoch,state,"
                       "terminal_summary_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("foreign", "w", 1, "test", "[]", "[]", "{}", 1,
                        None, 2, "ACTIVE", "{}", 1.0, 1.0))
            db.execute("UPDATE orchestration_assignments SET session_id='foreign' "
                       "WHERE assignment_id='r1'")
        with self.assertRaises(ConflictError):
            self.run_commit()
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_corrupted_result_payload_or_digest_fails_closed(self):
        cases = [("payload_json", "{invalid"),
                 ("payload_json", _canonical({"message": "different"})),
                 ("message_digest", "0" * 64)]
        for field, altered in cases:
            with self.subTest(field=field):
                with self.store.transaction() as db:
                    previous = db.execute("SELECT " + field + " FROM orchestration_mailbox "
                                          "WHERE message_id='r1'").fetchone()[0]
                    db.execute("UPDATE orchestration_mailbox SET " + field + "=? "
                               "WHERE message_id='r1'", (altered,))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit()
                    self.assertEqual(0, self.count("orchestration_consumption_receipts"))
                finally:
                    with self.store.transaction() as db:
                        db.execute("UPDATE orchestration_mailbox SET " + field + "=? "
                                   "WHERE message_id='r1'", (previous,))

    def test_canonical_digest_compatibility(self):
        payload = {"한글": "값", "nested": {"b": 2, "a": 1}}
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_mailbox SET payload_json=?,message_digest=? "
                       "WHERE message_id='r1'", (_canonical(payload), _digest(payload)))
            db.execute("UPDATE orchestration_assignments SET terminal_result_json=? "
                       "WHERE assignment_id='r1'", (_canonical(payload),))
        result = self.run_commit(results=[("r1", _digest(payload))])
        self.assertFalse(result["idempotent"])


    def test_reconciled_result_exact_receipt_and_independent_consumers(self):
        result = self.make_reconciled_result()
        first = self.run_commit(results=[result])
        self.assertFalse(first["idempotent"])
        self.assertTrue(self.run_commit(results=[result])["idempotent"])
        self.assertFalse(self.run_commit(
            consumer="c2", decision_id="d2", results=[result],
        )["idempotent"])
        self.assertEqual(2, self.count("orchestration_consumption_receipts"))
        self.assertEqual(2, self.count("orchestration_consumption_decisions"))
        with self.store.transaction() as db:
            self.assertIsNone(db.execute(
                "SELECT consumed_at FROM orchestration_mailbox WHERE message_id='r1'"
            ).fetchone()[0])

    def test_reconciled_and_normal_results_commit_atomically(self):
        reconciled = self.make_reconciled_result("r1")
        normal = ("r2", _digest({"message": "r2"}))
        results = [reconciled, normal]
        self.assertEqual(2, self.run_commit(results=results)["results"])
        self.assertTrue(self.run_commit(results=results)["idempotent"])
        self.assertEqual(2, self.count("orchestration_consumption_receipts"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_reconciled_without_original_proof_is_not_promoted(self):
        with self.store.transaction() as db:
            db.execute("UPDATE orchestration_mailbox SET kind='RECONCILED_RESULT' "
                       "WHERE message_id='r1'")
        with self.assertRaises(ConflictError):
            self.run_commit()
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_reconciled_proof_tampering_fails_closed(self):
        result = self.make_reconciled_result()
        with self.store.transaction() as db:
            original = dict(db.execute(
                "SELECT * FROM orchestration_reconciliations WHERE assignment_id='r1'"
            ).fetchone())
        evidence = json.loads(original["evidence_json"])
        cases = [
            ("decision", "NOT_VERIFIED"),
            ("manager_epoch", 1),
            ("generation", 2),
            ("assignment_id", "r2"),
            ("decision_id", "result.wrong"),
            ("evidence_json", "{bad"),
            ("evidence_json", _canonical({**evidence, "result_digest": "0" * 64})),
            ("evidence_json", _canonical({**evidence, "result_message_id": "r2"})),
            ("evidence_json", _canonical({**evidence, "original_operation_id": "foreign"})),
            ("evidence_json", _canonical({**evidence, "extra": "unexpected"})),
        ]
        for field, invalid in cases:
            with self.subTest(field=field, invalid=invalid):
                with self.store.transaction() as db:
                    db.execute("UPDATE orchestration_reconciliations SET "
                               + field + "=? WHERE decision_id=?",
                               (invalid, original["decision_id"]))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit(results=[result])
                    self.assertEqual(0, self.count("orchestration_consumption_decisions"))
                    self.assertEqual(0, self.count("orchestration_consumption_receipts"))
                finally:
                    with self.store.transaction() as db:
                        db.execute("UPDATE orchestration_reconciliations SET "
                                   + field + "=? WHERE assignment_id='r1'",
                                   (original[field],))

    def test_reconciled_duplicate_proof_and_original_fencing(self):
        result = self.make_reconciled_result()
        with self.store.transaction() as db:
            db.execute("INSERT INTO orchestration_reconciliations "
                       "(decision_id,session_id,assignment_id,generation,manager_epoch,"
                       "decision,evidence_json,created_at) "
                       "SELECT 'extra-proof',session_id,assignment_id,generation,"
                       "manager_epoch,decision,evidence_json,created_at "
                       "FROM orchestration_reconciliations WHERE assignment_id='r1'")
        with self.assertRaisesRegex(ConflictError, "PROOF_NOT_UNIQUE"):
            self.run_commit(results=[result])
        with self.store.transaction() as db:
            db.execute("DELETE FROM orchestration_reconciliations WHERE decision_id='extra-proof'")
        for field, wrong in (
                ("work_id", "foreign"), ("target", "other-session"),
                ("outcome", "APPLIED"), ("state", "RUNNING"),
                ("assignment_epoch", 9), ("capability", "read"),
                ("evidence_json", _canonical({"operation": "dispatch",
                                               "session_id": "s", "assignment_id": "r2"}))):
            with self.subTest(field=field):
                with self.store.transaction() as db:
                    old = db.execute("SELECT " + field + " FROM operations "
                                     "WHERE operation_id='original-dispatch-r1'").fetchone()[0]
                    db.execute("UPDATE operations SET " + field + "=? "
                               "WHERE operation_id='original-dispatch-r1'", (wrong,))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit(results=[result])
                    self.assertEqual(0, self.count("orchestration_consumption_decisions"))
                finally:
                    with self.store.transaction() as db:
                        db.execute("UPDATE operations SET " + field + "=? "
                                   "WHERE operation_id='original-dispatch-r1'", (old,))

    def test_reconciled_worker_and_terminal_mismatch_rejected(self):
        result = self.make_reconciled_result()
        for table, field, filter_sql, changed in (
            ("orchestration_assignment_attempts", "worker_node_id", "assignment_id='r1'", "other"),
            ("orchestration_assignment_attempts", "manager_epoch", "assignment_id='r1'", 3),
            ("orchestration_assignment_attempts", "state", "assignment_id='r1'", "FAILED"),
            ("orchestration_assignments", "state", "assignment_id='r1'", "UNKNOWN"),
            ("orchestration_mailbox", "sender_node_id", "message_id='r1'", "other"),
            ("orchestration_mailbox", "message_digest", "message_id='r1'", "0" * 64),
            ("orchestration_mailbox", "payload_json", "message_id='r1'", "{bad"),
        ):
            with self.subTest(table=table, field=field):
                with self.store.transaction() as db:
                    old = db.execute(f"SELECT {field} FROM {table} WHERE {filter_sql}").fetchone()[0]
                    db.execute(f"UPDATE {table} SET {field}=? WHERE {filter_sql}", (changed,))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit(results=[result])
                    self.assertEqual(0, self.count("orchestration_consumption_decisions"))
                finally:
                    with self.store.transaction() as db:
                        db.execute(f"UPDATE {table} SET {field}=? WHERE {filter_sql}", (old,))

    def test_reconciled_stale_epoch_and_transaction_rollback(self):
        result = self.make_reconciled_result()
        with self.assertRaisesRegex(ConflictError, "STALE_MANAGER_EPOCH"):
            self.run_commit(epoch=1, results=[result])
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_reconciled_receipt BEFORE INSERT ON "
                       "orchestration_consumption_receipts BEGIN "
                       "SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(Exception):
            self.run_commit(results=[result])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))

    def test_dispatch_requires_explicit_original_assignment_id(self):
        result = self.make_reconciled_result()
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET evidence_json=? WHERE operation_id=?",
                       (_canonical({"operation": "dispatch", "session_id": "s"}),
                        "original-dispatch-r1"))
        with self.assertRaisesRegex(ConflictError, "DISPATCH_ASSIGNMENT_MISMATCH"):
            self.run_commit(results=[result])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_takeover_unknown_exact_worker_scope_and_fail_closed(self):
        result = self.make_reconciled_result()
        takeover = {"phase": "ORCHESTRATION_RECOVERY_TAKEOVER",
                    "session_id": "s", "assignment_ids": ["r1"]}
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET evidence_json=?,error=? "
                       "WHERE operation_id='original-dispatch-r1'",
                       (_canonical(takeover), "ORCHESTRATION_RECOVERY_TAKEOVER"))
            db.execute("INSERT INTO events(kind,subject_id,data_json,created_at) "
                       "VALUES(?,?,?,?)",
                       ("ORCHESTRATION_RECOVERY_TAKEOVER","original-dispatch-r1",
                        _canonical({"session_id":"s","assignment_ids":["r1"]}),1.0))
        self.assertFalse(self.run_commit(results=[result])["idempotent"])
        self.assertTrue(self.run_commit(results=[result])["idempotent"])
        with self.store.transaction() as db:
            db.execute("DELETE FROM orchestration_consumption_receipts")
            db.execute("DELETE FROM orchestration_consumption_decisions")
        altered_cases = [
            ({"phase": "ORCHESTRATION_RECOVERY_TAKEOVER",
              "session_id": "s", "assignment_ids": []}, "ORCHESTRATION_RECOVERY_TAKEOVER"),
            ({"phase": "ORCHESTRATION_RECOVERY_TAKEOVER",
              "session_id": "foreign", "assignment_ids": ["r1"]}, "ORCHESTRATION_RECOVERY_TAKEOVER"),
            ({"phase": "ORCHESTRATION_RECOVERY_TAKEOVER",
              "session_id": "s", "assignment_ids": ["r1", "r1"]}, "ORCHESTRATION_RECOVERY_TAKEOVER"),
            (takeover, None),
        ]
        for evidence, error in altered_cases:
            with self.subTest(evidence=evidence, error=error):
                with self.store.transaction() as db:
                    db.execute("UPDATE operations SET evidence_json=?,error=? "
                               "WHERE operation_id='original-dispatch-r1'",
                               (_canonical(evidence), error))
                with self.assertRaises(ConflictError):
                    self.run_commit(results=[result])
                self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_takeover_event_must_match_exact_assignment(self):
        result = self.make_reconciled_result()
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET evidence_json=?,error=? "
                       "WHERE operation_id='original-dispatch-r1'",
                       (_canonical({"phase":"ORCHESTRATION_RECOVERY_TAKEOVER",
                                    "session_id":"s","assignment_ids":["r1"]}),
                        "ORCHESTRATION_RECOVERY_TAKEOVER"))
        with self.assertRaisesRegex(ConflictError,"TAKEOVER_EVENT_MISSING"):
            self.run_commit(results=[result])
        with self.store.transaction() as db:
            db.execute("INSERT INTO events(kind,subject_id,data_json,created_at) "
                       "VALUES(?,?,?,?)",
                       ("ORCHESTRATION_RECOVERY_TAKEOVER","original-dispatch-r1",
                        _canonical({"session_id":"s","assignment_ids":["r2"]}),1.0))
        with self.assertRaisesRegex(ConflictError,"TAKEOVER_EVENT_MISMATCH"):
            self.run_commit(results=[result])
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))

    def make_atomic_resolver(self, *, source_id="r1", recovered="APPLIED"):
        original_id = "original-dispatch-" + source_id
        resolver_id = "resolver-" + source_id
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET outcome=?,error=NULL,evidence_json=? "
                       "WHERE operation_id=?",
                       (recovered, _canonical({
                           "phase": "ORCHESTRATION_RECOVERED",
                           "resolver_operation_id": resolver_id,
                           "recovered_outcome": recovered,
                       }), original_id))
            db.execute("INSERT INTO operations "
                       "(operation_id,work_id,principal_id,request_digest,capability,"
                       "target,state,outcome,evidence_json,error,assignment_epoch,"
                       "policy_revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (resolver_id, "w", "owner", "resolver-request", "orchestrate",
                        "s", "FINISHED", recovered, _canonical({
                            "operation": "reconcile", "session_id": "s",
                            "assignment_id": source_id,
                            "result_message_id": source_id,
                        }), None, 1, "fixture", 1.0, 1.0))
            db.execute("INSERT INTO events (kind,subject_id,data_json,created_at) "
                       "VALUES(?,?,?,?)",
                       ("OPERATION_RECONCILED", original_id, _canonical({
                           "resolver_operation_id": resolver_id,
                           "original_outcome": recovered,
                           "resolved_outcome": recovered,
                           "claims_released": True,
                       }), 1.0))

    def test_atomic_recovery_receipt_matches_exact_resolver(self):
        result = self.make_reconciled_result()
        self.make_atomic_resolver()
        first = self.run_commit(results=[result])
        second = self.run_commit(results=[result])
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_receipts"))
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_atomic_recovery_wrong_resolver_or_event_fails_closed(self):
        result = self.make_reconciled_result()
        self.make_atomic_resolver()
        cases = [
            ("operations", "target", "operation_id='resolver-r1'", "foreign-session"),
            ("operations", "work_id", "operation_id='resolver-r1'", "foreign"),
            ("operations", "outcome", "operation_id='resolver-r1'", "FAILED"),
            ("operations", "assignment_epoch", "operation_id='resolver-r1'", 3),
            ("operations", "evidence_json", "operation_id='resolver-r1'",
             _canonical({"operation":"reconcile","session_id":"s",
                         "assignment_id":"r2","result_message_id":"r1"})),
            ("operations", "evidence_json", "operation_id='resolver-r1'",
             _canonical({"operation":"reconcile","session_id":"s",
                         "assignment_id":"r1","result_message_id":"other"})),
            ("events", "data_json", "subject_id='original-dispatch-r1'",
             _canonical({"resolver_operation_id":"resolver-r1",
                         "original_outcome":"UNKNOWN","resolved_outcome":"APPLIED"})),
            ("operations", "evidence_json", "operation_id='original-dispatch-r1'",
             _canonical({"phase":"ORCHESTRATION_RECOVERED",
                         "resolver_operation_id":"resolver-r1",
                         "recovered_outcome":"FAILED"})),
        ]
        for table, field, condition, changed in cases:
            with self.subTest(table=table, field=field, changed=changed):
                with self.store.transaction() as db:
                    previous = db.execute(
                        f"SELECT {field} FROM {table} WHERE {condition}"
                    ).fetchone()[0]
                    db.execute(f"UPDATE {table} SET {field}=? WHERE {condition}",
                               (changed,))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit(results=[result])
                    self.assertEqual(0, self.count("orchestration_consumption_decisions"))
                finally:
                    with self.store.transaction() as db:
                        db.execute(f"UPDATE {table} SET {field}=? WHERE {condition}",
                                   (previous,))

    def make_chain_plan(self):
        result = self.make_reconciled_result()
        plan = {"tasks":[{"assignment_id":"r1", "worker_node_id":"worker",
                          "attachment_id":"attach", "instruction":"read",
                          "acceptance":{}}],
                "synthesis":{"assignment_id":"c1"},
                "takeover":None,"timeout_s":30.0}
        plan_id = "plan." + hashlib.sha256(
            b"s:original-dispatch-r1"
        ).hexdigest()[:32]
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET evidence_json=? WHERE operation_id=?",
                       (_canonical({"operation": "chain-run", "session_id": "s"}),
                        "original-dispatch-r1"))
            db.execute("INSERT INTO orchestration_mailbox "
                       "(message_id,session_id,assignment_id,assignment_generation,"
                       "kind,sender_node_id,recipient_node_id,message_digest,payload_json,"
                       "created_at,delivered_at,consumed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (plan_id,"s",None,None,"PLAN",None,None,_digest(plan),
                        _canonical(plan),1.0,1.0,None))
            db.execute("INSERT INTO events(kind,subject_id,data_json,created_at) "
                       "VALUES(?,?,?,?)",
                       ("ORCHESTRATION_CHAIN_PLAN_RECORDED", "s",
                        _canonical({"operation_id": "original-dispatch-r1",
                                    "plan_digest": _digest(plan)}), 1.0))
        return result, plan_id, plan

    def test_chain_proven_plan_and_claim_required(self):
        result, plan_id, plan = self.make_chain_plan()
        self.assertFalse(self.run_commit(results=[result])["idempotent"])
        self.assertTrue(self.run_commit(results=[result])["idempotent"])
        self.assertEqual(1, self.count("orchestration_consumption_decisions"))

    def test_chain_plan_tampering_and_claim_fencing(self):
        result, plan_id, plan = self.make_chain_plan()
        tamper = [
            ("orchestration_mailbox","message_digest","message_id='"+plan_id+"'","0"*64),
            ("orchestration_mailbox","payload_json","message_id='"+plan_id+"'",
             _canonical({**plan,"tasks":[{"assignment_id":"r2"}]})),
            ("resource_claims","work_id",
             "resource_key='orchestration-run:s:r1'","foreign"),
            ("operations","evidence_json","operation_id='original-dispatch-r1'",
             _canonical({"operation":"chain-run","session_id":"foreign"})),
            ("operations","evidence_json","operation_id='original-dispatch-r1'",
             _canonical({"operation":"chain-run","session_id":"s",
                         "assignment_id":"r2"})),
        ]
        for table,field,condition,changed in tamper:
            with self.subTest(table=table,field=field):
                with self.store.transaction() as db:
                    old=db.execute(f"SELECT {field} FROM {table} WHERE {condition}").fetchone()[0]
                    db.execute(f"UPDATE {table} SET {field}=? WHERE {condition}",
                               (changed,))
                try:
                    with self.assertRaises(ConflictError):
                        self.run_commit(results=[result])
                    self.assertEqual(0,self.count("orchestration_consumption_decisions"))
                finally:
                    with self.store.transaction() as db:
                        db.execute(f"UPDATE {table} SET {field}=? WHERE {condition}",(old,))

    def test_chain_resume_atomic_original_and_worker_result_proven(self):
        for aggregate, state in (("APPLIED", "FINISHED"), ("FAILED", "PARTIAL")):
            with self.subTest(aggregate=aggregate):
                # Each subcase resets only its own isolated fixture rows.
                if self.count("orchestration_reconciliations") == 0:
                    result, plan_id, plan = self.make_chain_plan()
                    self.make_atomic_resolver()
                with self.store.transaction() as db:
                    db.execute("UPDATE operations SET outcome=?,evidence_json=? "
                               "WHERE operation_id='original-dispatch-r1'",
                               (aggregate, _canonical({
                                   "phase": "ORCHESTRATION_RECOVERED",
                                   "resolver_operation_id": "resolver-r1",
                                   "recovered_outcome": aggregate,
                               })))
                    db.execute("UPDATE operations SET outcome=?,evidence_json=? "
                               "WHERE operation_id='resolver-r1'",
                               (aggregate, _canonical({
                                   "operation": "chain-resume",
                                   "session_id": "s", "session_state": state,
                               })))
                    db.execute("UPDATE orchestration_sessions SET state=? "
                               "WHERE session_id='s'", (state,))
                    db.execute("UPDATE events SET data_json=? WHERE "
                               "kind='OPERATION_RECONCILED' "
                               "AND subject_id='original-dispatch-r1'",
                               (_canonical({
                                   "resolver_operation_id": "resolver-r1",
                                   "original_outcome": aggregate,
                                   "resolved_outcome": aggregate,
                                   "claims_released": True,
                               }),))
                first = self.run_commit(results=[("r1", _digest({
                    "message": "r1", "reconciled": True,
                }))], decision_id="chain-"+aggregate)
                self.assertFalse(first["idempotent"])
                self.assertTrue(self.run_commit(results=[("r1", _digest({
                    "message": "r1", "reconciled": True,
                }))], decision_id="chain-"+aggregate)["idempotent"])
                with self.store.transaction() as db:
                    db.execute("DELETE FROM orchestration_consumption_receipts")
                    db.execute("DELETE FROM orchestration_consumption_decisions")

    def test_chain_resume_session_fence_rejects_mismatch(self):
        result, plan_id, plan = self.make_chain_plan()
        self.make_atomic_resolver()
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET evidence_json=? "
                       "WHERE operation_id='resolver-r1'", (_canonical({
                           "operation": "chain-resume", "session_id": "s",
                           "session_state": "FINISHED",
                       }),))
        with self.assertRaisesRegex(ConflictError, "CHAIN_RESUME_MISMATCH"):
            self.run_commit(results=[result])
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))

    def test_chain_plan_worker_attachment_and_missing_plan_fences(self):
        result, plan_id, plan = self.make_chain_plan()
        cases = [
            ("wrong_worker", {**plan, "tasks": [{**plan["tasks"][0],
                                                "worker_node_id": "other"}]}),
            ("wrong_attachment", {**plan, "tasks": [{**plan["tasks"][0],
                                                    "attachment_id": "wrong"}]}),
        ]
        for label, changed in cases:
            with self.subTest(label=label):
                with self.store.transaction() as db:
                    db.execute("UPDATE orchestration_mailbox SET payload_json=?,message_digest=? "
                               "WHERE message_id=?",(_canonical(changed),_digest(changed),plan_id))
                    db.execute("UPDATE events SET data_json=? "
                               "WHERE kind='ORCHESTRATION_CHAIN_PLAN_RECORDED' "
                               "AND subject_id='s'",
                               (_canonical({"operation_id":"original-dispatch-r1",
                                            "plan_digest":_digest(changed)}),))
                with self.assertRaisesRegex(ConflictError,"CHAIN_TARGET_MISMATCH"):
                    self.run_commit(results=[result])
                self.assertEqual(0,self.count("orchestration_consumption_decisions"))
        with self.store.transaction() as db:
            db.execute("DELETE FROM orchestration_mailbox WHERE message_id=?",(plan_id,))
        with self.assertRaisesRegex(ConflictError,"CHAIN_PLAN_MISSING"):
            self.run_commit(results=[result])
        self.assertEqual(0,self.count("orchestration_consumption_decisions"))

    def test_proven_chain_replacement_event_permits_new_generation(self):
        result, plan_id, plan = self.make_chain_plan()
        with self.store.transaction() as db:
            db.execute("INSERT INTO orchestration_attachments "
                       "(attachment_id,generation,node_id,kind,instance_id,"
                       "external_session_id,tab_id,window_id,conversation_key,"
                       "endpoint,relay_role,binding_receipt_id,active,observed_at) "
                       "SELECT 'other-attach',1,'other',kind,'other-instance',"
                       "external_session_id,14,window_id,'other-conversation',"

                       "endpoint,relay_role,binding_receipt_id,active,observed_at "
                       "FROM orchestration_attachments WHERE attachment_id='attach'")
            db.execute("UPDATE orchestration_assignment_attempts SET state='NOT_APPLIED' "
                       "WHERE assignment_id='r1' AND generation=1")
            db.execute("INSERT INTO orchestration_assignment_attempts "
                       "(assignment_id,generation,manager_epoch,worker_node_id,"
                       "attachment_id,attachment_generation,state,created_at,updated_at) "
                       "VALUES('r1',2,2,'other','other-attach',1,'APPLIED',1.0,1.0)")
            db.execute("UPDATE orchestration_assignments SET current_generation=2 "
                       "WHERE assignment_id='r1'")
            db.execute("UPDATE orchestration_mailbox SET assignment_generation=2,"
                       "sender_node_id='other' WHERE message_id='r1'")
            rec=db.execute("SELECT * FROM orchestration_reconciliations "
                           "WHERE assignment_id='r1' AND decision='IMPORT_EXACT_RCC_RESULT'").fetchone()
            replacement_id = "replace." + hashlib.sha256(b"r1:2").hexdigest()[:32]
            replacement={"reason":"not sent","evidence":{},"prior_generation":1,
                         "prior_result_digest":"a"*64,
                         "replacement_worker_node_id":"other",
                         "replacement_attachment_id":"other-attach"}
            db.execute("INSERT INTO orchestration_reconciliations "
                       "(decision_id,session_id,assignment_id,generation,manager_epoch,"
                       "decision,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (replacement_id,"s","r1",1,2,"REPLACE_PROVEN_NOT_APPLIED",
                        _canonical(replacement),1.0))
            db.execute("INSERT INTO events(kind,subject_id,data_json,created_at)"
                       " VALUES(?,?,?,?)",
                       ("ORCHESTRATION_WORKER_REPLACED","r1",_canonical({
                           "prior_generation":1,"generation":2,"worker_node_id":"other",
                           "decision_id":replacement_id}),1.0))
            new_id="result."+hashlib.sha256(b"original-dispatch-r1:r1:2").hexdigest()[:32]
            db.execute("UPDATE orchestration_reconciliations SET generation=2,"
                       "decision_id=? WHERE decision_id=?",(new_id,rec["decision_id"]))
        self.assertFalse(self.run_commit(results=[result])["idempotent"])
        self.assertTrue(self.run_commit(results=[result])["idempotent"])
        self.assertEqual(1,self.count("orchestration_consumption_receipts"))
        # Mutation of the replacement event invalidates even a prior exact
        # consumer replay: the new provenance must still be verified.
        with self.store.transaction() as db:
            db.execute("DELETE FROM orchestration_consumption_receipts")
            db.execute("DELETE FROM orchestration_consumption_decisions")
            db.execute("UPDATE events SET data_json=? "
                       "WHERE kind='ORCHESTRATION_WORKER_REPLACED' "
                       "AND subject_id='r1'",
                       (_canonical({"prior_generation":1,"generation":2,
                                    "worker_node_id":"worker","decision_id":replacement_id}),))
        with self.assertRaisesRegex(ConflictError, "CHAIN_REPLACEMENT_MISMATCH"):
            self.run_commit(results=[result])
        self.assertEqual(0,self.count("orchestration_consumption_receipts"))

    def test_new_schema_does_not_backfill_legacy(self):
        self.assertEqual(0, self.count("orchestration_consumption_receipts"))
        self.assertEqual(0, self.count("orchestration_consumption_decisions"))


if __name__ == "__main__":
    unittest.main()
