"""Shared BCT prompt composition for an existing Project Run Delivery.

Not a transport, role privilege, or a new message queue. Read the one
canonical ACTIVE conversation roster and the one relay-message settings
document each time a *new* message is prepared. The resulting exact bytes are
SHA-fenced by the existing Delivery Ledger. No implicit resend on changes.
"""
from __future__ import annotations

import hashlib
import json
import re

from bct.conversation_network import node_labels_for_conversations
from bct.project_run import _members, project_run_scope_view
from bct.relay_settings import read_relay_settings, utf16_units

_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z", re.I)
_SCOPE = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")


def compose_worker_delivery(
    *, store, scope_id: str, manager_conversation_key: str,
    worker_conversation_key: str, task: str, work_id: str = "",
) -> str:
    """Compute a static-once prompt from fresh advisory group membership.

    Roles never grant a BCT capability; the coordinator separately checks
    Work policy, live RCC route and immutable operation/Delivery ID.
    """
    if not isinstance(scope_id, str) or not _SCOPE.fullmatch(scope_id):
        raise ValueError("DELIVERY_COMPOSE_SCOPE_INVALID")
    manager = str(manager_conversation_key or "").lower()
    worker = str(worker_conversation_key or "").lower()
    if (not _UUID.fullmatch(manager) or not _UUID.fullmatch(worker)
            or manager == worker):
        raise ValueError("DELIVERY_COMPOSE_TARGET_INVALID")
    if (not isinstance(task, str) or not task.strip()
            or len(task) > 8000 or "\x00" in task):
        raise ValueError("DELIVERY_COMPOSE_TASK_INVALID")
    db = store._connect()
    try:
        db.execute("PRAGMA query_only=ON")
        group = db.execute(
            "SELECT active FROM conversation_network_projects WHERE project_id=?",
            (scope_id,),
        ).fetchone()
        if group is None or not bool(group["active"]):
            raise ValueError("DELIVERY_COMPOSE_SCOPE_NOT_ACTIVE")
        roster = _members(db, scope_id)
    finally:
        db.close()
    by_key = {str(item["conversation_key"]).lower(): item for item in roster}
    if manager not in by_key or worker not in by_key:
        raise ValueError("DELIVERY_COMPOSE_TARGET_NOT_IN_SCOPE")
    if len(roster) > 40:
        raise ValueError("DELIVERY_COMPOSE_ROSTER_TOO_LARGE")
    keys = [item["conversation_key"] for item in roster]
    labels = node_labels_for_conversations(store, conversation_keys=keys)
    members = [
        {"conversation_uuid": item["conversation_key"],
         "node_label": labels.get(item["conversation_key"], ""),
         "name": item["display_name"],
         "role_tags": list(item["role_tags"])}
        for item in roster
    ]
    # The binding is a per-message observation, not a mutable source of
    # identity or a permission to re-route the already prepared Delivery.
    settings = read_relay_settings(scope_id)
    scope = {}
    run = None
    try:
        view = project_run_scope_view(store, scope_id=scope_id)
    except (KeyError, ValueError):
        view = {}
    scope = view.get("scope") or {}
    run = view.get("active_run")
    work_goal = ""
    if work_id:
        work_goal = store.get_work(work_id).request_summary
    optional = {
        "project": str(settings["project_display_name"] or
                       (scope.get("project") or {}).get("display_name") or "")[:200],
        "project_goal": str(settings["project_goal"] or
                            (run or {}).get("objective") or work_goal)[:4000],
        "completion_criteria": settings["completion_criteria"],
        "project_context_note": settings["project_context_note"],
        "current_members": members,
    }
    body = {
        "schema": 1,
        "settings_sha256": settings["config_sha256"],
        "scope_id": scope_id,
        "work_id": work_id,
        "manager_conversation_uuid": manager,
        "worker_conversation_uuid": worker,
    }
    for field in settings["worker_context_fields"]:
        body[field] = optional[field]
    body.update({
        "role": "WORKER",
        "task": task,
        "return_instruction": settings["worker_return_instruction"],
    })
    if settings["worker_additional_instruction"]:
        body["additional_instruction"] = settings["worker_additional_instruction"]
    prompt = (
        settings["worker_intro"] + "\n" + settings["worker_context_notice"] + "\n"
        "[BCT_DELIVERY_WORKER_V1]"
        + json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        + "[/BCT_DELIVERY_WORKER_V1]"
    )
    if utf16_units(prompt) > 12000:
        raise ValueError("DELIVERY_COMPOSE_MESSAGE_TOO_LARGE")
    return prompt


def compose_manager_return_frame(
    *, store, work_id: str, delivery_id: str,
    manager_conversation_key: str, worker_conversation_key: str,
    scope_id: str = "", original_task: str = "",
    worker_result_sha256: str = "",
) -> tuple[str, str, str]:
    """Prepare one Manager return around the FULL current-turn Worker result.

    RCC owns the captured response. It inserts that text between these
    frames, hash-fences the single message, and submits exactly once.
    """
    settings = read_relay_settings(scope_id)
    work = store.get_work(work_id)
    scope = {}
    run = None
    if scope_id:
        try:
            view = project_run_scope_view(store, scope_id=scope_id)
        except (KeyError, ValueError):
            view = {}
        scope = view.get("scope") or {}
        run = view.get("active_run")
    context = {
        "schema": 1,
        "work_id": work_id,
        "delivery_id": delivery_id,
        "scope_id": scope_id,
        "manager_conversation_uuid": manager_conversation_key,
        "worker_conversation_uuid": worker_conversation_key,
        "worker_result_sha256": worker_result_sha256,
        "settings_sha256": settings["config_sha256"],
    }
    optional = {
        "project": str(settings["project_display_name"] or
                       (scope.get("project") or {}).get("display_name") or "")[:200],
        "project_goal": str(settings["project_goal"] or
                            (run or {}).get("objective") or work.request_summary)[:4000],
        "completion_criteria": settings["completion_criteria"],
        "project_context_note": settings["project_context_note"],
        "current_members": [
            {"node": member.get("node_label"), "role_tags": member.get("role_tags", []),
             "monitor_match": member.get("monitor_match")}
            for member in scope.get("members", [])[:settings["manager_member_limit"]]
        ],
        "project_run_state": str((run or {}).get("state") or ""),
        "original_worker_task": original_task[:8000],
    }
    for field in settings["manager_context_fields"]:
        context[field] = optional[field]
    pieces = {
        "context": (
            settings["manager_intro"]
            + "\n[BCT_MANAGER_RETURN_CONTEXT_V1]"
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
            + "[/BCT_MANAGER_RETURN_CONTEXT_V1]\n"
        ),
        "worker_result": "\n[BCT_CURRENT_WORKER_RESULT_FULL]\n",
        "action": "\n" + "\n".join(
            item for item in (
                settings["manager_result_notice"],
                settings["manager_action"],
                settings["manager_additional_instruction"],
            ) if item
        ) + "\n",
    }
    before = []
    after = []
    current = before
    for section in settings["manager_sections"]:
        if section == "worker_result":
            current.append(pieces[section])
            current = after
            current.append("\n[/BCT_CURRENT_WORKER_RESULT_FULL]\n")
        else:
            current.append(pieces[section])
    return "".join(before), "".join(after), settings["config_sha256"]


def preview_delivery_messages(
    *, store, work_id: str, delivery_id: str, scope_id: str,
    manager_conversation_key: str, worker_conversation_key: str,
    task: str, worker_result_preview: str,
) -> dict[str, object]:
    """Compose both exact messages without creating a Delivery or calling RCC."""
    if (not isinstance(worker_result_preview, str)
            or not worker_result_preview.strip() or "\x00" in worker_result_preview
            or utf16_units(worker_result_preview) > 12000):
        raise ValueError("DELIVERY_PREVIEW_WORKER_RESULT_INVALID")
    expected_revision = read_relay_settings(scope_id)["config_sha256"]
    worker_message = compose_worker_delivery(
        store=store, work_id=work_id, scope_id=scope_id,
        manager_conversation_key=manager_conversation_key,
        worker_conversation_key=worker_conversation_key, task=task,
    )
    header, footer, manager_revision = compose_manager_return_frame(
        store=store, work_id=work_id, delivery_id=delivery_id,
        manager_conversation_key=manager_conversation_key,
        worker_conversation_key=worker_conversation_key,
        scope_id=scope_id, original_task=task,
        worker_result_sha256=hashlib.sha256(
            worker_result_preview.encode("utf-8")
        ).hexdigest(),
    )
    if manager_revision != expected_revision or expected_revision not in worker_message:
        raise ValueError("DELIVERY_PREVIEW_SETTINGS_CHANGED")
    manager_message = header + worker_result_preview + footer
    return {
        "effect": "NONE_PREVIEW_ONLY",
        "settings_sha256": expected_revision,
        "scope_id": scope_id,
        "work_id": work_id,
        "delivery_id": delivery_id,
        "manager_conversation_uuid": str(manager_conversation_key).lower(),
        "worker_conversation_uuid": str(worker_conversation_key).lower(),
        "worker_message": {
            "text": worker_message,
            "sha256": hashlib.sha256(worker_message.encode("utf-8")).hexdigest(),
            "utf16_units": utf16_units(worker_message),
            "fits_current_limit": utf16_units(worker_message) <= 12000,
        },
        "manager_return_message": {
            "text": manager_message,
            "sha256": hashlib.sha256(manager_message.encode("utf-8")).hexdigest(),
            "utf16_units": utf16_units(manager_message),
            "fits_current_limit": utf16_units(manager_message) <= 12000,
            "worker_result_sha256": hashlib.sha256(
                worker_result_preview.encode("utf-8")
            ).hexdigest(),
        },
    }
