from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from bct.conversation_network import upsert_project, upsert_conversation, set_membership
from bct.core.models import ConfirmedFailure, Outcome, PreconditionError, Work
from bct.core.store import Store
from bct.features.rcc import RelayBrowserFeature

MGR = "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"
WORKER = "6ad7ff62-fa64-83ee-a485-1138f1538e53"


class StubExistingRcc:
    def __init__(self):
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        which = kwargs["command"]
        delivery = kwargs["extra"]["deliveryId"]
        if which == "delivery-start":
            return {"ok": True, "deliveryId": delivery, "state": "SENT_WAITING",
                    "workerTabId": 100, "workerWindowId": 200}
        if which == "delivery-status":
            body = "4줄 결과"
            return {"ok": True, "deliveryId": delivery, "state": "REPLY_CAPTURED",
                    "responseSha256": hashlib.sha256(body.encode()).hexdigest(),
                    "responseLength": len(body)}
        if which == "delivery-return":
            return {"ok": True, "deliveryId": delivery, "state": "RETURNED",
                    "managerTabId": 300, "managerWindowId": 200}
        if which == "delivery-manager-status":
            body = "목표를 충족했고 남은 위험이 없어 여기서 정리합니다."
            return {"ok": True, "deliveryId": delivery, "state": "RETURNED",
                    "managerResponseText": body,
                    "managerResponseSha256": hashlib.sha256(body.encode()).hexdigest(),
                    "managerResponseLength": len(body)}
        raise ValueError(which)


class DeliveryPromptCompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "state.sqlite")
        upsert_project(self.store, project_id="network.test", display_name="브라우저 작업")
        upsert_conversation(self.store, conversation_key=MGR, display_name="Manager")
        upsert_conversation(self.store, conversation_key=WORKER, display_name="Worker")
        set_membership(self.store, project_id="network.test",
                       conversation_key=MGR, tags=["Manager"])
        set_membership(self.store, project_id="network.test",
                       conversation_key=WORKER, tags=["Worker"])
        self.work = self.store.create_work(Work(
            "prompt-work", "bounded one delivery", (self.tmp.name,),
            frozenset({"relay_browser"}), "owner",
        ))
        self.host = StubExistingRcc()
        self.feature = RelayBrowserFeature(self.host, store=self.store)
        self.cfg = Path(self.tmp.name) / "notes"
        self.cfg.mkdir()
        (self.cfg / "worker-relay-note.txt").write_text(
            "LEGACY_WORKER_NOTE COMPLETE FOLLOW_UP 4줄 JSON", encoding="utf-8")
        (self.cfg / "manager-relay-note.txt").write_text(
            "LEGACY_MANAGER_NOTE COMPLETE FOLLOW_UP", encoding="utf-8")
        self.patch = patch("bct.features.orchestration._RELAY_NOTES_DIR", self.cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.settings = Path(self.tmp.name) / "relay-message-settings.json"
        self.settings_env = patch.dict(
            os.environ, {"BCT_RELAY_SETTINGS_PATH": str(self.settings)}
        )
        self.settings_env.start()
        self.addCleanup(self.settings_env.stop)
        self.base = {
            "instance_id": "6174664e1c1b4e6db1d4729c841db3c9",
            "delivery_id": "prompt-delivery-1", "manager_conversation_key": MGR,
            "worker_conversation_key": WORKER, "scope_id": "network.test",
            "text": "파일 상태를 조사한 뒤 4줄로 결과를 반환하세요.",
        }

    def run_delivery(self, args, opid):
        value = self.feature.prepare(work=self.work, arguments=args)
        return self.feature.execute(replace(value, operation_id=opid))

    @staticmethod
    def parse_body(text):
        start = "[BCT_DELIVERY_WORKER_V1]"
        end = "[/BCT_DELIVERY_WORKER_V1]"
        return json.loads(text.split(start, 1)[1].split(end, 1)[0])

    def test_current_roster_and_single_settings_source_use_delivery_return(self):
        result = self.run_delivery({"command":"delivery-start", **self.base}, "start-1")
        self.assertEqual(Outcome.APPLIED, result.outcome)
        start = self.host.calls[0]
        self.assertEqual("delivery-start", start["command"])
        body = self.parse_body(start["text"])
        self.assertEqual("network.test", body["scope_id"])
        self.assertEqual(self.work.work_id, body["work_id"])
        self.assertEqual("브라우저 작업", body["project"])
        self.assertEqual("bounded one delivery", body["project_goal"])
        self.assertEqual([MGR, WORKER],
                         [x["conversation_uuid"] for x in body["current_members"]])
        self.assertEqual(["Manager"], body["current_members"][0]["role_tags"])
        self.assertNotIn("role_note", body)
        self.assertIn("전체 원문", body["return_instruction"])
        self.assertNotIn("LEGACY_WORKER_NOTE", start["text"])
        self.assertEqual(self.base["text"], body["task"])
        self.assertEqual(hashlib.sha256(start["text"].encode("utf-8")).hexdigest(),
                         start["extra"]["requestSha256"])
        state = self.run_delivery(
            {"command":"delivery-status", "instance_id":self.base["instance_id"],
             "delivery_id":self.base["delivery_id"]}, "status-1")
        self.assertEqual("REPLY_CAPTURED", state.evidence["delivery_state"])
        ret = self.run_delivery(
            {"command":"delivery-return", "instance_id":self.base["instance_id"],
             "delivery_id":self.base["delivery_id"]}, "return-1")
        self.assertEqual("RETURNED", ret.evidence["delivery_state"])
        decision = self.run_delivery(
            {"command":"delivery-manager-status","instance_id":self.base["instance_id"],
             "delivery_id":self.base["delivery_id"]}, "manager-status-1")
        self.assertIn("목표를 충족", decision.output["result"]["managerResponseText"])
        self.assertEqual(
            ["delivery-start","delivery-status","delivery-return","delivery-manager-status"],
            [x["command"] for x in self.host.calls])
        self.assertEqual(
            {"prompt-delivery-1"}, {x["extra"]["deliveryId"] for x in self.host.calls})

    def test_unchanged_original_no_scope_keeps_exact_text(self):
        args={k:v for k,v in self.base.items() if k!="scope_id"}
        self.run_delivery({"command":"delivery-start",**args}, "raw-start")
        self.assertEqual(args["text"], self.host.calls[0]["text"])

    def test_member_removed_before_new_start_does_not_send(self):
        set_membership(self.store,project_id="network.test",
                       conversation_key=WORKER,activity="EXCLUDED")
        with self.assertRaisesRegex(PreconditionError,"TARGET_NOT_IN_SCOPE"):
            self.feature.prepare(work=self.work,arguments={"command":"delivery-start",**self.base})
        self.assertEqual([],self.host.calls)

    def test_runtime_settings_change_only_a_new_delivery(self):
        self.run_delivery({"command":"delivery-start",**self.base}, "start-1")
        self.settings.write_text(json.dumps({
            "version": 1,
            "defaults": {
                "worker_additional_instruction": "다음 작업부터 적용되는 새로운 추가 지시.",
            },
            "projects": {},
        }, ensure_ascii=False), encoding="utf-8")
        same = {"command":"delivery-start",**self.base}
        # A changed prompt must be fenced by the persisted Delivery hash,
        # never sent again under an existing delivery_id.
        with self.assertRaisesRegex(ConfirmedFailure,"DELIVERY_ID_REUSE_MISMATCH"):
            self.run_delivery(same,"start-changed")
        self.assertEqual(1,len(self.host.calls))
        other={**same, "delivery_id":"prompt-delivery-2"}
        self.run_delivery(other,"new-start")
        self.assertIn("새로운 추가 지시",self.host.calls[-1]["text"])
        self.assertEqual(2,len(self.host.calls))

    def test_delivery_preview_composes_both_messages_without_rcc_or_ledger_effect(self):
        result = self.run_delivery({
            "command": "delivery-preview",
            **self.base,
            "worker_result_preview": "실제 Worker 결과 전문 예시 📦",
        }, "preview-1")
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual([], self.host.calls)
        preview = result.output["preview"]
        self.assertEqual("NONE_PREVIEW_ONLY", preview["effect"])
        self.assertIn(self.base["text"], preview["worker_message"]["text"])
        manager_text = preview["manager_return_message"]["text"]
        self.assertEqual(1, manager_text.count("실제 Worker 결과 전문 예시 📦"))
        self.assertIn("bounded one delivery", manager_text)
        self.assertIn("단일 Delivery 경로", manager_text)
        self.assertNotIn("LEGACY_MANAGER_NOTE", manager_text)
        self.assertNotIn("COMPLETE", manager_text)
        self.assertNotIn("FOLLOW_UP", manager_text)
        self.assertTrue(preview["worker_message"]["fits_current_limit"])
        self.assertTrue(preview["manager_return_message"]["fits_current_limit"])
        db = self.store._connect()
        try:
            self.assertEqual(0, db.execute(
                "SELECT COUNT(*) FROM relay_deliveries"
            ).fetchone()[0])
        finally:
            db.close()

    def test_missing_scope_and_invalid_identity_fail_pre_submit(self):
        for update in ({"scope_id":"network.not-found"},
                       {"scope_id":"network.test","worker_conversation_key":MGR},
                       {"scope_id":123}):
            with self.subTest(update=update):
                with self.assertRaises(PreconditionError):
                    self.feature.prepare(
                        work=self.work, arguments={"command":"delivery-start",**self.base,**update})
        self.assertEqual([],self.host.calls)


    def test_manager_return_frame_uses_same_delivery_and_original_worker_task(self):
        self.run_delivery({"command": "delivery-start", **self.base}, "wake-start")
        self.run_delivery({
            "command": "delivery-status", "instance_id": self.base["instance_id"],
            "delivery_id": self.base["delivery_id"],
        }, "wake-status")
        ret = self.run_delivery({
            "command": "delivery-return", "instance_id": self.base["instance_id"],
            "delivery_id": self.base["delivery_id"],
        }, "wake-return")
        self.assertEqual("RETURNED", ret.evidence["delivery_state"])
        commands = [item["command"] for item in self.host.calls]
        self.assertEqual(["delivery-start", "delivery-status", "delivery-return"], commands)
        payload = self.host.calls[-1]["extra"]
        self.assertIn("[BCT_MANAGER_RETURN_CONTEXT_V1]", payload["managerReturnHeader"])
        self.assertIn(self.base["text"], payload["managerReturnHeader"])
        self.assertIn("[BCT_CURRENT_WORKER_RESULT_FULL]", payload["managerReturnHeader"])
        self.assertIn("[/BCT_CURRENT_WORKER_RESULT_FULL]", payload["managerReturnFooter"])
        self.assertIn("단일 Delivery 경로", payload["managerReturnFooter"])
        self.assertNotIn("LEGACY_MANAGER_NOTE", payload["managerReturnFooter"])
        self.assertNotIn("COMPLETE", payload["managerReturnFooter"])
        self.assertNotIn("FOLLOW_UP", payload["managerReturnFooter"])
        self.assertIn("managerReturnSettingsSha256", payload)
        persisted = self.feature.delivery_ledger.get_for_work(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
        )
        self.assertEqual(self.base["text"], persisted["observation"]["original_task"])



if __name__ == "__main__":
    unittest.main()
