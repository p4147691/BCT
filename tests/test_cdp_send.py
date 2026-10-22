"""CDP one-submit contract tests: fake MCP responses, never real Chrome."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bct.core.models import AuthorizationError, ConflictError, PreconditionError
from bct.features.cdp_send import _parse_status
from bct.integrations.cdp_connection import CDPConnectionManager
from bct.integrations.cdp_send_script import (
    build_submit_function, delivery_fingerprint, validate_submit_function,
)
from bct.service import BCT


UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PAGE = 7
TEXT = '한국어 릴레이 1회 test "quoted"\nline two'
SHA = hashlib.sha256(TEXT.encode("utf8")).hexdigest()
PARAMS = {
    "operation": "send_once", "page_id": PAGE, "conversation_uuid": UUID,
    "text": TEXT, "expected_sha256": SHA,
    "expected_connection_generation": 1,
}


def reply(status="CONFIRMED", code="USER_TURN_VISIBLE", **changes):
    return {"structuredContent": {"status": status, "code": code,
            "pageId": PAGE, "conversationUUID": UUID,
            "intent": delivery_fingerprint(UUID, TEXT), **changes}}


class ScriptSafetyTests(unittest.TestCase):
    def test_fixed_script_handles_korean_quotes_and_unicode(self):
        function = build_submit_function(PAGE, UUID, TEXT)
        self.assertTrue(validate_submit_function(PAGE, function))
        self.assertFalse(validate_submit_function(PAGE + 1, function))
        self.assertFalse(validate_submit_function(PAGE, function.replace(
            "send.click();", "send.click();send.click();")))
        payload = json.loads(function.split("const cfg = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(TEXT, payload["text"])
        self.assertEqual(UUID, payload["uuid"])

    def test_non_chatgpt_or_new_page_not_supported(self):
        for bad in [0, -1, True]:
            with self.assertRaises(ValueError):
                build_submit_function(bad, UUID, TEXT)
        with self.assertRaises(ValueError):
            build_submit_function(PAGE, "new-chat", TEXT)
        with self.assertRaises(ValueError):
            build_submit_function(PAGE, UUID, "")
        with self.assertRaises(ValueError):
            build_submit_function(PAGE, UUID, "\0")

    def test_arbitrary_js_mcp_call_is_denied(self):
        manager = CDPConnectionManager()
        for code in ["() => document.cookie", "() => document.body.innerText",
                     "() => document.querySelector('button').click()"]:
            with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
                manager.request("tools/call", {"name": "evaluate_script",
                    "arguments": {"pageId": PAGE, "function": code,
                                  "waitForStableDom": False}})
        # Exact script alone is allowed past the in-process whitelist,
        # but no MCP process can start without explicit CDP configuration.
        with self.assertRaisesRegex(RuntimeError, "NOT_CONFIGURED"):
            manager.request("tools/call", {"name": "evaluate_script",
                "arguments": {"pageId": PAGE,
                              "function": build_submit_function(PAGE, UUID, TEXT),
                              "waitForStableDom": False}})

    def test_official_tool_json_response_parsing(self):
        value = reply()["structuredContent"]
        self.assertEqual(value, _parse_status({"content": [{"type": "text",
            "text": "Script returned:\n" +
                    chr(96) * 3 + "json\n" +
                    json.dumps(value) + "\n" + chr(96) * 3}]}))
        self.assertIsNone(_parse_status({"isError": True}))


class CDPSendBCTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bct = BCT(state_path=Path(self.temp.name) / "state.sqlite",
                       policy_path=Path("bct.toml"))
        self.addCleanup(self.bct.cdp_connections.close)
        from bct.core.models import Principal
        self.principal = Principal("cdp-test", "fixture",
            frozenset(self.bct.operations.capabilities))
        self.bct.create_work(work_id="send-allowed", request_summary="once",
            roots=[self.temp.name], actions=["cdp_send"], principal=self.principal)
        self.bct.create_work(work_id="send-denied", request_summary="no",
            roots=[self.temp.name], actions=["read"], principal=self.principal)

    def run_send(self, operation="once-01", work="send-allowed", data=None):
        return self.bct.operations.run(
            principal=self.principal, work_id=work, operation_id=operation,
            capability="cdp_send", arguments=data or dict(PARAMS))

    def test_authorized_once_and_duplicate_receipt_no_resubmit(self):
        with patch.object(self.bct.cdp_connections, "request",
                          return_value=reply()) as mock:
            first = self.run_send()
            duplicate = self.run_send()
        self.assertEqual(first.outcome.value, "APPLIED")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(first.evidence["text_sha256"], SHA)
        self.assertNotIn(TEXT, json.dumps(first.as_dict(), ensure_ascii=False))
        self.assertEqual(first.evidence["submission_count"], 1)
        mock.assert_called_once()
        payload = mock.call_args.args
        self.assertEqual(payload[0], "tools/call")
        self.assertEqual(payload[1]["name"], "evaluate_script")
        self.assertTrue(validate_submit_function(PAGE, payload[1]["arguments"]["function"]))
        self.assertEqual(mock.call_args.kwargs["expected_generation"], 1)

    def test_other_work_and_wrong_sha_denied_before_mcp(self):
        with patch.object(self.bct.cdp_connections, "request") as mock:
            with self.assertRaises(AuthorizationError):
                self.run_send(work="send-denied")
            with self.assertRaises(PreconditionError):
                self.run_send("wrong-sha", data={**PARAMS, "expected_sha256": "0"*64})
            mock.assert_not_called()

    def test_unknown_transport_keeps_claim_and_no_replay(self):
        with patch.object(self.bct.cdp_connections, "request",
                          side_effect=RuntimeError("MCP EOF")) as mock:
            first = self.run_send()
            self.assertEqual(first.outcome.value, "UNKNOWN")
            duplicate = self.run_send()
            self.assertTrue(duplicate.duplicate)
            with self.assertRaises(ConflictError):
                self.run_send("different-op-id")
            mock.assert_called_once()

    def test_uncertain_after_click_retains_claim(self):
        with patch.object(self.bct.cdp_connections, "request",
             return_value=reply("UNCERTAIN", "USER_TURN_NOT_CONFIRMED")):
            first = self.run_send()
        self.assertEqual(first.outcome.value, "UNKNOWN")

    def test_stale_generation_is_confirmed_non_submission(self):
        from bct.features.cdp_persistent import StaleCDPConnection
        with patch.object(self.bct.cdp_connections, "request",
                          side_effect=StaleCDPConnection("generation mismatch")):
            result = self.run_send()
        self.assertEqual(result.outcome.value, "FAILED")
        self.assertIn("STALE_CONNECTION", result.error)

    def test_send_denied_if_manager_has_no_existing_generation(self):
        manager = CDPConnectionManager()
        manager.configure(("nonexistent-program",))
        with self.assertRaisesRegex(Exception, "GENERATION_CHANGED"):
            manager.request("tools/call", {"name": "evaluate_script", "arguments": {
                "pageId": PAGE, "function": build_submit_function(PAGE, UUID, TEXT),
                "waitForStableDom": False,
            }}, expected_generation=1)
        self.assertFalse(manager.connected)
        manager.close()

    def test_preclick_rejection_releases_claim(self):
        with patch.object(self.bct.cdp_connections, "request",
                          return_value=reply("NOT_SUBMITTED", "EDITOR_NOT_EMPTY")):
            result = self.run_send()
        self.assertEqual(result.outcome.value, "FAILED")
        with patch.object(self.bct.cdp_connections, "request",
                          return_value=reply()) as mock:
            next_result = self.run_send("after-preclick-rejection")
            self.assertEqual(next_result.outcome.value, "APPLIED")
            mock.assert_called_once()

    def test_wrong_page_or_message_intent_never_claim_success(self):
        with patch.object(self.bct.cdp_connections, "request",
                          return_value=reply(pageId=PAGE+1)):
            first = self.run_send()
        self.assertEqual(first.outcome.value, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
