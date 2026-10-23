from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import Work
from bct.core.store import Store
from bct.conversation_network import upsert_project, upsert_conversation, set_membership
from bct.core.delivery_ledger import DeliveryLedger
from bct.relay_settings import read_relay_settings, utf16_units, propose_relay_settings_patch
from bct.relay_prompt import compose_worker_delivery, compose_manager_return_frame

MGR = "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"
WORKER = "6ad7ff62-fa64-83ee-a485-1138f1538e53"


class RelayRuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = self.root / "settings.json"
        self.env = patch.dict(os.environ, {"BCT_RELAY_SETTINGS_PATH": str(self.settings)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Store(self.root / "store.sqlite")
        self.work = self.store.create_work(Work(
            "test-configuration-work", "원래 프로젝트 목표를 검증",
            (str(self.root),), frozenset({"relay_browser"}), "owner",
        ))
        upsert_project(self.store, project_id="network.test", display_name="브라우저 작업")
        upsert_conversation(self.store, conversation_key=MGR, display_name="Manager")
        upsert_conversation(self.store, conversation_key=WORKER, display_name="Worker")
        set_membership(self.store, project_id="network.test",
                       conversation_key=MGR, tags=["Manager"])
        set_membership(self.store, project_id="network.test",
                       conversation_key=WORKER, tags=["Worker"])

    def write(self, *, manager_action: str, scope: bool = False):
        data = {"version": 1, "defaults": {"manager_action": manager_action}, "projects": {}}
        if scope:
            data["projects"]["network.test"] = {
                "worker_return_instruction": "이 업무를 검증하고 조치 전문을 제출하세요.",
                "manager_sections": ["context", "action", "worker_result"],
            }
        self.settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_hot_edit_applies_to_next_unsent_worker_and_manager_return(self):
        self.write(manager_action="지금 결과를 검토해 후속 지시를 결정하세요.", scope=True)
        worker = compose_worker_delivery(
            store=self.store, scope_id="network.test",
            manager_conversation_key=MGR, worker_conversation_key=WORKER,
            task="이번 작업 결과를 보고해",
        )
        self.assertIn("조치 전문", worker)
        self.assertIn("이번 작업 결과를 보고해", worker)
        first, last, rev = compose_manager_return_frame(
            store=self.store, work_id=self.work.work_id, delivery_id="delivery-1",
            scope_id="network.test", original_task="이번 작업 결과를 보고해",
            manager_conversation_key=MGR, worker_conversation_key=WORKER,
            worker_result_sha256=hashlib.sha256("실제 처리 결과".encode()).hexdigest(),
        )
        full = first + "실제 처리 결과" + last
        self.assertEqual(1, full.count("실제 처리 결과"))
        self.assertIn("지금 결과를 검토", full)
        self.assertIn("이번 작업 결과를 보고해", full)
        self.assertIn("원래 프로젝트 목표를 검증", full)
        self.assertEqual(hashlib.sha256(self.settings.read_bytes()).hexdigest(), rev)
        self.write(manager_action="다음 업무에서는 미완료 항목을 먼저 확인하세요.", scope=True)
        new_first, new_last, new_rev = compose_manager_return_frame(
            store=self.store, work_id=self.work.work_id, delivery_id="delivery-2",
            scope_id="network.test", original_task="이번 작업 결과를 보고해",
            manager_conversation_key=MGR, worker_conversation_key=WORKER,
        )
        self.assertNotEqual(rev, new_rev)
        self.assertIn("미완료 항목을 먼저", new_first + new_last)
        self.assertIn("지금 결과를 검토", full)  # frozen original is unaffected

    def test_invalid_config_never_falls_back_silently(self):
        self.settings.write_text('{"version":1,"version":1,"defaults":{},"projects":{}}')
        with self.assertRaisesRegex(ValueError, "INVALID_JSON"):
            read_relay_settings()
        self.settings.write_text('{"version":1,"defaults":{"pending_limit":-1},"projects":{}}')
        with self.assertRaisesRegex(ValueError, "PENDING_LIMIT_INVALID"):
            read_relay_settings()

    def test_default_and_unicode_files_and_project_override(self):
        self.assertIn("manager_action", read_relay_settings())
        self.write(manager_action="검증해 주세요. 📦", scope=True)
        raw = self.settings.read_text(encoding="utf-8")
        self.settings.write_bytes(raw.encode("utf-16"))
        self.assertIn("📦", read_relay_settings()["manager_action"])
        self.assertEqual(["context", "action", "worker_result"],
                         read_relay_settings("network.test")["manager_sections"])
        self.assertEqual(2, utf16_units("📦"))

    def test_ledger_preserves_scope_and_task_only_for_new_scoped_deliveries(self):
        ledger = DeliveryLedger(self.store)
        task = "현재 작업의 전체 결과를 돌려받아 판단한다"
        created, row = ledger.create_or_get(
            delivery_id="roundtrip-1", work_id=self.work.work_id, instance_id="rcc-1",
            manager_conversation_key=MGR, worker_conversation_key=WORKER,
            request_sha256=hashlib.sha256(task.encode()).hexdigest(),
            scope_id="network.test", original_task=task,
        )
        self.assertTrue(created)
        self.assertEqual(task, row["observation"]["original_task"])
        same, again = ledger.create_or_get(
            delivery_id="roundtrip-1", work_id=self.work.work_id, instance_id="rcc-1",
            manager_conversation_key=MGR, worker_conversation_key=WORKER,
            request_sha256=hashlib.sha256(task.encode()).hexdigest(),
            scope_id="network.test", original_task=task,
        )
        self.assertFalse(same)
        self.assertEqual(row["observation"], again["observation"])


    def test_manager_patch_preview_keeps_other_fields_and_preserves_work_scope(self):
        self.write(manager_action="original scope action", scope=True)
        original = self.settings.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        proposed = propose_relay_settings_patch(
            scope_id="network.test",
            changes={
                "manager_action": "new manager directive during the same project",
                "pending_limit": 2,
            },
        )
        self.assertEqual("NONE_PREVIEW_ONLY", proposed["effect"])
        self.assertEqual(digest, proposed["expected_sha256"])
        self.assertFalse(proposed["expected_absent"])
        self.assertEqual(original, self.settings.read_bytes())
        self.assertEqual(2, proposed["effective_preview"]["pending_limit"])
        encoded = proposed["new_content"].encode("utf-8")
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), proposed["new_sha256"])
        self.settings.write_bytes(encoded)
        current = read_relay_settings("network.test")
        self.assertEqual("new manager directive during the same project",
                         current["manager_action"])
        self.assertEqual(2, current["pending_limit"])
        self.assertEqual("original scope action",
                         read_relay_settings()["manager_action"])
        self.assertIn("조치 전문", current["worker_return_instruction"])

    def test_manager_patch_preview_first_creation_then_remove_override(self):
        self.assertFalse(self.settings.exists())
        initial = propose_relay_settings_patch(
            scope_id="network.test",
            changes={"include_pending": False},
        )
        self.assertTrue(initial["expected_absent"])
        self.assertIsNone(initial["expected_sha256"])
        self.assertFalse(self.settings.exists())  # preview never writes
        self.settings.write_text(initial["new_content"], encoding="utf-8")
        self.assertFalse(read_relay_settings("network.test")["include_pending"])
        self.assertTrue(read_relay_settings()["include_pending"])
        reset = propose_relay_settings_patch(
            scope_id="network.test",
            changes={"include_pending": None},
        )
        self.assertFalse(reset["expected_absent"])
        self.settings.write_text(reset["new_content"], encoding="utf-8")
        self.assertTrue(read_relay_settings("network.test")["include_pending"])
        raw = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("network.test", raw["projects"])

    def test_manager_patch_rejects_invalid_type_and_reserved_markers_before_write(self):
        self.write(manager_action="unchanged")
        original = self.settings.read_bytes()
        for candidate in [
            {"pending_limit": 900},
            {"manager_sections": ["worker_result", "worker_result", "action"]},
            {"manager_action": "[BCT_ORCHESTRATION_RESULT_V1]"},
            {"extra_privilege": True},
            {},
        ]:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    propose_relay_settings_patch(
                        scope_id="network.test", changes=candidate,
                    )
                self.assertEqual(original, self.settings.read_bytes())

    def test_manager_patch_rejects_malformed_original_instead_of_repairing(self):
        self.settings.write_text('{"invalid":true}', encoding="utf-8")
        original = self.settings.read_bytes()
        with self.assertRaises(ValueError):
            propose_relay_settings_patch(changes={"pending_limit": 4})
        self.assertEqual(original, self.settings.read_bytes())


if __name__ == "__main__":
    unittest.main()
