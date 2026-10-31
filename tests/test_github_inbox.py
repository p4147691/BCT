from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import Principal
from bct.core.models import PreconditionError


class Runs:
    def __init__(self, conclusion: str = "success", sha: str = "a" * 40):
        self.conclusion, self.sha, self.calls = conclusion, sha, 0
    def get_workflow_runs_for_head(self, repository, head_sha):
        return [{"name": "BCT CI", "event": "pull_request", "id": 7,
                 "head_sha": head_sha}]

    def get_workflow_run(self, repository, run_id):
        self.calls += 1
        return {"repository": {"full_name": repository}, "head_sha": self.sha,
                "status": "completed", "conclusion": self.conclusion,
                "html_url": f"https://github.com/{repository}/actions/runs/{run_id}"}
    def get_workflow_jobs(self, repository, run_id):
        return [{"name": "unit", "conclusion": self.conclusion}]


class GitHubInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.policy = root / "bct.toml"
        self.policy.write_text('[policy]\nnormal_actions=["github_run_watch"]\napproval_actions=[]\n[github_inbox]\ninitial_seconds=5\nmax_seconds=5\ntimeout_seconds=30\n', encoding="utf-8")
        self.principal = Principal("p", "test", frozenset({"github_run_watch"}))
        self.runs = Runs(); self.bct = BCT(state_path=root / "state.sqlite", policy_path=self.policy, github_client=self.runs)
        for work in ("w1", "w2"):
            self.bct.create_work(work_id=work, request_summary="watch", roots=[str(root)], actions=["github_run_watch"], principal=self.principal)
    def tearDown(self): self.temp.cleanup()
    def watch(self, work, node="n1", **more):
        return self.bct.operations.run(principal=self.principal, work_id=work, operation_id="op-"+work,
            capability="github_run_watch", arguments={"repository":"Owner/Repo", "run_id":7, "head_sha":"a"*40, "workflow":"CI", "initiator_node_id":node, "trigger":"github-run:7:terminal", **more})
    def eventually(self):
        for _ in range(50):
            rows = self.bct.store.get_github_run_inbox(node_id="n1")
            if rows and rows[0]["state"] != "WAITING_EXTERNAL": return rows
            time.sleep(.01)
        return self.bct.store.get_github_run_inbox(node_id="n1")
    def test_production_inbox_timeout_covers_long_core_ci(self):
        from bct.features.github_inbox import _settings
        root = Path(__file__).resolve().parents[1]
        initial, maximum, timeout = _settings(root / "bct.toml")
        self.assertGreaterEqual(timeout, 1800)
        self.assertLessEqual(maximum, 30)
        self.assertGreaterEqual(initial, 5)

    def test_follow_head_auto_discovers_run_and_preserves_original_work(self):
        result = self.bct.operations.run(
            principal=self.principal, work_id="w1", operation_id="watch-head",
            capability="github_run_watch", arguments={
                "repository": "Owner/Repo", "head_sha": "a"*40,
                "follow_head": True, "workflow": "BCT CI",
                "initiator_node_id": "work:fixture",
                "trigger": f"github-head:{'a'*40}:terminal",
            },
        )
        self.assertEqual("APPLIED", result.outcome.value)
        rows = self.bct.store.get_github_run_inbox(work_id="w1")
        self.assertEqual(1, len(rows))
        self.assertEqual(7, rows[0]["run_id"])
        self.assertEqual("SUCCESS", rows[0]["state"])
        self.assertTrue(rows[0]["unread"])

    def test_follow_head_rejects_ambiguous_workflow_runs(self):
        self.runs.get_workflow_runs_for_head = lambda repo, sha: [
            {"name":"BCT CI","event":"pull_request","id":7,"head_sha":sha},
            {"name":"BCT CI","event":"pull_request","id":8,"head_sha":sha},
        ]
        result = self.bct.operations.run(
            principal=self.principal,work_id="w1",operation_id="watch-head-ambiguous",
            capability="github_run_watch",arguments={
                "repository":"owner/repo","head_sha":"a"*40,
                "follow_head":True,"workflow":"BCT CI","initiator_node_id":"work:fixture",
                "trigger":f"github-head:{'a'*40}:terminal",
            })
        self.assertNotEqual("APPLIED", result.outcome.value)
        self.assertEqual([], self.bct.store.get_github_run_inbox(work_id="w1"))

    def test_duplicate_merges_recipient_and_is_terminal_once(self):
        first = self.watch("w1"); second = self.watch("w2", node="n2")
        self.assertTrue(first.evidence["watcher_started"]); self.assertFalse(second.evidence["watcher_started"])
        rows = self.eventually(); self.assertEqual("SUCCESS", rows[0]["state"]); self.assertEqual(1, self.runs.calls)
        self.assertEqual(1, len(self.bct.store.get_github_run_inbox(node_id="n2")))
    def test_failure_and_read_ack(self):
        self.runs.conclusion = "failure"; self.watch("w1")
        rows = self.eventually(); self.assertEqual("FAILED", rows[0]["state"])
        self.assertTrue(rows[0]["unread"])
        self.bct.store.get_github_run_inbox(node_id="n1", acknowledge=True)
        self.assertFalse(self.bct.store.get_github_run_inbox(node_id="n1")[0]["unread"])
    def test_sha_mismatch_fails_without_claim(self):
        self.runs.sha = "b"*40; self.watch("w1")
        rows = self.eventually(); self.assertEqual("FAILED", rows[0]["state"])
        self.assertEqual([], self.bct.store.monitor_snapshot()["unresolved_claims"])

    def test_cancelled_is_terminal_and_unread(self):
        self.runs.conclusion = "cancelled"; self.watch("w1")
        self.assertEqual("CANCELLED", self.eventually()[0]["state"])

    def test_skipped_is_cancelled(self):
        self.runs.conclusion = "skipped"; self.watch("w1")
        self.assertEqual("CANCELLED", self.eventually()[0]["state"])

    def test_notify_nodes_and_manager_are_merged(self):
        self.watch("w1", notify_nodes=["n2", "n3"], notify_manager=True, manager_node_id="manager")
        self.assertEqual(1, len(self.bct.store.get_github_run_inbox(node_id="n2", work_id="w1")))
        self.assertEqual(1, len(self.bct.store.get_github_run_inbox(node_id="manager", work_id="w1")))

    def test_duplicate_after_terminal_is_unread_for_new_recipient(self):
        self.watch("w1"); self.watch("w2", node="n2")
        row = self.bct.store.get_github_run_inbox(node_id="n2", work_id="w2")[0]
        self.assertTrue(row["unread"])

    def test_waiting_rows_are_not_marked_unread_or_acknowledged(self):
        record, _ = self.bct.store.register_github_run_inbox(subscription_id="x", repository="owner/repo", run_id=8,
            head_sha="a" * 40, workflow="CI", context={}, work_id="w1", node_id="n1", conversation_uuid=None,
            notify_user=True, notify_manager=False, next_step="wait", trigger="github-run:8:terminal")
        self.assertFalse(self.bct.store.get_github_run_inbox(node_id="n1", work_id="w1")[0]["unread"])
        self.bct.store.get_github_run_inbox(node_id="n1", work_id="w1", acknowledge=True)
        self.assertFalse(self.bct.store.get_github_run_inbox(node_id="n1", work_id="w1")[0]["unread"])

    def test_per_recipient_next_step(self):
        self.watch("w1", next_step="node one")
        self.watch("w2", node="n2", next_step="node two")
        self.assertEqual("node two", self.bct.store.get_github_run_inbox(node_id="n2", work_id="w2")[0]["next_step"])

    def test_rejects_boolean_run_id(self):
        with self.assertRaises(PreconditionError): self.watch("w1", run_id=True)

    def test_rejects_short_sha(self):
        with self.assertRaises(PreconditionError): self.watch("w1", head_sha="a" * 39)

    def test_rejects_missing_trigger(self):
        feature = self.bct.operations._features["github_run_watch"]
        work = self.bct.store.get_work("w1")
        with self.assertRaises(PreconditionError): feature.prepare(work=work, arguments={"repository":"owner/repo", "run_id":1, "head_sha":"a"*40, "workflow":"CI", "initiator_node_id":"n1"})

    def test_rejects_unbounded_notify_nodes(self):
        with self.assertRaises(PreconditionError): self.watch("w1", notify_nodes=[str(i) for i in range(17)])

    def test_monitor_projection_is_read_only(self):
        self.watch("w1")
        snapshot = self.bct.store.monitor_snapshot()
        self.assertEqual("SUCCESS", snapshot["github_run_inbox"][0]["state"])
        self.assertEqual("ACTIVE", self.bct.store.get_work("w1").state)

    def test_manager_remains_opt_in_when_id_is_supplied(self):
        self.watch('w1', manager_node_id='manager', notify_manager=False)
        self.assertEqual([], self.bct.store.get_github_run_inbox(node_id='manager', work_id='w1'))
        self.assertFalse(self.bct.store.get_github_run_inbox(node_id='n1', work_id='w1')[0]['notify_manager'])

    def test_wrong_exact_terminal_trigger_is_rejected(self):
        with self.assertRaises(PreconditionError):
            self.watch('w1', trigger='github-run:8:terminal')

    def test_second_node_same_work_has_independent_registration(self):
        self.watch('w1')
        outcome = self.bct.operations.run(
            principal=self.principal, work_id='w1', operation_id='op-w1-second-node',
            capability='github_run_watch',
            arguments={'repository':'owner/repo','run_id':7,'head_sha':'a'*40,
                       'workflow':'CI','initiator_node_id':'n2',
                       'trigger':'github-run:7:terminal'},
        )
        self.assertEqual('APPLIED', outcome.outcome.value)
        self.assertFalse(outcome.evidence['watcher_started'])
        self.assertEqual(1, len(self.bct.store.get_github_run_inbox(node_id='n2',work_id='w1')))

    def test_failed_step_is_bounded_in_terminal_diagnostic(self):
        self.runs.conclusion = 'failure'
        self.runs.get_workflow_jobs = lambda repo, run: [{'name':'build', 'conclusion':'failure',
            'steps':[{'name':'compile','conclusion':'success'},{'name':'link','conclusion':'failure'}]}]
        self.watch('w1')
        self.assertEqual('failed job: build; step: link', self.eventually()[0]['error_summary'])

    def test_api_outage_timeout_does_not_block_other_work(self):
        from unittest.mock import patch
        import bct.features.github_inbox as inbox
        self.runs.get_workflow_run = lambda repo, run: (_ for _ in ()).throw(OSError('fixture outage'))
        with patch.object(inbox, '_settings', return_value=(0.01,0.03,0.05)):
            self.watch('w1')
        row = self.bct.store.get_github_run_inbox(node_id='n1',work_id='w1')[0]
        self.assertEqual('TIMED_OUT', row['state'])
        self.assertEqual('ACTIVE', self.bct.store.get_work('w2').state)
        self.assertEqual([], self.bct.store.monitor_snapshot()['unresolved_claims'])

    def test_two_repositories_monitor_projection(self):
        self.watch('w1')
        self.bct.store.register_github_run_inbox(subscription_id='second-repo',repository='other/tool',
            run_id=17, head_sha='b'*40, workflow='other',context={'kind':'release'},
            work_id='w2',node_id='n2',conversation_uuid=None,notify_user=True,
            notify_manager=False,next_step='review',trigger='github-run:17:terminal')
        snapshot = self.bct.store.monitor_snapshot()
        self.assertEqual({'owner/repo','other/tool'},
            {row['repository'] for row in snapshot['github_run_inbox']})

    def test_busy_node_result_remains_ready_without_relay_effect(self):
        self.watch('w1')
        row = self.eventually()[0]
        self.assertEqual('READY_IN_INBOX', row['delivery_state'])
        self.assertTrue(row['unread'])
        self.assertIn('github-run:7:terminal', row['trigger'])
