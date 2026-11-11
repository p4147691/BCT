"""A new user Chain Recipe must not persist a NEW_TASK with no targets."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.chain_direction import ChainDirectionLedger
from bct.core.models import Work
from bct.core.store import Store
from bct.mcp_server import build_mcp


class Operations:
    capabilities = ("browser",)


class NewTaskAssessmentPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        self.store.create_work(Work(
            "review-work", "contract test", (), frozenset({"browser"}),
            "bct-mcp-local", 1,
        ))
        self.server = build_mcp(
            SimpleNamespace(operations=Operations(), store=self.store),
            compact_catalogue=True, status_provider=lambda: {"monitor": {}},
        )

    async def _cleanup(self):
        self.tmp.cleanup()

    async def save(self, *, direction_id, decision="NEW_TASK", assessment_marker=False, assessment=None):
        source = "Review exact PR SHA with already registered Supervisor without rewriting node roles."
        _, prep = await self.server.call_tool("bct_chain_recipe", {
            "action": "prepare", "source_kind": "USER",
            "work_id": "review-work", "source_text": source,
        })
        self.assertEqual(prep["status"], "RECIPE_READY")
        args = {
            "action": "save", "source_kind": "USER", "work_id": "review-work",
            "source_text": source, "direction_id": direction_id,
            "entry_context_id": prep["entry_context_id"],
            "decision": decision, "direction_text": "Read-only code review.",
        }
        if assessment_marker:
            args["assessment"] = assessment
        _, result = await self.server.call_tool("bct_chain_recipe", args)
        return result

    async def test_new_user_task_without_assessment_is_rejected_before_store(self):
        result = await self.save(direction_id="review-no-target")
        self.assertEqual(result["status"], "INVALID_REQUEST")
        self.assertEqual(result["reason"], "CHAIN_DIRECTION_ASSESSMENT_REQUIRED")
        self.assertIn("targets", result["assessment_contract"]["required_for_new_task"])
        self.assertIsNone(ChainDirectionLedger(self.store).get(direction_id="review-no-target"))

    async def test_empty_assessment_still_fails_closed(self):
        result = await self.save(
            direction_id="review-empty", assessment_marker=True, assessment={},
        )
        self.assertEqual(result["status"], "INVALID_REQUEST")
        self.assertIsNone(ChainDirectionLedger(self.store).get(direction_id="review-empty"))

    async def test_explicit_three_role_assessment_is_saved_without_sending(self):
        manager = "11111111-1111-4111-8111-111111111111"
        worker = "22222222-2222-4222-8222-222222222222"
        supervisor = "33333333-3333-4333-8333-333333333333"
        result = await self.save(
            direction_id="review-valid", assessment_marker=True, assessment={
                "manager_conversation_key": manager,
                "worker_conversation_key": worker,
                "supervisor_conversation_key": supervisor,
                "network_updates": [],
                "targets": [{
                    "conversation_key": worker,
                    "role": "worker",
                    "instruction": "Review within your own bounded role.",
                }],
            },
        )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["chain_direction"]["chain_state"], "NOT_PLANNED")
        self.assertEqual(result["chain_direction"]["assessment"]["targets"][0]["conversation_key"], worker)

    async def test_supervisor_only_topology_is_not_invented(self):
        from bct.chain_direction import validate_direction_assessment
        supervisor = "6aeed472-62d8-83ee-b86d-16cd79d48132"
        with self.assertRaisesRegex(ValueError, "MANAGER_CONVERSATION_KEY_REQUIRED"):
            validate_direction_assessment({
                "supervisor_conversation_key": supervisor,
                "network_updates": [],
                "targets": [{
                    "conversation_key": supervisor,
                    "role": "supervisor",
                    "instruction": "Independently review the exact two PR SHAs.",
                }],
            }, decision="NEW_TASK")

    async def test_hold_without_assessment_remains_valid(self):
        result = await self.save(direction_id="review-hold", decision="HOLD")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["chain_direction"]["decision"], "HOLD")


if __name__ == "__main__":
    unittest.main()
