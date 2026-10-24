"""Pure capability manifest and mock-only temporary general-node supervision."""
from __future__ import annotations
import hashlib
import json
from typing import Any

CAPABILITIES = {
    "status_read": "bct_status",
    "receipt_read": "bct_operation_get",
    "inbox_read": "bct_inbox_get",
    "candidate_read": "bct_conversation_network_get",
    "card_write": "bct_work_create",
    "assignment": "bct_relay_control",
    "result_read": "bct_delivery_status",
    "settings_propose": "relay_settings_propose",
    "settings_preview": "relay_settings_preview",
}
EFFECTFUL = frozenset({"card_write", "assignment"})
PROTECTED = frozenset({"main_merge", "core_deploy", "chrome_reload", "rcc_reload", "external_resend"})

def capability_manifest(*, successor: str, scope: str, available_tools: set[str],
                        expressly_allowed: set[str], connected: bool = True) -> dict[str, Any]:
    if not successor or not scope:
        raise ValueError("SUCCESSOR_IDENTITY_SCOPE_REQUIRED")
    tools = {}
    for purpose, tool in sorted(CAPABILITIES.items()):
        if not connected or tool not in available_tools:
            state = "UNAVAILABLE"
        elif purpose in EFFECTFUL and purpose not in expressly_allowed:
            state = "ESCALATE"
        else:
            state = "AVAILABLE"
        tools[purpose] = {"tool": tool, "state": state}
    return {"schema": "BCT_TEMP_SUPERVISOR_CAPABILITY_V1",
            "successor": successor, "role": "TEMP_GENERAL_NODE_SUPERVISOR",
            "scope": scope, "role_tags_grant_authority": False,
            "tools": tools, "protected_actions": sorted(PROTECTED),
            "authority": "EXPLICIT_SCOPE_AND_AVAILABLE_TOOLS_ONLY"}

def mock_supervision(*, card: dict[str, Any], manifest: dict[str, Any],
                     assignments: list[dict[str, str]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """No side effects. Unique cards are prepared; result snapshots are supplied."""
    if card.get("schema") != "BCT_RECOVERY_CARD_V1":
        raise ValueError("INVALID_RECOVERY_CARD")
    if manifest.get("role") != "TEMP_GENERAL_NODE_SUPERVISOR":
        raise ValueError("INVALID_SUPERVISOR")
    if len(assignments) != 2 or len({a["id"] for a in assignments}) != 2:
        raise ValueError("TWO_INDEPENDENT_ASSIGNMENTS_REQUIRED")
    if manifest["tools"]["assignment"]["state"] != "AVAILABLE":
        return {"state": "ESCALATE", "reason": "ASSIGNMENT_CAPABILITY_NOT_AVAILABLE",
                "effects": []}
    trace = ["STATUS_REVIEWED", "PRIORITY_SELECTED"]
    prepared = []
    for a in sorted(assignments, key=lambda v: v["id"]):
        if not a.get("task") or not a.get("candidate"):
            raise ValueError("INCOMPLETE_ASSIGNMENT")
        key = hashlib.sha256(json.dumps([card["card_sha256"], a["id"], a["candidate"], a["task"]],
                                        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        prepared.append({"id": a["id"], "candidate": a["candidate"], "task": a["task"],
                         "idempotency_key": key, "state": "MOCK_ONLY"})
    trace.append("TWO_ASSIGNMENTS_PREPARED")
    collected = []
    for a in prepared:
        r = results.get(a["id"])
        collected.append({"assignment": a["id"], "state": "RESULT_RECEIVED" if r and r.get("verified") else "UNKNOWN",
                          "result_sha256": r.get("sha256") if r and r.get("verified") else None})
    trace.append("RESULT_INBOX_REVIEWED")
    next_step = "REVIEW_UNKNOWN_RESULTS" if any(c["state"] == "UNKNOWN" for c in collected) else "SUPERVISOR_DECIDE_NEXT_CARD_OR_COMPLETE"
    trace.append("NEXT_STEP_DECIDED")
    return {"state": "MOCK_COMPLETE", "assignments": prepared, "results": collected,
            "next_minimal_step": next_step, "trace": trace, "effects": []}
