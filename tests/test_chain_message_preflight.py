"""No-browser-effect acceptance for Chain Message Work/continuation preflight."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.chain_message_preflight import (
    EXPLICIT_NEXT_TASK_SUFFIX,
    check_chain_work,
    prepare_chain_instruction,
)
from bct.core.models import Work
from bct.chain_direction import ChainDirectionLedger
from bct.core.store import Store
from bct.send_delayed_message import InstructionError, extract_next_instruction
from bct.mcp_server import build_mcp


WORKER = "b" * 8 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 4 + "-" + "b" * 12
MANAGER = "c" * 8 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 4 + "-" + "c" * 12


class Applied:
    def as_dict(self):
        return {"state": "FINISHED", "outcome": "APPLIED", "evidence": {"command": "fixture"}}


class NoBrowserEffects:
    capabilities = ("browser",)

    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return Applied()


class ChainMessagePreflightTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(lambda: self.tmp.cleanup())
        self.store = Store(Path(self.tmp.name) / "db.sqlite")
        self.operations = NoBrowserEffects()
        self.work_id = "preflight-work"
        self.mcp = build_mcp(
            SimpleNamespace(operations=self.operations, store=self.store),
            compact_catalogue=True,
        )

    def register(self, *, actions=frozenset({"browser"}), owner="bct-mcp-local", state="ACTIVE"):
        return self.store.create_work(Work(
            self.work_id, "strict fixture", (self.tmp.name,),
            actions, owner, 1, state,
        ))

    def args(self, **kwargs):
        result = {
            "work_id": self.work_id, "task_id": "preflight-task",
            "operation_id": "preflight-op", "action": "preflight",
            "instance_id": "fixed-instance", "session_id": "a" * 32,
            "target_tab_id": 19, "target_window_id": 42,
            "target_conversation_key": WORKER,
            "origin_conversation_key": MANAGER,
            "instruction": "Implement and verify an owned isolated change.",
        }
        return {**result, **kwargs}

    async def call(self, **kwargs):
        _, result = await self.mcp.call_tool("bct_chain_message", self.args(**kwargs))
        return result

    async def test_missing_browser_action_blocks_without_upgrade_or_send(self):
        self.register(actions=frozenset({"read", "execute", "write", "test"}))
        before = self.store.get_work(self.work_id)
        preflight = await self.call()
        self.assertEqual("BLOCKED", preflight["status"])
        self.assertEqual("CHAIN_MESSAGE_BROWSER_ACTION_REQUIRED", preflight["reason"])
        self.assertEqual("browser", preflight["required_action"])
        rejected = await self.call(action="start")
        self.assertEqual("BLOCKED", rejected["status"])
        self.assertEqual([], self.operations.calls)
        after = self.store.get_work(self.work_id)
        self.assertEqual(before.actions, after.actions)
        self.assertNotIn("browser", after.actions)

    async def test_inactive_or_foreign_work_blocks_before_side_effects(self):
        self.register(state="CLOSED")
        self.assertEqual(
            "CHAIN_MESSAGE_WORK_NOT_ACTIVE", (await self.call())["reason"]
        )
        self.assertEqual([], self.operations.calls)
        self.assertEqual(frozenset({"browser"}), self.store.get_work(self.work_id).actions)

    async def test_missing_work_fails_closed_not_auto_created(self):
        response = await self.call()
        self.assertEqual("BLOCKED", response["status"])
        self.assertEqual("CHAIN_MESSAGE_WORK_NOT_FOUND", response["reason"])
        self.assertEqual([], self.operations.calls)

    async def test_preflight_is_read_only_and_reports_exact_effective_digest(self):
        self.register()
        original = "One exact A authored instruction.  "
        preflight = await self.call(
            instruction=original,
            continuation_output_contract="explicit-next-task-v1",
        )
        self.assertEqual("READY", preflight["status"])
        self.assertEqual("NONE_READ_ONLY", preflight["effects"])
        self.assertFalse(preflight["authorizes_send"])
        self.assertEqual("browser", preflight["required_action"])
        self.assertTrue(preflight["contract_appended"])
        self.assertEqual(EXPLICIT_NEXT_TASK_SUFFIX, preflight["contract_suffix"])
        expected = original + "\n\n" + EXPLICIT_NEXT_TASK_SUFFIX
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(),
                         preflight["outgoing_instruction_sha256"])
        self.assertEqual(len(expected), preflight["outgoing_instruction_characters"])
        self.assertEqual([], self.operations.calls)
        # The real node-recovery guard stays enforced in production; only
        # the stub's missing RCC node is mocked for this no-send contract test.
        with patch("bct.node_recovery.NodeRecoveryLedger.assert_send_allowed", return_value=None):
            start = await self.call(
                action="start", instruction=original,
                continuation_output_contract="explicit-next-task-v1",
            )
        self.assertEqual("WATCHING", start["status"])
        self.assertEqual(2, len(self.operations.calls))
        arm, send = self.operations.calls
        self.assertEqual(expected, arm["arguments"]["planned_send_text"])
        self.assertEqual(expected, send["arguments"]["text"])
        self.assertEqual("send-delayed-message", arm["arguments"]["command"])
        self.assertEqual("send-message", send["arguments"]["command"])
        self.assertEqual("DIRECT_EXACT_TARGET", arm["arguments"]["execution_path"])
        self.assertEqual("DIRECT_EXACT_TARGET", start["execution_path"])

    async def test_default_start_is_exact_backward_compatible_prompt(self):
        self.register()
        original = "Exact task with a preexisting newline\n"
        preflight = await self.call(instruction=original)
        self.assertEqual("READY", preflight["status"])
        self.assertFalse(preflight["contract_appended"])
        self.assertEqual("", preflight["contract_suffix"])
        with patch("bct.node_recovery.NodeRecoveryLedger.assert_send_allowed", return_value=None):
            result = await self.call(action="start", instruction=original)
        self.assertEqual("WATCHING", result["status"])
        self.assertEqual(original, self.operations.calls[0]["arguments"]["planned_send_text"])
        self.assertEqual(original, self.operations.calls[1]["arguments"]["text"])

    async def test_invalid_contract_and_size_fail_before_reservation(self):
        self.register()
        self.assertEqual(
            "CHAIN_MESSAGE_OUTPUT_CONTRACT_INVALID",
            (await self.call(action="start", continuation_output_contract="automatic-followup"))["reason"],
        )
        self.assertEqual(
            "CHAIN_MESSAGE_OUTPUT_CONTRACT_TOO_LONG",
            (await self.call(action="start", instruction="x" * 11995,
                             continuation_output_contract="explicit-next-task-v1"))["reason"],
        )
        self.assertEqual([], self.operations.calls)

    async def test_direction_preflight_never_plans_or_modifies_a_direction(self):
        self.register()
        ledger = ChainDirectionLedger(self.store)
        original = "Apply the exact A-authored direction."
        ledger.save(
            direction_id="direction-preview", work_id=self.work_id,
            source_kind="USER", decision="NEW_TASK", direction_text=original,
        )
        preview = await self.call(
            instruction="", chain_direction_id="direction-preview",
            continuation_output_contract="explicit-next-task-v1",
        )
        self.assertEqual("READY", preview["status"])
        self.assertEqual("NOT_PLANNED", ledger.get(direction_id="direction-preview")["chain_state"])
        self.assertEqual([], self.operations.calls)
        with patch("bct.node_recovery.NodeRecoveryLedger.assert_send_allowed", return_value=None):
            started = await self.call(
                action="start", instruction="", chain_direction_id="direction-preview",
                continuation_output_contract="explicit-next-task-v1",
            )
        self.assertEqual("WATCHING", started["status"])
        self.assertEqual("CHAIN_STARTED", ledger.get(direction_id="direction-preview")["chain_state"])
        self.assertEqual(original, ledger.get(direction_id="direction-preview")["direction_text"])
        self.assertEqual(original + "\n\n" + EXPLICIT_NEXT_TASK_SUFFIX,
                         self.operations.calls[1]["arguments"]["text"])

    async def test_preflight_does_not_create_missing_direction_tables(self):
        self.register()
        result = await self.call(chain_direction_id="missing-direction")
        self.assertEqual("INVALID_REQUEST", result["status"])
        self.assertEqual("CHAIN_DIRECTION_READ_UNAVAILABLE", result["reason"])
        with self.store._readonly() as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='chain_directions'"
            ).fetchone())
        self.assertEqual([], self.operations.calls)

    async def test_blocked_work_does_not_plan_existing_direction(self):
        self.register(actions=frozenset({"read"}))
        ledger = ChainDirectionLedger(self.store)
        ledger.save(
            direction_id="existing-direction", work_id=self.work_id,
            source_kind="USER", decision="NEW_TASK",
            direction_text="Only an explicitly authorized Work may dispatch.",
        )
        result = await self.call(
            action="start", instruction="", chain_direction_id="existing-direction",
        )
        self.assertEqual("CHAIN_MESSAGE_BROWSER_ACTION_REQUIRED", result["reason"])
        self.assertEqual("NOT_PLANNED", ledger.get(direction_id="existing-direction")["chain_state"])
        self.assertEqual([], self.operations.calls)

    async def test_pure_contract_never_guesses_response_route(self):
        self.assertEqual(
            "CHAIN_MESSAGE_BROWSER_ACTION_REQUIRED",
            check_chain_work(Work("w", "x", (), frozenset({"orchestrate"}),
                                  "bct-mcp-local"), principal_id="bct-mcp-local")["reason"],
        )
        self.assertEqual(
            "CHAIN_MESSAGE_WORK_OWNER_MISMATCH",
            check_chain_work(Work("w", "x", (), frozenset({"browser"}), "foreign"),
                             principal_id="bct-mcp-local")["reason"],
        )
        with self.assertRaises(InstructionError):
            extract_next_instruction("Done. The implementation is complete.")
        full = prepare_chain_instruction("Do work", output_contract="explicit-next-task-v1")
        self.assertIn("NEXT TASK — MANAGER:", full["instruction"])
        self.assertIn("NEXT TASK — SELF:", full["instruction"])


if __name__ == "__main__":
    unittest.main()
