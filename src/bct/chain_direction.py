"""Question-guided A directions and their exact per-target instructions.

The caller AI answers the questions. BCT supplies current evidence, validates
the answers and keeps their relationship to each delivery; it is not an LLM.
"""
from __future__ import annotations

import time
import re
import hashlib
import json
import sqlite3
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_DECISIONS = {"COMPLETE", "NEW_TASK", "ASK_USER", "HOLD"}
_SOURCES = {"USER", "MANAGER_RETURN"}
_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")
_BRANCH_KINDS = {"PRIMARY", "DELIVERY", "OBSERVATION", "DIAGNOSIS", "FIX", "VERIFICATION", "RESUME"}
_BRANCH_STATES = {
    "READY", "IN_PROGRESS", "WAITING_INPUT", "WAITING_EXTERNAL",
    "IDENTITY_MISMATCH", "CHECK_FAILED", "NOT_APPLIED", "UNKNOWN",
    "BLOCKED", "COMPLETED",
}

# These are questions for A, not an additional questionnaire for the user.
DIRECTION_QUESTIONS = (
    ("intent", "사용자 의도", "원문 또는 반환 보고에서 사용자가 실제로 원하는 결과는 무엇인가? 이전 목표를 유지하면서 무엇을 보완해야 하는가?"),
    ("acceptance", "완료 기준", "무엇을 직접 확인하면 완료인가? 이미 끝난 것, 남은 것, 아직 확인하지 못한 것을 구분하라."),
    ("scope", "범위와 조건", "허용 범위, 금지사항, 우선순위, 보존할 사용자 작업과 외부 효과는 무엇인가? 모르는 것은 어떻게 확인할 것인가?"),
    ("network", "대화망 선택", "열린 Node Info(우클릭 정보)의 대화망·역할·담당 작업·메모와 저장된 대화망 이력을 비교하라. 재사용·신규·병합 중 무엇을 왜 선택하는가?"),
    ("manager", "Manager", "지시를 받은 A가 어떤 대화망의 Manager가 되는가? 기존 Manager가 있으면 어떤 기록을 보존하고 역할을 넘겨받는가?"),
    ("supervisor", "Supervisor", "전역 Supervisor 하나를 어떻게 유지하는가? 없거나 닫혔으면 기존 노드 재사용·새 노드 준비·승계를 판단하고, 여럿이면 역할을 하나로 정리하라."),
    ("delegation", "대상별 분담", "AB·AC·AD 중 필요한 대상 수와 각각 맡길 일은 무엇인가? 독립 작업과 순서 의존성을 구분하고 각 대상에 별도 지시문을 작성하라."),
    ("resources", "자율 선택", "필요한 부품·모듈·블럭·레시피·프로그램·PowerShell·BDC·브라우저 기능은 무엇인가? 창·탭 생성/이동/정리 계획과 B의 자율 선택 범위를 정하라. 등록·허용된 실제 기능을 확인하라."),
    ("recovery", "정체와 승계", "Manager·Worker·Supervisor가 멈추면 Check Node → Recheck Node → Pause Node → Replace Node → Reset Node 중 무엇을 사용하는가? 기존 영수증과 UNKNOWN을 보존하라."),
    ("integration", "검증과 반환", "각 Worker는 Worktree의 필요한 로컬 검증과 증거 보고만 하는가, 아니면 예외적으로 PR/push가 필요한가? 통합 PR·main 병합·main CI·E2E를 맡을 정확한 대상 하나와 순서를 정하라. PR은 가벼운 범위/설명서 확인이고 전체 CI는 main 뒤에 실행됨을 반영하라. 비동기 CI 알림, rollback, 대상의 SELF/A 반환 조건을 정하라."),
)


def direction_assessment_contract(value: Any = None, *, reason: str = "") -> dict[str, Any]:
    """Return recovery-safe schema guidance for the fields that actually failed."""
    answers = value.get("answers") if isinstance(value, dict) else None
    expected_answers = [key for key, _, _ in DIRECTION_QUESTIONS]
    answer_keys = set(answers) if isinstance(answers, dict) else set()
    targets = value.get("targets") if isinstance(value, dict) else None
    target_diagnostics = []
    if isinstance(targets, list):
        for index, target in enumerate(targets):
            diagnostic = {"index": index, "issues": []}
            if not isinstance(target, dict):
                diagnostic["issues"].append("target must be an object")
                diagnostic["received_fields"] = []
            else:
                expected_fields = {"conversation_key", "role", "instruction"}
                if set(target) != expected_fields:
                    diagnostic["issues"].append("target fields do not match the contract")
                    diagnostic["received_fields"] = sorted(target)
                conversation_key = target.get("conversation_key")
                if not isinstance(conversation_key, str) or not _UUID.fullmatch(conversation_key):
                    diagnostic["issues"].append("conversation_key must be a lowercase canonical UUID")
                if (not isinstance(target.get("role"), str)
                        or not target["role"].strip() or len(target["role"]) > 80):
                    diagnostic["issues"].append("role must be a non-empty label of at most 80 characters")
                instruction = target.get("instruction")
                if (not isinstance(instruction, str) or not instruction.strip()
                        or len(instruction) > 6000):
                    diagnostic["issues"].append(
                        "instruction must be a non-empty string of at most 6000 characters")
            if diagnostic["issues"]:
                diagnostic["expected_fields"] = ["conversation_key", "role", "instruction"]
                target_diagnostics.append(diagnostic)
    return {
        "reason": reason,
        "answers": {
            "required_keys": [],
            "guidance_keys": expected_answers,
            "missing_guidance_keys": sorted(set(expected_answers) - answer_keys),
            "unexpected_keys": sorted(answer_keys - set(expected_answers)),
            "value_rule": "answers are optional A reasoning notes; each provided value must be a non-empty string of at most 4000 characters",
        },
        "required_for_new_task": {
            "manager_conversation_key": "A's return destination: lowercase canonical ChatGPT conversation UUID; not a Monitor node number",
            "worker_conversation_key": "the one existing initial Worker UUID; omit only when worker_preparations declares the initial Worker to create",
            "supervisor_conversation_key": "the one global Supervisor UUID; it must differ from Manager and Worker",
            "targets": [{
                "conversation_key": "lowercase canonical ChatGPT conversation UUID; not N96 or a tab title",
                "role": "A's free-form role label, for example worker, reviewer, or deployer",
                "instruction": "non-empty per-target instruction, at most 6000 characters",
            }],
            "network_updates": "list of existing bct_set_conversation_network argument objects; [] is valid when reusing the network unchanged. Select topology in this order: an existing global Supervisor, then an unassigned idle Worker; create only the missing node. Never select a Manager from another network as Worker or Supervisor.",
            "worker_preparations": "optional persisted create-chat-tab/window requests for missing Workers; execute one by preparation_id through bct_chain_recipe(action='provision_worker')",
        },
        "optional_node_recovery": {
            "conversation_key": "the exact lowercase canonical UUID of one node A explicitly asks Recover Node R to observe before sending",
        },
        "optional_derived_tasks": {
            "contract": "Manager-declared derived work; BCT validates the classification and safe immediate dispatch set but does not infer a task from prose.",
            "classification": ["SELF", "INDEPENDENT", "BLOCKED", "RISK", "ASK_USER"],
            "independent_rule": "An INDEPENDENT task names one declared target, has no unresolved depends_on entries, and may not share mutable_scopes with another INDEPENDENT task.",
            "deferred_rule": "BLOCKED, RISK, ASK_USER, SELF, and dependent INDEPENDENT tasks are stored as Manager evidence and are not sent by this Direction.",
        },
        "target_diagnostics": target_diagnostics,
        "recovery": "Correct only the reported fields, re-enter bct_chain_recipe(action='prepare'), then call bct_chain_recipe(action='save') with its current entry_context_id and the same intended direction_id. Read the saved record with bct_get_direction before starting.",
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def direction_source_evidence(source_kind: str) -> str:
    # A user request copied into an MCP argument is not authenticated chat-turn evidence.
    return "VERIFIED_MANAGER_RETURN" if source_kind == "MANAGER_RETURN" else "CALLER_PROVIDED_TEXT"


def validate_direction_assessment(value: dict, *, decision: str) -> dict:
    """Validate A's declared decisions without pretending to evaluate prose."""
    if not isinstance(value, dict) or set(value) - {
        "answers", "manager_conversation_key", "worker_conversation_key", "supervisor_conversation_key",
        "network_name", "targets", "network_updates", "node_recovery", "derived_tasks",
        "worker_preparations",
    }:
        raise ValueError("DIRECTION_ASSESSMENT_INVALID")
    answers = value.get("answers", {})
    guidance_keys = {key for key, _, _ in DIRECTION_QUESTIONS}
    if (not isinstance(answers, dict) or set(answers) - guidance_keys
            or any(not isinstance(v, str) or not v.strip() or len(v) > 4000
                   for v in answers.values())):
        raise ValueError("DIRECTION_ANSWERS_INVALID")
    value = {**value, "answers": answers}
    targets = value.get("targets", [])
    preparations = value.get("worker_preparations", [])
    updates = value.get("network_updates", [])
    recovery = value.get("node_recovery")
    if (not isinstance(targets, list) or not isinstance(updates, list)
            or not isinstance(preparations, list)):
        raise ValueError("DIRECTION_TARGETS_INVALID")
    if recovery is not None:
        if (not isinstance(recovery, dict) or set(recovery) != {"conversation_key"}
                or not isinstance(recovery["conversation_key"], str)
                or not _UUID.fullmatch(recovery["conversation_key"])):
            raise ValueError("DIRECTION_NODE_RECOVERY_INVALID")
        value["node_recovery"] = {"conversation_key": recovery["conversation_key"]}
    if decision != "NEW_TASK" and (targets or updates or recovery is not None
                                    or preparations or value.get("derived_tasks") is not None):
        raise ValueError("DIRECTION_TERMINAL_HAS_ACTIONS")
    if decision == "NEW_TASK":
        required_identities = ["manager_conversation_key", "supervisor_conversation_key"]
        if not preparations:
            required_identities.append("worker_conversation_key")
        for field in required_identities:
            if (not isinstance(value.get(field), str) or not _UUID.fullmatch(value[field])):
                raise ValueError("DIRECTION_" + field.upper() + "_REQUIRED")
        identities = [value[field] for field in required_identities]
        if len(set(identities)) != len(identities):
            raise ValueError("DIRECTION_TOPOLOGY_IDENTITIES_MUST_DIFFER")
        if "network_name" in value and (not isinstance(value["network_name"], str)
                                        or len(value["network_name"]) > 200):
            raise ValueError("DIRECTION_NETWORK_INVALID")
        if not targets and not preparations:
            raise ValueError("DIRECTION_TARGETS_REQUIRED")
    if preparations:
        from bct.chain_worker_preparation import validate_worker_preparation
        normalized_preparations = [validate_worker_preparation(item) for item in preparations]
        preparation_ids = [item["preparation_id"] for item in normalized_preparations]
        if len(preparation_ids) != len(set(preparation_ids)) or len(preparation_ids) > 32:
            raise ValueError("CHAIN_WORKER_PREPARATION_ID_CONFLICT")
        value["worker_preparations"] = normalized_preparations
    keys = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"conversation_key", "role", "instruction"}:
            raise ValueError("DIRECTION_TARGET_INVALID")
        key = target["conversation_key"]
        if not isinstance(key, str) or not _UUID.fullmatch(key) or key in keys:
            raise ValueError("DIRECTION_TARGET_CONFLICT")
        keys.add(key)
        if (not isinstance(target["role"], str) or not target["role"].strip()
                or len(target["role"]) > 80):
            raise ValueError("DIRECTION_TARGET_ROLE_INVALID")
        if not isinstance(target["instruction"], str) or not target["instruction"].strip() or len(target["instruction"]) > 6000:
            raise ValueError("DIRECTION_TARGET_INSTRUCTION_REQUIRED")
    if (decision == "NEW_TASK" and not preparations
            and value["worker_conversation_key"] not in keys):
        raise ValueError("DIRECTION_WORKER_TARGET_REQUIRED")
    if "derived_tasks" in value:
        from bct.chain_derived_tasks import validate_derived_tasks
        value["derived_tasks"] = validate_derived_tasks(
            value["derived_tasks"], target_keys=keys,
        )
    # Resource bounds, not a cap on autonomous SELF continuation.
    if len(_json(value)) > 90000 or len(targets) > 32 or len(updates) > 64:
        raise ValueError("DIRECTION_ASSESSMENT_TOO_LARGE")
    return json.loads(_json(value))


def resolve_direction_target(*, snapshot: dict, conversation_key: str) -> dict:
    """Resolve the same UUID after a tab/window move, never by title or order."""
    from bct.status_views import status_view
    nodes = status_view(snapshot, "node").get("current_nodes", {})
    if nodes.get("observation", {}).get("state") != "FRESH":
        raise ValueError("DIRECTION_NODES_NOT_FRESH")
    matches = [n for n in nodes.get("items", []) if n.get("status") == "CONFIRMED"
               and n.get("conversation_uuid") == conversation_key]
    if len(matches) != 1:
        raise ValueError("DIRECTION_TARGET_NOT_UNIQUE_OR_OPEN")
    attachments = []
    for instance in status_view(snapshot, "rcc").get("rcc", {}).get("instances", []):
        if instance.get("state") != "OPEN" or instance.get("cached") is True:
            continue
        for tab in instance.get("tabs", []):
            if tab.get("presence") == "OPEN" and tab.get("conversation_key") == conversation_key:
                if (not re.fullmatch(r"[a-f0-9]{32}", str(instance.get("instance_id", "")))
                        or not re.fullmatch(r"[a-f0-9]{32}", str(instance.get("session_id", "")))
                        or type(tab.get("tab_id")) is not int or tab["tab_id"] <= 0
                        or type(tab.get("window_id")) is not int or tab["window_id"] <= 0):
                    raise ValueError("DIRECTION_ATTACHMENT_INVALID")
                attachments.append({"instance_id": instance["instance_id"],
                                    "session_id": instance["session_id"],
                                    "tab_id": tab["tab_id"], "window_id": tab["window_id"]})
    if len(attachments) != 1:
        raise ValueError("DIRECTION_ATTACHMENT_NOT_UNIQUE_OR_OPEN")
    if any(matches[0].get(key) != attachments[0][key] for key in ("tab_id", "window_id")):
        raise ValueError("DIRECTION_NODE_ATTACHMENT_MISMATCH")
    return {**attachments[0], "node_info": matches[0]}


def resolve_direction_network(*, snapshot: dict, assessment: dict, targets: list) -> tuple:
    """Resolve a declared Manager–Worker–Supervisor topology before delivery.

    This is a proof gate, not an election or creation mechanism: A must name
    the three identities and current Node Info/RCC must still resolve each one.
    A Manager is never reusable as a Worker or Supervisor, including when it
    belongs to a different conversation network.
    """
    origin = resolve_direction_target(snapshot=snapshot, conversation_key=assessment["manager_conversation_key"])
    worker = resolve_direction_target(snapshot=snapshot, conversation_key=assessment["worker_conversation_key"])
    supervisor = resolve_direction_target(snapshot=snapshot, conversation_key=assessment["supervisor_conversation_key"])
    if len({assessment["manager_conversation_key"], assessment["worker_conversation_key"],
            assessment["supervisor_conversation_key"]}) != 3:
        raise ValueError("DIRECTION_TOPOLOGY_IDENTITIES_MUST_DIFFER")
    def has_role(route: dict, role: str) -> bool:
        roles = route["node_info"].get("roles")
        return isinstance(roles, list) and any(str(item).strip().casefold() == role for item in roles)
    if not has_role(origin, "manager"):
        raise ValueError("DIRECTION_MANAGER_ROLE_NOT_CONFIRMED")
    if has_role(origin, "worker") or has_role(origin, "supervisor"):
        raise ValueError("DIRECTION_MANAGER_ROLE_CONFLICT")
    if has_role(worker, "manager"):
        raise ValueError("DIRECTION_WORKER_CANNOT_BE_MANAGER")
    if not has_role(worker, "worker"):
        raise ValueError("DIRECTION_WORKER_ROLE_NOT_CONFIRMED")
    if has_role(worker, "supervisor"):
        raise ValueError("DIRECTION_WORKER_ROLE_CONFLICT")
    if has_role(supervisor, "manager"):
        raise ValueError("DIRECTION_SUPERVISOR_CANNOT_BE_MANAGER")
    if has_role(supervisor, "worker"):
        raise ValueError("DIRECTION_SUPERVISOR_CANNOT_BE_WORKER")
    if not has_role(supervisor, "supervisor"):
        raise ValueError("DIRECTION_SUPERVISOR_ROLE_NOT_CONFIRMED")
    manager_scope = str(origin["node_info"].get("network_id") or origin["node_info"].get("network") or "").strip()
    worker_scope = str(worker["node_info"].get("network_id") or worker["node_info"].get("network") or "").strip()
    supervisor_scope = str(supervisor["node_info"].get("network_id") or supervisor["node_info"].get("network") or "").strip()
    if not manager_scope or manager_scope != worker_scope:
        raise ValueError("DIRECTION_MANAGER_WORKER_NETWORK_MISMATCH")
    if supervisor_scope:
        raise ValueError("DIRECTION_SUPERVISOR_MUST_BE_GLOBAL")
    resolved = []
    for i, target in targets:
        route = resolve_direction_target(snapshot=snapshot, conversation_key=target["conversation_key"])
        resolved.append((i, target, route))
    return origin, resolved


def target_direction_id(direction: dict, target: dict) -> str:
    suffix = hashlib.sha256((direction["direction_id"] + ":" + target["conversation_key"]).encode()).hexdigest()[:24]
    return "direction-" + suffix


def current_work_context_block(*, direction: dict, child_direction_id: str,
                               target_conversation_key: str, task_id: str,
                               delivery_kind: str = "DELIVERY") -> str:
    """Compose a bounded local context card for one recipient.

    This is intentionally not a second instruction, authority rule, or a
    durable conversation-network mutation.  The Manager's direction remains
    the text above it.  The card gives a child enough positional awareness to
    return evidence through the same Root Work without copying the entire
    network into every message.
    """
    root_work_id = str(direction.get("root_work_id") or direction.get("work_id") or "")
    parent_work_id = str(direction.get("work_id") or "")
    parent_direction_id = str(direction.get("direction_id") or "")
    upstream_direction_id = str(direction.get("parent_direction_id") or "")
    upstream_kind = str(direction.get("branch_kind") or "PRIMARY")
    upstream_step = str(direction.get("parent_step_id") or "")
    upstream_reason = str(direction.get("branch_reason") or "")
    lines = [
        "[현재 작업 맥락 — 참고 정보, 새 지시 아님]",
        f"root_work_id={root_work_id}",
        f"local_direction_id={child_direction_id}",
        f"parent_work_id={parent_work_id}",
        f"parent_direction_id={parent_direction_id}",
        f"task_id={task_id}; target_conversation_uuid={target_conversation_key}",
        f"local_kind={delivery_kind}; local_state=READY_TO_SEND",
    ]
    if upstream_direction_id:
        lines.append(f"upstream_parent_direction_id={upstream_direction_id}")
        lines.append(f"upstream_kind={upstream_kind}; upstream_step={upstream_step or 'UNSPECIFIED'}")
        if upstream_reason:
            lines.append(f"upstream_branch_reason={upstream_reason}")
    lines.extend([
        "반환/새 분기 요청은 이 Root Work와 정확한 Direction·Task·영수증에 연결한다.",
        "이 카드는 현재 위치 안내일 뿐, 대상 선택·새 노드 생성·재전송 판단은 Manager의 다음 Chain Recipe가 한다.",
        "[/현재 작업 맥락]",
    ])
    return "\n".join(lines)


def compose_target_direction(*, direction: dict, target: dict, task_id: str,
                             recorded_direction: dict | None = None) -> tuple[str, str]:
    """Compose a new instruction, or preserve its exact recorded predecessor."""
    assessment = json.loads(direction.get("assessment_json") or "{}")
    if target not in assessment.get("targets", []):
        raise ValueError("DIRECTION_TARGET_NOT_DECLARED")
    child_id = target_direction_id(direction, target)
    # A new manual must never rewrite an already recorded instruction/digest.
    if recorded_direction is not None:
        expected = {"direction_id": child_id, "work_id": direction["work_id"],
                    "parent_direction_id": direction["direction_id"],
                    "target_conversation_key": target["conversation_key"], "decision": "NEW_TASK"}
        expected.update({key: direction[key] for key in (
            "source_kind", "source_task_id", "source_generation", "source_result_sha256")})
        if any(recorded_direction.get(key) != value for key, value in expected.items()):
            raise ValueError("DIRECTION_TARGET_RECORD_MISMATCH")
        return child_id, recorded_direction["direction_text"]
    from bct.component_library import get_manual_guidance
    guidance = get_manual_guidance()
    if guidance["status"] != "AVAILABLE":
        raise ValueError("MANUAL_GUIDANCE_UNAVAILABLE")
    context = current_work_context_block(
        direction=direction, child_direction_id=child_id,
        target_conversation_key=target["conversation_key"], task_id=task_id,
    )
    text = (direction["direction_text"] + "\n\n이번 대상에게 맡기는 일:\n" + target["instruction"]
            + f"\n\n이번 대상의 역할: {target['role']}. 이 작업의 실행계획과 결과는 다음 식별값에 연결한다: "
            + f"work_id={direction['work_id']}, direction_id={child_id}, task_id={task_id}, generation=1. "
            + "\n\n" + context
            + f"\n\n공통 설명서의 노드 안내 (manual SHA-256: {guidance['manual_sha256']}):\n"
            + guidance["text"])
    from bct.chain_message_preflight import prepare_chain_instruction
    # Include the actual marker suffix in the size check before any effects.
    prepare_chain_instruction(text, output_contract="explicit-next-task-v1")
    return child_id, text


def compose_prepared_worker_direction(
    *, direction: dict, preparation_id: str, conversation_key: str,
    role: str, instruction: str, task_id: str,
    recorded_direction: dict | None = None,
) -> tuple[str, str]:
    """Compose one receipt-bound child Direction for a newly prepared Worker."""
    suffix = hashlib.sha256(
        (direction["direction_id"] + ":prepared:" + preparation_id).encode()
    ).hexdigest()[:24]
    child_id = "direction-" + suffix
    if recorded_direction is not None:
        expected = {
            "direction_id": child_id, "work_id": direction["work_id"],
            "parent_direction_id": direction["direction_id"],
            "target_conversation_key": conversation_key, "decision": "NEW_TASK",
        }
        expected.update({key: direction[key] for key in (
            "source_kind", "source_task_id", "source_generation", "source_result_sha256"
        )})
        if any(recorded_direction.get(key) != value for key, value in expected.items()):
            raise ValueError("DIRECTION_PREPARED_WORKER_RECORD_MISMATCH")
        return child_id, recorded_direction["direction_text"]
    from bct.component_library import get_manual_guidance
    guidance = get_manual_guidance()
    if guidance["status"] != "AVAILABLE":
        raise ValueError("MANUAL_GUIDANCE_UNAVAILABLE")
    context = current_work_context_block(
        direction=direction, child_direction_id=child_id,
        target_conversation_key=conversation_key, task_id=task_id,
    )
    text = (
        direction["direction_text"] + "\n\n이번 대상에게 맡기는 일:\n" + instruction
        + f"\n\n이번 대상의 역할: {role}. 이 작업의 실행계획과 결과는 다음 식별값에 연결한다: "
        + f"work_id={direction['work_id']}, direction_id={child_id}, "
        + f"task_id={task_id}, generation=1. "
        + "\n\n" + context
        + f"\n\n공통 설명서의 노드 안내 (manual SHA-256: {guidance['manual_sha256']}):\n"
        + guidance["text"]
    )
    from bct.chain_message_preflight import prepare_chain_instruction
    prepare_chain_instruction(text, output_contract="explicit-next-task-v1")
    return child_id, text


class ChainDirectionLedger:
    """Store an A decision and its free-form direction without sending."""

    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_directions (
                    direction_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    source_generation INTEGER NOT NULL,
                    source_result_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    direction_text TEXT NOT NULL,
                    chain_task_id TEXT NOT NULL DEFAULT '',
                    chain_operation_id TEXT NOT NULL DEFAULT '',
                    chain_send_operation_id TEXT NOT NULL DEFAULT '',
                    chain_state TEXT NOT NULL DEFAULT 'NOT_PLANNED',
                    recipe_state TEXT NOT NULL DEFAULT 'LEGACY_UNCLASSIFIED',
                    next_safe_step TEXT NOT NULL DEFAULT 'INSPECT_DIRECTION',
                    recipe_reason TEXT NOT NULL DEFAULT '',
                    root_work_id TEXT NOT NULL DEFAULT '',
                    parent_work_id TEXT NOT NULL DEFAULT '',
                    parent_step_id TEXT NOT NULL DEFAULT '',
                    branch_kind TEXT NOT NULL DEFAULT 'PRIMARY',
                    branch_reason TEXT NOT NULL DEFAULT '',
                    branch_request_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(chain_directions)")}
            for name, default in (("assessment_json", "{}"), ("source_text", ""),
                                  ("parent_direction_id", ""), ("target_conversation_key", ""),
                                  ("recipe_state", "LEGACY_UNCLASSIFIED"),
                                  ("next_safe_step", "INSPECT_DIRECTION"),
                                  ("recipe_reason", ""),
                                  ("root_work_id", ""), ("parent_work_id", ""),
                                  ("parent_step_id", ""), ("branch_kind", "PRIMARY"),
                                  ("branch_reason", ""), ("branch_request_id", "")):
                if name not in columns:
                    db.execute(f"ALTER TABLE chain_directions ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_branch_requests (
                    request_id TEXT PRIMARY KEY,
                    root_work_id TEXT NOT NULL,
                    parent_work_id TEXT NOT NULL,
                    parent_direction_id TEXT NOT NULL,
                    parent_step_id TEXT NOT NULL,
                    parent_task_id TEXT NOT NULL,
                    parent_generation INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    exact_refs_json TEXT NOT NULL,
                    required INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    state_reason TEXT NOT NULL,
                    next_safe_step TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    child_direction_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    @staticmethod
    def _validate(*, direction_id: str, work_id: str, source_kind: str,
                  source_task_id: str, source_generation: int,
                  source_result_sha256: str, decision: str,
                  direction_text: str) -> None:
        if not all(isinstance(value, str) and _ID.fullmatch(value)
                   for value in (direction_id, work_id)):
            raise ValueError("CHAIN_DIRECTION_ID_INVALID")
        if source_kind not in _SOURCES or decision not in _DECISIONS:
            raise ValueError("CHAIN_DIRECTION_STATE_INVALID")
        if not isinstance(direction_text, str) or not direction_text.strip() or len(direction_text) > 12000:
            raise ValueError("CHAIN_DIRECTION_TEXT_INVALID")
        if source_kind == "MANAGER_RETURN":
            if (not isinstance(source_task_id, str) or not _ID.fullmatch(source_task_id)
                    or type(source_generation) is not int or source_generation < 1
                    or not isinstance(source_result_sha256, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", source_result_sha256)):
                raise ValueError("CHAIN_DIRECTION_RETURN_SOURCE_INVALID")
        elif source_task_id or source_generation or source_result_sha256:
            raise ValueError("CHAIN_DIRECTION_USER_SOURCE_INVALID")

    def save(self, *, direction_id: str, work_id: str, source_kind: str,
             source_task_id: str = "", source_generation: int = 0,
             source_result_sha256: str = "", decision: str,
             direction_text: str, assessment: dict | None = None,
             source_text: str = "", parent_direction_id: str = "",
             target_conversation_key: str = "", parent_work_id: str = "",
             parent_step_id: str = "", branch_kind: str = "PRIMARY",
             branch_reason: str = "", branch_request_id: str = "") -> dict[str, Any]:
        self._validate(
            direction_id=direction_id, work_id=work_id, source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_result_sha256=source_result_sha256, decision=decision,
            direction_text=direction_text,
        )
        checked = validate_direction_assessment(assessment, decision=decision) if assessment is not None else {}
        if checked and source_kind == "USER" and (not source_text.strip() or len(source_text) > 12000):
            raise ValueError("CHAIN_DIRECTION_SOURCE_TEXT_REQUIRED")
        if (not isinstance(branch_kind, str) or branch_kind not in _BRANCH_KINDS
                or not isinstance(branch_reason, str) or len(branch_reason) > 2000
                or not isinstance(parent_step_id, str) or len(parent_step_id) > 120):
            raise ValueError("CHAIN_BRANCH_CONTEXT_INVALID")
        if parent_direction_id and not _ID.fullmatch(parent_direction_id):
            raise ValueError("DIRECTION_PARENT_TARGET_INVALID")
        if target_conversation_key and not _UUID.fullmatch(target_conversation_key):
            raise ValueError("DIRECTION_PARENT_TARGET_INVALID")
        if branch_request_id and not _ID.fullmatch(branch_request_id):
            raise ValueError("CHAIN_BRANCH_REQUEST_ID_INVALID")
        if parent_direction_id and not (parent_work_id or target_conversation_key or parent_step_id):
            raise ValueError("CHAIN_BRANCH_PARENT_CONTEXT_REQUIRED")
        assessment_json = _json(checked)
        if decision == "NEW_TASK":
            recipe_state = "READY"
            next_safe_step = "START_CHAIN_RECIPE"
            recipe_reason = (
                "A saved a new direction. The Chain Recipe has not started; "
                "A must supply the exact task, operation, and target boundary."
            )
        else:
            recipe_state = "COMPLETED"
            next_safe_step = "NONE"
            recipe_reason = "This Direction does not declare a new delivery chain."
        proposed = (
            work_id, source_kind, source_task_id, source_generation,
            source_result_sha256, decision, direction_text, assessment_json,
            source_text, parent_direction_id, target_conversation_key,
        )
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[key] for key in (
                    "work_id", "source_kind", "source_task_id", "source_generation",
                    "source_result_sha256", "decision", "direction_text", "assessment_json",
                    "source_text", "parent_direction_id", "target_conversation_key",
                ))
                if actual != proposed:
                    raise ValueError("CHAIN_DIRECTION_CONFLICT")
                # Historical per-target Directions have the old primary
                # defaults. Preserve those receipts verbatim instead of
                # rewriting their newly-added branch metadata on replay.
                if branch_request_id and existing["branch_request_id"] != branch_request_id:
                    raise ValueError("CHAIN_BRANCH_CONTEXT_CONFLICT")
                return {**dict(existing), "assessment": json.loads(existing["assessment_json"]),
                        "source_evidence": direction_source_evidence(existing["source_kind"]), "duplicate": True}
            parent = None
            if parent_direction_id:
                parent = db.execute(
                    "SELECT * FROM chain_directions WHERE direction_id=?", (parent_direction_id,)
                ).fetchone()
                if parent is None or parent["work_id"] != (parent_work_id or work_id):
                    # Existing ledgers can contain a historical per-target
                    # parent pointer which is no longer present. Preserve it
                    # verbatim; only the new explicit branch contract needs
                    # a live, exact parent at write time.
                    if branch_request_id or parent_step_id or branch_kind != "PRIMARY":
                        raise ValueError("CHAIN_BRANCH_PARENT_NOT_FOUND")
                    parent = None
                if parent_direction_id == direction_id:
                    raise ValueError("CHAIN_BRANCH_CYCLE")
            root_work_id = str(parent["root_work_id"] or parent["work_id"]) if parent else work_id
            resolved_parent_work = parent_work_id or (str(parent["work_id"]) if parent else "")
            resolved_step = parent_step_id or ("SEND_DIRECTION" if parent else "")
            resolved_kind = branch_kind
            resolved_reason = branch_reason
            if branch_request_id:
                request = db.execute(
                    "SELECT * FROM chain_branch_requests WHERE request_id=?", (branch_request_id,)
                ).fetchone()
                if request is None or request["root_work_id"] != root_work_id:
                    raise ValueError("CHAIN_BRANCH_REQUEST_NOT_FOUND")
                if request["child_direction_id"] and request["child_direction_id"] != direction_id:
                    raise ValueError("CHAIN_BRANCH_REQUEST_ALREADY_ADOPTED")
                if (parent_direction_id and parent_direction_id != request["parent_direction_id"]
                        or parent_work_id and parent_work_id != request["parent_work_id"]
                        or parent_step_id and parent_step_id != request["parent_step_id"]
                        or branch_kind != "PRIMARY" and branch_kind != request["kind"]):
                    raise ValueError("CHAIN_BRANCH_REQUEST_CONTEXT_MISMATCH")
                parent_direction_id = str(request["parent_direction_id"])
                resolved_parent_work = str(request["parent_work_id"])
                resolved_step = str(request["parent_step_id"])
                resolved_kind = str(request["kind"])
                resolved_reason = str(request["reason"])
            db.execute("""
                INSERT INTO chain_directions(
                    direction_id,work_id,source_kind,source_task_id,source_generation,
                    source_result_sha256,decision,direction_text,assessment_json,
                    source_text,parent_direction_id,target_conversation_key,
                    recipe_state,next_safe_step,recipe_reason,root_work_id,parent_work_id,
                    parent_step_id,branch_kind,branch_reason,branch_request_id,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (direction_id, work_id, source_kind, source_task_id, source_generation,
                  source_result_sha256, decision, direction_text, assessment_json, source_text,
                  parent_direction_id, target_conversation_key, recipe_state, next_safe_step,
                  recipe_reason, root_work_id, resolved_parent_work, resolved_step, resolved_kind,
                  resolved_reason, branch_request_id, now, now))
            if branch_request_id:
                db.execute("""
                    UPDATE chain_branch_requests
                    SET state='READY', state_reason='A recorded a child Direction; it has not started.',
                        next_safe_step='START_CHAIN_RECIPE', child_direction_id=?, updated_at=?
                    WHERE request_id=?
                """, (direction_id, now, branch_request_id))
        return {**(self.get(direction_id=direction_id) or {}), "duplicate": False}

    def target_direction(self, *, direction: dict, target: dict, task_id: str) -> dict:
        """Reuse the existing exact 1:1 ledger for each A-approved recipient."""
        child_id, text = compose_target_direction(direction=direction, target=target, task_id=task_id,
            recorded_direction=self.get(direction_id=target_direction_id(direction, target)))
        return self.save(
            direction_id=child_id, work_id=direction["work_id"],
            source_kind=direction["source_kind"], source_task_id=direction["source_task_id"],
            source_generation=direction["source_generation"], source_result_sha256=direction["source_result_sha256"],
            decision="NEW_TASK", direction_text=text,
            parent_direction_id=direction["direction_id"], target_conversation_key=target["conversation_key"],
            parent_work_id=direction["work_id"], parent_step_id="SEND_DIRECTION",
            branch_kind="DELIVERY", branch_reason="Manager-declared target delivery.",
        )

    def get(self, *, direction_id: str) -> dict[str, Any] | None:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            targets = db.execute(
                "SELECT direction_id,target_conversation_key,chain_task_id,chain_operation_id,"
                "chain_send_operation_id,chain_state FROM chain_directions "
                "WHERE parent_direction_id=? ORDER BY direction_id", (direction_id,),
            ).fetchall()
        if row is None:
            return None
        direction = {**dict(row), "assessment": json.loads(row["assessment_json"]),
                "source_evidence": direction_source_evidence(row["source_kind"]),
                "target_deliveries": [dict(target) for target in targets]}
        direction["chain_continuation"] = {
            "state": direction.get("recipe_state") or "LEGACY_UNCLASSIFIED",
            "reason": direction.get("recipe_reason") or "",
            "next_safe_step": direction.get("next_safe_step") or "INSPECT_DIRECTION",
            "chain_state": direction["chain_state"],
            "work_id": direction["work_id"],
            "direction_id": direction["direction_id"],
        }
        direction["chain_branch"] = {
            "root_work_id": direction.get("root_work_id") or direction["work_id"],
            "parent_work_id": direction.get("parent_work_id") or "",
            "parent_direction_id": direction.get("parent_direction_id") or "",
            "parent_step_id": direction.get("parent_step_id") or "",
            "kind": direction.get("branch_kind") or "PRIMARY",
            "reason": direction.get("branch_reason") or "",
            "branch_request_id": direction.get("branch_request_id") or "",
        }
        return direction

    @classmethod
    def list_pending_chain_starts(cls, *, store, principal_id: str,
                                  limit: int = 20) -> list[dict[str, Any]]:
        """Read A's saved Directions that have not yet re-entered Chain Recipe.

        This is visibility only: it does not choose a target, create an
        Operation, or turn the saved Direction into a send.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("CHAIN_DIRECTION_LIST_LIMIT_INVALID")
        try:
            with store._readonly() as db:
                loop_filter = ""
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='loop_recipe_runs'").fetchone():
                    loop_filter = " AND NOT EXISTS (SELECT 1 FROM loop_recipe_runs l WHERE l.work_id=d.work_id AND l.direction_id=d.direction_id)"
                rows = db.execute("""
                    SELECT d.* FROM chain_directions AS d
                    JOIN works AS w ON w.work_id=d.work_id
                    WHERE w.owner_principal_id=? AND d.recipe_state='READY'
                    """ + loop_filter + """ ORDER BY d.updated_at DESC LIMIT ?
                """, (principal_id, limit)).fetchall()
        except sqlite3.OperationalError:
            # Status remains a read-only observation for stores created before
            # this additive field. A later Direction write performs migration.
            return []
        result = []
        for row in rows:
            direction = cls(store).get(direction_id=str(row["direction_id"]))
            if direction is not None:
                result.append(direction["chain_continuation"])
        return result

    def plan_chain(self, *, direction_id: str, work_id: str, task_id: str,
                   operation_id: str, instruction_text: str = "") -> dict[str, Any]:
        if not all(isinstance(value, str) and _ID.fullmatch(value)
                   for value in (direction_id, work_id, task_id, operation_id)):
            raise ValueError("CHAIN_DIRECTION_ID_INVALID")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if row is None or row["work_id"] != work_id:
                raise ValueError("CHAIN_DIRECTION_NOT_FOUND")
            if row["decision"] != "NEW_TASK":
                raise ValueError("CHAIN_DIRECTION_NOT_A_NEW_TASK")
            if json.loads(row["assessment_json"]):
                raise ValueError("DIRECTION_REQUIRES_TARGET_DELIVERY")
            if instruction_text and instruction_text != row["direction_text"]:
                raise ValueError("CHAIN_DIRECTION_TEXT_MISMATCH")
            current = (row["chain_task_id"], row["chain_operation_id"])
            wanted = (task_id, operation_id)
            if current != ("", "") and current != wanted:
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
            if current == ("", ""):
                db.execute("""
                    UPDATE chain_directions
                    SET chain_task_id=?,chain_operation_id=?,chain_state='CHAIN_PLANNED',
                        recipe_state='IN_PROGRESS',next_safe_step='PREARM_AND_SEND',
                        recipe_reason='Exact Chain Recipe start was planned; prearm and send use this operation.',
                        updated_at=?
                    WHERE direction_id=?
                """, (task_id, operation_id, time.time(), direction_id))
                if row["branch_request_id"]:
                    db.execute("""
                        UPDATE chain_branch_requests
                        SET state='IN_PROGRESS', state_reason='Child Chain Recipe has a planned exact operation.',
                            next_safe_step='PREARM_AND_SEND', updated_at=?
                        WHERE request_id=?
                    """, (time.time(), row["branch_request_id"]))
        return self.get(direction_id=direction_id) or {}

    def mark_chain_started(self, *, direction_id: str, work_id: str,
                           task_id: str, operation_id: str) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_directions WHERE direction_id=?", (direction_id,)
            ).fetchone()
            if (row is None or row["work_id"] != work_id
                    or row["chain_task_id"] != task_id
                    or row["chain_operation_id"] != operation_id):
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
            if row["chain_state"] == "CHAIN_STARTED":
                return {**dict(row), "duplicate": True}
            if row["chain_state"] != "CHAIN_PLANNED":
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
            updated = db.execute("""
                UPDATE chain_directions
                SET chain_state='CHAIN_STARTED',chain_send_operation_id=?,
                    recipe_state='IN_PROGRESS',next_safe_step='WAIT_FOR_RETURN',
                    recipe_reason='The exact direction was sent and its durable Watch now owns the return boundary.',
                    updated_at=?
                WHERE direction_id=? AND chain_state='CHAIN_PLANNED'
            """, (operation_id + "-send", time.time(), direction_id))
            if updated.rowcount != 1:
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
        return {**(self.get(direction_id=direction_id) or {}), "duplicate": False}


class ChainBranchRequestLedger:
    """Durable reports requesting a Manager-authored child Chain.

    A request has no transport side effect and is not a child Direction.  A
    Manager later adopts it by saving a normal Direction with branch_request_id.
    """

    def __init__(self, store):
        self.store = store
        # The direction ledger owns the additive schema so one transaction can
        # bind adoption without an orphaned child Direction.
        ChainDirectionLedger(store)

    @staticmethod
    def _refs(value: dict | None) -> dict:
        if value is None:
            return {}
        allowed = {"conversation_key", "operation_id", "receipt_id", "generation", "task_id", "direction_id"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("CHAIN_BRANCH_EXACT_REFS_INVALID")
        if "conversation_key" in value and (not isinstance(value["conversation_key"], str)
                                             or not _UUID.fullmatch(value["conversation_key"])):
            raise ValueError("CHAIN_BRANCH_EXACT_REFS_INVALID")
        for key in ("operation_id", "receipt_id", "task_id", "direction_id"):
            if key in value and (not isinstance(value[key], str) or not _ID.fullmatch(value[key])):
                raise ValueError("CHAIN_BRANCH_EXACT_REFS_INVALID")
        if "generation" in value and (type(value["generation"]) is not int or value["generation"] < 1):
            raise ValueError("CHAIN_BRANCH_EXACT_REFS_INVALID")
        return value

    def request(self, *, request_id: str, root_work_id: str, parent_work_id: str,
                parent_direction_id: str, parent_step_id: str, parent_task_id: str,
                parent_generation: int, kind: str, reason: str, exact_refs: dict | None = None,
                required: bool = True) -> dict:
        if (not all(isinstance(value, str) and _ID.fullmatch(value) for value in
                    (request_id, root_work_id, parent_work_id, parent_direction_id, parent_task_id))
                or not isinstance(parent_step_id, str) or not parent_step_id or len(parent_step_id) > 120
                or kind not in _BRANCH_KINDS - {"PRIMARY", "DELIVERY", "RESUME"}
                or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
                or type(parent_generation) is not int or parent_generation < 1
                or type(required) is not bool):
            raise ValueError("CHAIN_BRANCH_REQUEST_INVALID")
        refs = self._refs(exact_refs)
        now = time.time()
        with self.store.transaction() as db:
            parent = db.execute("SELECT * FROM chain_directions WHERE direction_id=?", (parent_direction_id,)).fetchone()
            if (parent is None or parent["work_id"] != parent_work_id
                    or str(parent["root_work_id"] or parent["work_id"]) != root_work_id
                    or parent["chain_task_id"] != parent_task_id
                    or parent["chain_state"] != "CHAIN_STARTED"):
                raise ValueError("CHAIN_BRANCH_PARENT_NOT_EXACT")
            existing = db.execute("SELECT * FROM chain_branch_requests WHERE request_id=?", (request_id,)).fetchone()
            proposed = (root_work_id, parent_work_id, parent_direction_id, parent_step_id,
                        parent_task_id, parent_generation, kind, reason, _json(refs), int(required))
            if existing is not None:
                actual = tuple(existing[key] for key in (
                    "root_work_id", "parent_work_id", "parent_direction_id", "parent_step_id",
                    "parent_task_id", "parent_generation", "kind", "reason", "exact_refs_json", "required"))
                if actual != proposed:
                    raise ValueError("CHAIN_BRANCH_REQUEST_CONFLICT")
                return {**dict(existing), "duplicate": True, "exact_refs": json.loads(existing["exact_refs_json"])}
            duplicate = db.execute("""
                SELECT request_id FROM chain_branch_requests
                WHERE root_work_id=? AND parent_direction_id=? AND parent_step_id=?
                  AND parent_task_id=? AND parent_generation=? AND kind=?
                  AND exact_refs_json=? AND state!='COMPLETED'
            """, (root_work_id, parent_direction_id, parent_step_id, parent_task_id,
                  parent_generation, kind, _json(refs))).fetchone()
            if duplicate is not None:
                raise ValueError("CHAIN_BRANCH_DUPLICATE_REQUEST")
            db.execute("""
                INSERT INTO chain_branch_requests(
                    request_id,root_work_id,parent_work_id,parent_direction_id,parent_step_id,
                    parent_task_id,parent_generation,kind,reason,exact_refs_json,required,state,
                    state_reason,next_safe_step,evidence_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'WAITING_INPUT',?,'MANAGER_REVIEW_BRANCH_REQUEST','{}',?,?)
            """, (request_id, *proposed,
                  "A Manager must decide whether to create a linked child Chain Direction.", now, now))
        return self.get(request_id=request_id) or {}

    def report(self, *, request_id: str, state: str, reason: str,
               next_safe_step: str, evidence: dict | None = None) -> dict:
        if (state not in _BRANCH_STATES or state in {"READY", "IN_PROGRESS"}
                or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
                or not isinstance(next_safe_step, str) or not next_safe_step or len(next_safe_step) > 120
                or evidence is not None and not isinstance(evidence, dict)):
            raise ValueError("CHAIN_BRANCH_REPORT_INVALID")
        if state == "UNKNOWN" and "RECONCILE" not in next_safe_step.upper():
            raise ValueError("CHAIN_BRANCH_UNKNOWN_RECONCILE_REQUIRED")
        if state == "COMPLETED" and not (isinstance(evidence, dict) and any(
                key in evidence for key in ("receipt_id", "task_id", "direction_id"))):
            raise ValueError("CHAIN_BRANCH_COMPLETION_EVIDENCE_REQUIRED")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM chain_branch_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("CHAIN_BRANCH_REQUEST_NOT_FOUND")
            db.execute("""
                UPDATE chain_branch_requests
                SET state=?,state_reason=?,next_safe_step=?,evidence_json=?,updated_at=?
                WHERE request_id=?
            """, (state, reason, next_safe_step, _json(evidence or {}), time.time(), request_id))
        return self.get(request_id=request_id) or {}

    def get(self, *, request_id: str) -> dict | None:
        with self.store._readonly() as db:
            row = db.execute("SELECT * FROM chain_branch_requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["exact_refs"] = json.loads(result.pop("exact_refs_json"))
        result["evidence"] = json.loads(result.pop("evidence_json"))
        result["required"] = bool(result["required"])
        if result["state"] == "UNKNOWN":
            result["prohibited_actions"] = ["DO_NOT_RESEND_OR_CREATE_A_REPLACEMENT_OPERATION"]
        else:
            result["prohibited_actions"] = []
        return result

    @classmethod
    def tree(cls, *, store, root_work_id: str) -> dict:
        """Read one root's durable tree without changing a receipt or a watch."""
        try:
            with store._readonly() as db:
                directions = [dict(row) for row in db.execute(
                    "SELECT * FROM chain_directions WHERE root_work_id=? OR (root_work_id='' AND work_id=?) ORDER BY created_at,direction_id",
                    (root_work_id, root_work_id),
                ).fetchall()]
                requests = [dict(row) for row in db.execute(
                    "SELECT * FROM chain_branch_requests WHERE root_work_id=? ORDER BY created_at,request_id",
                    (root_work_id,),
                ).fetchall()]
                try:
                    watches = [dict(row) for row in db.execute(
                        "SELECT task_id,generation,state,context_json FROM delayed_send_watches ORDER BY generation DESC"
                    ).fetchall()]
                except sqlite3.OperationalError:
                    watches = []
        except sqlite3.OperationalError:
            return {"root_work_id": root_work_id, "nodes": [], "branch_requests": [], "manager_attention": []}
        latest_watches = {}
        for watch in watches:
            latest_watches.setdefault(str(watch["task_id"]), watch)
        nodes = []
        for direction in directions:
            state = str(direction.get("recipe_state") or "LEGACY_UNCLASSIFIED")
            reason = str(direction.get("recipe_reason") or "")
            next_step = str(direction.get("next_safe_step") or "INSPECT_DIRECTION")
            watch = latest_watches.get(str(direction.get("chain_task_id") or ""))
            if watch:
                watch_state = str(watch["state"])
                if watch_state == "WATCHING":
                    state, next_step = "WAITING_EXTERNAL", "WAIT_FOR_EXACT_RESPONSE"
                    reason = "The exact sent operation is waiting for its durable response Watch."
                elif watch_state in {"MANAGER_DECISION_REQUIRED", "RETURNED_TO_MANAGER"}:
                    state, next_step = "WAITING_INPUT", "MANAGER_REENTER_CHAIN_RECIPE"
                    reason = "The exact Worker return is recorded; A must prepare and save the next Direction."
                elif watch_state == "UNKNOWN":
                    state, next_step = "UNKNOWN", "RECONCILE_SAME_RECEIPT_ONLY"
                    reason = "The external effect is uncertain. Do not resend or create a replacement operation."
                elif watch_state == "SELF_SENT":
                    state, next_step = "IN_PROGRESS", "WAIT_FOR_CURRENT_GENERATION"
                    reason = "The same exact task has a later self-continuation."
            nodes.append({
                "direction_id": direction["direction_id"], "work_id": direction["work_id"],
                "parent_work_id": direction.get("parent_work_id") or "",
                "parent_direction_id": direction.get("parent_direction_id") or "",
                "parent_step_id": direction.get("parent_step_id") or "",
                "kind": direction.get("branch_kind") or "PRIMARY",
                "reason": direction.get("branch_reason") or reason,
                "branch_request_id": direction.get("branch_request_id") or "",
                "task_id": direction.get("chain_task_id") or "",
                "operation_id": direction.get("chain_operation_id") or "",
                "send_operation_id": direction.get("chain_send_operation_id") or "",
                "state": state, "state_reason": reason, "next_safe_step": next_step,
                "watch_state": str(watch["state"]) if watch else "",
                "prohibited_actions": (["DO_NOT_RESEND_OR_CREATE_A_REPLACEMENT_OPERATION"]
                                       if state == "UNKNOWN" else []),
            })
        branch_requests = []
        for row in requests:
            item = dict(row)
            item["exact_refs"] = json.loads(item.pop("exact_refs_json"))
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["required"] = bool(item["required"])
            item["prohibited_actions"] = (["DO_NOT_RESEND_OR_CREATE_A_REPLACEMENT_OPERATION"]
                                           if item["state"] == "UNKNOWN" else [])
            branch_requests.append(item)
        attention = [item for item in branch_requests if item["state"] not in {"COMPLETED", "IN_PROGRESS"}]
        attention += [item for item in nodes if item["state"] in {
            "WAITING_INPUT", "IDENTITY_MISMATCH", "CHECK_FAILED", "NOT_APPLIED", "UNKNOWN", "BLOCKED"}]
        return {"root_work_id": root_work_id, "nodes": nodes,
                "branch_requests": branch_requests, "manager_attention": attention}
