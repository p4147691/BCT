"""Read-only Phase 7B continuation planning for a single Delivery Ledger ID.

This module produces *data*, not dispatch authority. No Browser/Chrome/RCC
message mutation, Claim, wake, or second receipt store is created here.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

DECISION_START = "[BCT_DELIVERY_NEXT_V1]"
DECISION_END = "[/BCT_DELIVERY_NEXT_V1]"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class NextPreviewError(ValueError):
    """An untrusted Manager response failed the explicit, bounded contract."""


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NextPreviewError("DELIVERY_NEXT_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _string(value: Any, *, max_length: int, code: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or len(value) > max_length or "\\x00" in value):
        raise NextPreviewError(code)
    return value


def parse_manager_next(text: str) -> dict[str, Any]:
    """Accept exactly one versioned decision, rejecting wrappers and extra keys."""
    if not isinstance(text, str) or len(text) > 12000:
        raise NextPreviewError("DELIVERY_NEXT_TEXT_INVALID")
    raw = text.strip()
    if not (raw.startswith(DECISION_START) and raw.endswith(DECISION_END)):
        raise NextPreviewError("DELIVERY_NEXT_MARKERS_MISSING")
    source = raw[len(DECISION_START):-len(DECISION_END)].strip()
    try:
        value = json.loads(source, object_pairs_hook=_pairs_unique)
    except (ValueError, TypeError) as exc:
        raise NextPreviewError("DELIVERY_NEXT_JSON_INVALID") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema", "run_id", "parent_delivery_id", "parent_result_sha256",
        "kind", "summary", "successor",
    }:
        raise NextPreviewError("DELIVERY_NEXT_FIELDS_INVALID")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise NextPreviewError("DELIVERY_NEXT_SCHEMA_INVALID")
    for key in ("run_id", "parent_delivery_id"):
        if not isinstance(value[key], str) or not _ID.fullmatch(value[key]):
            raise NextPreviewError("DELIVERY_NEXT_ID_INVALID")
    if not isinstance(value["parent_result_sha256"], str) or not _SHA.fullmatch(value["parent_result_sha256"]):
        raise NextPreviewError("DELIVERY_NEXT_PARENT_RESULT_HASH_INVALID")
    _string(value["summary"], max_length=1500, code="DELIVERY_NEXT_SUMMARY_INVALID")
    if value["kind"] == "COMPLETE":
        if value["successor"] is not None:
            raise NextPreviewError("DELIVERY_NEXT_COMPLETE_SUCCESSOR_FORBIDDEN")
    elif value["kind"] == "CONTINUE":
        successor = value["successor"]
        if not isinstance(successor, dict) or set(successor) != {
            "worker_conversation_key", "instruction", "acceptance",
        }:
            raise NextPreviewError("DELIVERY_NEXT_SUCCESSOR_FIELDS_INVALID")
        worker_key = successor["worker_conversation_key"]
        if not isinstance(worker_key, str) or not _UUID.fullmatch(worker_key):
            raise NextPreviewError("DELIVERY_NEXT_WORKER_UUID_INVALID")
        _string(successor["instruction"], max_length=8000, code="DELIVERY_NEXT_INSTRUCTION_INVALID")
        _string(successor["acceptance"], max_length=1500, code="DELIVERY_NEXT_ACCEPTANCE_INVALID")
    else:
        raise NextPreviewError("DELIVERY_NEXT_KIND_INVALID")
    return value


def preview_next_delivery(
    *, run: dict[str, Any], parent: dict[str, Any],
    manager_text: str, manager_sha256: str, work_id: str,
) -> dict[str, Any]:
    """Create a deterministic *proposal* from a verified exact Manager answer.

    The caller must have obtained manager_text from the RCC's exact-turn
    read-only delivery-manager-status, not from an arbitrary message.
    """
    if run["state"] != "READY" or run["work_id"] != work_id:
        raise NextPreviewError("DELIVERY_NEXT_RUN_NOT_AUTHORIZED")
    if parent["work_id"] != work_id or parent["state"] != "RETURNED":
        raise NextPreviewError("DELIVERY_NEXT_PARENT_NOT_RETURNED")
    if parent["manager_conversation_key"] != run["manager_conversation_key"]:
        raise NextPreviewError("DELIVERY_NEXT_MANAGER_MISMATCH")
    if not _SHA.fullmatch(manager_sha256) or hashlib.sha256(manager_text.encode("utf-8")).hexdigest() != manager_sha256:
        raise NextPreviewError("DELIVERY_NEXT_MANAGER_HASH_MISMATCH")
    decision = parse_manager_next(manager_text)
    if (decision["run_id"] != run["run_id"]
            or decision["parent_delivery_id"] != parent["delivery_id"]
            or decision["parent_result_sha256"] != parent["response_sha256"]):
        raise NextPreviewError("DELIVERY_NEXT_PARENT_BINDING_MISMATCH")
    output = {
        "run_id": run["run_id"],
        "parent_delivery_id": parent["delivery_id"],
        "manager_reply_sha256": manager_sha256,
        "kind": decision["kind"],
        "summary": decision["summary"],
        "next_delivery": None,
        "mutated": False,
    }
    if decision["kind"] == "COMPLETE":
        return output
    worker = decision["successor"]["worker_conversation_key"]
    current_members = {
        item["conversation_key"] for item in run["members"]
    }
    if worker == run["manager_conversation_key"] or worker not in current_members:
        raise NextPreviewError("DELIVERY_NEXT_WORKER_OUT_OF_SCOPE")
    instruction = decision["successor"]["instruction"]
    delivery_key = hashlib.sha256(
        json.dumps([run["run_id"], parent["delivery_id"], manager_sha256],
                   ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:40]
    output["next_delivery"] = {
        "delivery_id": "next." + delivery_key,
        "manager_conversation_key": run["manager_conversation_key"],
        "worker_conversation_key": worker,
        "text": instruction,
        "request_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "acceptance": decision["successor"]["acceptance"],
    }
    return output
