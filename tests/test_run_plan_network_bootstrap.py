from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.store import Store
from bct.core.project_memory import ProjectMemoryStore
from bct.features.conversation_network import ConversationNetworkUpdateFeature
from bct.conversation_network import project_view


class RunPlanNetworkBootstrapTests(unittest.TestCase):
    def test_network_project_upsert_is_reusable(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            feature = ConversationNetworkUpdateFeature(store)
            args = {"operation": "project-upsert", "project_id": "new.project", "display_name": "New Project"}
            request = feature.prepare(work=None, arguments=args)
            self.assertEqual("APPLIED", feature.execute(request).outcome.value)
            self.assertEqual("APPLIED", feature.execute(request).outcome.value)
            self.assertEqual("New Project", project_view(store, project_id="new.project")["project"]["display_name"])

    def test_plan_ledger_revision_and_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            store = ProjectMemoryStore(Path(root) / "project-context" / "central")
            record = {
                "title": "Run plan p1", "goal": "Implement feature",
                "scope_note": "Project: demo; discretion: normal",
                "summary": "Tests pass",
                "links": [{"type": "bct_work", "id": "work-1"}],
                "items": [{"text": "1/2: implement | done: code", "evidence": []},
                          {"text": "2/2: test | done: pass", "evidence": []}],
                "decisions": [{"text": "discretion: normal", "evidence": []}],
                "next_actions": [], "checkpoints": {"external": {"plan_id": "p1", "project": "demo"}},
            }
            first = store.save("run-plan-p1", expected_revision=0, author="tester", record=record)
            self.assertEqual(1, first["revision"])
            duplicate = store.save("run-plan-p1", expected_revision=0, author="tester", record=record)
            self.assertTrue(duplicate["duplicate"])
            revised = {**record, "summary": "Tests and CI pass"}
            second = store.save("run-plan-p1", expected_revision=1, author="tester", record=revised)
            self.assertEqual(2, second["revision"])
            self.assertEqual("Tests and CI pass", store.get("run-plan-p1")["record"]["summary"])


if __name__ == "__main__":
    unittest.main()
