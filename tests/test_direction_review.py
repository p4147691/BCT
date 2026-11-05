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
        "manager_conversation_key": A, "supervisor_conversation_key": C,
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
                      "tab_id": number, "window_id": 10, "generating": False})
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
        self.mcp = build_mcp(SimpleNamespace(operations=self.ops, store=self.store),
                             compact_catalogue=True, status_provider=lambda: copy.deepcopy(self.snapshot))
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
        self.assertEqual("DIRECTION_REQUIRED", result["status"], result)
        self.assertEqual(10, len(result["questions"]))
        self.assertIn("사용자에게 이 질문지를 넘기지 않는다", result["instructions_for_a"])
        self.assertIn("Historical network", json.dumps(result["conversation_network"]))
        self.assertIn(A, json.dumps(result["conversation_network"]))
        self.assertIn("bct_set_direction", result["available_tools"])
        self.assertEqual("bct_capabilities", result["resource_discovery"]["tool"])
        self.assertEqual(get_manual_guidance(), result["manual_guidance"])
        self.assertIn("bct_capabilities", result["instructions_for_a"])
        self.assertIsNone(result["reality"]["work"])
        self.assertFalse(result["authorizes_send"])
        self.assertEqual("CALLER_PROVIDED_TEXT", result["source_evidence"])
        self.assertEqual([], self.ops.calls)
        with self.store._readonly() as db:
            self.assertEqual([tuple(r) for r in before], [tuple(r) for r in db.execute("SELECT name FROM sqlite_master ORDER BY name")])

    async def test_save_requires_ai_answers_and_preserves_original_user_text(self):
        value = assessment()
        del value["answers"]["recovery"]
        self.assertEqual("DIRECTION_ANSWERS_REQUIRED", (await self.save(value))["reason"])
        saved = await self.save()
        self.assertEqual("OK", saved["status"], saved)
        row = saved["chain_direction"]
        self.assertEqual(assessment(), row["assessment"])
        self.assertEqual("CALLER_PROVIDED_TEXT", row["source_evidence"])
        self.assertEqual("Complete the translation program safely.", row["source_text"])
        self.assertEqual([], self.ops.calls)
        replay = await self.save()
        self.assertTrue(replay["chain_direction"]["duplicate"])
        self.assertEqual(assessment(), replay["chain_direction"]["assessment"])
        value = assessment()
        value["targets"][0]["instruction"] = "Changed instruction"
        self.assertEqual("CHAIN_DIRECTION_CONFLICT", (await self.save(value))["reason"])

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
        read = await self.call("bct_get_direction", work_id=self.work.work_id, direction_id="direction-review")
        self.assertEqual(2, len(read["chain_direction"]["target_deliveries"]))
        repeat = await self.start()
        self.assertEqual(["ALREADY_STARTED", "ALREADY_STARTED"], [r["status"] for r in repeat["targets"]])
        self.assertEqual(2, len(self.sends()))

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

    async def test_roles_are_rechecked_between_targets(self):
        await self.save()
        self.ops.after_send = lambda _: self.tabs[2]["conversation_scope"].update(role_tags=[])
        result = await self.start()
        self.assertEqual("PARTIAL", result["status"], result)
        self.assertEqual("TARGET_DISPATCH", result["stage"])
        self.assertEqual(1, len(self.sends()))
        self.assertEqual("DIRECTION_SUPERVISOR_PREPARATION_REQUIRED", result["targets"][1]["reason"])

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

    async def test_absent_supervisor_does_not_guess_or_send(self):
        await self.save()
        self.tabs[2]["presence"] = "CLOSED"
        result = await self.start()
        self.assertEqual("NETWORK_PREPARATION_REQUIRED", result["status"], result)
        self.assertEqual([], self.ops.calls)

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

    async def test_invalid_network_arguments_fail_during_save(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": "N1"}]
        self.assertEqual("INVALID_REQUEST", (await self.save(value))["status"])
        self.assertEqual([], self.ops.calls)

    async def test_closed_target_blocks_before_any_network_effect(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": A,
            "display_name": "A", "scope_name": "Project", "role_tags": ["manager"],
            "expected_scope_id": "", "expected_role_tags_sha256": role_tags_sha256([])}]
        await self.save(value)
        self.tabs[1]["presence"] = "CLOSED"
        result = await self.start()
        self.assertEqual("BEFORE_NETWORK_EFFECTS", result["stage"], result)
        self.assertFalse(result["network_preparation_applied"])
        self.assertEqual([], self.ops.calls)

    async def test_target_closing_during_preparation_keeps_partial_effect_receipt(self):
        value = assessment()
        value["network_updates"] = [{"operation": "node-info-set", "conversation_key": A,
            "display_name": "A", "scope_name": "Project", "role_tags": ["manager"],
            "expected_scope_id": "", "expected_role_tags_sha256": role_tags_sha256([])}]
        await self.save(value)
        self.ops.after_network = lambda _: self.tabs[1].update(presence="CLOSED")
        result = await self.start()
        self.assertEqual("AFTER_NETWORK_EFFECTS", result["stage"], result)
        self.assertTrue(result["network_preparation_applied"])
        self.assertFalse(result["all_targets_started"])
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
        SendDelayedMessageRunner(ledger, read_response=lambda _: {
            "conversation_key": B, "response_turn_id": watch.response_turn_id,
            "response_turn_key": "response-b", "response_sha256": "c" * 64,
            "response_text": "Tests passed.\nNEXT TASK — MANAGER\nAsk Supervisor to review release.",
            "response_complete": True, "input_ready": True}, send_message=lambda *_: "return-b"
        ).poll_once(watch, manager_conversation_key=A)
        result = await self.call("bct_chain_message", action="prepare", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="returned-b", source_generation=1)
        self.assertEqual("DIRECTION_REQUIRED", result["status"], result)
        self.assertEqual("c" * 64, result["source_result_sha256"])
        self.assertEqual("VERIFIED_MANAGER_RETURN", result["source_evidence"])
        self.assertIn("Tests passed.", json.dumps(result["source_return"]))
        self.assertEqual(10, len(result["questions"]))
        invalid = await self.call("bct_chain_message", action="prepare", work_id=self.work.work_id,
            source_kind="MANAGER_RETURN", source_task_id="missing", source_generation=1)
        self.assertEqual("CHAIN_DIRECTION_RETURN_NOT_EXACT", invalid["reason"])
        self.assertEqual([], self.ops.calls)

    async def test_foreign_work_cannot_save_or_start(self):
        self.store.create_work(Work("foreign-work", "another user", (), frozenset({"browser"}), "foreign", 1))
        self.assertEqual("NOT_FOUND", (await self.save(work_id="foreign-work"))["status"])
        self.assertEqual("BLOCKED", (await self.start(work_id="foreign-work"))["status"])
        self.assertEqual([], self.ops.calls)


class DirectionAssessmentValidationTests(unittest.TestCase):
    def test_manager_supervisor_and_duplicate_target_conflicts(self):
        for mutate in [lambda v: v.update(supervisor_conversation_key=A),
                       lambda v: v["targets"].append(copy.deepcopy(v["targets"][0])),
                       lambda v: v["targets"][0].update(conversation_key=A)]:
            value = assessment()
            mutate(value)
            with self.assertRaises(ValueError):
                validate_direction_assessment(value, decision="NEW_TASK")

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
