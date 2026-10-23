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
    "worker_intro": "BCT 협업 작업입니다. 제공된 작업 내용을 수행하세요.",
    "worker_return_instruction": (
        "이번 업무에서 직접 처리한 결과를 빠뜨리지 말고 보고하세요. "
        "완료하지 않은 일은 완료라고 주장하지 마세요. "
        "BCT가 결과 전문을 Manager에게 전달하므로 다른 대화로 중복 전송하지 마세요."
    ),
    "manager_intro": "BCT 협업 결과 반환입니다. 이 메시지 자체가 Manager의 기본 Wake입니다.",
    "manager_action": (
        "이번 Worker의 처리 결과 전문을 읽고 원래 목표·완료 조건에 비추어 판단하세요. "
        "현재 프로젝트의 보류·미완료 업무도 확인하고 필요한 설정을 조정할 수 있습니다. "
        "후속 업무가 필요하면 현재 사용 가능한 Worker에게 허용된 BCT "
        "relay_browser delivery-start로 실제로 전달하고 결과를 확인하세요. "
        "사용 가능한 도구가 없으면 실행했다고 주장하지 말고 FOLLOW_UP 업무를 보고하세요. "
        "계획한다고 말하는 것만으로 완료 처리하지 마세요. "
        "불확실한 과거 전송을 임의로 다시 제출하지 마세요."
    ),
    "manager_sections": ["context", "worker_result", "action"],
    "include_pending": True,
    "pending_limit": 6,
}
_TEXT_KEYS = {"worker_intro", "worker_return_instruction", "manager_intro", "manager_action"}
_ALLOWED = set(_DEFAULTS)
_LAYOUT = {"context", "worker_result", "action"}


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
        elif key == "manager_sections":
            if (not isinstance(value, list) or len(value) != len(_LAYOUT)
                    or any(not isinstance(v, str) for v in value) or set(value) != _LAYOUT):
                raise ValueError("RELAY_SETTINGS_LAYOUT_INVALID")
            result[key] = list(value)
        elif key == "include_pending":
            if not isinstance(value, bool):
                raise ValueError("RELAY_SETTINGS_PENDING_INVALID")
            result[key] = value
        elif key == "pending_limit":
            if type(value) is not int or value < 0 or value > 12:
                raise ValueError("RELAY_SETTINGS_PENDING_LIMIT_INVALID")
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
    return {"version": 1, "settings": value, "revision": value["config_sha256"]}


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
