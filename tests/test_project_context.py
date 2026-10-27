from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bct.core.models import Work
from bct.features.project_context import ProjectContextFeature


def record(title: str, work_id: str | None = None):
    links = [] if work_id is None else [{"type": "bct_work", "id": work_id}]
    return {
        "title": title, "goal": "keep shared context", "scope_note": "bounded summary",
        "summary": "current facts only", "links": links, "items": [], "decisions": [],
        "next_actions": [], "checkpoints": {"bct_event_id": 0, "external": {}},
    }


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.work = Work("context-work", "context", (self.temp.name,),
                         frozenset({"project_context"}), "p")
        self.feature = ProjectContextFeature(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def run_feature(self, **arguments):
        return self.feature.execute(self.feature.prepare(work=self.work, arguments=arguments))

    def test_central_and_worklog_are_separate_and_revision_fenced(self):
        self.run_feature(operation="central-save", project="demo", expected_revision=0,
                         author="manager", record=record("central"))
        central = self.run_feature(operation="central-get", project="demo")
        self.assertEqual("central", central.output["record"]["title"])

        self.run_feature(operation="worklog-save", project="demo", journal_work_id="context-work",
                         expected_revision=0, author="worker", record=record("journal", "context-work"))
        journal = self.run_feature(operation="worklog-get", project="demo", journal_work_id="context-work")
        self.assertEqual("journal", journal.output["record"]["title"])
        overview = self.run_feature(operation="overview", project="demo")
        self.assertEqual(1, len(overview.output["worklogs"]))

    def test_worklog_requires_exact_work_link(self):
        with self.assertRaisesRegex(Exception, "PROJECT_CONTEXT_WORK_LINK_REQUIRED"):
            self.feature.prepare(work=self.work, arguments={
                "operation": "worklog-save", "project": "demo", "journal_work_id": "context-work",
                "expected_revision": 0, "author": "worker", "record": record("missing link"),
            })
