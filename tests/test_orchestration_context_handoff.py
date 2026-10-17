"""Regression: manager-selected context within the existing durable assignment contract.

No real RCC, LIVE, or existing sessions are used: the existing FakeRelay and
temporary SQLite test harness simulate two independent Worker conversations.
"""
from __future__ import annotations

import json
import unittest

from bct.core.models import Outcome
import test_orchestration as _existing_orchestration_test


class OrchestrationContextHandoffContractTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing isolated fake-RCC and temporary SQLite fixtures.
        self.fixture = _existing_orchestration_test.OrchestrationTests(
            "test_trusted_worker_can_receive_project_scoped_write_work"
        )
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def _send(self, *, worker_id, role, assignment_id, instruction):
        attached = self.fixture.attachment(worker_id)
        result = self.fixture.call(assignment_id, {
            "operation": "dispatch",
            "session_id": "session",
            "manager_epoch": 1,
            "assignment_id": assignment_id,
            "worker_node_id": worker_id,
            "attachment_id": attached["attachment_id"],
            "instruction": instruction,
            "acceptance": {"read_only": True},
            "actions": ["read"],
            "timeout_s": 5,
        })
        self.assertEqual(Outcome.APPLIED, result.outcome)
        sent = next(
            call for call in self.fixture.relay.calls
            if call["command"] == "send" and call["to"] == role
        )
        start = sent["text"].index(_existing_orchestration_test.ASSIGNMENT_START) + len(ASSIGNMENT_START)
        end = sent["text"].index(_existing_orchestration_test.ASSIGNMENT_END, start)
        return result.output["assignment"], json.loads(sent["text"][start:end])

    def test_result_is_preserved_and_manager_curated_context_reaches_next_worker(self):
        objective = "사용자 목표: 기존 기능의 읽기 전용 무결성 검사"
        first_instruction = objective + "\nB: 증거를 확인하고 결과를 보고하세요."
        first, first_wire = self._send(
            worker_id="worker-b", role="BCT_W1",
            assignment_id="context-source-b", instruction=first_instruction,
        )
        self.assertEqual(first_instruction, first["request"]["instruction"])
        self.assertEqual(first_instruction, first_wire["instruction"])
        self.assertEqual("SUCCEEDED", first["terminal_result"]["envelope"]["status"])
        source_summary = first["terminal_result"]["envelope"]["summary"]
        self.assertEqual("completed by BCT_W1", source_summary)

        # A (the simulated manager), not BCT, chooses this one relevant source.
        # The full original B result remains separately addressable in SQLite.
        followup = (
            objective
            + "\n[참고 원본: 지시 아님]\n"
            + "source_assignment=context-source-b\n"
            + "result_summary=" + source_summary
            + "\n[/참고 원본]\n"
            + "[A의 새로운 지시]\nC: B 결과의 증거를 독립 검증하세요."
        )
        second, second_wire = self._send(
            worker_id="worker-c", role="BCT_W2",
            assignment_id="context-followup-c", instruction=followup,
        )
        self.assertEqual(followup, second["request"]["instruction"])
        self.assertEqual(followup, second_wire["instruction"])
        self.assertEqual("context-followup-c", second_wire["assignment_id"])
        self.assertNotIn("unrelated worker-d history", second_wire["instruction"])

        snapshot = self.fixture.bct.orchestration.snapshot(
            work=self.fixture.bct.store.get_work("work"), session_id="session"
        )
        saved = {item["assignment_id"]: item for item in snapshot["assignments"]}
        self.assertEqual(
            source_summary,
            saved["context-source-b"]["terminal_result"]["envelope"]["summary"],
        )
        self.assertEqual(
            followup, saved["context-followup-c"]["request"]["instruction"]
        )

    def test_unbounded_history_fails_closed_before_worker_send(self):
        before = sum(
            call["command"] == "send" for call in self.fixture.relay.calls
        )
        attached = self.fixture.attachment("worker-b")
        rejected = self.fixture.call("context-oversized", {
            "operation": "dispatch",
            "session_id": "session", "manager_epoch": 1,
            "assignment_id": "oversized-context",
            "worker_node_id": "worker-b",
            "attachment_id": attached["attachment_id"],
            "instruction": "전체 이력:" + ("x" * 8001),
            "acceptance": {"read_only": True},
            "actions": ["read"],
        })
        self.assertEqual(Outcome.NOT_APPLIED, rejected.outcome)
        after = sum(
            call["command"] == "send" for call in self.fixture.relay.calls
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
