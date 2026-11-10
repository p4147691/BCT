"""Regression checks for reusable Chain Recipe instruction blocks."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace

from bct.chain_recipe_blocks import (
    EXPLICIT_NEXT_TASK_SUFFIX,
    check_chain_work,
    prepare_chain_instruction,
)


class ChainRecipeBlocksTests(unittest.TestCase):
    def test_default_instruction_is_unchanged_and_digest_is_exact(self):
        message = "지시문 원문 / Work·Direction"
        actual = prepare_chain_instruction(message)
        self.assertEqual(message, actual["instruction"])
        self.assertEqual(hashlib.sha256(message.encode("utf-8")).hexdigest(), actual["instruction_sha256"])
        self.assertFalse(actual["output_contract_appended"])
        self.assertFalse(actual["execution_plan_contract_appended"])

    def test_explicit_continuation_and_execute_plan_use_one_final_digest(self):
        message = "원래 Direction"
        actual = prepare_chain_instruction(
            message,
            output_contract="explicit-next-task-v1",
            execution_plan_context={
                "work_id": "work-a", "direction_id": "direction-b",
                "task_id": "task-c", "generation": 1,
            },
        )
        self.assertIn(EXPLICIT_NEXT_TASK_SUFFIX, actual["instruction"])
        self.assertIn('bct_set_execute_plan(work_id="work-a"', actual["instruction"])
        self.assertIn("generation=1", actual["instruction"])
        self.assertTrue(actual["output_contract_appended"])
        self.assertTrue(actual["execution_plan_contract_appended"])
        self.assertEqual(
            hashlib.sha256(actual["instruction"].encode("utf-8")).hexdigest(),
            actual["instruction_sha256"],
        )

    def test_work_check_is_observation_only(self):
        work = SimpleNamespace(owner_principal_id="owner", state="ACTIVE", actions=["browser"])
        value = check_chain_work(work, principal_id="owner")
        self.assertEqual("OBSERVED", value["status"])
        self.assertEqual("MATCHED", value["work_access"])
        self.assertEqual("ACTIVE", work.state)

    def test_rejects_invalid_contract_before_send(self):
        with self.assertRaisesRegex(ValueError, "CHAIN_MESSAGE_OUTPUT_CONTRACT_INVALID"):
            prepare_chain_instruction("hello", output_contract="invalid")
        with self.assertRaisesRegex(ValueError, "CHAIN_MESSAGE_OUTPUT_CONTRACT_TOO_LONG"):
            prepare_chain_instruction("x" * 11900, output_contract="explicit-next-task-v1")

    def test_legacy_module_path_is_not_required(self):
        package = Path(__file__).resolve().parents[1] / "src" / "bct"
        self.assertTrue((package / "chain_recipe_blocks.py").is_file())
        self.assertFalse((package / "chain_message_preflight.py").exists())


if __name__ == "__main__":
    unittest.main()
