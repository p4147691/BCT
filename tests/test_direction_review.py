"""Question-guided Chain entry: real ledgers/MCP, isolated browser-effect fixture."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.chain_direction import (
    ChainDirectionLedger, DIRECTION_QUESTIONS, resolve_direction_target,
    validate_direction_assessment,
)
from bct.chain_execution_plan import ChainExecutionPlanLedger
from bct.component_library import get_manual_guidance
from bct.conversation_network import upsert_project, role_tags_sha256
from bct.core.models import Work
from bct.core.store import Store
from bct.send_delayed_message import DurableWatchLedger, SendDelayedMessageRunner, Watch
from bct.features.conversation_network import ConversationNetworkUpdateFeature
from bct.mcp_server import build_mcp


def key(letter):
    return f"{letter * 8}-{letter * 4}-{letter * 4}-{letter * 4}-{letter * 12}"


A, B, C = (key(letter) for letter in "abc")


def assessment():
    return {
        "answers": {name: f"A's explicit decision about {name}." for name, _, _ in DIRECTION_QUESTIONS},
        "manager_conversation_key": A, "worker_conversation_key": B,
        "supervisor_conversation_key": C,
        "network_name": "Project", "network_updates": [],
        "targets": [
            {"conversation_key": B, "role": "worker", "instruction": "Inspect the owned source without changing LIVE."},
            {"conversation_key": C, "role": "supervisor", "instruction": "Independently review existing release receipts; do not deploy yet."},
        ],
    }


def snapshot():
    items, tabs = [], []
    for number, uuid, roles, network in [(1, A, ["manager"], "Project"),
                                        (2, B, ["worker"], "Project"), (3, C, ["supervisor"], "")]:
        items.append({"status": "CONFIRMED", "conversation_uuid": uuid, "node_number": f"N{number}",
                      "tab_id": number, "window_id": 10, "generating": False,
                      "roles": roles, "network": network,
                      "network_id": "project" if network else ""})
        tabs.append({"presence": "OPEN", "conversation_key": uuid, "tab_id": number, "window_id": 10,
                     "title": f"Node {number}", "conversation_scope": {
                         "scope_name": network, "role_tags": roles, "node_memo": "Keep user data",
                         "assigned_task": "Current task"}})
    return {"monitor": {"current_nodes": {"observation": {"state": "FRESH"}, "items": items},
                        "rcc": {"instances": [{"state": "OPEN", "instance_id": "a" * 32,
                                              "session_id": "b" * 32, "tabs": tabs}]}}}


class Operations:
    capabilities = ("browser", "conversation_network_update")

    def __init__(self, owner):
        self.owner = owner
        self.calls = []
        self.unknown_target = None
        self.after_send = None
        self.after_network = None
        self.network_receipts = {}

    def run(self, **kwargs):
        self.calls.append(kwargs)
        args = kwargs["arguments"]
        outcome = "APPLIED"
        if kwargs["capability"] == "conversation_network_update":
            # Existing setter implementation, with idempotent receipt replay.
            if kwargs["operation_id"] not in self.network_receipts:
                feature = ConversationNetworkUpdateFeature(self.owner.store)
                request = feature.prepare(work=self.owner.work, arguments=args)
                feature.execute(request)
                for tab in self.owner.tabs:
                    if tab["conversation_key"] == args.get("conversation_key"):
                        tab["conversation_scope"].update(scope_name=args["scope_name"], role_tags=args["role_tags"])
                self.network_receipts[kwargs["operation_id"]] = True
                if self.after_network:
                    self.after_network(args)
        elif args["command"] == "send-message":
            if self.unknown_target == args["conversation_key"]:
                outcome = "UNKNOWN"
            if self.after_send:
                self.after_send(args)
        return SimpleNamespace(as_dict=lambda: {"state": "FINISHED", "outcome": outcome,
                                                "evidence": {"command": "isolated-fixture"}})


class DirectionReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "db.sqlite")
        self.work = self.store.create_work(Work("review-work", "bounded review", (),
            frozenset({"browser", "conversation_network_update"}), "bct-mcp-local", 1))
        self.snapshot = snapshot()
        self.tabs = self.snapshot["monitor"]["rcc"]["instances"][0]["tabs"]
        self.ops = Operations(self)
        self.status_reads = 0
        def status_provider():
            self.status_reads += 1
            return copy.deepcopy(self.snapshot)
        self.mcp = build_mcp(SimpleNamespace(operations=self.ops, store=self.store),
                             compact_catalogue=True, status_provider=status_provider)
        guard = patch("bct.node_recovery.NodeRecoveryLedger.assert_send_allowed", return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    async def call(self, tool, **args):
        _, result = await self.mcp.call_tool(tool, args)
        return result

    async def save(self, value=None, **overrides):
        return await self.call("bct_set_direction", **{
            "work_id": self.work.work_id, "direction_id": "direction-review", "decision": "NEW_TASK",
            "source_text": "Complete the translation program safely.",
            "direction_text": "Preserve user data and produce verified results.",
            "assessment": assessment() if value is None else value, **overrides,
        })

    async def start(self, **overrides):
        return await self.call("bct_chain_message", **{
            "work_id": self.work.work_id, "task_id": "review-task", "operation_id": "review-operation",
            "chain_direction_id": "direction-review", **overrides,
        })

    def sends(self):
        return [call for call in self.ops.calls if call["arguments"].get("command") == "send-message"]

    async def test_instruction_only_entry_reads_current_and_historical_networks_without_writes(self):
        upsert_project(self.store, project_id="old-project", display_name="Historical network")
        with self.store._readonly() as db:
            before = list(db.execute("SELECT name FROM sqlite_master ORDER BY name"))
        result = await self.call("bct_chain_message", instruction="Finish the translation program.")
        self.assertEqual("RECIPE_READY", result["status"], result)
        self.assertNotIn("questions", result["direction"])
        self.assertIn("Historical network", json.dumps(result["state"]["stored_networks"]))
        self.assertIn(A, json.dumps(result["state"]["current_nodes"]))
        self.assertEqual("bct_set_direction", result["direction"]["save"]["tool"])
        self.assertEqual("WORK_REQUIRED", result["direction"]["save_gate"]["status"])
        self.assertFalse(result["authorizes_send"])
        self.assertEqual("CALLER_PROVIDED_TEXT", result["input"]["source_evidence"])
        self.assertEqual([], self.ops.calls)
        with self.store._readonly() as db:
            self.assertEqual([tuple(r) for r in before], [tuple(r) for r in db.execute("SELECT name FROM sqlite_master ORDER BY name")])

    async def test_prepare_state_includes_only_the_declared_a_recovery_notices(self):
        ledger = DurableWatchLedger(self.store)
        ledger.prearm_task(
            task_id="stalled-task", work_id=self.work.work_id,
            principal_id=self.work.owner_principal_id,
            assignment_epoch=self.work.assignment_epoch,
            instance_id="fixture-instance", conversation_key=B,
            manager_conversation_key=A, manager_instance_id="fixture-instance",
            baseline={"responseTurnCount": 0, "generating": False,
                      "responseTurnKey": "", "responseSha256": ""},
            registration_receipt="arm-stalled", planned_send_operation_id="send-stalled",
            planned_send_text="Perform the bounded task.",
        )
        self.assertTrue(ledger.record_recovery_needed(
            ledger.get("stalled-task", 1), kind="CONNECTION_DISCONNECTED", observed_at=100.0,
        ))
        result = await self.call(
            "bct_chain_recipe", action="prepare", work_id=self.work.work_id,
            source_text="Continue the existing work safely.", report_target_conversation_key=A,
        )
        notices = result["state"]["recovery_notices"]
        self.assertEqual("OK", notices["status"])
        self.assertEqual("AUTHOR_RECOVER_NODE_DIRECTION", notices["next_action"])
        self.assertEqual(B, notices["notices"][0]["node_conversation_key"])
        self.assertEqual([], self.ops.calls)

    async def test_prepare_state_orders_topology_candidates_without_reassigning_roles(self):
        # C is the only global Supervisor in the fixture.  A and B are already
        # assigned, so neither is silently offered as a reusable Worker.
        result = await self.call(
            "bct_chain_recipe", action="prepare", work_id=self.work.work_id,
            source_text="Prepare a new chain without stealing another Manager.",
        )
        topology = result["state"]["chain_topology_preparation"]
        self.assertEqual("READY", topology["status"])
        self.assertEqual([C], [item["conversation_key"] for item in topology["global_supervisor_candidates"]])
        self.assertEqual([], topology["unassigned_worker_candidates"])
        self.assertTrue(topology["required_creation"]["worker"])
        self.assertFalse(topology["required_creation"]["supervisor"])
        self.assertIn(A, [item["conversation_key"] for item in topology["reserved_nodes"]])

    async def test_global_supervisor_with_an_earlier_project_memo_remains_reusable(self):
        # Memo and assigned-task history are not project membership. C remains
        # the global Supervisor while A/B retain their own current network.
        self.tabs[2]["conversation_scope"]["node_memo"] = "Previous Browser Bridge review"
        self.tabs[2]["conversation_scope"]["assigned_task"] = "Review earlier Browser Bridge receipts"
        result = await self.call(
            "bct_chain_recipe", action="prepare", work_id=self.work.work_id,
            source_text="Prepare a separate VTL chain without creating another Supervisor.",
        )
        topology = result["state"]["chain_topology_preparation"]
        self.assertEqual([C], [item["conversation_key"] for item in topology["global_supervisor_candidates"]])
        self.assertFalse(topology["required_creation"]["supervisor"])

    async def test_manager_cannot_be_selected_as_worker_even_with_worker_tag(self):
        await self.save()
        self.snapshot["monitor"]["current_nodes"]["items"][1]["roles"] = ["manager", "worker"]
        self.tabs[1]["conversation_scope"]["role_tags"] = ["manager", "worker"]
        result = await self.start()
        self.assertEqual("NETWORK_PREPARATION_REQUIRED", result["status"], result)
        self.assertEqual("DIRECTION_WORKER_CANNOT_BE_MANAGER", result["reason"])
        self.assertEqual([], self.sends())

    async def test_prepare_state_includes_only_the_declared_a_github_ci_notices(self):
        self.store.register_github_run_inbox(
            subscription_id="ci-for-a", repository="owner/repo", run_id=7,
            head_sha="a" * 40, workflow="CI", context={"pr": 1},
            work_id=self.work.work_id, node_id="manager-a", conversation_uuid=A,
            notify_user=True, notify_manager=False, next_step="Review CI.",
            trigger="github-run:7:terminal",
        )
        self.store.register_github_run_inbox(
            subscription_id="ci-for-b", repository="owner/repo", run_id=8,
            head_sha="b" * 40, workflow="CI", context={"pr": 2},
            work_id=self.work.work_id, node_id="manager-b", conversation_uuid=B,
            notify_user=True, notify_manager=False, next_step="Review CI.",
            trigger="github-run:8:terminal",
        )
        self.store.finish_github_run_inbox(
            subscription_id="ci-for-a", state="SUCCESS", conclusion="success",
            url="https://example.invalid/runs/7", error_summary=None,
        )
        self.store.finish_github_run_inbox(
            subscription_id="ci-for-b", state="FAILED", conclusion="failure",
            url="https://example.invalid/runs/8", error_summary="failed job: Core",
        )
        result = await self.call(
            "bct_chain_recipe", action="prepare", work_id=self.work.work_id,
            source_text="Review the completed CI safely.", report_target_conversation_key=A,
        )
        notices = result["state"]["github_ci_notices"]
        self.assertEqual("OK", notices["status"])
        self.assertEqual("REVIEW_CI_RESULT_AND_AUTHOR_NEXT_DIRECTION", notices["next_action"])
        self.assertEqual(["ci-for-a"], [notice["subscription_id"] for notice in notices["notices"]])
        self.assertEqual([], self.ops.calls)

    async def test_saved_direction_exposes_the_next_recipe_stage(self):
        result = await self.save()
        self.assertEqual("OK", result["status"])
        self.assertEqual(
            ["Input R", "State R", "Write Direction R", "Save Direction R"],
            [stage["name"] for stage in result["recipe_progress"]["completed"]],
        )
        self.assertEqual("Prepare Send Direction R", result["recipe_progress"]["next"]["name"])

    async def test_declared_recover_node_recipe_checks_then_rereads_state_before_send(self):
        value = assessment()
        value["node_recovery"] = {"conversation_key": B}
        saved = await self.save(value)
        self.assertEqual("Recover Node R", saved["recipe_progress"]["next"]["name"])
        recovered = await self.call(
            "bct_chain_recipe", action="recover_node", work_id=self.work.work_id,
            direction_id="direction-review",
        )
        self.assertEqual("CHECKED", recovered["status"], recovered)
        self.assertEqual("OK", recovered["recover_node"]["result"])
        self.assertIn(B, json.dumps(recovered["state"]["current_nodes"]))
        self.assertEqual("Prepare Send Direction R", recovered["recipe_progress"]["next"]["name"])
        sent = await self.call(
            "bct_chain_recipe", action="send", work_id=self.work.work_id,
            direction_id="direction-review", task_id="review-task", operation_id="review-operation",
        )
        self.assertEqual("CHECKED", sent["recover_node"]["status"])
        self.assertEqual("STARTED", sent["status"], sent)

    async def test_prepare_send_recipe_is_read_only_and_stops_before_network_apply(self):
        await self.save()
        before = len(self.ops.calls)
        result = await self.call(
            "bct_chain_recipe", action="prepare_send", work_id=self.work.work_id,
            direction_id="direction-review", task_id="review-task", operation_id="review-operation",
        )
        self.assertEqual("READY", result["status"])
        self.assertEqual(2, len(result["targets"]))
        self.assertEqual("Apply Conversation Network R", result["recipe_progress"]["next"]["name"])
        self.assertEqual(before, len(self.ops.calls))

    async def test_apply_network_recipe_exposes_send_as_the_next_stage(self):
        await self.save()
        result = await self.call(
            "bct_chain_recipe", action="apply_network", work_id=self.work.work_id,
            direction_id="direction-review", task_id="review-task", operation_id="review-operation",
        )
        self.assertEqual("READY", result["status"])
        self.assertEqual("Send Direction R", result["recipe_progress"]["next"]["name"])
        self.assertEqual([], result["network_results"])

    async def test_send_direction_recipe_runs_stage_six_from_chain_recipe(self):
        await self.save()
        result = await self.call(
            "bct_chain_recipe", action="send", work_id=self.work.work_id,
            direction_id="direction-review", task_id="review-task", operation_id="review-operation",
        )
        self.assertEqual("STARTED", result["status"], result)
        self.assertEqual(
            ["Input R", "State R", "Write Direction R", "Save Direction R",
             "Recover Node R", "Prepare Send Direction R", "Apply Conversation Network R", "Send Direction R"],
            [stage["name"] for stage in result["recipe_progress"]["completed"]],
        )
        self.assertIsNone(result["recipe_progress"]["next"])
        self.assertEqual(2, len(self.sends()))
        self.assertEqual({B, C}, {
            call["arguments"]["conversation_key"] for call in self.sends()
        })

    async def test_chain_recipe_input_r_accepts_unbound_user_text_without_observing_or_sending(self):
        self.status_reads = 0
        result = await self.call("bct_chain_recipe", source_text="Finish the translation program.")
        self.assertEqual("RECIPE_READY", result["status"], result)
        self.assertEqual({"name": "chain_recipe", "kind": "full_recipe"}, result["recipe"])
        self.assertEqual([
            {"number": 0, "name": "Input R"},
            {"number": 1, "name": "State R"},
            {"number": 2, "name": "Write Direction R", "status": "A_REQUIRED"},
        ], result["completed_stages"])
        self.assertEqual({"number": 2, "name": "Write Direction R", "status": "A_REQUIRED"}, result["next_stage"])
        self.assertEqual([
            "Input R", "State R", "Write Direction R", "Save Direction R",
            "Recover Node R", "Prepare Send Direction R", "Apply Conversation Network R", "Send Direction R",
        ], [stage["name"] for stage in result["recipe_outline"]])
        self.assertEqual(
            ["Check Chain Work", "Read Saved Direction", "Send Delayed Message", "Send Direction Message"],
            [block["name"] for block in result["recipe_outline"][-1]["contains"]],
        )
        self.assertEqual(
            ["Watch Alarm R", "Continuation R"],
            [part["name"] for part in result["recipe_outline"][-1]["after_response"]["contains"]],
        )
        self.assertEqual(
            ["Interpret Next Task", "SELF / MANAGER follow-up"],
            [part["name"] for part in result["recipe_outline"][-1]["after_response"]["contains"][1]["contains"]],
        )
        self.assertEqual("UNCONNECTED", result["input"]["connection"])
        self.assertEqual("CALLER_PROVIDED_TEXT", result["input"]["source_evidence"])
        self.assertEqual(1, self.status_reads)
        self.assertTrue(result["state"]["read_only"])
        self.assertIn("network_comparison", result["state"])
        self.assertEqual("A_DIRECTION_REQUIRED", result["direction"]["status"])
        self.assertEqual("WORK_REQUIRED", result["direction"]["save_gate"]["status"])
        self.assertEqual("bct_set_direction", result["direction"]["save"]["tool"])
        self.assertEqual("save", result["direction"]["save"]["action"])
        self.assertIn("direction_text", result["direction"]["save"]["required"])
        self.assertIn("assessment", result["direction"]["save"]["optional"])
        self.assertNotIn("questions", result["direction"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["authorizes_send"])
        self.assertEqual([], self.ops.calls)

    async def test_save_keeps_ai_answers_optional_and_preserves_original_user_text(self):
        value = assessment()
        del value["answers"]["recovery"]
        missing = await self.save(value)
        self.assertEqual("OK", missing["status"], missing)
        self.assertNotIn("recovery", missing["chain_direction"]["assessment"]["answers"])
        no_answers = assessment()
        del no_answers["answers"]
        saved_without_answers = await self.save(
            no_answers, direction_id="direction-without-answers")
        self.assertEqual("OK", saved_without_answers["status"], saved_without_answers)
        self.assertEqual({}, saved_without_answers["chain_direction"]["assessment"]["answers"])
        invalid_answers = assessment()
        invalid_answers["answers"]["made_up_gate"] = "must not become a new requirement"
        rejected_answers = await self.save(
            invalid_answers, direction_id="direction-invalid-answers")
        self.assertEqual("DIRECTION_ANSWERS_INVALID", rejected_answers["reason"])
        self.assertEqual(
            ["made_up_gate"],
            rejected_answers["assessment_contract"]["answers"]["unexpected_keys"],
        )
        malformed = assessment()
        malformed["targets"][0] = {"node": "N96", "role": "worker", "instruction": "Do the work."}
        rejected = await self.save(malformed)
        self.assertEqual("DIRECTION_TARGET_INVALID", rejected["reason"])
        self.assertEqual(0, rejected["assessment_contract"]["target_diagnostics"][0]["index"])
        self.assertEqual(["conversation_key", "role", "instruction"],
                         rejected["assessment_contract"]["target_diagnostics"][0]["expected_fields"])
        malformed = assessment()
        malformed["targets"][0] = {
            "conversation_key": "N96", "role": "", "instruction": " "}
        rejected = await self.save(malformed)
        self.assertEqual("DIRECTION_TARGET_CONFLICT", rejected["reason"])
        diagnostic = rejected["assessment_contract"]["target_diagnostics"][0]
        self.assertEqual(0, diagnostic["index"])
        self.assertIn("conversation_key must be a lowercase canonical UUID", diagnostic["issues"])
        self.assertIn("role must be a non-empty label of at most 80 characters", diagnostic["issues"])
        self.assertIn(
            "instruction must be a non-empty string of at most 6000 characters",
            diagnostic["issues"],
        )
        saved = await self.save(direction_id="direction-complete-answers")
        self.assertEqual("OK", saved["status"], saved)
        row = saved["chain_direction"]
        self.assertEqual(assessment(), row["assessment"])
        self.assertEqual("CALLER_PROVIDED_TEXT", row["source_evidence"])
        self.assertEqual("Complete the translation program safely.", row["source_text"])
        self.assertEqual([], self.ops.calls)
        replay = await self.save(direction_id="direction-complete-answers")
        self.assertTrue(replay["chain_direction"]["duplicate"])
        self.assertEqual(assessment(), replay["chain_direction"]["assessment"])
        value = assessment()
        value["targets"][0]["instruction"] = "Changed instruction"
        self.assertEqual(
            "CHAIN_DIRECTION_CONFLICT",
            (await self.save(value, direction_id="direction-complete-answers"))["reason"],
        )

    async def test_multi_target_preflight_is_read_only(self):
        await self.save()
        with self.store._readonly() as db:
            before = list(db.iterdump())
        result = await self.start(action="preflight")
        self.assertEqual("READY", result["status"], result)
        self.assertEqual([B, C], [r["conversation_key"] for r in result["targets"]])
        self.assertEqual([], self.ops.calls)
        with self.store._readonly() as db:
            self.assertEqual(before, list(db.iterdump()))
        row = ChainDirectionLedger(self.store).get(direction_id="direction-review")
        self.assertEqual([], row["target_deliveries"])
        self.assertEqual("NOT_PLANNED", row["chain_state"])

    async def test_each_target_receives_own_instruction_and_b_authors_plan_after_send(self):
        await self.save()
        result = await self.start()
        self.assertEqual("STARTED", result["status"], result)
        self.assertEqual(2, len(self.sends()))
        for index, target in enumerate(assessment()["targets"]):
            arm, send = self.ops.calls[index * 2:index * 2 + 2]
            self.assertEqual("send-delayed-message", arm["arguments"]["command"])
            self.assertEqual(target["conversation_key"], send["arguments"]["conversation_key"])
            self.assertEqual(arm["arguments"]["planned_send_text"], send["arguments"]["text"])
            self.assertIn(target["instruction"], send["arguments"]["text"])
            self.assertIn(get_manual_guidance()["text"], send["arguments"]["text"])
            self.assertIn(get_manual_guidance()["manual_sha256"], send["arguments"]["text"])
            self.assertNotIn(assessment()["targets"][1 - index]["instruction"], send["arguments"]["text"])
            child = ChainDirectionLedger(self.store).get(direction_id=result["targets"][index]["direction_id"])
            self.assertEqual("direction-review", child["parent_direction_id"])
            self.assertEqual(target["conversation_key"], child["target_conversation_key"])
            self.assertEqual("CHAIN_STARTED", child["chain_state"])
            plan = ChainExecutionPlanLedger(self.store).save(plan_id=f"plan-{index}", work_id=self.work.work_id,
                direction_id=child["direction_id"], task_id=f"review-task-{index + 1}", generation=1,
                plan_text="B independently chooses steps, parts and verification.")
            self.assertEqual(child["direction_id"], plan["direction_id"])
            self.assertEqual("DIRECTION_DECLARED", result["targets"][index]["execution_path"])
            self.assertEqual(child["direction_id"], result["targets"][index]["chain_direction_id"])
        read = await self.call("bct_get_direction", work_id=self.work.work_id, direction_id="direction-review")
        self.assertEqual(2, len(read["chain_direction"]["target_deliveries"]))
        repeat = await self.start()
        self.assertEqual(["ALREADY_STARTED", "ALREADY_STARTED"], [r["status"] for r in repeat["targets"]])
        self.assertEqual(2, len(self.sends()))

    async def test_declared_independent_derived_task_starts_while_blocker_is_deferred(self):
        value = assessment()
        value["derived_tasks"] = [
            {
                "task_id": "worker-fix", "classification": "INDEPENDENT",
                "summary": "Fix the independent regression.", "depends_on": [],
                "target_conversation_key": B, "mutable_scopes": ["src/fix.py"],
            },
            {
                "task_id": "environment-blocker", "classification": "BLOCKED",
                "summary": "Wait for the separately recorded environment prerequisite.",
                "depends_on": [], "target_conversation_key": "", "mutable_scopes": [],
            },
        ]
        await self.save(value)
        result = await self.start()
        self.assertEqual("STARTED", result["status"], result)
        self.assertEqual([B], [entry["arguments"]["conversation_key"] for entry in self.sends()])
        self.assertEqual("MANAGER_DECLARED", result["derived_dispatch"]["classification"])
        self.assertEqual(["environment-blocker", ""], [
            item["task_id"] for item in result["derived_dispatch"]["deferred"]
        ])

    async def test_moved_tab_is_reacquired_by_same_uuid(self):
        await self.save()
        self.tabs[1].update(tab_id=25, window_id=26)
        self.snapshot["monitor"]["current_nodes"]["items"][1].update(tab_id=25, window_id=26)
        result = await self.start(target_conversation_key=B)
        self.assertEqual("STARTED", result["status"], result)
        self.assertEqual(25, self.sends()[0]["arguments"]["tab_id"])
        self.assertEqual(26, self.sends()[0]["arguments"]["window_id"])

    async def test_manual_change_keeps_recorded_instruction_and_no_resend(self):
        await self.save()
        self.ops.unknown_target = B
        first = await self.start()
        sent_texts = [s["arguments"]["text"] for s in self.sends()]
        with patch("bct.component_library.get_manual_guidance", side_effect=AssertionError("Must reuse recorded text")):
            result = await self.start(operation_id="another-prefix")
        self.assertEqual(["RECEIPT_REVIEW_REQUIRED", "ALREADY_STARTED"], [t["status"] for t in result["targets"]])
        self.assertEqual(sent_texts, [s["arguments"]["text"] for s in self.sends()])
        self.assertEqual("PARTIAL", first["status"])
        self.assertEqual("review-task-1", result["targets"][0]["task_id"])
        self.assertEqual("review-operation-1", result["targets"][0]["operation_id"])

    async def test_legacy_recorded_child_without_manual_survives_upgrade(self):
        await self.save()
        ledger = ChainDirectionLedger(self.store)
        parent = ledger.get(direction_id="direction-review")
        from bct.chain_direction import target_direction_id
        target = assessment()["targets"][0]
        child_id = target_direction_id(parent, target)
        ledger.save(direction_id=child_id, work_id=self.work.work_id, source_kind="USER",
                    decision="NEW_TASK", direction_text="Old exact instruction, no new manual.",
                    parent_direction_id=parent["direction_id"], target_conversation_key=B)
        with patch("bct.component_library.get_manual_guidance", side_effect=AssertionError("Old text must be immutable")):
            result = await self.start(target_conversation_key=B)
        self.assertEqual("STARTED", result["status"], result)
        self.assertTrue(self.sends()[0]["arguments"]["text"].startswith("Old exact instruction, no new manual."))
        self.assertNotIn("공통 설명서의 노드 안내", self.sends()[0]["arguments"]["text"])

    async def test_missing_manual_blocks_new_instruction_before_effects(self):
        await self.save()
        with patch("bct.component_library.get_manual_guidance", return_value={"status": "UNAVAILABLE"}):
            result = await self.start()
        self.assertEqual("MANUAL_GUIDANCE_UNAVAILABLE", result["reason"])
        self.assertEqual([], self.ops.calls)

    async def test_recorded_child_with_wrong_parent_is_not_reused(self):
        await self.save()
        ledger = ChainDirectionLedger(self.store)
        parent = ledger.get(direction_id="direction-review")
        from bct.chain_direction import target_direction_id
        ledger.save(direction_id=target_direction_id(parent, assessment()["targets"][0]),
                    work_id=self.work.work_id, source_kind="USER", decision="NEW_TASK",
                    direction_text="Wrong parent instruction", parent_direction_id="different-parent",
                    target_conversation_key=B)
        result = await self.start()
        self.assertEqual("DIRECTION_TARGET_RECORD_MISMATCH", result["reason"])
        self.assertEqual([], self.ops.calls)

    async def test_supervisor_role_drift_between_targets_blocks_that_target(self):
        await self.save()
        self.ops.after_send = lambda _: self.tabs[2]["conversation_scope"].update(role_tags=[])
        result = await self.start()
        self.assertEqual("PARTIAL", result["status"], result)
        self.assertEqual("TARGET_DISPATCH", result["stage"])
        self.assertEqual(1, len(self.sends()))
        self.assertEqual("DIRECTION_SUPERVISOR_ROLE_NOT_CONFIRMED", result["targets"][1]["reason"])

    async def test_busy_second_target_reports_dispatch_stage_without_resending_first(self):
        await self.save()
        self.ops.after_send = lambda _: self.snapshot["monitor"]["current_nodes"]["items"][2].update(generating=True)
        result = await self.start()
        self.assertEqual("PARTIAL", result["status"], result)
        self.assertEqual("TARGET_DISPATCH", result["stage"])
        self.assertFalse(result["all_targets_started"])
        self.assertEqual("TARGET_BUSY", result["targets"][1]["status"])
        self.assertEqual(1, len(self.sends()))
        replay = await self.start()
        self.assertEqual("ALREADY_STARTED", replay["targets"][0]["status"])
        self.assertEqual("TARGET_BUSY", replay["targets"][1]["status"])
        self.assertEqual(1, len(self.sends()))

    async def test_missing_supervisor_blocks_initial_chain_dispatch(self):
        await self.save()
        self.tabs[2]["presence"] = "CLOSED"
        result = await self.start()
        self.assertEqual("NETWORK_PREPARATION_REQUIRED", result["status"], result)
        self.assertEqual("DIRECTION_ATTACHMENT_NOT_UNIQUE_OR_OPEN", result["reason"])
        self.assertEqual([], self.sends())

    async def test_prepared_network_updates_use_existing_setter_before_sending(self):
        self.tabs[0]["conversation_scope"].update(scope_name="", role_tags=[])
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": A,
            "display_name": "Manager A", "scope_name": "Project", "role_tags": ["manager"],
            "expected_scope_id": "", "expected_role_tags_sha256": role_tags_sha256([])}]
        self.assertEqual("OK", (await self.save(value))["status"])
        self.assertEqual("NETWORK_PREPARATION_REQUIRED", (await self.start(action="preflight"))["status"])
        self.assertEqual([], self.ops.calls)
        result = await self.start()
        self.assertEqual("STARTED", result["status"], result)
        self.assertEqual("conversation_network_update", self.ops.calls[0]["capability"])
        self.assertEqual(2, len(self.sends()))
        await self.start()
        self.assertEqual(1, len(self.ops.network_receipts))
        self.assertEqual(2, len(self.sends()))

    async def test_invalid_network_arguments_fail_during_apply(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": "N1"}]
        self.assertEqual("OK", (await self.save(value))["status"])
        self.assertEqual("INVALID_REQUEST", (await self.start(action="preflight"))["status"])
        self.assertEqual([], self.ops.calls)

    async def test_missing_initial_worker_blocks_dispatch_after_network_update(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": A,
            "display_name": "A", "scope_name": "Project", "role_tags": ["manager"],
            "expected_scope_id": "", "expected_role_tags_sha256": role_tags_sha256([])}]
        await self.save(value)
        self.tabs[1]["presence"] = "CLOSED"
        result = await self.start()
        self.assertEqual("NETWORK_PREPARATION_REQUIRED", result["status"], result)
        self.assertEqual("AFTER_NETWORK_EFFECTS", result["stage"])
        self.assertTrue(result["network_preparation_applied"])
        self.assertEqual([], self.sends())

    async def test_initial_worker_closing_during_network_preparation_blocks_dispatch(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": A,
            "display_name": "A", "scope_name": "Project", "role_tags": ["manager"],
            "expected_scope_id": "", "expected_role_tags_sha256": role_tags_sha256([])}]
        await self.save(value)
        self.ops.after_network = lambda _: self.tabs[1].update(presence="CLOSED")
        result = await self.start()
        self.assertEqual("NETWORK_PREPARATION_REQUIRED", result["status"], result)
        self.assertEqual("AFTER_NETWORK_EFFECTS", result["stage"])
        self.assertTrue(result["network_preparation_applied"])
        self.assertEqual("APPLIED", result["network_results"][0]["outcome"])
        self.assertEqual([], self.sends())

    async def test_unknown_keeps_original_ids_and_is_not_resent(self):
        await self.save()
        self.ops.unknown_target = B
        result = await self.start()
        self.assertEqual("PARTIAL", result["status"], result)
        self.assertEqual(2, len(self.sends()))
        replay = await self.start(operation_id="different-prefix")
        self.assertEqual("TARGET_DISPATCH", replay["stage"])
        self.assertEqual("RECEIPT_REVIEW_REQUIRED", replay["targets"][0]["status"], replay)
        self.assertEqual("review-operation-1", replay["targets"][0]["operation_id"])
        self.assertEqual("ALREADY_STARTED", replay["targets"][1]["status"])
        self.assertEqual(2, len(self.sends()))

    async def test_oversized_composed_text_fails_before_network_or_send_effects(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": A,
            "display_name": "A", "scope_name": "Project", "role_tags": ["manager"],
            "expected_scope_id": "", "expected_role_tags_sha256": role_tags_sha256([])}]
        await self.save(value, direction_text="x" * 11990)
        self.assertEqual("INVALID_REQUEST", (await self.start())["status"])
        self.assertEqual([], self.ops.calls)

    async def test_caller_cannot_override_recorded_target_or_instruction(self):
        await self.save()
        self.assertEqual("DIRECTION_TARGET_NOT_DECLARED", (await self.start(target_conversation_key=key("d")))["reason"])
        self.assertEqual("DIRECTION_USES_RECORDED_IDENTITIES", (await self.start(target_tab_id=50))["reason"])
        self.assertEqual("DIRECTION_USES_RECORDED_IDENTITIES", (await self.start(instruction="Different"))["reason"])
        self.assertEqual([], self.ops.calls)

    async def test_exact_return_reenters_same_questions_with_provenance(self):
        ledger = DurableWatchLedger(self.store)
        ledger.prearm_task(task_id="returned-b", work_id=self.work.work_id, principal_id="bct-mcp-local",
            assignment_epoch=1, instance_id="a" * 32, conversation_key=B, manager_conversation_key=A,
            manager_instance_id="a" * 32, baseline={"responseTurnCount": 1, "generating": True,
                "responseTurnKey": "old", "responseSha256": "a" * 64,
                "latestUserTurnKey": "source-user", "latestUserSha256": "b" * 64}, registration_receipt="arm-b")
        watch = Watch("returned-b", 1, B, "task:returned-b:1", "arm-b")
        outcome = SendDelayedMessageRunner(ledger, read_response=lambda _: {
            "conversation_key": B, "response_turn_id": watch.response_turn_id,
            "response_turn_key": "response-b", "response_sha256": "c" * 64,
            "response_text": "Tests passed.\nNEXT TASK — MANAGER\nAsk Supervisor to review release.",
            "response_complete": True, "input_ready": True}, send_message=lambda *_: "return-b"
        ).poll_once(watch, manager_conversation_key=A)
        self.assertEqual("RETURNED_TO_MANAGER", outcome.status)
        recipe_return = await self.call("bct_chain_recipe", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="returned-b", source_generation=1)
        self.assertEqual("RECIPE_READY", recipe_return["status"], recipe_return)
        self.assertEqual("EXACT_RETURN_BOUND", recipe_return["input"]["connection"])
        self.assertEqual("c" * 64, recipe_return["input"]["source_result_sha256"])
        result = await self.call("bct_chain_message", action="prepare", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="returned-b", source_generation=1)
        self.assertEqual("RECIPE_READY", result["status"], result)
        self.assertEqual("c" * 64, result["input"]["source_result_sha256"])
        self.assertEqual("EXACT_RETURN_BOUND", result["input"]["connection"])
        self.assertIn("Tests passed.", json.dumps(result["input"]["source_return"]))
        self.assertEqual("NOT_DECLARED", result["state"]["return_execute_plan_check"]["status"])
        self.assertNotIn("questions", result["direction"])
        invalid = await self.call("bct_chain_message", action="prepare", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="missing", source_generation=1)
        self.assertEqual("CHAIN_DIRECTION_RETURN_NOT_EXACT", invalid["reason"])
        self.assertEqual([], self.ops.calls)

    async def test_exact_return_state_includes_its_plan_check_without_writing(self):
        directions = ChainDirectionLedger(self.store)
        directions.save(direction_id="return-direction", work_id=self.work.work_id,
                        source_kind="USER", decision="NEW_TASK", direction_text="Bounded task.")
        directions.plan_chain(direction_id="return-direction", work_id=self.work.work_id,
                              task_id="returned-plan", operation_id="return-plan")
        directions.mark_chain_started(direction_id="return-direction", work_id=self.work.work_id,
                                      task_id="returned-plan", operation_id="return-plan")
        plans = ChainExecutionPlanLedger(self.store)
        plans.save(plan_id="return-plan-id", work_id=self.work.work_id,
                   direction_id="return-direction", task_id="returned-plan", generation=1,
                   plan_text="1. Inspect.\n2. Verify.")
        ledger = DurableWatchLedger(self.store)
        ledger.prearm_task(task_id="returned-plan", work_id=self.work.work_id,
            principal_id="bct-mcp-local", assignment_epoch=1, instance_id="a" * 32,
            conversation_key=B, manager_conversation_key=A, manager_instance_id="a" * 32,
            baseline={"responseTurnCount": 1, "generating": True, "responseTurnKey": "old",
                      "responseSha256": "a" * 64, "latestUserTurnKey": "source-user",
                      "latestUserSha256": "b" * 64}, registration_receipt="arm-plan",
            execution_path="DIRECTION_DECLARED", chain_direction_id="return-direction")
        watch = Watch("returned-plan", 1, B, "task:returned-plan:1", "arm-plan")
        outcome = SendDelayedMessageRunner(ledger, read_response=lambda _: {
            "conversation_key": B, "response_turn_id": watch.response_turn_id,
            "response_turn_key": "response-plan", "response_sha256": "d" * 64,
            "response_text": "PLAN REVISION: 0\nPROGRESS: 2/2 — complete\nDone.\nNEXT TASK — MANAGER\nReturn the evidence to A.",
            "response_complete": True, "input_ready": True}, send_message=lambda *_: "return-plan"
        ).poll_once(watch, manager_conversation_key=A)
        self.assertEqual("RETURNED_TO_MANAGER", outcome.status)

        result = await self.call("bct_chain_recipe", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="returned-plan", source_generation=1)
        self.assertEqual("RECIPE_READY", result["status"], result)
        card = result["state"]["return_execute_plan_check"]
        self.assertEqual("RECORDED", card["status"])
        self.assertEqual("return-direction", card["chain"]["direction_id"])
        self.assertEqual("return-plan-id", card["plan"]["plan_id"])
        self.assertEqual(2, card["return_check"]["completed_steps"])
        self.assertEqual([], card["return_check"]["issues"])

        saved = await self.call(
            "bct_chain_recipe", action="save", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="returned-plan", source_generation=1,
            direction_id="return-to-supervisor", decision="NEW_TASK",
            direction_text="Have the declared targets review the returned evidence.",
            assessment=assessment(),
        )
        self.assertEqual("OK", saved["status"], saved)
        legacy_route = await self.call(
            "bct_prepare_supervisor_chain", work_id=self.work.work_id,
            direction_id="return-to-supervisor",
        )
        self.assertEqual("INVALID_REQUEST", legacy_route["status"], legacy_route)
        self.assertEqual("SUPERVISOR_ROUTE_LEGACY_COMPATIBILITY_ONLY", legacy_route["reason"])
        started = await self.call(
            "bct_chain_recipe", action="send", work_id=self.work.work_id,
            direction_id="return-to-supervisor", task_id="supervisor-review",
            operation_id="supervisor-review-operation",
        )
        self.assertEqual("STARTED", started["status"], started)
        self.assertNotIn("supervisor_route", started)
        self.assertEqual({B, C}, {
            call["arguments"]["conversation_key"] for call in self.sends()
        })

    async def test_foreign_work_cannot_save_or_start(self):
        self.store.create_work(Work("foreign-work", "another user", (), frozenset({"browser"}), "foreign", 1))
        self.assertEqual("NOT_FOUND", (await self.save(work_id="foreign-work"))["status"])
        # Work ownership is now an observation at Chain Message entry.  The
        # separate saved-Direction binding still rejects a non-matching Work.
        self.assertEqual("INVALID_REQUEST", (await self.start(work_id="foreign-work"))["status"])
        self.assertEqual([], self.ops.calls)


class DirectionAssessmentValidationTests(unittest.TestCase):
    def test_duplicate_target_conflicts_but_roles_are_free_labels(self):
        value = assessment()
        value["targets"].append(copy.deepcopy(value["targets"][0]))
        with self.assertRaises(ValueError):
            validate_direction_assessment(value, decision="NEW_TASK")
        value = assessment()
        value["targets"][0]["role"] = "deployer"
        value.pop("supervisor_conversation_key")
        with self.assertRaisesRegex(ValueError, "SUPERVISOR_CONVERSATION_KEY_REQUIRED"):
            validate_direction_assessment(value, decision="NEW_TASK")
        value = assessment()
        value["targets"][0]["role"] = "deployer"
        self.assertEqual("deployer", validate_direction_assessment(
            value, decision="NEW_TASK")["targets"][0]["role"])

    def test_terminal_direction_may_not_carry_effects(self):
        with self.assertRaisesRegex(ValueError, "TERMINAL_HAS_ACTIONS"):
            validate_direction_assessment(assessment(), decision="COMPLETE")

    def test_stale_cached_or_duplicate_attachment_rejected(self):
        cases = []
        value = snapshot()
        value["monitor"]["current_nodes"]["observation"]["state"] = "STALE"
        cases.append(value)
        value = snapshot()
        value["monitor"]["rcc"]["instances"][0]["cached"] = True
        cases.append(value)
        value = snapshot()
        tabs = value["monitor"]["rcc"]["instances"][0]["tabs"]
        tabs.append(copy.deepcopy(tabs[1]))
        cases.append(value)
        for value in cases:
            with self.assertRaises(ValueError):
                resolve_direction_target(snapshot=value, conversation_key=B)

    def test_migration_keeps_legacy_direction_identity_and_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "db.sqlite")
            ledger = ChainDirectionLedger(store)
            ledger.save(direction_id="old-chain-direction", work_id="old-work", source_kind="USER",
                        decision="NEW_TASK", direction_text="Existing instruction")
            ledger.plan_chain(direction_id="old-chain-direction", work_id="old-work", task_id="old-task", operation_id="old-op")
            # Reconstruct the pre-migration schema, not a new blank database.
            with store.transaction() as db:
                for column in ["assessment_json", "source_text", "parent_direction_id", "target_conversation_key"]:
                    db.execute(f"ALTER TABLE chain_directions DROP COLUMN {column}")
            restored = ChainDirectionLedger(store).get(direction_id="old-chain-direction")
            self.assertEqual("old-op", restored["chain_operation_id"])
            self.assertEqual("CHAIN_PLANNED", restored["chain_state"])
            self.assertEqual("Existing instruction", restored["direction_text"])
            self.assertEqual({}, restored["assessment"])


if __name__ == "__main__":
    unittest.main()
