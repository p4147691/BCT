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


if __name__ == "__main__":
    import sys
    requested_scope = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(preview_relay_settings(requested_scope), ensure_ascii=False, indent=2))
