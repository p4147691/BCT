from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import Principal
from bct.features.decision import DecisionModelFeature
from bct.integrations.decision import DEFAULT_QUESTIONS


class _DecisionClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def status(self):
        if self.fail:
            raise OSError("offline")
        return {"ready": True, "model_name": "act-laya-v2", "owner": "bct"}

    def recommend(self, structured_input, questions=None):
        if self.fail:
            raise TimeoutError("slow")
        self.calls.append((structured_input, questions))
        return {
            "model": "act-laya-v2",
            "answers": {"task_type": {"choice": "READ", "confidence": 0.97}},
            "advisory_only": True,
        }


class DecisionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["decision_model"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.client = _DecisionClient()
        self.bct.operations._features["decision_model"] = DecisionModelFeature(self.policy, self.client)
        self.principal = Principal("developer", "test", frozenset({"decision_model"}))
        self.bct.create_work(
            work_id="decision-work", request_summary="decision advice", roots=[str(self.root)],
            actions=["decision_model"], principal=self.principal,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, operation_id, arguments):
        return self.bct.operations.run(
            principal=self.principal, work_id="decision-work", operation_id=operation_id,
            capability="decision_model", arguments=arguments,
        )

    def test_status_and_recommendation_are_advisory(self):
        status = self.call("decision-status", {"operation": "status"})
        advice = self.call("decision-recommend", {
            "operation": "recommend", "input": {"request": "파일을 읽어줘"},
        })
        self.assertTrue(status.output["available"])
        self.assertTrue(status.output["ready"])
        self.assertEqual(advice.output["answers"]["task_type"]["choice"], "READ")
        self.assertTrue(advice.output["advisory_only"])
        self.assertEqual(len(self.client.calls), 1)

    def test_timeout_returns_deterministic_fallback_without_changing_policy(self):
        self.bct.operations._features["decision_model"] = DecisionModelFeature(
            self.policy, _DecisionClient(fail=True),
        )
        result = self.call("decision-offline", {
            "operation": "recommend", "input": {"request": "test"},
        })
        self.assertEqual(result.outcome.value, "APPLIED")
        self.assertFalse(result.output["available"])
        self.assertEqual(result.output["fallback"], "deterministic")

    def test_duplicate_recommendation_does_not_call_model_again(self):
        arguments = {"operation": "recommend", "input": {"request": "inspect"}}
        first = self.call("decision-duplicate", arguments)
        second = self.call("decision-duplicate", arguments)
        self.assertTrue(first.output["available"])
        self.assertTrue(second.duplicate)
        self.assertEqual(len(self.client.calls), 1)

    def test_default_questions_use_laya_choice_contract(self):
        self.assertEqual(set(DEFAULT_QUESTIONS), {
            "task_type", "executor", "failure_cause", "next_action",
        })
        for question in DEFAULT_QUESTIONS.values():
            self.assertEqual(question["type"], "choice")
            self.assertIsInstance(question["criteria"], dict)
            self.assertGreaterEqual(len(question["criteria"]), 2)
            self.assertNotIn("options", question)


if __name__ == "__main__":
    unittest.main()
