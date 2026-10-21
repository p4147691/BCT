from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, Work
from bct.features.rcc import RelayBrowserFeature
from bct.runtime_server import (
    MONITOR_EXTENSION_ORIGIN,
    ensure_monitor_work,
    monitor_extension_origin_allowed,
    run_monitor_conversation_rename,
    run_monitor_conversation_order_update,
    run_monitor_conversation_scope_update,
    run_monitor_rcc_reload,
)
from bct.service import BCT


class FakeRelayClient:
    def __init__(self):
        self.calls: list[dict] = []

    def request(self, **values):
        self.calls.append(values)
        if values["command"] == "state":
            return {
                "type": "host:result", "ok": True,
                "state": {"instanceId": values["instance_id"],
                          "sessionId": "session-current", "endpoints": []},
            }
        if values["command"] == "reload-extension":
            return {
                "type": "host:result", "ok": True,
                "instanceId": values["instance_id"], "reloading": True,
            }
        return {
            "type": "host:result",
            "ok": True,
            "savedTitle": values["extra"]["title"],
            "tabId": values["extra"]["tabId"],
            "conversationKey": values["extra"]["conversationKey"],
        }


class MonitorConversationRenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        policy = self.root / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["relay_browser"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=policy)
        self.client = FakeRelayClient()
        self.bct.operations._features["relay_browser"] = RelayBrowserFeature(self.client)
        self.principal = ensure_monitor_work(self.bct, runtime_root=self.root)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **changes):
        value = {
            "instance_id": "instance123",
            "session_id": "session123",
            "tab_id": 17,
            "conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "title": "바뀐 실제 제목",
            "operation_id": "monitor-rename-1",
        }
        value.update(changes)
        return value

    def test_exact_origin_only(self):
        self.assertTrue(monitor_extension_origin_allowed(MONITOR_EXTENSION_ORIGIN))
        self.assertTrue(monitor_extension_origin_allowed(MONITOR_EXTENSION_ORIGIN + "/"))
        self.assertFalse(monitor_extension_origin_allowed(""))
        self.assertFalse(monitor_extension_origin_allowed("https://chatgpt.com"))
        self.assertFalse(monitor_extension_origin_allowed("chrome-extension://foreign"))

    def test_rename_uses_normal_receipt_and_duplicate_does_not_dispatch_twice(self):
        first = run_monitor_conversation_rename(
            self.bct, principal=self.principal, payload=self.payload()
        )
        duplicate = run_monitor_conversation_rename(
            self.bct, principal=self.principal, payload=self.payload()
        )
        self.assertEqual(Outcome.APPLIED.value, first["outcome"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(1, len(self.client.calls))
        self.assertEqual("monitor-rename-1", self.client.calls[0]["extra"]["operationId"])
        self.assertEqual("session123", self.client.calls[0]["extra"]["sessionId"])
        with self.bct.store.transaction() as db:
            stored = db.execute(
                "SELECT display_name FROM conversation_network_conversations WHERE conversation_key=?",
                (self.payload()["conversation_key"],),
            ).fetchone()
        self.assertEqual("바뀐 실제 제목", stored["display_name"])

    def test_scope_update_has_no_manager_uniqueness_or_execution_claim(self):
        first = run_monitor_conversation_scope_update(self.bct, payload={
            "conversation_key": self.payload()["conversation_key"],
            "display_name": "첫 대화",
            "scope_name": "BCT 작업",
            "role_tags": ["Manager", "구현"],
        })
        second = run_monitor_conversation_scope_update(self.bct, payload={
            "conversation_key": "6ad5afa4-b1e0-83ee-8692-aec4bb51523e",
            "display_name": "둘째 대화",
            "scope_name": "BCT 작업",
            "role_tags": ["Manager", "검토"],
        })
        self.assertEqual("BCT 작업", first["scope_name"])
        self.assertEqual("BCT 작업", second["scope_name"])
        self.assertIn("Manager", first["role_tags"])
        self.assertIn("Manager", second["role_tags"])
        self.assertEqual([], self.bct.store.claim_diagnostics())

    def test_order_update_is_metadata_only_and_keeps_claims_empty(self):
        keys = [
            self.payload()["conversation_key"],
            "6ad5afa4-b1e0-83ee-8692-aec4bb51523e",
        ]
        for index, key in enumerate(keys):
            run_monitor_conversation_scope_update(self.bct, payload={
                "conversation_key": key,
                "display_name": f"대화 {index}",
                "scope_name": "BCT 작업",
                "role_tags": [],
            })
        scope_id = run_monitor_conversation_scope_update(self.bct, payload={
            "conversation_key": keys[0],
            "display_name": "대화 0",
            "scope_name": "BCT 작업",
            "role_tags": [],
        })["scope_id"]
        result = run_monitor_conversation_order_update(self.bct, payload={
            "conversation_keys": list(reversed(keys)),
            "scope_id": scope_id,
            "moved_conversation_key": "",
        })
        self.assertEqual(list(reversed(keys)), result["conversation_keys"])
        self.assertEqual([], self.bct.store.claim_diagnostics())

    def test_invalid_or_changed_request_is_rejected_without_dispatch(self):
        with self.assertRaisesRegex(ValueError, "MONITOR_RENAME_TITLE_INVALID"):
            run_monitor_conversation_rename(
                self.bct, principal=self.principal, payload=self.payload(title="")
            )
        with self.assertRaisesRegex(ValueError, "MONITOR_RENAME_OPERATION_ID_INVALID"):
            run_monitor_conversation_rename(
                self.bct, principal=self.principal, payload=self.payload(operation_id="bad operation")
            )
        with self.assertRaisesRegex(ValueError, "MONITOR_RENAME_FIELD_NOT_ALLOWED"):
            run_monitor_conversation_rename(
                self.bct, principal=self.principal, payload=self.payload(role="MANAGER")
            )
        self.assertEqual([], self.client.calls)

    def test_rcc_reload_uses_exact_instance_and_durable_duplicate_receipt(self):
        payload = {
            "instance_id": "instance123",
            "operation_id": "monitor-rcc-reload-1",
            "timeout_s": 10,
        }
        first = run_monitor_rcc_reload(
            self.bct, principal=self.principal, payload=payload,
        )
        duplicate = run_monitor_rcc_reload(
            self.bct, principal=self.principal, payload=payload,
        )
        self.assertEqual(Outcome.APPLIED.value, first["outcome"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(2, len(self.client.calls))
        self.assertEqual(["state", "reload-extension"], [
            call["command"] for call in self.client.calls
        ])
        self.assertEqual("instance123", self.client.calls[1]["instance_id"])

    def test_rcc_reload_rejects_ambiguous_fields_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "MONITOR_RCC_RELOAD_INSTANCE_ID_INVALID"):
            run_monitor_rcc_reload(self.bct, principal=self.principal, payload={
                "instance_id": "", "operation_id": "reload-1",
            })
        with self.assertRaisesRegex(ValueError, "MONITOR_RCC_RELOAD_FIELD_NOT_ALLOWED"):
            run_monitor_rcc_reload(self.bct, principal=self.principal, payload={
                "instance_id": "instance123", "operation_id": "reload-1", "force": True,
            })
        self.assertEqual([], self.client.calls)

    def test_existing_foreign_monitor_work_fails_closed(self):
        other_root = self.root / "other"
        other_root.mkdir()
        second = BCT(
            state_path=other_root / "state.sqlite",
            policy_path=self.root / "bct.toml",
        )
        second.store.create_work(Work(
            "bct-monitor-extension-control",
            "foreign",
            (str(other_root),),
            frozenset({"relay_browser"}),
            "foreign-owner",
        ))
        with self.assertRaisesRegex(RuntimeError, "MONITOR_WORK_CONTRACT_MISMATCH"):
            ensure_monitor_work(second, runtime_root=other_root)


if __name__ == "__main__":
    unittest.main()
