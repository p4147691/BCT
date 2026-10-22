"""Shared BCT prompt composition for an existing Project Run Delivery.

Not a transport, role privilege, or a new message queue. Read the one
canonical ACTIVE conversation roster and human-editable role note each time
a *new* delivery is prepared. The resulting exact bytes are SHA-fenced by
the existing Delivery Ledger. No implicit resend on roster changes.
"""
from __future__ import annotations

import json
import re

from bct.conversation_network import node_labels_for_conversations
from bct.project_run import _members

_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z", re.I)
_SCOPE = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")


def compose_worker_delivery(
    *, store, scope_id: str, manager_conversation_key: str,
    worker_conversation_key: str, task: str,
) -> str:
    """Compute a static-once prompt from fresh advisory group membership.

    Roles never grant a BCT capability; the coordinator separately checks
    Work policy, live RCC route and immutable operation/Delivery ID.
    """
    from bct.features.orchestration import _relay_note

    if not isinstance(scope_id, str) or not _SCOPE.fullmatch(scope_id):
        raise ValueError("DELIVERY_COMPOSE_SCOPE_INVALID")
    manager = str(manager_conversation_key or "").lower()
    worker = str(worker_conversation_key or "").lower()
    if (not _UUID.fullmatch(manager) or not _UUID.fullmatch(worker)
            or manager == worker):
        raise ValueError("DELIVERY_COMPOSE_TARGET_INVALID")
    if (not isinstance(task, str) or not task.strip()
            or len(task) > 4000 or "\x00" in task):
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
    body = {
        "schema": 1,
        "scope_id": scope_id,
        "manager_conversation_uuid": manager,
        "worker_conversation_uuid": worker,
        "current_members": members,
        "role": "WORKER",
        "role_note": _relay_note("worker"),
        "task": task,
        "return_instruction": (
            "업무를 수행하고 완료·미완료·검증 사항을 실제 결과에 맞춰 "
            "마지막 답변에 작성하세요. 요청에 4줄 요약이 있으면 그 형식을 지키세요. "
            "BCT Delivery가 이 결과를 Manager에게 전달합니다. "
            "실제로 접근할 수 없는 도구를 호출했다고 주장하지 마세요. "
            "다른 대화에 같은 결과를 직접 중복 전송하지 마세요."
        ),
    }
    prompt = (
        "BCT 협업 작업입니다. 구성원 명단과 역할 태그는 참고 정보이며 "
        "실행 권한이나 다른 노드에 대한 전송 허가는 아닙니다. "
        "다음 JSON의 task를 수행하세요.\n"
        "[BCT_DELIVERY_WORKER_V1]"
        + json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "[/BCT_DELIVERY_WORKER_V1]"
    )
    if len(prompt) > 12000:
        raise ValueError("DELIVERY_COMPOSE_MESSAGE_TOO_LARGE")
    return prompt
