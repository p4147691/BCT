from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.conversation_network import (
    configure_conversation_scope,
    conversation_scope_directory,
)
from bct.core.models import Outcome, Principal
from bct.service import BCT


MANAGER = "6ad5afa4-b1e0-83ee-8692-aec4bb51523e"


class ConversationNetworkUpdateFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["conversation_network_update"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.principal = Principal(
            "manager", "test", frozenset({"conversation_network_update"})
        )
        self.bct.create_work(
            work_id="role-work",
            request_summary="역할 태그 갱신",
            roots=[str(self.root)],
            actions=["conversation_network_update"],
            principal=self.principal,
        )
        self.configured = configure_conversation_scope(
            self.bct.store,
            conversation_key=MANAGER,
            display_name="매니저",
            scope_name="테스트 대화망",
            role_tags=["Manager", "조정"],
            now=100.0,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_manager_can_patch_advisory_roles_with_a_durable_receipt(self):
        arguments = {
            "operation": "role-patch",
            "project": "테스트 대화망",
            "node_label": "N1",
            "add": ["CI", "검증"],
            "remove": ["조정"],
            "expected_role_tags_sha256": self.configured["role_tags_sha256"],
        }
        first = self.bct.operations.run(
            principal=self.principal,
            work_id="role-work",
            operation_id="role-patch-1",
            capability="conversation_network_update",
            arguments=arguments,
        )
        duplicate = self.bct.operations.run(
            principal=self.principal,
            work_id="role-work",
            operation_id="role-patch-1",
            capability="conversation_network_update",
            arguments=arguments,
        )
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(duplicate.duplicate)
        current = conversation_scope_directory(
            self.bct.store, conversation_keys=[MANAGER]
        )[MANAGER]
        self.assertCountEqual(["Manager", "CI", "검증"], current["role_tags"])
        self.assertEqual(first.output["role_tags_sha256"], current["role_tags_sha256"])
        self.assertEqual([], self.bct.store.claim_diagnostics())

    def test_stale_ai_patch_fails_closed_without_holding_a_claim(self):
        configure_conversation_scope(
            self.bct.store,
            conversation_key=MANAGER,
            display_name="매니저",
            scope_name="테스트 대화망",
            role_tags=["Manager", "새 편집"],
            expected_role_tags_sha256=self.configured["role_tags_sha256"],
            now=101.0,
        )
        result = self.bct.operations.run(
            principal=self.principal,
            work_id="role-work",
            operation_id="role-patch-stale",
            capability="conversation_network_update",
            arguments={
                "project": "테스트 대화망",
                "node_label": "N1",
                "add": ["CI"],
                "remove": [],
                "expected_role_tags_sha256": self.configured["role_tags_sha256"],
            },
        )
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual(
            "CONVERSATION_NETWORK_ROLE_TAGS_CONFLICT", result.error
        )
        self.assertEqual([], self.bct.store.claim_diagnostics())


if __name__ == "__main__":
    unittest.main()
