from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bct.core.models import Work
from bct.core.store import Store
from bct.features.cdp_reasoning import CDPReasoningFeature
from bct.reasoning_control import (
    CDPReasoningController, LEVELS, MAX_ATTEMPTS, ReasoningChangeRecovery,
    build_prepare_function, build_verify_function, validate_reasoning_function,
)


KEY = "6adbfb63-ddb0-83ee-8a42-dcdb8e56874c"
INSTANCE = "6174664e1c1b4e6db1d4729c841db3c9"


def response(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


class FakeManager:
    def __init__(self):
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        name = params["name"]
        if name == "list_pages":
            return response(
                "## Pages\n3: 메시지 확인 (https://chatgpt.com/c/" + KEY + ")\n"
            )
        if name == "evaluate_script":
            function = params["arguments"]["function"]
            if function.startswith("async"):
                return response(
                    'Script ran on page and returned:\n```json\n'
                    '{"status":"READY","current":"Medium","index":2}\n```'
                )
            return response(
                'Script ran on page and returned:\n```json\n'
                '{"status":"VERIFIED","current":"Extra High"}\n```'
            )
        if name == "press_key":
            return response("Successfully pressed key")
        raise AssertionError(name)


class FakeRelay:
    def __init__(self, *, generating=False, level="Medium"):
        self.generating = generating
        self.level = level

    def request(self, **kwargs):
        return {"ok": True, "state": {"endpoints": [{
            "conversationKey": KEY, "presence": "OPEN",
            "generating": self.generating,
            "reasoning": {"status": "OBSERVED", "level": self.level},
        }]}}


class ReasoningControlTests(unittest.TestCase):
    def test_script_validator_accepts_only_exact_builders(self):
        for target in LEVELS:
            for function in (
                build_prepare_function(KEY, target), build_verify_function(KEY, target),
            ):
                self.assertTrue(validate_reasoning_function(3, function))
                self.assertFalse(validate_reasoning_function(3, function + "\nvoid 0"))

    def test_controller_moves_absolute_level_and_reads_back(self):
        manager = FakeManager()
        result = CDPReasoningController(manager).apply(KEY, "Extra High")
        self.assertEqual("Medium", result["before"])
        self.assertEqual("Extra High", result["after"])
        keys = [call[1]["arguments"]["key"] for call in manager.calls
                if call[1]["name"] == "press_key"]
        self.assertEqual(["ArrowRight", "ArrowRight", "Escape"], keys)

    def test_busy_request_stays_pending_without_cdp(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.sqlite")
            store.create_work(Work("W", "reasoning", (temp,),
                                   frozenset({"cdp_reasoning"}), "user"))
            manager = FakeManager()
            recovery = ReasoningChangeRecovery(
                store, manager, FakeRelay(generating=True),
            )
            recovery.enqueue(
                request_id="R1", work_id="W", instance_id=INSTANCE,
                conversation_key=KEY, target_level="High",
            )
            self.assertEqual(
                {"examined": 1, "applied": 0, "deferred": 1},
                recovery.run_once(),
            )
            self.assertEqual("PENDING", recovery.get("R1")["state"])
            self.assertEqual([], manager.calls)

    def test_terminal_ui_contract_failure_does_not_retry_forever(self):
        class MissingSelectorManager(FakeManager):
            def request(self, method, params):
                if params["name"] == "list_pages":
                    return super().request(method, params)
                if params["name"] == "evaluate_script":
                    return response('```json\n{"status":"SELECTOR_MISSING"}\n```')
                raise AssertionError(params["name"])

        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.sqlite")
            store.create_work(Work("W", "reasoning", (temp,),
                                   frozenset({"cdp_reasoning"}), "user"))
            recovery = ReasoningChangeRecovery(
                store, MissingSelectorManager(), FakeRelay(),
            )
            recovery.enqueue(
                request_id="R1", work_id="W", instance_id=INSTANCE,
                conversation_key=KEY, target_level="High",
            )
            self.assertEqual(1, recovery.run_once()["deferred"])
            row = recovery.get("R1")
            self.assertEqual("FAILED", row["state"])
            self.assertEqual(1, row["attempts"])

    def test_transient_failure_is_bounded(self):
        class UnavailableRelay(FakeRelay):
            def request(self, **kwargs):
                raise OSError("offline")

        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.sqlite")
            store.create_work(Work("W", "reasoning", (temp,),
                                   frozenset({"cdp_reasoning"}), "user"))
            recovery = ReasoningChangeRecovery(
                store, FakeManager(), UnavailableRelay(),
            )
            recovery.enqueue(
                request_id="R1", work_id="W", instance_id=INSTANCE,
                conversation_key=KEY, target_level="High",
            )
            for attempt in range(MAX_ATTEMPTS):
                with store.transaction() as db:
                    db.execute(
                        "UPDATE reasoning_change_requests SET next_attempt_at=0 "
                        "WHERE request_id='R1'"
                    )
                recovery.run_once()
            row = recovery.get("R1")
            self.assertEqual("FAILED", row["state"])
            self.assertEqual(MAX_ATTEMPTS, row["attempts"])

    def test_new_pending_request_supersedes_old_and_applies(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.sqlite")
            store.create_work(Work("W", "reasoning", (temp,),
                                   frozenset({"cdp_reasoning"}), "user"))
            manager = FakeManager()
            recovery = ReasoningChangeRecovery(store, manager, FakeRelay())
            recovery.enqueue(request_id="R1", work_id="W", instance_id=INSTANCE,
                             conversation_key=KEY, target_level="High")
            recovery.enqueue(request_id="R2", work_id="W", instance_id=INSTANCE,
                             conversation_key=KEY, target_level="Extra High")
            self.assertEqual("SUPERSEDED", recovery.get("R1")["state"])
            self.assertEqual(1, recovery.run_once()["applied"])
            row = recovery.get("R2")
            self.assertEqual("APPLIED", row["state"])
            self.assertEqual("Extra High", row["observed_after"])

    def test_feature_records_request_then_reports_status(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.sqlite")
            work = store.create_work(Work("W", "reasoning", (temp,),
                                          frozenset({"cdp_reasoning"}), "user"))
            recovery = ReasoningChangeRecovery(store, FakeManager(), FakeRelay())
            feature = CDPReasoningFeature(recovery)
            queued = feature.execute(feature.prepare(work=work, arguments={
                "operation": "request", "request_id": "R1",
                "instance_id": INSTANCE, "conversation_uuid": KEY,
                "target_level": "Pro",
            }))
            self.assertEqual("PENDING", queued.output["reasoning_change"]["state"])
            status = feature.execute(feature.prepare(work=work, arguments={
                "operation": "status", "request_id": "R1",
            }))
            self.assertEqual("Pro", status.output["reasoning_change"]["target_level"])


if __name__ == "__main__":
    unittest.main()
