from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct.chat_continuity import (
    ChatObservation, abandon_unknown_instance_claim, decide,
)
from bct.core.models import ConflictError, Outcome, Work
from bct.core.store import Store


class ChatContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        self.work = Work("original", "test dedicated chat", (self.tmp.name,),
                         frozenset({"relay_browser"}), "test-owner")
        self.store.create_work(self.work)
        self.instance = "instance-1"
        self.resource = "rcc-instance:" + self.instance
        self._unknown("old-send", self.instance)

    def _unknown(self, operation: str, instance: str):
        exists, _ = self.store.begin_operation(
            operation_id=operation, work=self.work, principal_id="test-owner",
            request_digest="sha-" + operation, capability="relay_browser",
            target=instance, resources=("rcc-instance:" + instance,),
            policy_revision="test",
        )
        self.assertTrue(exists)
        self.store.finish_operation(
            operation_id=operation, outcome=Outcome.UNKNOWN,
            evidence={"command": "send"}, error="RCC_EFFECT_UNVERIFIED",
            release_claims=False,
        )

    def _observation(self, **overrides):
        values = {"bct_owned": True, "user_active": False,
                  "checks": 2, "no_progress_seconds": 120}
        values.update(overrides)
        return ChatObservation(**values)

    def _retire(self, **overrides):
        params = {
            "original_work_id": "original", "original_operation_id": "old-send",
            "instance_id": self.instance,
            "observation": self._observation(), "reason": "Stalled BCT-owned chat",
        }
        params.update(overrides)
        return abandon_unknown_instance_claim(self.store, **params)

    def _claim(self, resource=None):
        d = self.store._connect()
        try:
            return d.execute(
                "SELECT operation_id,unresolved FROM resource_claims "
                "WHERE resource_key=?", (resource or self.resource,),
            ).fetchone()
        finally:
            d.close()

    def _old_outcome(self):
        d = self.store._connect()
        try:
            return dict(d.execute(
                "SELECT outcome,error,request_digest FROM operations "
                "WHERE operation_id='old-send'",
            ).fetchone())
        finally:
            d.close()

    def test_stalled_bct_chat_gets_replacement_not_same_message_retry(self):
        self.assertEqual("RECREATE_CHAT", decide(self._observation()))
        result = self._retire()
        self.assertEqual("ABANDONED_UNVERIFIED", result["action"])
        self.assertEqual("NEW_CHAT_NEW_OPERATION_ID", result["next"])
        self.assertEqual(0, self._claim()["unresolved"])
        self.assertEqual("UNKNOWN", self._old_outcome()["outcome"])
        self.assertEqual("sha-old-send", self._old_outcome()["request_digest"])

    def test_only_target_claim_is_released(self):
        self._unknown("unrelated", "another-instance")
        self._retire()
        self.assertEqual(0, self._claim()["unresolved"])
        self.assertEqual(1, self._claim("rcc-instance:another-instance")["unresolved"])

    def test_repeated_abandon_does_not_emit_duplicate_events(self):
        self._retire()
        result = self._retire()
        self.assertEqual("ALREADY_ABANDONED", result["action"])
        d = self.store._connect()
        try:
            count = d.execute(
                "SELECT count(*) FROM events "
                "WHERE kind='OPERATION_CLAIM_ABANDONED_UNVERIFIED' "
                "AND subject_id='old-send'",
            ).fetchone()[0]
            payload = json.loads(d.execute(
                "SELECT data_json FROM events "
                "WHERE kind='OPERATION_CLAIM_ABANDONED_UNVERIFIED' "
                "AND subject_id='old-send'",
            ).fetchone()[0])
        finally:
            d.close()
        self.assertEqual(1, count)
        self.assertEqual(True, payload["no_resend_original"])
        self.assertEqual("UNKNOWN", payload["original_outcome"])

    def test_user_chat_and_active_user_cannot_be_abandoned(self):
        for observation in (
            self._observation(bct_owned=False),
            self._observation(user_active=True),
        ):
            self.assertEqual("PROTECT_USER_CHAT", decide(observation))
            with self.assertRaisesRegex(ConflictError, "NOT_STALE_OR_USER_ACTIVE"):
                self._retire(observation=observation)
        self.assertEqual(1, self._claim()["unresolved"])

    def test_recent_progress_or_confirmed_result_never_abandoned(self):
        for obs, expected in (
            (self._observation(progress_seen=True), "KEEP_WORKING"),
            (self._observation(response_confirmed=True), "ACCEPT_RESULT"),
        ):
            self.assertEqual(expected, decide(obs))
            with self.assertRaises(ConflictError):
                self._retire(observation=obs)

    def test_two_inspections_and_elapsed_time_needed_not_two_sends(self):
        for obs in (
            self._observation(checks=1),
            self._observation(no_progress_seconds=89),
        ):
            self.assertEqual("CHECK_AGAIN", decide(obs))
            with self.assertRaises(ConflictError):
                self._retire(observation=obs)

    def test_wrong_original_work_id_or_target_does_not_release(self):
        for kwargs in (
            {"original_work_id": "other-work"},
            {"instance_id": "wrong-instance"},
            {"original_operation_id": "nonexistent"},
        ):
            with self.assertRaises(ConflictError):
                self._retire(**kwargs)
        self.assertEqual(1, self._claim()["unresolved"])

    def test_unknown_operation_remains_idempotent_not_resubmitted(self):
        self._retire()
        is_new, duplicate = self.store.begin_operation(
            operation_id="old-send", work=self.work, principal_id="test-owner",
            request_digest="sha-old-send", capability="relay_browser",
            target=self.instance, resources=(self.resource,),
            policy_revision="test",
        )
        self.assertFalse(is_new)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(Outcome.UNKNOWN, duplicate.outcome)

    def test_non_unknown_and_running_operation_cannot_be_abandoned(self):
        d = self.store._connect()
        try:
            d.execute("UPDATE operations SET outcome='APPLIED' "
                      "WHERE operation_id='old-send'")
        finally:
            d.close()
        with self.assertRaisesRegex(ConflictError, "EXACT_UNKNOWN_REQUIRED"):
            self._retire()
        self.assertEqual(1, self._claim()["unresolved"])

    def test_readonly_decision_does_not_change_original_receipt(self):
        previous = dict(self._old_outcome())
        self.assertEqual("RECREATE_CHAT", decide(self._observation()))
        self.assertEqual(previous, self._old_outcome())
        self.assertEqual(1, self._claim()["unresolved"])


if __name__ == "__main__":
    unittest.main()
