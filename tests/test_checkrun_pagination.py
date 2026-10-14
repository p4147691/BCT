from __future__ import annotations

import unittest
from unittest.mock import patch

from bct.integrations.github import GhCliClient
from bct.features.github import _check_evidence


class CheckRunPaginationTests(unittest.TestCase):
    def test_two_pages_all_required_checks(self):
        pages = [
            {"total_count": 101, "check_runs": [{"id": i, "name": "other", "status": "completed", "conclusion": "success"} for i in range(1, 101)]},
            {"total_count": 101, "check_runs": [{"id": 101, "name": "required", "status": "completed", "conclusion": "success", "app": {"slug": "github-actions"}}]},
        ]
        client = GhCliClient()
        with patch.object(client, "_api", return_value=pages) as api:
            runs = client.get_check_runs("owner/repo", "a" * 40)
        self.assertEqual(len(runs), 101)
        self.assertIn("--paginate", api.call_args.args)
        self.assertIn("--slurp", api.call_args.args)
        self.assertTrue(_check_evidence(runs, ["required"])[0])

    def test_missing_last_page_fails_closed(self):
        client = GhCliClient()
        with patch.object(client, "_api", return_value=[{"total_count": 101, "check_runs": [{"id": 1, "name": "test"}]}]):
            with self.assertRaisesRegex(RuntimeError, "GITHUB_CHECK_RUNS_INCOMPLETE"):
                client.get_check_runs("owner/repo", "a" * 40)

    def test_total_count_change_fails_closed(self):
        client = GhCliClient()
        pages = [{"total_count": 2, "check_runs": [{"id": 1}]}, {"total_count": 3, "check_runs": [{"id": 2}]}]
        with patch.object(client, "_api", return_value=pages):
            with self.assertRaisesRegex(RuntimeError, "GITHUB_CHECK_RUNS_CHANGED_DURING_PAGINATION"):
                client.get_check_runs("owner/repo", "a" * 40)

    def test_duplicate_id_fails_closed(self):
        client = GhCliClient()
        with patch.object(client, "_api", return_value=[{"total_count": 2, "check_runs": [{"id": 1}, {"id": 1}]}]):
            with self.assertRaisesRegex(RuntimeError, "GITHUB_CHECK_RUNS_DUPLICATE"):
                client.get_check_runs("owner/repo", "a" * 40)

    def test_provider_collision_is_not_success(self):
        runs = [
            {"id": 10, "name": "test", "status": "completed", "conclusion": "failure", "app": {"slug": "provider-a"}},
            {"id": 11, "name": "test", "status": "completed", "conclusion": "success", "app": {"slug": "provider-b"}},
        ]
        ready, evidence = _check_evidence(runs, ["test"])
        self.assertFalse(ready)
        self.assertEqual(evidence[0]["status"], "AMBIGUOUS_PROVIDER")

    def test_same_provider_rerun_uses_latest(self):
        runs = [
            {"id": 10, "name": "test", "status": "completed", "conclusion": "failure", "app": {"slug": "github-actions"}},
            {"id": 11, "name": "test", "status": "completed", "conclusion": "success", "app": {"slug": "github-actions"}},
        ]
        self.assertTrue(_check_evidence(runs, ["test"])[0])

    def test_missing_required_check_stays_missing(self):
        ready, evidence = _check_evidence([], ["required"])
        self.assertFalse(ready)
        self.assertEqual(evidence[0]["status"], "MISSING")


if __name__ == "__main__":
    unittest.main()
