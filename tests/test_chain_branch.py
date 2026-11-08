from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.chain_direction import ChainBranchRequestLedger, ChainDirectionLedger
from bct.core.models import Work
from bct.core.store import Store
from bct.mcp_server import build_mcp


class Operations:
    capabilities = ("browser",)


class ChainBranchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.root.name) / "state.sqlite")
        self.directions = ChainDirectionLedger(self.store)
        self.directions.save(
            direction_id="direction-b", work_id="work-root", source_kind="USER",
            decision="NEW_TASK", direction_text="Perform the primary bounded task.",
        )
        self.directions.plan_chain(
            direction_id="direction-b", work_id="work-root", task_id="task-b", operation_id="op-b",
        )
        self.directions.mark_chain_started(
            direction_id="direction-b", work_id="work-root", task_id="task-b", operation_id="op-b",
        )
        self.branches = ChainBranchRequestLedger(self.store)

    def tearDown(self):
        self.root.cleanup()

    def request(self, request_id="request-ba", **overrides):
        fields = {
            "request_id": request_id, "root_work_id": "work-root", "parent_work_id": "work-root",
            "parent_direction_id": "direction-b", "parent_step_id": "CAPTURE_OBSERVATION",
            "parent_task_id": "task-b", "parent_generation": 1, "kind": "DIAGNOSIS",
            "reason": "Capture observation did not provide a usable image.", "required": True,
            "exact_refs": {"task_id": "task-b", "direction_id": "direction-b", "generation": 1},
        }
        fields.update(overrides)
        return self.branches.request(**fields)

    def test_worker_request_is_waiting_for_manager_and_does_not_create_child(self):
        request = self.request()
        self.assertEqual("WAITING_INPUT", request["state"])
        self.assertEqual("MANAGER_REVIEW_BRANCH_REQUEST", request["next_safe_step"])
        self.assertEqual("", request["child_direction_id"])
        tree = ChainBranchRequestLedger.tree(store=self.store, root_work_id="work-root")
        self.assertEqual(["request-ba"], [item["request_id"] for item in tree["manager_attention"]])
        self.assertEqual(1, len(tree["nodes"]))

    def test_manager_adoption_links_child_direction_then_exact_recipe_start(self):
        self.request()
        child = self.directions.save(
            direction_id="direction-ba", work_id="work-root", source_kind="USER",
            decision="NEW_TASK", direction_text="Diagnose the capture boundary without retransmitting it.",
            branch_request_id="request-ba",
        )
        self.assertEqual("direction-b", child["chain_branch"]["parent_direction_id"])
        self.assertEqual("DIAGNOSIS", child["chain_branch"]["kind"])
        adopted = self.branches.get(request_id="request-ba")
        self.assertEqual("READY", adopted["state"])
        self.assertEqual("direction-ba", adopted["child_direction_id"])
        self.directions.plan_chain(
            direction_id="direction-ba", work_id="work-root", task_id="task-ba", operation_id="op-ba",
        )
        self.assertEqual("IN_PROGRESS", self.branches.get(request_id="request-ba")["state"])
        tree = ChainBranchRequestLedger.tree(store=self.store, root_work_id="work-root")
        child_node = next(item for item in tree["nodes"] if item["direction_id"] == "direction-ba")
        self.assertEqual("direction-b", child_node["parent_direction_id"])
        self.assertEqual("CAPTURE_OBSERVATION", child_node["parent_step_id"])
        self.assertEqual("DIAGNOSIS", child_node["kind"])

    def test_unknown_is_visible_and_requires_same_receipt_reconciliation(self):
        self.request()
        with self.assertRaisesRegex(ValueError, "UNKNOWN_RECONCILE_REQUIRED"):
            self.branches.report(
                request_id="request-ba", state="UNKNOWN", reason="The send outcome is uncertain.",
                next_safe_step="RETRY_SEND",
            )
        reported = self.branches.report(
            request_id="request-ba", state="UNKNOWN", reason="The exact original send outcome is uncertain.",
            next_safe_step="RECONCILE_SAME_RECEIPT_ONLY", evidence={"receipt_id": "op-b-send"},
        )
        self.assertEqual("UNKNOWN", reported["state"])
        self.assertIn("DO_NOT_RESEND", reported["prohibited_actions"][0])
        tree = ChainBranchRequestLedger.tree(store=self.store, root_work_id="work-root")
        unknown = next(item for item in tree["branch_requests"] if item["request_id"] == "request-ba")
        self.assertEqual("UNKNOWN", unknown["state"])
        self.assertIn("DO_NOT_RESEND", unknown["prohibited_actions"][0])

    def test_wrong_parent_task_cannot_create_an_anonymous_branch(self):
        with self.assertRaisesRegex(ValueError, "PARENT_NOT_EXACT"):
            self.request(request_id="request-wrong", parent_task_id="task-other")

    def test_duplicate_request_is_rejected_and_not_applied_survives_worker_restart(self):
        self.request()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_REQUEST"):
            self.request(request_id="request-ba-duplicate")
        recorded = self.branches.report(
            request_id="request-ba", state="NOT_APPLIED",
            reason="The capture action was confirmed not to have been applied.",
            next_safe_step="MANAGER_DECIDE_RETRY_OR_DIAGNOSIS",
            evidence={"receipt_id": "op-b-send"},
        )
        self.assertEqual("NOT_APPLIED", recorded["state"])
        reopened = ChainBranchRequestLedger(Store(Path(self.root.name) / "state.sqlite"))
        restored = reopened.get(request_id="request-ba")
        self.assertEqual("NOT_APPLIED", restored["state"])
        self.assertEqual("MANAGER_DECIDE_RETRY_OR_DIAGNOSIS", restored["next_safe_step"])

    def test_grandchild_and_resume_remain_linked_without_blocking_an_independent_root(self):
        self.request()
        self.directions.save(
            direction_id="direction-ba", work_id="work-root", source_kind="USER",
            decision="NEW_TASK", direction_text="Diagnose the observation.",
            branch_request_id="request-ba",
        )
        self.directions.plan_chain(direction_id="direction-ba", work_id="work-root",
                                   task_id="task-ba", operation_id="op-ba")
        self.directions.mark_chain_started(direction_id="direction-ba", work_id="work-root",
                                           task_id="task-ba", operation_id="op-ba")
        grandchild_request = self.branches.request(
            request_id="request-baa", root_work_id="work-root", parent_work_id="work-root",
            parent_direction_id="direction-ba", parent_step_id="DIAGNOSIS_RESULT",
            parent_task_id="task-ba", parent_generation=1, kind="FIX",
            reason="The diagnosis found one bounded repair.", exact_refs={"task_id": "task-ba"},
            required=False,
        )
        self.assertFalse(grandchild_request["required"])
        grandchild = self.directions.save(
            direction_id="direction-baa", work_id="work-root", source_kind="USER",
            decision="NEW_TASK", direction_text="Apply the bounded repair and verify.",
            branch_request_id="request-baa",
        )
        self.assertEqual("direction-ba", grandchild["chain_branch"]["parent_direction_id"])
        # A resumes the original B branch with an ordinary Manager-authored
        # Direction; this records a link and does not silently send anything.
        resumed = self.directions.save(
            direction_id="direction-b-resume", work_id="work-root", source_kind="USER",
            decision="NEW_TASK", direction_text="Resume B at its next safe verification step.",
            parent_direction_id="direction-b", parent_work_id="work-root",
            parent_step_id="RESUME_AFTER_DIAGNOSIS", branch_kind="RESUME",
            branch_reason="A accepted the diagnostic result and chose the next B step.",
        )
        self.assertEqual("RESUME", resumed["chain_branch"]["kind"])
        with self.assertRaisesRegex(ValueError, "COMPLETION_EVIDENCE_REQUIRED"):
            self.branches.report(request_id="request-ba", state="COMPLETED", reason="Done.",
                                 next_safe_step="NONE", evidence={})
        completed = self.branches.report(
            request_id="request-ba", state="COMPLETED", reason="A recorded the returned diagnostic evidence.",
            next_safe_step="NONE", evidence={"direction_id": "direction-b-resume"},
        )
        self.assertEqual("COMPLETED", completed["state"])
        tree = ChainBranchRequestLedger.tree(store=self.store, root_work_id="work-root")
        self.assertEqual(4, len(tree["nodes"]))
        self.assertNotIn("request-ba", [item["request_id"] for item in tree["manager_attention"]
                                          if "request_id" in item])


class ChainBranchPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_branch_request_tree_and_status_attention_are_manager_visible(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            work = store.create_work(Work(
                "work-root", "fixture", (), frozenset({"browser"}), "bct-mcp-local", 1,
            ))
            directions = ChainDirectionLedger(store)
            directions.save(direction_id="direction-b", work_id=work.work_id, source_kind="USER",
                            decision="NEW_TASK", direction_text="Perform the primary task.")
            directions.plan_chain(direction_id="direction-b", work_id=work.work_id,
                                  task_id="task-b", operation_id="op-b")
            directions.mark_chain_started(direction_id="direction-b", work_id=work.work_id,
                                          task_id="task-b", operation_id="op-b")
            mcp = build_mcp(SimpleNamespace(operations=Operations(), store=store),
                            compact_catalogue=True, status_provider=lambda: {"monitor": {}})
            _, requested = await mcp.call_tool("bct_chain_branch", {
                "action": "request", "work_id": work.work_id, "request_id": "request-ba",
                "parent_direction_id": "direction-b", "parent_step_id": "CAPTURE_OBSERVATION",
                "parent_task_id": "task-b", "parent_generation": 1, "kind": "DIAGNOSIS",
                "reason": "Capture observation needs diagnosis.",
            })
            self.assertEqual("WAITING_INPUT", requested["status"])
            self.assertIn("create_child_direction", requested["does_not"])
            _, tree = await mcp.call_tool("bct_chain_branch", {"action": "tree", "work_id": work.work_id})
            self.assertEqual("NONE_READ_ONLY", tree["effects"])
            self.assertEqual("request-ba", tree["chain_tree"]["manager_attention"][0]["request_id"])
            _, status = await mcp.call_tool("bct_status", {"scope": "bct"})
            self.assertEqual("request-ba", status["chain_branch_attention"][0]["request_id"])
