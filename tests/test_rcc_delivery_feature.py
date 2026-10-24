from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from bct.core.delivery_state import DeliveryEvent
from bct.core.models import ConfirmedFailure, Outcome, PreconditionError, UnknownEffectError, Work
from bct.core.store import Store
from bct.features.rcc import RelayBrowserFeature
from bct.integrations.rcc import RelayUnavailable


class FakeDeliveryHost:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        delivery_id = kwargs["extra"].get("deliveryId")
        if kwargs["command"] == "retire-composer-draft":
            extra = kwargs["extra"]
            return {
                "ok": True, "retired": True, "effectState": "APPLIED",
                "conversationKey": extra["conversationKey"],
                "draftSha256": extra["expectedDraftSha256"],
                "draftLength": 321, "composerEmpty": True,
                "retiredExecutionId": extra["supersededDeliveryId"],
                "supersededDeliveryId": extra["supersededDeliveryId"],
                "resumedDelivery": {
                    "deliveryId": extra["resumeDeliveryId"],
                    "state": "SENT_WAITING",
                },
            }
        if kwargs["command"] == "retire-recovered-execution":
            extra = kwargs["extra"]
            return {
                "ok": True, "retired": True, "effectState": "APPLIED",
                "deliveryId": extra["deliveryId"],
                "conversationKey": extra["conversationKey"],
                "requestSha256": extra["expectedRequestSha256"],
                "responseSha256": extra["expectedResponseSha256"],
                "responseLength": extra["expectedResponseLength"],
                "executionAbsent": True,
            }
        if kwargs["command"] == "delivery-start":
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "SENT_WAITING", "workerTabId": 11,
                    "workerWindowId": 22}
        if kwargs["command"] == "delivery-manager-status":
            text = "manager next"
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "RETURNED", "managerResponseText": text,
                    "managerResponseSha256": hashlib.sha256(text.encode()).hexdigest(),
                    "managerResponseLength": len(text)}
        if kwargs["command"] == "delivery-status":
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "REPLY_CAPTURED",
                    "responseSha256": hashlib.sha256(b"reply").hexdigest(),
                    "responseLength": 5}
        if kwargs["command"] == "delivery-cancel":
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "NOT_APPLIED", "cancelled": True,
                    "error": "DELIVERY_CANCELLED_PRE_SUBMIT"}
        return {"ok": True, "deliveryId": delivery_id,
                "state": "RETURNED", "managerTabId": 33,
                "managerWindowId": 44}


class DeliveryFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.work = self.store.create_work(Work(
            "work", "thin relay", (self.temp.name,),
            frozenset({"relay_browser"}), "owner",
        ))
        self.host = FakeDeliveryHost()
        self.feature = RelayBrowserFeature(self.host, store=self.store)
        self.base = {
            "instance_id": "6174664e1c1b4e6db1d4729c841db3c9",
            "delivery_id": "delivery-001",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def execute(self, arguments, operation_id):
        request = self.feature.prepare(work=self.work, arguments=arguments)
        return self.feature.execute(replace(request, operation_id=operation_id))

    def test_one_delivery_id_drives_one_exact_roundtrip(self) -> None:
        result = self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "원문 그대로 한 번",
        }, "outer-start")
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("SENT_WAITING", result.evidence["delivery_state"])
        result = self.execute({**self.base, "command": "delivery-status"}, "outer-status")
        self.assertEqual("REPLY_CAPTURED", result.evidence["delivery_state"])
        result = self.execute({**self.base, "command": "delivery-return"}, "outer-return")
        self.assertEqual("RETURNED", result.evidence["delivery_state"])
        self.assertEqual(
            ["delivery-start", "delivery-status", "delivery-return"],
            [call["command"] for call in self.host.calls],
        )
        self.assertTrue(all(
            call["extra"]["deliveryId"] == "delivery-001" for call in self.host.calls
        ))

    def test_busy_manager_return_is_queued_without_false_failure(self) -> None:
        self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "return after manager idle",
        }, "busy-return-start")
        self.execute({**self.base, "command": "delivery-status"}, "busy-return-status")
        original = self.host.request

        def queued(**kwargs):
            if kwargs["command"] == "delivery-return":
                return {
                    "ok": True, "pending": True, "queued": True,
                    "deliveryId": "delivery-001", "state": "REPLY_CAPTURED",
                    "responseSha256": hashlib.sha256(b"reply").hexdigest(),
                    "responseLength": 5,
                    "managerReturnSha256": "a" * 64,
                    "managerReturnLength": 123,
                    "error": "",
                }
            return original(**kwargs)

        self.host.request = queued
        result = self.execute({**self.base, "command": "delivery-return"},
                              "busy-return-queued")
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("REPLY_CAPTURED", result.evidence["delivery_state"])
        self.assertTrue(result.evidence["pending"])
        self.assertTrue(result.evidence["queued"])
        self.assertEqual("REPLY_CAPTURED", self.feature.delivery_ledger.get_for_work(
            delivery_id="delivery-001", work_id=self.work.work_id,
        )["state"])

    def test_manager_reply_is_read_only_and_bound_to_returned_id(self) -> None:
        self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "Manager, delegate once",
        }, "manager-start")
        pending = self.execute({**self.base, "command": "delivery-manager-status"},
                               "manager-status-before-return")
        self.assertTrue(pending.evidence["pending"])
        self.assertEqual(1, len(self.host.calls))
        self.execute({**self.base, "command": "delivery-status"}, "manager-worker-status")
        self.execute({**self.base, "command": "delivery-return"}, "manager-return")
        observed = self.execute({**self.base, "command": "delivery-manager-status"},
                                "manager-read-1")
        self.assertEqual("manager next", observed.output["result"]["managerResponseText"])
        self.assertFalse(observed.evidence["pending"])
        self.assertEqual("RETURNED", self.feature.delivery_ledger.get_for_work(
            delivery_id="delivery-001", work_id=self.work.work_id)["state"])
        observed2 = self.execute({**self.base, "command": "delivery-manager-status"},
                                 "manager-read-2")
        self.assertEqual(observed.evidence["manager_reply_sha256"],
                         observed2.evidence["manager_reply_sha256"])
        self.assertTrue(observed2.evidence["durable_replay"])
        self.assertEqual("manager next", observed2.output["result"]["managerResponseText"])
        persisted = self.feature.delivery_ledger.get_for_work(
            delivery_id="delivery-001", work_id=self.work.work_id,
        )["observation"]
        self.assertEqual("manager next", persisted["manager_response_text"])
        self.assertEqual(
            hashlib.sha256(b"manager next").hexdigest(),
            persisted["manager_response_sha256"],
        )
        self.assertEqual(len("manager next"), persisted["manager_response_length"])
        self.assertEqual(1, sum(call["command"] == "delivery-start"
                                for call in self.host.calls))
        self.assertEqual(1, sum(call["command"] == "delivery-return"
                                for call in self.host.calls))
        self.assertEqual(1, sum(call["command"] == "delivery-manager-status"
                                for call in self.host.calls))

    def test_manager_reply_hash_mismatch_never_changes_delivery(self) -> None:
        self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "Once only",
        }, "bad-hash-start")
        self.execute({**self.base, "command": "delivery-status"}, "bad-hash-status")
        self.execute({**self.base, "command": "delivery-return"}, "bad-hash-return")
        original = self.host.request

        def tampered(**kwargs):
            result = original(**kwargs)
            if kwargs["command"] == "delivery-manager-status":
                result["managerResponseSha256"] = "0" * 64
            return result

        self.host.request = tampered
        with self.assertRaisesRegex(ConfirmedFailure, "RCC_DELIVERY_MANAGER_REPLY_INVALID"):
            self.execute({**self.base, "command": "delivery-manager-status"},
                         "bad-hash-read")
        self.assertEqual("RETURNED", self.feature.delivery_ledger.get_for_work(
            delivery_id="delivery-001", work_id=self.work.work_id)["state"])
        self.assertEqual(1, sum(call["command"] == "delivery-start"
                                for call in self.host.calls))

    def test_duplicate_start_does_not_resend(self) -> None:
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "same",
        }
        self.execute(args, "outer-start-1")
        replay = self.execute(args, "outer-start-2")
        self.assertTrue(replay.evidence["replayed"])
        self.assertEqual(1, len(self.host.calls))

    def test_busy_worker_is_durably_queued_then_resumed_in_order(self) -> None:
        phase = {"status": 0}

        def queued_host(**kwargs):
            self.host.calls.append(kwargs)
            delivery_id = kwargs["extra"]["deliveryId"]
            if kwargs["command"] == "delivery-start":
                return {"ok": True, "deliveryId": delivery_id,
                        "state": "WAITING_TARGET", "queued": True,
                        "waitingReason": "TARGET_GENERATING"}
            phase["status"] += 1
            if phase["status"] == 1:
                return {"ok": True, "deliveryId": delivery_id,
                        "state": "SENT_WAITING", "pending": True,
                        "resumed": True, "workerTabId": 11,
                        "workerWindowId": 22}
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "REPLY_CAPTURED",
                    "responseSha256": hashlib.sha256(b"reply").hexdigest(),
                    "responseLength": 5}

        self.host.request = queued_host
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "처리 중이면 입력하지 말고 보관",
        }
        queued = self.execute(args, "queued-start")
        self.assertEqual(Outcome.APPLIED, queued.outcome)
        self.assertEqual("WAITING_TARGET", queued.evidence["delivery_state"])
        self.assertTrue(queued.evidence["queued"])
        replay = self.execute(args, "queued-replay")
        self.assertTrue(replay.evidence["replayed"])
        self.assertEqual(1, len(self.host.calls))
        resumed = self.execute({**self.base, "command": "delivery-status"},
                               "queued-resume")
        self.assertEqual("SENT_WAITING", resumed.evidence["delivery_state"])
        captured = self.execute({**self.base, "command": "delivery-status"},
                                "queued-capture")
        self.assertEqual("REPLY_CAPTURED", captured.evidence["delivery_state"])
        self.assertEqual(
            ["delivery-start", "delivery-status", "delivery-status"],
            [call["command"] for call in self.host.calls],
        )
        policy = self.host.calls[0]["extra"]
        self.assertEqual("queue_until_idle", policy["targetBusyPolicy"])
        self.assertEqual("trailing_space_once", policy["composerWakeMode"])
        self.assertEqual(1000, policy["sendButtonWaitMs"])

    def test_queued_delivery_can_be_cancelled_before_physical_submit(self) -> None:
        def queued_or_cancelled(**kwargs):
            self.host.calls.append(kwargs)
            delivery_id = kwargs["extra"]["deliveryId"]
            if kwargs["command"] == "delivery-start":
                return {"ok": True, "deliveryId": delivery_id,
                        "state": "WAITING_TARGET", "queued": True,
                        "waitingReason": "TARGET_GENERATING"}
            return {"ok": True, "deliveryId": delivery_id,
                    "state": "NOT_APPLIED", "cancelled": True,
                    "error": "DELIVERY_CANCELLED_PRE_SUBMIT"}

        self.host.request = queued_or_cancelled
        queued = self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "아직 제출하지 말고 대기",
        }, "cancel-start")
        self.assertEqual("WAITING_TARGET", queued.evidence["delivery_state"])
        cancelled = self.execute(
            {**self.base, "command": "delivery-cancel"}, "cancel-before-submit",
        )
        self.assertEqual(Outcome.APPLIED, cancelled.outcome)
        self.assertTrue(cancelled.evidence["cancelled"])
        stored = self.feature.delivery_ledger.get_for_work(
            delivery_id="delivery-001", work_id=self.work.work_id,
        )
        self.assertEqual("NOT_APPLIED", stored["state"])
        self.assertEqual(
            "DELIVERY_CANCELLED_PRE_SUBMIT", stored["observation"]["error_code"],
        )
        self.assertEqual(
            ["delivery-start", "delivery-cancel"],
            [call["command"] for call in self.host.calls],
        )

    def test_delivery_cancel_rejects_after_submit_before_host_call(self) -> None:
        self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "이미 제출된 업무",
        }, "late-cancel-start")
        with self.assertRaisesRegex(
            ConfirmedFailure, "RCC_DELIVERY_CANCEL_STATE_INVALID",
        ):
            self.execute(
                {**self.base, "command": "delivery-cancel"}, "late-cancel",
            )
        self.assertEqual(["delivery-start"], [call["command"] for call in self.host.calls])

    def test_exact_orphan_draft_retirement_resumes_only_bound_waiting_delivery(self) -> None:
        def queued_then_retired(**kwargs):
            if kwargs["command"] == "delivery-start":
                self.host.calls.append(kwargs)
                return {
                    "ok": True, "deliveryId": kwargs["extra"]["deliveryId"],
                    "state": "WAITING_TARGET", "queued": True,
                    "waitingReason": "TARGET_COMPOSER_OCCUPIED",
                }
            return FakeDeliveryHost.request(self.host, **kwargs)

        self.host.request = queued_then_retired
        worker = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
        queued = self.execute({
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": worker,
            "text": "대기 중인 새 업무",
        }, "draft-retire-start")
        self.assertEqual("WAITING_TARGET", queued.evidence["delivery_state"])
        draft_sha = hashlib.sha256("과거 BCT 초안".encode()).hexdigest()
        old_work = self.store.create_work(Work(
            "old-work", "superseded relay", (self.temp.name,),
            frozenset({"relay_browser"}), self.work.owner_principal_id,
        ))
        self.feature.delivery_ledger.create_or_get(
            delivery_id="old-delivery", work_id=old_work.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key=worker, request_sha256=draft_sha,
        )
        self.feature.delivery_ledger.observe(
            delivery_id="old-delivery", work_id=old_work.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
        )
        retired = self.execute({
            "instance_id": self.base["instance_id"],
            "command": "retire-composer-draft",
            "conversation_key": worker,
            "expected_draft_sha256": draft_sha,
            "resume_delivery_id": self.base["delivery_id"],
            "superseded_work_id": old_work.work_id,
            "superseded_delivery_id": "old-delivery",
        }, "draft-retire-exact")
        self.assertEqual(Outcome.APPLIED, retired.outcome)
        self.assertEqual(draft_sha, retired.evidence["retired_draft_sha256"])
        self.assertEqual("old-delivery", retired.evidence["retired_execution_id"])
        self.assertEqual("SENT_WAITING", retired.evidence["resumed_delivery_state"])
        self.assertEqual(
            ["delivery-start", "retire-composer-draft"],
            [call["command"] for call in self.host.calls],
        )

    def test_draft_retirement_rejects_wrong_waiting_delivery_before_host_call(self) -> None:
        self.feature.delivery_ledger.create_or_get(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key="6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            request_sha256=hashlib.sha256(b"queued").hexdigest(),
        )
        old_work = self.store.create_work(Work(
            "old-work", "superseded relay", (self.temp.name,),
            frozenset({"relay_browser"}), self.work.owner_principal_id,
        ))
        self.feature.delivery_ledger.create_or_get(
            delivery_id="old-delivery", work_id=old_work.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key="6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            request_sha256="a" * 64,
        )
        self.feature.delivery_ledger.observe(
            delivery_id="old-delivery", work_id=old_work.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
        )
        with self.assertRaisesRegex(
            ConfirmedFailure, "RCC_DRAFT_RETIRE_RESUME_IDENTITY_INVALID",
        ):
            self.execute({
                "instance_id": self.base["instance_id"],
                "command": "retire-composer-draft",
                "conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
                "expected_draft_sha256": "a" * 64,
                "resume_delivery_id": self.base["delivery_id"],
                "superseded_work_id": old_work.work_id,
                "superseded_delivery_id": "old-delivery",
            }, "draft-retire-not-waiting")
        self.assertEqual([], self.host.calls)

    def test_draft_retirement_rejects_cross_owner_superseded_delivery(self) -> None:
        worker = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
        draft_sha = "a" * 64
        foreign = self.store.create_work(Work(
            "foreign-work", "foreign superseded relay", (self.temp.name,),
            frozenset({"relay_browser"}), "different-owner",
        ))
        self.feature.delivery_ledger.create_or_get(
            delivery_id="foreign-delivery", work_id=foreign.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key=worker, request_sha256=draft_sha,
        )
        self.feature.delivery_ledger.observe(
            delivery_id="foreign-delivery", work_id=foreign.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
        )
        with self.assertRaisesRegex(
            PreconditionError, "RCC_DRAFT_RETIRE_SUPERSEDED_IDENTITY_INVALID",
        ):
            self.execute({
                "instance_id": self.base["instance_id"],
                "command": "retire-composer-draft",
                "conversation_key": worker,
                "expected_draft_sha256": draft_sha,
                "resume_delivery_id": self.base["delivery_id"],
                "superseded_work_id": foreign.work_id,
                "superseded_delivery_id": "foreign-delivery",
            }, "draft-retire-cross-owner")
        self.assertEqual([], self.host.calls)

    def test_draft_retirement_rejects_superseded_state_worker_or_hash_mismatch(self) -> None:
        manager = "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"
        worker = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
        other_worker = "7ad4bb5d-6624-83ee-b045-e57fdad5120e"
        expected_sha = "a" * 64
        old_work = self.store.create_work(Work(
            "old-work", "superseded relay", (self.temp.name,),
            frozenset({"relay_browser"}), self.work.owner_principal_id,
        ))
        cases = (
            ("wrong-state", worker, expected_sha, False),
            ("wrong-worker", other_worker, expected_sha, True),
            ("wrong-hash", worker, "b" * 64, True),
        )
        for name, stored_worker, stored_sha, mark_review in cases:
            delivery_id = "old-" + name
            self.feature.delivery_ledger.create_or_get(
                delivery_id=delivery_id, work_id=old_work.work_id,
                instance_id=self.base["instance_id"],
                manager_conversation_key=manager,
                worker_conversation_key=stored_worker, request_sha256=stored_sha,
            )
            if mark_review:
                self.feature.delivery_ledger.observe(
                    delivery_id=delivery_id, work_id=old_work.work_id,
                    event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
                )
            with self.subTest(name=name), self.assertRaisesRegex(
                PreconditionError, "RCC_DRAFT_RETIRE_SUPERSEDED_IDENTITY_INVALID",
            ):
                self.execute({
                    "instance_id": self.base["instance_id"],
                    "command": "retire-composer-draft",
                    "conversation_key": worker,
                    "expected_draft_sha256": expected_sha,
                    "resume_delivery_id": self.base["delivery_id"],
                    "superseded_work_id": old_work.work_id,
                    "superseded_delivery_id": delivery_id,
                }, "draft-retire-" + name)
        self.assertEqual([], self.host.calls)

    def test_exact_recovered_execution_retirement_requires_terminal_reply_identity(self) -> None:
        worker = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
        request_sha = "a" * 64
        response_text = "exact recovered response"
        response_sha = hashlib.sha256(response_text.encode()).hexdigest()
        self.feature.delivery_ledger.create_or_get(
            delivery_id="recovered-delivery", work_id=self.work.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key=worker, request_sha256=request_sha,
        )
        self.feature.delivery_ledger.observe(
            delivery_id="recovered-delivery", work_id=self.work.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
        )
        retired = self.execute({
            "instance_id": self.base["instance_id"],
            "command": "retire-recovered-execution",
            "conversation_key": worker,
            "delivery_id": "recovered-delivery",
            "expected_request_sha256": request_sha,
            "expected_response_sha256": response_sha,
            "expected_response_length": len(response_text),
        }, "retire-recovered-exact")
        self.assertEqual(Outcome.APPLIED, retired.outcome)
        self.assertTrue(retired.evidence["execution_absent"])
        self.assertEqual(response_sha, retired.evidence["response_sha256"])

    def test_recovered_execution_retirement_rejects_non_review_delivery(self) -> None:
        worker = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
        self.feature.delivery_ledger.create_or_get(
            delivery_id="not-review", work_id=self.work.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key=worker, request_sha256="a" * 64,
        )
        with self.assertRaisesRegex(
            PreconditionError, "RCC_RECOVERED_RETIRE_IDENTITY_INVALID",
        ):
            self.execute({
                "instance_id": self.base["instance_id"],
                "command": "retire-recovered-execution",
                "conversation_key": worker,
                "delivery_id": "not-review",
                "expected_request_sha256": "a" * 64,
                "expected_response_sha256": "b" * 64,
                "expected_response_length": 10,
            }, "retire-recovered-not-review")
        self.assertEqual([], self.host.calls)

    def test_mismatched_delivery_reuse_is_confirmed_before_host_call(self) -> None:
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "first exact message",
        }
        self.execute(args, "reuse-original")
        with self.assertRaisesRegex(ConfirmedFailure, "DELIVERY_ID_REUSE_MISMATCH"):
            self.execute({**args, "text": "different message"}, "reuse-mismatch")
        self.assertEqual(1, len(self.host.calls))

    def test_missing_delivery_status_is_confirmed_before_host_call(self) -> None:
        with self.assertRaisesRegex(ConfirmedFailure, "RCC_DELIVERY_NOT_FOUND") as caught:
            self.execute({
                "instance_id": self.base["instance_id"],
                "delivery_id": "delivery-never-created",
                "command": "delivery-status",
            }, "missing-delivery-status")
        self.assertTrue(caught.exception.release_claims)
        self.assertEqual([], self.host.calls)

    def test_status_transport_failure_is_retryable_but_return_failure_is_review(self) -> None:
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "same",
        }
        self.execute(args, "outer-start")

        class Down:
            def request(self, **_kwargs):
                raise RelayUnavailable("down")

        self.feature.client = Down()
        with self.assertRaisesRegex(ConfirmedFailure, "RCC_DELIVERY_STATUS_UNAVAILABLE"):
            self.execute({**self.base, "command": "delivery-status"}, "outer-status")
        self.assertEqual(
            "SENT_WAITING",
            self.feature.delivery_ledger.get_for_work(
                delivery_id="delivery-001", work_id=self.work.work_id,
            )["state"],
        )

        self.feature.client = self.host
        self.execute({**self.base, "command": "delivery-status"}, "outer-status-2")
        self.feature.client = Down()
        not_sent = self.execute({**self.base, "command": "delivery-return"}, "outer-return")
        self.assertEqual("NOT_APPLIED", not_sent.outcome.value)
        self.assertTrue(not_sent.evidence["not_submitted"])
        self.assertEqual(
            "REPLY_CAPTURED",
            self.feature.delivery_ledger.get_for_work(
                delivery_id="delivery-001", work_id=self.work.work_id,
            )["state"],
        )

    def test_exact_manager_turn_reconciles_return_unknown(self) -> None:
        args = {
            **self.base, "command": "delivery-start",
            "manager_conversation_key": "6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            "worker_conversation_key": "6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            "text": "exact manager return recovery",
        }
        self.execute(args, "reconcile-start")
        self.execute({**self.base, "command": "delivery-status"}, "reconcile-status")
        self.feature.delivery_ledger.observe(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
            observation={
                "host_state": "REPLY_CAPTURED",
                "error_code": "RCC_DELIVERY_EFFECT_UNKNOWN",
            },
        )
        original = self.host.request

        def reconciled(**kwargs):
            if kwargs["command"] == "delivery-manager-status":
                return {
                    "ok": True, "reconciled": True,
                    "deliveryId": self.base["delivery_id"],
                    "state": "RETURNED", "pending": True,
                    "managerTabId": 33, "managerWindowId": 44,
                }
            return original(**kwargs)

        self.host.request = reconciled
        result = self.execute(
            {**self.base, "command": "delivery-manager-status"},
            "reconcile-manager-status",
        )
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("RETURNED", result.evidence["delivery_state"])
        row = self.feature.delivery_ledger.get_for_work(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
        )
        self.assertEqual("RETURNED", row["state"])
        self.assertTrue(row["observation"]["manager_return_reconciled"])


    def _make_review_delivery(self):
        manager = "6ad7f5b6-c834-83e8-9c00-ff70bab4204d"
        worker = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
        original_sha = hashlib.sha256(b"one exact original").hexdigest()
        self.feature.delivery_ledger.create_or_get(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
            instance_id=self.base["instance_id"], manager_conversation_key=manager,
            worker_conversation_key=worker, request_sha256=original_sha,
        )
        self.feature.delivery_ledger.observe(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
            event=DeliveryEvent.EFFECT_BOUNDARY_UNPROVEN,
            observation={"error_code": "RELAY_EXACT_USER_TURN_NOT_CONFIRMED"},
        )
        return manager, worker, original_sha

    def _recovery_proof(self):
        manager, worker, original_sha = self._make_review_delivery()
        reply = "Recovered completed worker reply"
        return {
            "ok": True, "deliveryId": self.base["delivery_id"],
            "state": "NEEDS_REVIEW", "reconciled": False,
            "managerConversationKey": manager, "workerConversationKey": worker,
            "requestSha256": original_sha, "originalTurnKey": "exact:turn:user",
            "recordPhase": "submit-activated", "workerTabId": 101,
            "managerTabId": 102, "responseText": reply,
            "responseSha256": hashlib.sha256(reply.encode()).hexdigest(),
            "responseLength": len(reply)
        }

    def test_recovery_inspect_is_read_only_with_exact_original_proof(self):
        proof = self._recovery_proof()
        self.host.request = lambda **kwargs: (
            self.host.calls.append(kwargs) or dict(proof)
        )
        result = self.execute(
            {**self.base, "command": "delivery-recovery-inspect"},
            "inspect-only-once"
        )
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertFalse(result.evidence["reconciled"])
        self.assertEqual(proof["responseSha256"], result.evidence["response_sha256"])
        self.assertEqual(proof["responseText"], result.output["proof"]["responseText"])
        original = self.feature.delivery_ledger.get_for_work(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id
        )
        self.assertEqual("NEEDS_REVIEW", original["state"])
        self.assertIsNone(original["response_sha256"])
        self.assertEqual("RELAY_EXACT_USER_TURN_NOT_CONFIRMED",
                         original["observation"]["error_code"])
        # No additional message: only one host inspection.
        self.assertEqual(["delivery-recovery-inspect"],
                         [c["command"] for c in self.host.calls])

    def test_recovery_rejects_mutated_hash_identity_and_phase(self):
        template = self._recovery_proof()
        for index, (field, bad_value) in enumerate([
            ("responseSha256", "0" * 64),
            ("requestSha256", "0" * 64),
            ("workerConversationKey", "9" * 36),
            ("recordPhase", "submit-intent"),
            ("originalTurnKey", ""),
            ("reconciled", True),
            ("responseLength", 0),
        ]):
            proof = dict(template)
            proof[field] = bad_value
            self.host.request = lambda **kwargs: proof
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ConfirmedFailure, "RCC_DELIVERY_RECOVERY_PROOF_INSUFFICIENT"
                ):
                    self.execute(
                        {**self.base, "command": "delivery-recovery-inspect"},
                        f"recovery-bad-proof-{index}",
                    )
                self.assertEqual("NEEDS_REVIEW",
                    self.feature.delivery_ledger.get_for_work(
                        delivery_id=self.base["delivery_id"],
                        work_id=self.work.work_id)["state"])

    def test_recovery_cannot_inspect_non_review_delivery(self):
        self.feature.delivery_ledger.create_or_get(
            delivery_id=self.base["delivery_id"], work_id=self.work.work_id,
            instance_id=self.base["instance_id"],
            manager_conversation_key="6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
            worker_conversation_key="6ad4bb5d-6624-83ee-b045-e57fdad5120e",
            request_sha256="a" * 64,
        )
        with self.assertRaisesRegex(
            ConfirmedFailure, "RCC_DELIVERY_RECOVERY_NOT_UNKNOWN"
        ):
            self.execute(
                {**self.base, "command": "delivery-recovery-inspect"},
                "recovery-nonreview",
            )
        self.assertEqual([], self.host.calls)


if __name__ == "__main__":
    unittest.main()
