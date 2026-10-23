"""Exactly one CDP-mediated ChatGPT user message, with durable BCT fencing.

Execution is a single fixed MCP evaluate_script call.
Only an exact known conversation and pageId can be targeted.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from bct.core.models import (
    ConfirmedFailure, FeatureRequest, FeatureResult, Outcome,
    PreconditionError, UnknownEffectError, Work,
)
from bct.integrations.cdp_send_script import (
    build_submit_function, delivery_fingerprint,
)
from bct.features.cdp_persistent import StaleCDPConnection


_UUID = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


def _parse_status(response: dict[str, Any]) -> dict[str, Any] | None:
    """Parse official MCP evaluate_script output without trusting its prose."""
    if response.get("isError") is True:
        return None
    structured = response.get("structuredContent")
    if isinstance(structured, dict):
        candidate = structured.get("result", structured)
        if isinstance(candidate, dict) and isinstance(candidate.get("status"), str):
            return candidate
    content = response.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return None
    block = content[0]
    if not isinstance(block, dict) or block.get("type") != "text":
        return None
    result_text = block.get("text")
    if not isinstance(result_text, str) or len(result_text) > 30000:
        return None
    # Official DevTools MCP often wraps JS return values in a json code fence.
    match = re.search(r"\x60{3}json\s*(\{[^\x00]*?\})\s*\x60{3}", result_text, re.DOTALL)
    if match:
        try:
            candidate = json.loads(match.group(1))
            return candidate if isinstance(candidate, dict) else None
        except json.JSONDecodeError:
            return None
    try:
        candidate = json.loads(result_text.strip())
        return candidate if isinstance(candidate, dict) else None
    except json.JSONDecodeError:
        return None


class CDPSendFeature:
    capability = "cdp_send"

    def __init__(self, manager):
        self.manager = manager

    def prepare(self, *, work: Work, arguments: dict) -> FeatureRequest:
        if not isinstance(arguments, dict) or set(arguments) != {
            "operation", "page_id", "conversation_uuid", "text", "expected_sha256",
            "expected_connection_generation"
        } or arguments["operation"] != "send_once":
            raise PreconditionError("CDP_SEND_EXACT_ARGUMENTS_REQUIRED")
        page_id = arguments["page_id"]
        generation = arguments["expected_connection_generation"]
        if type(generation) is not int or generation < 1:
            raise PreconditionError("CDP_SEND_CONNECTION_GENERATION_INVALID")
        uuid = arguments["conversation_uuid"]
        text = arguments["text"]
        digest = arguments["expected_sha256"]
        if type(page_id) is not int or page_id < 1 or page_id > 10000000:
            raise PreconditionError("CDP_SEND_PAGE_ID_INVALID")
        if not isinstance(uuid, str) or not _UUID.fullmatch(uuid):
            raise PreconditionError("CDP_SEND_CONVERSATION_UUID_INVALID")
        if (not isinstance(text, str) or not text.strip() or len(text) > 5000
                or "\x00" in text):
            raise PreconditionError("CDP_SEND_TEXT_INVALID")
        if (not isinstance(digest, str) or not _SHA.fullmatch(digest)
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest):
            raise PreconditionError("CDP_SEND_ORIGINAL_SHA_MISMATCH")
        delivery_id = delivery_fingerprint(uuid, text)
        return FeatureRequest(
            self.capability,
            "cdp-chat:" + uuid,
            {
                "operation": "send_once",
                "page_id": page_id,
                "expected_connection_generation": generation,
                "conversation_uuid": uuid,
                "text": text,
                "expected_sha256": digest,
                "delivery_id": delivery_id,
            },
            ("cdp-chat:" + uuid,),
            {"conversation_uuid": uuid, "page_id": page_id,
             "connection_generation": generation, "text_sha256": digest},
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        args = request.arguments
        page = args["page_id"]
        uuid = args["conversation_uuid"]
        digest = args["expected_sha256"]
        function = build_submit_function(page, uuid, args["text"])
        try:
            response = self.manager.request("tools/call", {
                "name": "evaluate_script",
                "arguments": {
                    "pageId": page,
                    "function": function,
                    "waitForStableDom": False,
                },
            }, expected_generation=args["expected_connection_generation"])
        except StaleCDPConnection as exc:
            raise ConfirmedFailure(
                "CDP_SEND_STALE_CONNECTION_NO_SUBMIT", release_claims=True) from exc
        except Exception as exc:
            # A timeout or disconnect can occur after the physical click.
            raise UnknownEffectError("CDP_SEND_TRANSPORT_OR_EXECUTION_UNKNOWN") from exc
        parsed = _parse_status(response)
        if not isinstance(parsed, dict):
            raise UnknownEffectError("CDP_SEND_RESULT_UNPARSABLE")
        if (parsed.get("pageId") != page
                or parsed.get("conversationUUID") != uuid
                or parsed.get("intent") != args["delivery_id"]):
            raise UnknownEffectError("CDP_SEND_TARGET_OR_INTENT_UNVERIFIED")
        state = parsed.get("status")
        code = parsed.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z_]{4,80}", code):
            raise UnknownEffectError("CDP_SEND_STATUS_INVALID")
        if state == "NOT_SUBMITTED":
            raise ConfirmedFailure("CDP_SEND_NOT_SUBMITTED:" + code, release_claims=True)
        if state != "CONFIRMED" or code != "USER_TURN_VISIBLE":
            raise UnknownEffectError("CDP_SEND_OUTCOME_UNKNOWN:" + code)
        return FeatureResult(
            Outcome.APPLIED,
            {
                "operation": "send_once",
                "page_id": page,
                "conversation_uuid": uuid,
                "text_sha256": digest,
                "text_length": len(args["text"]),
                "delivery_id": args["delivery_id"],
                "observed": "USER_TURN_VISIBLE",
                "connection_generation": self.manager.generation,
                "submission_count": 1,
            },
        )
