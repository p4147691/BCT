"""Question-guided A directions and their exact per-target instructions.

The caller AI answers the questions. BCT supplies current evidence, validates
the answers and keeps their relationship to each delivery; it is not an LLM.
"""
from __future__ import annotations

import time
import re
import hashlib
import json
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_DECISIONS = {"COMPLETE", "NEW_TASK", "ASK_USER", "HOLD"}
_SOURCES = {"USER", "MANAGER_RETURN"}
_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")

# These are questions for A, not an additional questionnaire for the user.
DIRECTION_QUESTIONS = (
    ("intent", "사용자 의도", "원문 또는 반환 보고에서 사용자가 실제로 원하는 결과는 무엇인가? 이전 목표를 유지하면서 무엇을 보완해야 하는가?"),
    ("acceptance", "완료 기준", "무엇을 직접 확인하면 완료인가? 이미 끝난 것, 남은 것, 아직 확인하지 못한 것을 구분하라."),
    ("scope", "범위와 조건", "허용 범위, 금지사항, 우선순위, 보존할 사용자 작업과 외부 효과는 무엇인가? 모르는 것은 어떻게 확인할 것인가?"),
    ("network", "대화망 선택", "열린 Node Info(우클릭 정보)의 대화망·역할·담당 작업·메모와 저장된 대화망 이력을 비교하라. 전역 Supervisor의 과거 담당 작업·메모는 참고 정보이며 프로젝트 귀속이나 재사용 배제 근거가 아니다. 재사용·신규·병합 중 무엇을 왜 선택하는가?"),
    ("manager", "Manager", "지시를 받은 A가 어떤 대화망의 Manager가 되는가? 기존 Manager가 있으면 어떤 기록을 보존하고 역할을 넘겨받는가?"),
    ("supervisor", "Supervisor", "전역 Supervisor 하나를 어떻게 유지하는가? 대화망 미소속 Supervisor는 서로 다른 프로젝트 Manager가 같은 정확한 UUID로 재사용할 수 있으며, 각 Direction·Work·Task·Generation·Operation·영수증은 분리한다. Supervisor는 조정·독립 검수만 하고 Manager 지휘나 Worker 실행 책임을 대체하지 않는다. 없거나 닫혔으면 기존 노드 재사용·새 노드 준비·승계를 판단하고, 여럿이면 역할을 하나로 정리하라."),
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
            "supervisor_conversation_key": "the one global Supervisor UUID; it must differ from Manager and Worker. A network-unassigned Supervisor remains reusable across projects even when its node memo or assigned task names an earlier project; each Direction/Work/Task/generation/Operation receipt remains separate",
            "targets": [{
                "conversation_key": "lowercase canonical ChatGPT conversation UUID; not N96 or a tab title",
                "role": "A's free-form role label, for example worker, reviewer, or deployer",
                "instruction": "non-empty per-target instruction, at most 6000 characters",
            }],
            "network_updates": "list of existing bct_set_conversation_network argument objects; [] is valid when reusing the network unchanged. Select topology in this order: an existing network-unassigned global Supervisor (do not exclude it merely for an earlier-project memo or assigned task), then an unassigned idle Worker; create only the missing node. Never select a Manager from another network as Worker or Supervisor.",
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
        "recovery": "Correct only the reported fields, then call bct_set_direction(action='save') again with the same intended direction_id. Read the saved record with bct_get_direction before starting.",
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
    text = (direction["direction_text"] + "\n\n이번 대상에게 맡기는 일:\n" + target["instruction"]
            + f"\n\n이번 대상의 역할: {target['role']}. 이 작업의 실행계획과 결과는 다음 식별값에 연결한다: "
            + f"work_id={direction['work_id']}, direction_id={child_id}, task_id={task_id}, generation=1. "
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
    text = (
        direction["direction_text"] + "\n\n이번 대상에게 맡기는 일:\n" + instruction
        + f"\n\n이번 대상의 역할: {role}. 이 작업의 실행계획과 결과는 다음 식별값에 연결한다: "
        + f"work_id={direction['work_id']}, direction_id={child_id}, "
        + f"task_id={task_id}, generation=1. "
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
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(chain_directions)")}
            for name, default in (("assessment_json", "{}"), ("source_text", ""),
                                  ("parent_direction_id", ""), ("target_conversation_key", "")):
                if name not in columns:
                    db.execute(f"ALTER TABLE chain_directions ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")

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
             target_conversation_key: str = "") -> dict[str, Any]:
        self._validate(
            direction_id=direction_id, work_id=work_id, source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_result_sha256=source_result_sha256, decision=decision,
            direction_text=direction_text,
        )
        checked = validate_direction_assessment(assessment, decision=decision) if assessment is not None else {}
        if checked and source_kind == "USER" and (not source_text.strip() or len(source_text) > 12000):
            raise ValueError("CHAIN_DIRECTION_SOURCE_TEXT_REQUIRED")
        if parent_direction_id and (not _ID.fullmatch(parent_direction_id) or not _UUID.fullmatch(target_conversation_key)):
            raise ValueError("DIRECTION_PARENT_TARGET_INVALID")
        assessment_json = _json(checked)
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
                return {**dict(existing), "assessment": json.loads(existing["assessment_json"]),
                        "source_evidence": direction_source_evidence(existing["source_kind"]), "duplicate": True}
            db.execute("""
                INSERT INTO chain_directions(
                    direction_id,work_id,source_kind,source_task_id,source_generation,
                    source_result_sha256,decision,direction_text,assessment_json,
                    source_text,parent_direction_id,target_conversation_key,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (direction_id, *proposed, now, now))
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
        return {**dict(row), "assessment": json.loads(row["assessment_json"]),
                "source_evidence": direction_source_evidence(row["source_kind"]),
                "target_deliveries": [dict(target) for target in targets]}

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
                    SET chain_task_id=?,chain_operation_id=?,chain_state='CHAIN_PLANNED',updated_at=?
                    WHERE direction_id=?
                """, (task_id, operation_id, time.time(), direction_id))
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
                SET chain_state='CHAIN_STARTED',chain_send_operation_id=?,updated_at=?
                WHERE direction_id=? AND chain_state='CHAIN_PLANNED'
            """, (operation_id + "-send", time.time(), direction_id))
            if updated.rowcount != 1:
                raise ValueError("CHAIN_DIRECTION_CHAIN_CONFLICT")
        return {**(self.get(direction_id=direction_id) or {}), "duplicate": False}
