from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import ConflictError, Outcome, Work
from bct.features.rcc import RelayBrowserFeature
from bct.runtime_server import (
    MONITOR_EXTENSION_ORIGIN,
    ensure_monitor_work,
    monitor_extension_origin_allowed,
    run_monitor_conversation_rename,
)
from bct.service import BCT


class FakeRelayClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.rename_result: dict | None = None
        self.inspection_result: dict | None = None

    def request(self, **values):
        self.calls.append(values)
        if values["command"] == "rename-receipt" and self.inspection_result is not None:
            return self.inspection_result
        if values["command"] == "rename-conversation" and self.rename_result is not None:
            return self.rename_result
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
            "conversation_key": "conversation-123",
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

    def test_fresh_exact_rename_supersedes_prior_unknown_without_replaying_it(self):
        first_payload = self.payload(operation_id="monitor-rename-unknown", title="미확정 요청")
        self.client.rename_result = {"type": "host:result", "ok": False}
        first = run_monitor_conversation_rename(
            self.bct, principal=self.principal, payload=first_payload,
        )
        self.assertEqual(Outcome.UNKNOWN.value, first["outcome"])

        self.client.inspection_result = {
            "type": "host:result", "ok": True,
            "instanceId": "instance123", "relayId": "monitor-rename-unknown",
            "receipt": None, "receiptState": "MISSING",
            "observed": {
                "tabId": 17, "conversationKey": "conversation-123",
                "title": "현재 실제 제목", "presence": "OPEN",
                "currentSessionId": "session-after-reload",
            },
        }
        self.client.rename_result = None
        second = run_monitor_conversation_rename(
            self.bct,
            principal=self.principal,
            payload=self.payload(operation_id="monitor-rename-successor", title="새 사용자 제목"),
        )
        self.assertEqual(Outcome.APPLIED.value, second["outcome"])
        self.assertEqual(
            ["rename-conversation", "rename-receipt", "rename-conversation"],
            [call["command"] for call in self.client.calls],
        )
        original = self.bct.store.get_operation_for(
            operation_id="monitor-rename-unknown",
            work_id="bct-monitor-extension-control",
            principal_id="bct-monitor-extension",
        )
        self.assertEqual(Outcome.UNKNOWN, original.outcome)
        db = self.bct.store._connect()
        try:
            unresolved = db.execute(
                "SELECT COUNT(*) FROM resource_claims WHERE operation_id=? AND unresolved=1",
                ("monitor-rename-unknown",),
            ).fetchone()[0]
            event = db.execute(
                "SELECT kind FROM events WHERE subject_id=? ORDER BY event_id DESC LIMIT 1",
                ("monitor-rename-unknown",),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(0, unresolved)
        self.assertEqual("RCC_RENAME_UNKNOWN_SUPERSEDED", event)

    def test_prior_unknown_stays_blocked_when_fresh_identity_is_not_open(self):
        self.client.rename_result = {"type": "host:result", "ok": False}
        first = run_monitor_conversation_rename(
            self.bct,
            principal=self.principal,
            payload=self.payload(operation_id="monitor-rename-unknown"),
        )
        self.assertEqual(Outcome.UNKNOWN.value, first["outcome"])
        self.client.rename_result = None
        self.client.inspection_result = {
            "type": "host:result", "ok": True,
            "instanceId": "instance123", "relayId": "monitor-rename-unknown",
            "receipt": None, "receiptState": "MISSING",
            "observed": {
                "tabId": 17, "conversationKey": "conversation-123",
                "title": "현재 실제 제목", "presence": "CLOSED",
                "currentSessionId": "session-after-reload",
            },
        }
        with self.assertRaisesRegex(ConflictError, "MONITOR_RENAME_PRIOR_IDENTITY_NOT_OPEN"):
            run_monitor_conversation_rename(
                self.bct,
                principal=self.principal,
                payload=self.payload(operation_id="monitor-rename-successor", title="새 사용자 제목"),
            )
        self.assertEqual(2, len(self.client.calls))


if __name__ == "__main__":
    unittest.main()
