"""Declarative relay control plans stored in runtime settings.

This module only validates and previews data.  ``relay_executor`` separately
resolves a configured driver/call pair against a fixed registry while the
OperationCoordinator still enforces Work permissions and effect receipts.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any


_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_OUTCOME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
_PROFILE_KEYS = {
    "enabled", "variables", "functions", "routes", "selected_routes",
}
_FUNCTION_KEYS = {
    "driver", "call", "effect", "arguments", "timeout_seconds", "description",
}
_ROUTE_KEYS = {"description", "entry", "max_steps", "steps"}
_STEP_KEYS = {"use", "arguments", "save_as", "guard", "next"}
_EFFECTS = {"pure", "read", "external"}
_END = "END"


def empty_control() -> dict[str, Any]:
    return {
        "version": 1,
        "enabled": False,
        "variables": {},
        "functions": {},
        "routes": {},
        "selected_routes": {},
        "projects": {},
    }


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _name(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(code)
    return value


def _json_value(value: Any, *, depth: int = 0, nodes: list[int] | None = None) -> Any:
    """Copy a bounded JSON value while rejecting ambiguous/non-finite input."""
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 4096 or depth > 12:
        raise ValueError("RELAY_CONTROL_VALUE_TOO_COMPLEX")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("RELAY_CONTROL_VALUE_NONFINITE")
        return value
    if isinstance(value, str):
        if len(value) > 12_000 or "\x00" in value:
            raise ValueError("RELAY_CONTROL_VALUE_STRING_INVALID")
        return value
    if isinstance(value, list):
        if len(value) > 256:
            raise ValueError("RELAY_CONTROL_VALUE_LIST_TOO_LARGE")
        return [_json_value(item, depth=depth + 1, nodes=nodes) for item in value]
    if isinstance(value, dict):
        if len(value) > 256:
            raise ValueError("RELAY_CONTROL_VALUE_OBJECT_TOO_LARGE")
        answer: dict[str, Any] = {}
        for key, item in value.items():
            if (not isinstance(key, str) or not key or len(key) > 128
                    or "\x00" in key or key in answer):
                raise ValueError("RELAY_CONTROL_VALUE_KEY_INVALID")
            answer[key] = _json_value(item, depth=depth + 1, nodes=nodes)
        return answer
    raise ValueError("RELAY_CONTROL_VALUE_TYPE_INVALID")


def _validate_function(name: str, value: Any) -> dict[str, Any]:
    _name(name, "RELAY_CONTROL_FUNCTION_NAME_INVALID")
    if (not isinstance(value, dict) or set(value) - _FUNCTION_KEYS
            or not {"driver", "call", "effect"} <= set(value)):
        raise ValueError("RELAY_CONTROL_FUNCTION_INVALID:" + name)
    driver = _name(value["driver"], "RELAY_CONTROL_DRIVER_INVALID:" + name)
    call = _name(value["call"], "RELAY_CONTROL_CALL_INVALID:" + name)
    effect = value["effect"]
    if effect not in _EFFECTS:
        raise ValueError("RELAY_CONTROL_EFFECT_INVALID:" + name)
    timeout = value.get("timeout_seconds", 30)
    if (type(timeout) not in {int, float} or type(timeout) is bool
            or not math.isfinite(timeout) or not 0.1 <= float(timeout) <= 600):
        raise ValueError("RELAY_CONTROL_TIMEOUT_INVALID:" + name)
    description = value.get("description", "")
    if not isinstance(description, str) or len(description) > 1000 or "\x00" in description:
        raise ValueError("RELAY_CONTROL_DESCRIPTION_INVALID:" + name)
    arguments = value.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("RELAY_CONTROL_ARGUMENTS_INVALID:" + name)
    return {
        "driver": driver,
        "call": call,
        "effect": effect,
        "arguments": _json_value(arguments),
        "timeout_seconds": timeout,
        **({"description": description} if description else {}),
    }


def _validate_route(name: str, value: Any, functions: dict[str, Any]) -> dict[str, Any]:
    _name(name, "RELAY_CONTROL_ROUTE_NAME_INVALID")
    if (not isinstance(value, dict) or set(value) - _ROUTE_KEYS
            or not {"entry", "max_steps", "steps"} <= set(value)):
        raise ValueError("RELAY_CONTROL_ROUTE_INVALID:" + name)
    description = value.get("description", "")
    if not isinstance(description, str) or len(description) > 1000 or "\x00" in description:
        raise ValueError("RELAY_CONTROL_ROUTE_DESCRIPTION_INVALID:" + name)
    entry = _name(value["entry"], "RELAY_CONTROL_ROUTE_ENTRY_INVALID:" + name)
    max_steps = value["max_steps"]
    if type(max_steps) is not int or not 1 <= max_steps <= 1000:
        raise ValueError("RELAY_CONTROL_ROUTE_MAX_STEPS_INVALID:" + name)
    steps = value["steps"]
    if not isinstance(steps, dict) or not 1 <= len(steps) <= 128:
        raise ValueError("RELAY_CONTROL_ROUTE_STEPS_INVALID:" + name)
    if entry not in steps:
        raise ValueError("RELAY_CONTROL_ROUTE_ENTRY_MISSING:" + name)
    normalized: dict[str, Any] = {}
    for step_id, step in steps.items():
        _name(step_id, "RELAY_CONTROL_STEP_NAME_INVALID:" + name)
        if (not isinstance(step, dict) or set(step) - _STEP_KEYS
                or "use" not in step):
            raise ValueError("RELAY_CONTROL_STEP_INVALID:" + name + ":" + step_id)
        use = _name(step["use"], "RELAY_CONTROL_STEP_FUNCTION_INVALID:" + step_id)
        if use not in functions:
            raise ValueError("RELAY_CONTROL_STEP_FUNCTION_MISSING:" + use)
        arguments = step.get("arguments", {})
        guard = step.get("guard", {})
        transitions = step.get("next", {})
        if not isinstance(arguments, dict) or not isinstance(guard, dict):
            raise ValueError("RELAY_CONTROL_STEP_DATA_INVALID:" + step_id)
        if not isinstance(transitions, dict) or len(transitions) > 64:
            raise ValueError("RELAY_CONTROL_STEP_NEXT_INVALID:" + step_id)
        next_copy: dict[str, str] = {}
        for outcome, target in transitions.items():
            if not isinstance(outcome, str) or not _OUTCOME.fullmatch(outcome):
                raise ValueError("RELAY_CONTROL_OUTCOME_INVALID:" + step_id)
            if target != _END:
                _name(target, "RELAY_CONTROL_NEXT_TARGET_INVALID:" + step_id)
                if target not in steps:
                    raise ValueError("RELAY_CONTROL_NEXT_TARGET_MISSING:" + target)
            next_copy[outcome] = target
        save_as = step.get("save_as", "")
        if save_as:
            _name(save_as, "RELAY_CONTROL_SAVE_NAME_INVALID:" + step_id)
        normalized[step_id] = {
            "use": use,
            "arguments": _json_value(arguments),
            "guard": _json_value(guard),
            "next": next_copy,
            **({"save_as": save_as} if save_as else {}),
        }
    return {
        "entry": entry,
        "max_steps": max_steps,
        "steps": normalized,
        **({"description": description} if description else {}),
    }


def _validate_profile(value: Any, *, partial: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - _PROFILE_KEYS:
        raise ValueError("RELAY_CONTROL_PROFILE_INVALID")
    if not partial and "enabled" not in value:
        raise ValueError("RELAY_CONTROL_ENABLED_REQUIRED")
    answer: dict[str, Any] = {}
    if "enabled" in value:
        if type(value["enabled"]) is not bool:
            raise ValueError("RELAY_CONTROL_ENABLED_INVALID")
        answer["enabled"] = value["enabled"]
    for key in ("variables", "functions", "routes", "selected_routes"):
        if key in value and not isinstance(value[key], dict):
            raise ValueError("RELAY_CONTROL_MAP_INVALID:" + key)
    if "variables" in value:
        if len(value["variables"]) > 256:
            raise ValueError("RELAY_CONTROL_VARIABLES_TOO_LARGE")
        answer["variables"] = {
            _name(key, "RELAY_CONTROL_VARIABLE_NAME_INVALID"): _json_value(item)
            for key, item in value["variables"].items()
        }
    if "functions" in value:
        if len(value["functions"]) > 128:
            raise ValueError("RELAY_CONTROL_FUNCTIONS_TOO_LARGE")
        if partial:
            answer["functions"] = {
                _name(key, "RELAY_CONTROL_FUNCTION_NAME_INVALID"): _json_value(item)
                for key, item in value["functions"].items()
            }
        else:
            answer["functions"] = {
                key: _validate_function(key, item)
                for key, item in value["functions"].items()
            }
    # Route/function references are validated after global and project overlays merge.
    if "routes" in value:
        if len(value["routes"]) > 64:
            raise ValueError("RELAY_CONTROL_ROUTES_TOO_LARGE")
        answer["routes"] = {
            _name(key, "RELAY_CONTROL_ROUTE_NAME_INVALID"): _json_value(item)
            for key, item in value["routes"].items()
        }
    if "selected_routes" in value:
        if len(value["selected_routes"]) > 64:
            raise ValueError("RELAY_CONTROL_SELECTIONS_TOO_LARGE")
        selections: dict[str, str] = {}
        for purpose, route in value["selected_routes"].items():
            selections[_name(purpose, "RELAY_CONTROL_PURPOSE_INVALID")] = _name(
                route, "RELAY_CONTROL_SELECTED_ROUTE_INVALID"
            )
        answer["selected_routes"] = selections
    return answer


def _overlay(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    answer = _copy(base)
    if "enabled" in override:
        answer["enabled"] = override["enabled"]
    for key in ("variables", "selected_routes"):
        answer[key].update(_copy(override.get(key, {})))
    for key in ("functions", "routes"):
        for name, patch in override.get(key, {}).items():
            answer[key][name] = merge_patch(answer[key].get(name, {}), patch)
    return answer


def validate_control(value: Any, *, scope_pattern: re.Pattern[str]) -> dict[str, Any]:
    if (not isinstance(value, dict)
            or set(value) - (_PROFILE_KEYS | {"version", "projects"})
            or type(value.get("version")) is not int or value.get("version") != 1
            or not isinstance(value.get("projects", {}), dict)):
        raise ValueError("RELAY_CONTROL_SCHEMA_INVALID")
    global_profile = _validate_profile(
        {key: item for key, item in value.items() if key in _PROFILE_KEYS}
    )
    projects: dict[str, Any] = {}
    for scope_id, profile in value.get("projects", {}).items():
        if not isinstance(scope_id, str) or not scope_pattern.fullmatch(scope_id):
            raise ValueError("RELAY_CONTROL_PROJECT_INVALID")
        projects[scope_id] = _validate_profile(profile, partial=True)
    normalized = {"version": 1, **global_profile, "projects": projects}
    # Every possible effective profile must be internally consistent.
    effective_control(normalized, "")
    for scope_id in projects:
        effective_control(normalized, scope_id)
    return normalized


def effective_control(control: dict[str, Any], scope_id: str) -> dict[str, Any]:
    base = {
        "enabled": control.get("enabled", False),
        "variables": _copy(control.get("variables", {})),
        "functions": _copy(control.get("functions", {})),
        "routes": _copy(control.get("routes", {})),
        "selected_routes": _copy(control.get("selected_routes", {})),
    }
    if scope_id:
        base = _overlay(base, control.get("projects", {}).get(scope_id, {}))
    functions = {
        key: _validate_function(key, item) for key, item in base["functions"].items()
    }
    routes = {
        key: _validate_route(key, item, functions) for key, item in base["routes"].items()
    }
    for purpose, route in base["selected_routes"].items():
        _name(purpose, "RELAY_CONTROL_PURPOSE_INVALID")
        if route not in routes:
            raise ValueError("RELAY_CONTROL_SELECTED_ROUTE_MISSING:" + route)
    return {
        "enabled": bool(base["enabled"]),
        "variables": _json_value(base["variables"]),
        "functions": functions,
        "routes": routes,
        "selected_routes": dict(base["selected_routes"]),
    }


def merge_patch(target: Any, patch: Any, *, depth: int = 0) -> Any:
    """Apply RFC 7396-style merge patch to a detached JSON value."""
    if depth > 12:
        raise ValueError("RELAY_CONTROL_PATCH_TOO_DEEP")
    _json_value(patch)
    if not isinstance(patch, dict):
        return _copy(patch)
    answer = _copy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            answer.pop(key, None)
        else:
            answer[key] = merge_patch(answer.get(key), value, depth=depth + 1)
    return answer


def resolved_preview(control: dict[str, Any], *, scope_id: str) -> dict[str, Any]:
    """Return a data-only preview; relay_settings adds runtime registry truth."""
    effective = effective_control(control, scope_id)
    selected: dict[str, Any] = {}
    for purpose, route_name in effective["selected_routes"].items():
        route = effective["routes"][route_name]
        steps: dict[str, Any] = {}
        for step_id, step in route["steps"].items():
            function = effective["functions"][step["use"]]
            merged_arguments = merge_patch(
                function.get("arguments", {}), step.get("arguments", {})
            )
            steps[step_id] = {
                **_copy(step),
                "resolved_function": {
                    "driver": function["driver"],
                    "call": function["call"],
                    "effect": function["effect"],
                    "timeout_seconds": function["timeout_seconds"],
                    "arguments": merged_arguments,
                    "runtime_availability": "NOT_CHECKED_PREVIEW_ONLY",
                },
            }
        selected[purpose] = {
            "route": route_name,
            "entry": route["entry"],
            "max_steps": route["max_steps"],
            "steps": steps,
        }
    return {
        "scope_id": scope_id,
        "enabled": effective["enabled"],
        "variables": effective["variables"],
        "selected_routes": selected,
        "function_count": len(effective["functions"]),
        "route_count": len(effective["routes"]),
        "execution_connected": False,
        "effect": "NONE_PREVIEW_ONLY",
        "apply_boundary": "NEXT_UNSTARTED_FLOW",
        "prepared_or_started_flow": "FROZEN",
        "authority": "CONFIGURATION_DOES_NOT_GRANT_CAPABILITIES",
    }
