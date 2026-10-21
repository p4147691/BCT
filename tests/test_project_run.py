from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct import BCT
from bct.conversation_network import configure_conversation_scope
from bct.core.models import Outcome, Principal
from bct.core.store import Store
from bct.project_run import (
    ProjectRunError,
    bind_project_run_session,
    project_run_scope_view,
    project_run_view,
    start_project_run,
)


MANAGER = "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"
WORKER = "6ad7ff62-fa64-83ee-a485-1138f1538e53"
SCOPE = "network.test-project-run"


class ProjectRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        manager = configure_conversation_scope(
            self.store, conversation_key=MANAGER, display_name="Manager",
            scope_name="Browser Bridge", role_tags=["Manager"], now=100.0,
        )
        self.scope = str(manager["scope_id"])
        configure_conversation_scope(
            self.store, conversation_key=WORKER, display_name="Worker",
            scope_name="Browser Bridge", role_tags=["Worker"], now=101.0,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_requires_explicit_manager_tag_and_prevents_parallel_active_run(self):
        with self.assertRaisesRegex(ProjectRunError, "MANAGER_NOT_DESIGNATED"):
            start_project_run(
                self.store, run_id="run.bad", scope_id=self.scope,
                objective="Bridge", manager_conversation_key=WORKER, now=200.0,
            )
        created, run = start_project_run(
            self.store, run_id="run.bridge", scope_id=self.scope,
            objective="Bridge", manager_conversation_key=MANAGER, now=201.0,
        )
        self.assertTrue(created)
        self.assertEqual("PLANNED", run["state"])
        self.assertEqual([MANAGER, WORKER], [item["conversation_key"] for item in run["members"]])
        repeated, same = start_project_run(
            self.store, run_id="run.bridge", scope_id=self.scope,
            objective="Bridge", manager_conversation_key=MANAGER, now=202.0,
        )
        self.assertFalse(repeated)
        self.assertEqual("run.bridge", same["run_id"])
        with self.assertRaisesRegex(ProjectRunError, "SCOPE_ALREADY_ACTIVE"):
            start_project_run(
                self.store, run_id="run.other", scope_id=self.scope,
                objective="Other", manager_conversation_key=MANAGER, now=203.0,
            )

    def _insert_exact_orchestration_binding(self, *, conversation_key: str = MANAGER,
                                            node_id: str = "node.manager") -> None:
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                ("work.bridge", "Bridge", "[]", "[\"orchestrate\"]", "owner", 1, "ACTIVE"),
            )
            db.execute(
                "INSERT INTO nodes VALUES(?,?,?,?,?,?)",
                (node_id, "Manager", "MANAGER", "ORCHESTRATION", 1, 1),
            )
            db.execute(
                "INSERT INTO orchestration_sessions("
                "session_id,work_id,work_assignment_epoch,objective,roots_json,actions_json,"
                "acceptance_json,plan_revision,manager_node_id,manager_epoch,state,"
                "terminal_summary_json,wake_receipt_mode,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("session.bridge", "work.bridge", 1, "Bridge", "[]", "[\"orchestrate\"]", "{}",
                 1, node_id, 1, "ACTIVE", "{}", "RCC_RESULT_POLL_V1", 210.0, 210.0),
            )
            db.execute(
                "INSERT INTO orchestration_session_nodes VALUES(?,?,?,?)",
                ("session.bridge", node_id, "MANAGER", 1),
            )
            db.execute(
                "INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("attach.manager", 1, node_id, "rcc", "instance", "external", 1, 1,
                 conversation_key, "https://chatgpt.com/c/" + conversation_key,
                 "MANAGER", "receipt", 1, 210.0),
            )

    def test_binding_requires_exact_active_manager_attachment(self):
        start_project_run(
            self.store, run_id="run.bridge", scope_id=self.scope,
            objective="Bridge", manager_conversation_key=MANAGER, now=200.0,
        )
        self._insert_exact_orchestration_binding()
        bound = bind_project_run_session(
            self.store, run_id="run.bridge", work_id="work.bridge",
            orchestration_session_id="session.bridge", manager_node_id="node.manager",
            manager_attachment_id="attach.manager", manager_attachment_generation=1, now=220.0,
        )
        self.assertEqual("READY", bound["state"])
        self.assertEqual("session.bridge", bound["orchestration_session_id"])
        scope = project_run_scope_view(self.store, scope_id=self.scope)
        self.assertEqual("run.bridge", scope["active_run"]["run_id"])

    def test_binding_never_accepts_a_different_conversation_or_inactive_attachment(self):
        start_project_run(
            self.store, run_id="run.bridge", scope_id=self.scope,
            objective="Bridge", manager_conversation_key=MANAGER, now=200.0,
        )
        self._insert_exact_orchestration_binding(conversation_key=WORKER)
        with self.assertRaisesRegex(ProjectRunError, "MANAGER_CONVERSATION_MISMATCH"):
            bind_project_run_session(
                self.store, run_id="run.bridge", work_id="work.bridge",
                orchestration_session_id="session.bridge", manager_node_id="node.manager",
                manager_attachment_id="attach.manager", manager_attachment_generation=1, now=220.0,
            )
        self.assertEqual("PLANNED", project_run_view(self.store, run_id="run.bridge")["state"])

    def test_same_conversation_rebinds_to_new_active_attachment_generation(self):
        start_project_run(
            self.store, run_id="run.bridge", scope_id=self.scope,
            objective="Bridge", manager_conversation_key=MANAGER, now=200.0,
        )
        self._insert_exact_orchestration_binding()
        bind_project_run_session(
            self.store, run_id="run.bridge", work_id="work.bridge",
            orchestration_session_id="session.bridge", manager_node_id="node.manager",
            manager_attachment_id="attach.manager", manager_attachment_generation=1, now=220.0,
        )
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orchestration_attachments SET active=0 "
                "WHERE attachment_id='attach.manager' AND generation=1"
            )
            db.execute(
                "INSERT INTO orchestration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("attach.manager", 2, "node.manager", "rcc", "instance", "external-2",
                 2, 1, MANAGER, "https://chatgpt.com/c/" + MANAGER,
                 "MANAGER", "receipt-2", 1, 230.0),
            )
        with self.assertRaisesRegex(ProjectRunError, "ATTACHMENT_NOT_ACTIVE"):
            bind_project_run_session(
                self.store, run_id="run.bridge", work_id="work.bridge",
                orchestration_session_id="session.bridge", manager_node_id="node.manager",
                manager_attachment_id="attach.manager", manager_attachment_generation=1,
                now=231.0,
            )
        rebound = bind_project_run_session(
            self.store, run_id="run.bridge", work_id="work.bridge",
            orchestration_session_id="session.bridge", manager_node_id="node.manager",
            manager_attachment_id="attach.manager", manager_attachment_generation=2,
            now=232.0,
        )
        self.assertEqual("READY", rebound["state"])
        self.assertEqual(2, rebound["manager_attachment_generation"])


class ProjectRunOrchestrationFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        policy = self.root / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["orchestrate"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=policy)
        self.owner = Principal("owner", "test", frozenset({"orchestrate"}))
        self.work = self.bct.create_work(
            work_id="work.bridge", request_summary="Bridge",
            roots=[str(self.root)], actions=["orchestrate"], principal=self.owner,
        )
        manager = configure_conversation_scope(
            self.bct.store, conversation_key=MANAGER, display_name="Manager",
            scope_name="Browser Bridge", role_tags=["Manager"], now=100.0,
        )
        self.scope = str(manager["scope_id"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, operation_id: str, arguments: dict) -> object:
        return self.bct.operations.run(
            principal=self.owner, work_id=self.work.work_id,
            operation_id=operation_id, capability="orchestrate", arguments=arguments,
        )

    def test_public_orchestrate_path_plans_binds_and_reads_project_run(self):
        planned = self.call("plan", {
            "operation": "project-run-plan", "run_id": "run.bridge",
            "scope_id": self.scope, "objective": "Finish Browser Bridge",
            "manager_conversation_key": MANAGER,
        })
        self.assertEqual(Outcome.APPLIED, planned.outcome)
        self.assertEqual("PLANNED", planned.output["project_run"]["state"])
        self.bct.orchestration.start_session(
            work=self.work, session_id="session.bridge", objective="Finish Browser Bridge",
            acceptance={"complete": True}, roots=list(self.work.roots),
            actions=sorted(self.work.actions),
        )
        attachment = self.bct.orchestration.sync_attachment(
            work=self.work, session_id="session.bridge", node_id="node.manager",
            name="Manager", role="MANAGER", attachment_id="attach.manager",
            instance_id="instance", external_session_id="external", tab_id=1,
            window_id=1, conversation_key=MANAGER,
            endpoint="https://chatgpt.com/c/" + MANAGER, relay_role="MANAGER",
            binding_receipt_id="receipt",
        )
        self.bct.orchestration.takeover_manager(
            work=self.work, session_id="session.bridge", expected_epoch=0,
            manager_node_id="node.manager", reason="explicit selection", evidence={},
        )
        bound = self.call("bind", {
            "operation": "project-run-bind", "run_id": "run.bridge",
            "session_id": "session.bridge", "manager_node_id": "node.manager",
            "manager_attachment_id": "attach.manager",
            "manager_attachment_generation": attachment["generation"],
        })
        self.assertEqual(Outcome.APPLIED, bound.outcome)
        self.assertEqual("READY", bound.output["project_run"]["state"])
        status = self.call("status", {
            "operation": "project-run-status", "run_id": "run.bridge",
        })
        self.assertEqual(Outcome.APPLIED, status.outcome)
        self.assertEqual("session.bridge", status.output["project_run"]["orchestration_session_id"])


if __name__ == "__main__":
    unittest.main()
