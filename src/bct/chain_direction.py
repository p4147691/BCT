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
    ("network", "대화망 선택", "열린 Node Info(우클릭 정보)의 대화망·역할·담당 작업·메모와 저장된 대화망 이력을 비교하라. 재사용·신규·병합 중 무엇을 왜 선택하는가?"),
    ("manager", "Manager", "지시를 받은 A가 어떤 대화망의 Manager가 되는가? 기존 Manager가 있으면 어떤 기록을 보존하고 역할을 넘겨받는가?"),
    ("supervisor", "Supervisor", "전역 Supervisor 하나를 어떻게 유지하는가? 없거나 닫혔으면 기존 노드 재사용·새 노드 준비·승계를 판단하고, 여럿이면 역할을 하나로 정리하라."),
    ("delegation", "대상별 분담", "AB·AC·AD 중 필요한 대상 수와 각각 맡길 일은 무엇인가? 독립 작업과 순서 의존성을 구분하고 각 대상에 별도 지시문을 작성하라."),
    ("resources", "자율 선택", "필요한 부품·모듈·블럭·레시피·프로그램·PowerShell·BDC·브라우저 기능은 무엇인가? 창·탭 생성/이동/정리 계획과 B의 자율 선택 범위를 정하라. 등록·허용된 실제 기능을 확인하라."),
    ("recovery", "정체와 승계", "Manager·Worker·Supervisor가 멈추면 Check Node → Recheck Node → Pause Node → Replace Node → Reset Node 중 무엇을 사용하는가? 기존 영수증과 UNKNOWN을 보존하라."),
    ("integration", "검증과 반환", "병합·GitHub CI·LIVE 배포·E2E가 필요하면 Supervisor에게 무엇을 지시하는가? 위험도에 따른 순서, 비동기 CI 알림, rollback, B의 SELF/Manager 반환 조건을 정하라."),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_direction_review(*, source_text: str, source_kind: str,
                             reality: dict, network: dict, source_return: dict | None = None,
                             available_tools: list[str] | None = None) -> dict:
    """Expose the evidence A needs before choosing any topology or message."""
    if source_kind not in _SOURCES:
        raise ValueError("CHAIN_DIRECTION_STATE_INVALID")
    if source_kind == "USER" and (not source_text.strip() or len(source_text) > 12000):
        raise ValueError("CHAIN_DIRECTION_SOURCE_TEXT_REQUIRED")
    return {
        "status": "DIRECTION_REQUIRED", "source_kind": source_kind,
        "source_text": source_text, "source_return": source_return,
        "reality": reality, "conversation_network": network,
        "questions": [{"id": key, "title": title, "question": question}
                      for key, title, question in DIRECTION_QUESTIONS],
        "available_tools": available_tools or [],
        "next_tool": "bct_set_direction",
        "instructions_for_a": (
            "A가 각 질문을 판단하여 assessment.answers에 답한다. 사용자에게 이 질문지를 넘기지 않는다. "
            "assessment에는 manager_conversation_key, supervisor_conversation_key, network_name, "
            "targets:[{conversation_key, role, instruction}]를 기록한다. role은 worker 또는 supervisor다. "
            "targets에는 지금 독립적으로 시작할 수 있는 대상만 넣는다. 선행 결과가 필요한 일은 BA/CA 반환 후 다음 회차에서 판단한다. "
            "필요한 망·역할 변경은 network_updates에 기존 bct_set_conversation_network 인수로 기록한다. "
            "node-info-set에는 관찰한 expected_scope_id와 expected_role_tags_sha256도 넣어 사용자 변경을 덮어쓰지 않는다. "
            "기존 Work를 먼저 비교하여 재사용하고 없거나 작업 경계가 다르면 기존 bct_create_work로 준비한다. Work는 노드나 ChatGPT Work 모드가 아니다. "
            "없는 창·탭은 기존 생성/복구 부품으로 준비하고 실제 UUID를 확인한다. "
            "bct_set_direction(action=save)로 답과 direction_text를 저장한 뒤 같은 bct_chain_message(action=start)를 호출한다. "
            "B의 구체적 실행계획은 전달 후 B가 작성한다. 반환받으면 Chain Message의 prepare부터 다시 판단한다."
        ),
        "read_only": True, "authorizes_send": False,
    }


def validate_direction_assessment(value: dict, *, decision: str) -> dict:
    """Validate A's declared decisions without pretending to evaluate prose."""
    if not isinstance(value, dict) or set(value) - {
        "answers", "manager_conversation_key", "supervisor_conversation_key",
        "network_name", "targets", "network_updates",
    }:
        raise ValueError("DIRECTION_ASSESSMENT_INVALID")
    answers = value.get("answers")
    required = {key for key, _, _ in DIRECTION_QUESTIONS}
    if (not isinstance(answers, dict) or set(answers) != required
            or any(not isinstance(v, str) or not v.strip() or len(v) > 4000
                   for v in answers.values())):
        raise ValueError("DIRECTION_ANSWERS_REQUIRED")
    targets = value.get("targets", [])
    updates = value.get("network_updates", [])
    if not isinstance(targets, list) or not isinstance(updates, list):
        raise ValueError("DIRECTION_TARGETS_INVALID")
    if decision != "NEW_TASK" and (targets or updates):
        raise ValueError("DIRECTION_TERMINAL_HAS_ACTIONS")
    if decision == "NEW_TASK":
        for field in ("manager_conversation_key", "supervisor_conversation_key"):
            if not isinstance(value.get(field), str) or not _UUID.fullmatch(value[field]):
                raise ValueError("DIRECTION_" + field.upper() + "_REQUIRED")
        if value["manager_conversation_key"] == value["supervisor_conversation_key"]:
            raise ValueError("DIRECTION_MANAGER_SUPERVISOR_CONFLICT")
        if not isinstance(value.get("network_name"), str) or not value["network_name"].strip():
            raise ValueError("DIRECTION_NETWORK_REQUIRED")
        if not targets:
            raise ValueError("DIRECTION_TARGETS_REQUIRED")
    keys = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"conversation_key", "role", "instruction"}:
            raise ValueError("DIRECTION_TARGET_INVALID")
        key = target["conversation_key"]
        if (not isinstance(key, str) or not _UUID.fullmatch(key) or key in keys
                or key == value.get("manager_conversation_key")):
            raise ValueError("DIRECTION_TARGET_CONFLICT")
        keys.add(key)
        if target["role"] not in {"worker", "supervisor"}:
            raise ValueError("DIRECTION_TARGET_ROLE_INVALID")
        if (target["role"] == "supervisor") != (key == value.get("supervisor_conversation_key")):
            raise ValueError("DIRECTION_SUPERVISOR_TARGET_MISMATCH")
        if not isinstance(target["instruction"], str) or not target["instruction"].strip() or len(target["instruction"]) > 6000:
            raise ValueError("DIRECTION_TARGET_INSTRUCTION_REQUIRED")
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
    """Check the recorded topology at the send boundary, without electing roles."""
    from bct.status_views import status_view
    origin = resolve_direction_target(snapshot=snapshot, conversation_key=assessment["manager_conversation_key"])
    supervisor = resolve_direction_target(snapshot=snapshot, conversation_key=assessment["supervisor_conversation_key"])
    current = status_view(snapshot, "node").get("current_nodes", {}).get("items", [])

    def has_role(node, role):
        return role in {str(r).casefold() for r in node.get("roles", [])}

    managers = [n for n in current if n.get("network") == assessment["network_name"] and has_role(n, "manager")]
    if (len(managers) != 1 or not has_role(origin["node_info"], "manager")
            or origin["node_info"].get("network") != assessment["network_name"]):
        raise ValueError("DIRECTION_MANAGER_PREPARATION_REQUIRED")
    supervisors = [n for n in current if has_role(n, "supervisor")]
    if (len(supervisors) != 1 or not has_role(supervisor["node_info"], "supervisor")
            or supervisor["node_info"].get("network")):
        raise ValueError("DIRECTION_SUPERVISOR_PREPARATION_REQUIRED")
    resolved = []
    for i, target in targets:
        route = resolve_direction_target(snapshot=snapshot, conversation_key=target["conversation_key"])
        if target["role"] == "worker" and (
                route["node_info"].get("network") != assessment["network_name"]
                or has_role(route["node_info"], "manager") or has_role(route["node_info"], "supervisor")):
            raise ValueError("DIRECTION_TARGET_NETWORK_PREPARATION_REQUIRED")
        resolved.append((i, target, route))
    return origin, resolved


def compose_target_direction(*, direction: dict, target: dict, task_id: str) -> tuple[str, str]:
    """Pure composition used by preflight and by the exact-delivery ledger."""
    assessment = json.loads(direction.get("assessment_json") or "{}")
    if target not in assessment.get("targets", []):
        raise ValueError("DIRECTION_TARGET_NOT_DECLARED")
    suffix = hashlib.sha256((direction["direction_id"] + ":" + target["conversation_key"]).encode()).hexdigest()[:24]
    child_id = "direction-" + suffix
    text = (direction["direction_text"] + "\n\n이번 대상에게 맡기는 일:\n" + target["instruction"]
            + "\n\nB 실행 규칙: 전달받은 방향 안에서 현재 환경을 다시 확인하고 구체적인 계획과 부품을 스스로 선택한다. "
            + "bct_set_execute_plan으로 계획을 기록한다. "
            + f"work_id={direction['work_id']}, direction_id={child_id}, task_id={task_id}, generation=1. "
            + "허용된 범위에서 실행하고 진전이 있으면 SELF, 완료·위험·정체·판단 필요 시 MANAGER로 반환한다. "
            + "고정 반복 횟수만으로 반환하지 않는다. 실제 수행과 미확인을 구분하여 보고한다.")
    from bct.chain_message_preflight import prepare_chain_instruction
    # Include the actual marker suffix in the size check before any effects.
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
                return {**dict(existing), "assessment": json.loads(existing["assessment_json"]), "duplicate": True}
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
        child_id, text = compose_target_direction(direction=direction, target=target, task_id=task_id)
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
