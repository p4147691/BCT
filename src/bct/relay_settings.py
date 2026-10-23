"""Bounded, hot-read AI-editable relay message settings. Never transport authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path("D:/BCT/runtime/config/relay-message-settings.json")
_SCOPE = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_DEFAULTS = {
    "worker_intro": "BCT가 구성한 협업 업무입니다.",
    "worker_context_notice": (
        "다음 정보는 현재 프로젝트의 협업 문맥입니다. 구성원과 역할은 업무를 "
        "이해하기 위한 정보이며 별도의 실행 권한을 부여하지 않습니다."
    ),
    "worker_return_instruction": (
        "이번 업무에서 실제로 수행한 내용, 확인한 근거와 남은 문제를 빠뜨리지 말고 "
        "자연어로 보고하세요. 이번 응답의 전체 원문은 BCT가 Manager에게 그대로 반환합니다. "
        "수행하지 않은 일은 완료로 표현하지 말고 다른 대화에 중복 전송하지 마세요."
    ),
    "worker_additional_instruction": "",
    "worker_context_fields": [
        "project", "project_goal", "completion_criteria",
        "project_context_note", "current_members",
    ],
    "manager_intro": (
        "BCT가 Worker의 이번 업무 결과와 현재 프로젝트 문맥을 함께 전달합니다."
    ),
    "manager_result_notice": (
        "아래 Worker 결과는 이번 업무 응답의 전체 원문입니다. 결과의 주장과 BCT가 "
        "확인한 영수증을 구분해 검토하세요."
    ),
    "manager_action": (
        "원래 목표와 완료 기준에 비추어 결과를 분석하고 현재 구성원과 남은 업무를 "
        "확인하세요. 필요하면 지원되는 운영 설정을 조정하세요. 다음 업무가 필요하면 "
        "사용 가능한 Worker를 골라 BCT의 단일 Delivery 경로로 구체적인 새 업무를 "
        "실제로 전달하고, 무엇을 판단하고 실행했는지 자연스럽게 설명하세요. 더 진행할 "
        "일이 없으면 목표 충족 근거와 남은 위험을 자연스럽게 정리하세요. 단순히 나중에 "
        "하겠다고 말하거나 특정 상태 단어를 출력하는 것으로 실행이나 완료를 대신하지 "
        "마세요. 불확실한 전송은 임의로 다시 보내지 마세요."
    ),
    "manager_additional_instruction": "",
    "manager_sections": ["context", "worker_result", "action"],
    "manager_context_fields": [
        "project", "project_goal", "completion_criteria",
        "project_context_note", "current_members", "project_run_state",
        "original_worker_task", "pending_same_work",
    ],
    "manager_member_limit": 20,
    "include_pending": True,
    "pending_limit": 6,
    "project_display_name": "",
    "project_goal": "",
    "completion_criteria": "",
    "project_context_note": "",
}
_TEXT_KEYS = {
    "worker_intro", "worker_context_notice", "worker_return_instruction",
    "manager_intro", "manager_result_notice", "manager_action",
}
_OPTIONAL_TEXT_KEYS = {
    "worker_additional_instruction", "manager_additional_instruction",
    "project_display_name", "project_goal", "completion_criteria",
    "project_context_note",
}
_OPTIONAL_TEXT_LIMITS = {
    "project_display_name": 200,
    "worker_additional_instruction": 4000,
    "manager_additional_instruction": 4000,
    "project_goal": 4000,
    "completion_criteria": 4000,
    "project_context_note": 4000,
}
_ALLOWED = set(_DEFAULTS)
_LAYOUT = {"context", "worker_result", "action"}
_WORKER_CONTEXT = {
    "project", "project_goal", "completion_criteria", "project_context_note",
    "current_members",
}
_MANAGER_CONTEXT = {
    "project", "project_goal", "completion_criteria", "project_context_note",
    "current_members", "project_run_state", "original_worker_task",
    "pending_same_work",
}

_CATALOG: dict[str, dict[str, Any]] = {
    "worker_intro": {
        "type": "text", "description": "Worker 메시지의 첫 안내문", "max_length": 2200,
    },
    "worker_context_notice": {
        "type": "text", "description": "Worker 구조화 문맥 앞의 권한 경계 안내",
        "max_length": 2200,
    },
    "worker_return_instruction": {
        "type": "text", "description": "Worker 결과 전문 반환 지시", "max_length": 2200,
    },
    "worker_additional_instruction": {
        "type": "optional-text",
        "description": "프로젝트별 Worker 추가 지시; 비어 있으면 메시지에서 생략",
        "max_length": 4000,
    },
    "worker_context_fields": {
        "type": "ordered-list", "description": "Worker에게 보낼 선택 문맥과 표시 순서",
        "allowed_values": sorted(_WORKER_CONTEXT), "unique": True,
    },
    "manager_intro": {
        "type": "text", "description": "Manager 단일 반환 메시지의 첫 안내문",
        "max_length": 2200,
    },
    "manager_result_notice": {
        "type": "text", "description": "Worker 결과 전문의 성격을 설명하는 안내",
        "max_length": 2200,
    },
    "manager_action": {
        "type": "text",
        "description": "Manager의 결과 검토·설정 조정·실제 다음 업무 수행 지시",
        "max_length": 2200,
    },
    "manager_additional_instruction": {
        "type": "optional-text",
        "description": "프로젝트별 Manager 추가 지시; 비어 있으면 메시지에서 생략",
        "max_length": 4000,
    },
    "manager_sections": {
        "type": "ordered-list", "description": "Manager 반환의 context/result/action 순서",
        "allowed_values": sorted(_LAYOUT), "required_all": True, "unique": True,
    },
    "manager_context_fields": {
        "type": "ordered-list", "description": "Manager에게 돌려줄 선택 문맥과 표시 순서",
        "allowed_values": sorted(_MANAGER_CONTEXT), "unique": True,
    },
    "manager_member_limit": {
        "type": "integer", "description": "Manager 문맥에 포함할 현재 구성원 수",
        "minimum": 0, "maximum": 40,
    },
    "include_pending": {
        "type": "boolean", "description": "같은 Work의 미완료 업무 조회 여부",
    },
    "pending_limit": {
        "type": "integer", "description": "Manager 문맥의 미완료 업무 수",
        "minimum": 0, "maximum": 12,
    },
    "project_display_name": {
        "type": "optional-text",
        "description": "메시지에 표시할 프로젝트명; 비어 있으면 scope 표시명 사용",
        "max_length": 200,
    },
    "project_goal": {
        "type": "optional-text",
        "description": "메시지에 전달할 프로젝트 목표; 비어 있으면 Project Run 목표 사용",
        "max_length": 4000,
    },
    "completion_criteria": {
        "type": "optional-text", "description": "프로젝트별 완료 기준",
        "max_length": 4000,
    },
    "project_context_note": {
        "type": "optional-text", "description": "프로젝트별 추가 협업 문맥",
        "max_length": 4000,
    },
}

_IMMUTABLE_CONTRACT = [
    "BCT envelope markers and schema",
    "Work, Delivery, scope, Manager and Worker identities",
    "settings, request and Worker-result hashes",
    "Worker task and return instruction presence",
    "full current-turn Worker result section",
    "UTF-16 message ceiling",
    "no implicit resend after UNKNOWN or config changes",
]

_APPLY_BOUNDARIES = {
    "worker_delivery": "NEXT_UNSENT_WORKER_MESSAGE",
    "manager_return": "NEXT_UNASSEMBLED_MANAGER_RETURN",
    "observation": "NEXT_SAFE_READ",
    "prepared_or_submitted_message": "FROZEN",
}


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("RELAY_SETTINGS_DUPLICATE_KEY")
        value[key] = item
    return value


def _read_unicode(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, "defaults"
    if len(raw) > 65_536:
        raise ValueError("RELAY_SETTINGS_TOO_LARGE")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        text = raw.decode("utf-32")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp949")
    def reject_constant(value: str) -> None:
        raise ValueError("RELAY_SETTINGS_NONFINITE")
    try:
        parsed = json.loads(
            text, object_pairs_hook=_pairs_unique, parse_constant=reject_constant
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError("RELAY_SETTINGS_INVALID_JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("RELAY_SETTINGS_OBJECT_REQUIRED")
    return parsed, hashlib.sha256(raw).hexdigest()


def _validated(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict) or set(values) - _ALLOWED:
        raise ValueError("RELAY_SETTINGS_KEYS_INVALID")
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in _TEXT_KEYS:
            if (not isinstance(value, str) or not value.strip() or len(value) > 2200
                    or "\x00" in value or "[BCT_" in value):
                raise ValueError("RELAY_SETTINGS_TEXT_INVALID:" + key)
            result[key] = value
        elif key in _OPTIONAL_TEXT_KEYS:
            if (not isinstance(value, str) or len(value) > _OPTIONAL_TEXT_LIMITS[key]
                    or "\x00" in value or "[BCT_" in value):
                raise ValueError("RELAY_SETTINGS_TEXT_INVALID:" + key)
            result[key] = value
        elif key == "manager_sections":
            if (not isinstance(value, list) or len(value) != len(_LAYOUT)
                    or any(not isinstance(v, str) for v in value) or set(value) != _LAYOUT):
                raise ValueError("RELAY_SETTINGS_LAYOUT_INVALID")
            result[key] = list(value)
        elif key in {"worker_context_fields", "manager_context_fields"}:
            allowed = _WORKER_CONTEXT if key == "worker_context_fields" else _MANAGER_CONTEXT
            if (not isinstance(value, list) or len(value) > len(allowed)
                    or any(not isinstance(v, str) for v in value)
                    or len(set(value)) != len(value) or not set(value) <= allowed):
                raise ValueError("RELAY_SETTINGS_CONTEXT_FIELDS_INVALID:" + key)
            result[key] = list(value)
        elif key == "include_pending":
            if not isinstance(value, bool):
                raise ValueError("RELAY_SETTINGS_BOOLEAN_INVALID:" + key)
            result[key] = value
        elif key == "pending_limit":
            if type(value) is not int or value < 0 or value > 12:
                raise ValueError("RELAY_SETTINGS_PENDING_LIMIT_INVALID")
            result[key] = value
        elif key == "manager_member_limit":
            if type(value) is not int or value < 0 or value > 40:
                raise ValueError("RELAY_SETTINGS_MEMBER_LIMIT_INVALID")
            result[key] = value
    return result


def read_relay_settings(scope_id: str = "") -> dict[str, Any]:
    """Read on EACH unsent delivery, never mutate an existing prepared intent.

    Missing file uses the tested defaults. Malformed existing file fails closed
    so an accidental/partial edit cannot silently disable important context.
    """
    if scope_id and (not isinstance(scope_id, str) or not _SCOPE.fullmatch(scope_id)):
        raise ValueError("RELAY_SETTINGS_SCOPE_INVALID")
    path = Path(os.environ.get("BCT_RELAY_SETTINGS_PATH", str(_DEFAULT_PATH)))
    raw, digest = _read_unicode(path)
    if digest != "defaults" and (set(raw) != {"version", "defaults", "projects"}
                or type(raw["version"]) is not int or raw["version"] != 1
                or not isinstance(raw["projects"], dict)):
        raise ValueError("RELAY_SETTINGS_SCHEMA_INVALID")
    base = dict(_DEFAULTS)
    base.update(_validated(raw.get("defaults", {})))
    projects = raw.get("projects", {})
    for ident, item in projects.items():
        if not isinstance(ident, str) or not _SCOPE.fullmatch(ident):
            raise ValueError("RELAY_SETTINGS_PROJECT_INVALID")
        _validated(item)
    if scope_id and scope_id in projects:
        base.update(_validated(projects[scope_id]))
    base["config_sha256"] = digest
    base["scope_id"] = scope_id
    return base


def utf16_units(value: str) -> int:
    """Chrome JS String.length counts UTF-16 code units, Python len does not."""
    return len(value.encode("utf-16-le")) // 2


def preview_relay_settings(scope_id: str = "") -> dict[str, Any]:
    """Safe, read-only inspection for Managers through existing BCT execute."""
    value = read_relay_settings(scope_id)
    return {
        "version": 1,
        "settings": value,
        "revision": value["config_sha256"],
        "catalog": {key: dict(item) for key, item in _CATALOG.items()},
        "immutable_contract": list(_IMMUTABLE_CONTRACT),
        "apply_boundary": "NEXT_UNSENT_MESSAGE",
        "apply_boundaries": dict(_APPLY_BOUNDARIES),
        "message_sources": {
            "active": str(_DEFAULT_PATH),
            "legacy_relay_note_files_automatically_injected": False,
        },
    }


def propose_relay_settings_patch(
    *, scope_id: str = "", changes: dict[str, Any],
) -> dict[str, Any]:
    """Preview one partial update without any disk write.

    Send new_content and the exact precondition to the existing BCT write
    capability. It alone owns atomic replacement and optimistic CAS.
    This adds no new executable write engine or BCT authorization system.
    """
    if not isinstance(scope_id, str) or (scope_id and not _SCOPE.fullmatch(scope_id)):
        raise ValueError("RELAY_SETTINGS_SCOPE_INVALID")
    if not isinstance(changes, dict) or not 1 <= len(changes) <= len(_ALLOWED):
        raise ValueError("RELAY_SETTINGS_PATCH_INVALID")
    if set(changes) - _ALLOWED:
        raise ValueError("RELAY_SETTINGS_KEYS_INVALID")
    path = Path(os.environ.get("BCT_RELAY_SETTINGS_PATH", str(_DEFAULT_PATH)))
    raw, revision = _read_unicode(path)
    if revision != "defaults":
        read_relay_settings(scope_id)  # rejects malformed settings before patch
    raw = raw if revision != "defaults" else {
        "version": 1, "defaults": {}, "projects": {},
    }
    updated = json.loads(json.dumps(raw, ensure_ascii=False))
    target = (
        updated["projects"].setdefault(scope_id, {})
        if scope_id else updated["defaults"]
    )
    if not isinstance(target, dict):
        raise ValueError("RELAY_SETTINGS_TARGET_INVALID")
    for key, value in changes.items():
        if value is None:
            target.pop(key, None)
        else:
            _validated({key: value})
            target[key] = value
    if scope_id and not target:
        updated["projects"].pop(scope_id, None)
    _validated(updated["defaults"])
    for key, value in updated["projects"].items():
        if not isinstance(key, str) or not _SCOPE.fullmatch(key):
            raise ValueError("RELAY_SETTINGS_PROJECT_INVALID")
        _validated(value)
    content = json.dumps(
        updated, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    if len(content.encode("utf-8")) > 65_536:
        raise ValueError("RELAY_SETTINGS_TOO_LARGE")
    candidate_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    effective = dict(_DEFAULTS)
    effective.update(_validated(updated["defaults"]))
    if scope_id:
        effective.update(_validated(updated["projects"].get(scope_id, {})))
    return {
        "path": str(path),
        "scope_id": scope_id,
        "expected_absent": revision == "defaults",
        "expected_sha256": None if revision == "defaults" else revision,
        "new_sha256": candidate_sha,
        "new_content": content,
        "effective_preview": effective,
        "changed": revision != candidate_sha,
        "effect": "NONE_PREVIEW_ONLY",
    }


def _cli() -> None:
    """For AI Managers: old scope preview or propose scope JSON-patch.

    This CLI NEVER writes. The existing BCT write operation enforces roots,
    ownership, current SHA and atomicity before modifying a settings file.
    """
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args and args[0] == "propose":
        if len(args) != 3:
            raise ValueError("RELAY_SETTINGS_CLI_PROPOSE_ARGS")
        changes = json.loads(args[2], object_pairs_hook=_pairs_unique)
        answer = propose_relay_settings_patch(scope_id=args[1], changes=changes)
    elif len(args) <= 1:
        answer = preview_relay_settings(args[0] if args else "")
    else:
        raise ValueError("RELAY_SETTINGS_CLI_ARGS_INVALID")
    print(json.dumps(answer, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
