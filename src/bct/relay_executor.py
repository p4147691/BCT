"""Bounded execution adapter for hot-read relay control settings.

The settings document selects only handlers registered here.  It cannot import
Python, name an arbitrary BCT capability, or grant authority.  The surrounding
OperationCoordinator authorizes the selected existing capability and owns its
one durable effect receipt.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import re
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, PreconditionError, Work
from bct.relay_control import merge_patch
from bct.relay_settings import read_relay_control, utf16_units


_SCOPE = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_PURPOSE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
_REFERENCE = re.compile(r"\$\{([A-Za-z][A-Za-z0-9_.:-]*(?:\.[A-Za-z0-9_.:-]+)*)\}")
_MAX_CONTEXT_BYTES = 64 * 1024


def runtime_registry_catalog() -> dict[tuple[str, str], dict[str, str]]:
    """Return the fixed public registry; config aliases do not extend it."""
    return {
        ("message", "compose.worker"): {
            "kind": "pure", "effect": "pure", "capability": "",
        },
        ("rcc", "delivery.start"): {
            "kind": "operation", "effect": "external", "capability": "relay_browser",
            "command": "delivery-start", "timeout_argument": "timeout_s",
        },
        ("rcc", "delivery.status"): {
            "kind": "operation", "effect": "read", "capability": "relay_browser",
            "command": "delivery-status", "timeout_argument": "timeout_s",
        },
        ("rcc", "delivery.return"): {
            "kind": "operation", "effect": "external", "capability": "relay_browser",
            "command": "delivery-return", "timeout_argument": "timeout_s",
        },
        ("rcc", "delivery.manager_status"): {
            "kind": "operation", "effect": "read", "capability": "relay_browser",
            "command": "delivery-manager-status", "timeout_argument": "timeout_s",
        },
        ("rcc", "delivery.preview"): {
            "kind": "operation", "effect": "pure", "capability": "relay_browser",
            "command": "delivery-preview", "timeout_argument": "timeout_s",
        },
        ("rcc", "state"): {
            "kind": "operation", "effect": "read", "capability": "relay_browser",
            "command": "state", "timeout_argument": "timeout_s",
        },
        ("rcc", "send.to_tab"): {
            "kind": "operation", "effect": "external", "capability": "relay_browser",
            "command": "send-to-tab", "timeout_argument": "timeout_s",
        },
        ("cdp", "list_pages"): {
            "kind": "operation", "effect": "read", "capability": "cdp_inspect",
            "operation": "list_pages",
        },
    }


def registry_preview(functions: dict[str, Any]) -> dict[str, Any]:
    registry = runtime_registry_catalog()
    answer: dict[str, Any] = {}
    for name, function in functions.items():
        key = (str(function.get("driver") or ""), str(function.get("call") or ""))
        spec = registry.get(key)
        compatible = bool(spec and spec["effect"] == function.get("effect"))
        answer[name] = {
            "driver": key[0],
            "call": key[1],
            "declared_effect": function.get("effect"),
            "registered": spec is not None,
            "effect_compatible": compatible,
            "capability": spec.get("capability", "") if spec else "",
            "executable": compatible,
        }
    return answer


def _bounded_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreconditionError("RELAY_CONTROL_CONTEXT_INVALID")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        detached = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PreconditionError("RELAY_CONTROL_CONTEXT_INVALID") from exc
    if len(encoded) > _MAX_CONTEXT_BYTES or len(value) > 128:
        raise PreconditionError("RELAY_CONTROL_CONTEXT_TOO_LARGE")
    return detached


def _lookup(values: dict[str, Any], path: str) -> Any:
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise PreconditionError("RELAY_CONTROL_REFERENCE_MISSING:" + path)
        current = current[part]
    return current


def _resolve(value: Any, values: dict[str, Any], *, depth: int = 0) -> Any:
    if depth > 16:
        raise PreconditionError("RELAY_CONTROL_REFERENCE_TOO_DEEP")
    if isinstance(value, dict):
        return {key: _resolve(item, values, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, values, depth=depth + 1) for item in value]
    if not isinstance(value, str):
        return value
    full = _REFERENCE.fullmatch(value)
    if full:
        return json.loads(json.dumps(_lookup(values, full.group(1)), ensure_ascii=False))

    def substitute(match: re.Match[str]) -> str:
        selected = _lookup(values, match.group(1))
        if selected is None:
            return ""
        if type(selected) in {str, int, float, bool}:
            return str(selected).lower() if isinstance(selected, bool) else str(selected)
        return json.dumps(selected, ensure_ascii=False, separators=(",", ":"))

    return _REFERENCE.sub(substitute, value)


class RelayControlFeature:
    """Resolve one configured purpose to one existing, authorized operation."""

    capability = "relay_control"

    def __init__(self, *, store, features: dict[str, Any]):
        self.store = store
        self.features = features
        self.registry = runtime_registry_catalog()

    def _pure_compose_worker(
        self, *, work: Work, arguments: dict[str, Any], scope_id: str,
    ) -> dict[str, Any]:
        from bct.relay_prompt import compose_worker_delivery

        allowed = {
            "manager_conversation_key", "worker_conversation_key", "task", "scope_id",
        }
        if set(arguments) - allowed:
            raise PreconditionError("RELAY_CONTROL_PURE_ARGUMENT_NOT_ALLOWED")
        selected_scope = str(arguments.get("scope_id") or scope_id)
        if selected_scope != scope_id:
            raise PreconditionError("RELAY_CONTROL_SCOPE_OVERRIDE_DENIED")
        try:
            text = compose_worker_delivery(
                store=self.store, scope_id=scope_id,
                manager_conversation_key=str(arguments.get("manager_conversation_key") or ""),
                worker_conversation_key=str(arguments.get("worker_conversation_key") or ""),
                task=str(arguments.get("task") or ""), work_id=work.work_id,
            )
        except (KeyError, OSError, UnicodeError, ValueError) as exc:
            raise PreconditionError(str(exc)) from exc
        return {
            "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "utf16_units": utf16_units(text),
        }

    def _prepare_operation(
        self, *, work: Work, spec: dict[str, str], arguments: dict[str, Any],
    ) -> FeatureRequest:
        capability = spec["capability"]
        feature = self.features.get(capability)
        if feature is None or capability == self.capability:
            raise PreconditionError("RELAY_CONTROL_HANDLER_UNAVAILABLE:" + capability)
        delegated = dict(arguments)
        fixed = {key: value for key, value in spec.items() if key in {"command", "operation"}}
        for key, value in fixed.items():
            if key in delegated and delegated[key] != value:
                raise PreconditionError("RELAY_CONTROL_FIXED_ARGUMENT_MISMATCH:" + key)
            delegated[key] = value
        return feature.prepare(work=work, arguments=delegated)

    @staticmethod
    def _selection(arguments: dict[str, Any]) -> tuple[str, str, dict[str, Any], str, dict[str, Any]]:
        allowed = {"purpose", "scope_id", "context", "expected_settings_sha256"}
        if not isinstance(arguments, dict) or set(arguments) - allowed:
            raise PreconditionError("RELAY_CONTROL_ARGUMENT_NOT_ALLOWED")
        purpose = str(arguments.get("purpose") or "")
        scope_id = str(arguments.get("scope_id") or "")
        expected_revision = str(arguments.get("expected_settings_sha256") or "")
        if not _PURPOSE.fullmatch(purpose):
            raise PreconditionError("RELAY_CONTROL_PURPOSE_INVALID")
        if scope_id and not _SCOPE.fullmatch(scope_id):
            raise PreconditionError("RELAY_CONTROL_SCOPE_INVALID")
        try:
            control = read_relay_control(scope_id)
        except (OSError, UnicodeError, ValueError) as exc:
            raise PreconditionError(str(exc)) from exc
        revision = str(control["config_sha256"])
        if expected_revision and expected_revision != revision:
            raise PreconditionError("RELAY_CONTROL_SETTINGS_REVISION_CHANGED")
        if not control["enabled"]:
            raise PreconditionError("RELAY_CONTROL_DISABLED")
        route_name = control["selected_routes"].get(purpose)
        if not route_name:
            raise PreconditionError("RELAY_CONTROL_PURPOSE_NOT_SELECTED:" + purpose)
        return purpose, scope_id, control, route_name, control["routes"][route_name]

    def delegated_capability(self, arguments: dict[str, Any]) -> str:
        """Return the static policy action without composing or preparing I/O."""
        _purpose, _scope_id, control, _route_name, route = self._selection(arguments)
        step_id = route["entry"]
        for _index in range(route["max_steps"]):
            step = route["steps"][step_id]
            if step.get("guard"):
                raise PreconditionError("RELAY_CONTROL_GUARD_NOT_SUPPORTED:" + step_id)
            function = control["functions"][step["use"]]
            spec = self.registry.get((function["driver"], function["call"]))
            if spec is None:
                raise PreconditionError(
                    "RELAY_CONTROL_FUNCTION_NOT_REGISTERED:" + step["use"]
                )
            if spec["effect"] != function["effect"]:
                raise PreconditionError("RELAY_CONTROL_EFFECT_MISMATCH:" + step["use"])
            if spec["kind"] == "operation":
                if any(target != "END" for target in step.get("next", {}).values()):
                    raise PreconditionError(
                        "RELAY_CONTROL_OPERATION_MUST_TERMINATE:" + step_id
                    )
                return spec["capability"]
            target = step.get("next", {}).get("APPLIED", "END")
            if target == "END":
                raise PreconditionError("RELAY_CONTROL_OPERATION_STEP_REQUIRED")
            step_id = target
        raise PreconditionError("RELAY_CONTROL_ROUTE_DID_NOT_PREPARE_OPERATION")

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        purpose, scope_id, control, route_name, route = self._selection(arguments)
        revision = str(control["config_sha256"])
        context = _bounded_context(arguments.get("context", {}))
        values = {**control["variables"], **context}
        values.update({
            "scope_id": scope_id, "work_id": work.work_id,
            "settings_sha256": revision,
        })
        step_id = route["entry"]
        visited: list[dict[str, Any]] = []
        delegated: FeatureRequest | None = None
        delegated_spec: dict[str, str] | None = None
        for _index in range(route["max_steps"]):
            step = route["steps"][step_id]
            if step.get("guard"):
                raise PreconditionError("RELAY_CONTROL_GUARD_NOT_SUPPORTED:" + step_id)
            function = control["functions"][step["use"]]
            spec = self.registry.get((function["driver"], function["call"]))
            if spec is None:
                raise PreconditionError(
                    "RELAY_CONTROL_FUNCTION_NOT_REGISTERED:" + step["use"]
                )
            if spec["effect"] != function["effect"]:
                raise PreconditionError("RELAY_CONTROL_EFFECT_MISMATCH:" + step["use"])
            merged = merge_patch(function.get("arguments", {}), step.get("arguments", {}))
            resolved = _resolve(merged, values)
            if not isinstance(resolved, dict):
                raise PreconditionError("RELAY_CONTROL_RESOLVED_ARGUMENTS_INVALID")
            if spec["kind"] == "pure":
                if (function["driver"], function["call"]) != ("message", "compose.worker"):
                    raise PreconditionError("RELAY_CONTROL_PURE_HANDLER_UNAVAILABLE")
                output = self._pure_compose_worker(
                    work=work, arguments=resolved, scope_id=scope_id,
                )
                if step.get("save_as"):
                    values[step["save_as"]] = output
                visited.append({
                    "step": step_id, "function": step["use"], "outcome": "APPLIED",
                    "output_sha256": hashlib.sha256(json.dumps(
                        output, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")).hexdigest(),
                })
                target = step.get("next", {}).get("APPLIED", "END")
                if target == "END":
                    raise PreconditionError("RELAY_CONTROL_OPERATION_STEP_REQUIRED")
                step_id = target
                continue
            if delegated is not None:
                raise PreconditionError("RELAY_CONTROL_MULTIPLE_OPERATION_STEPS")
            if any(target != "END" for target in step.get("next", {}).values()):
                raise PreconditionError("RELAY_CONTROL_OPERATION_MUST_TERMINATE:" + step_id)
            timeout_argument = spec.get("timeout_argument")
            if timeout_argument:
                resolved.setdefault(timeout_argument, function["timeout_seconds"])
            delegated = self._prepare_operation(
                work=work, spec=spec, arguments=resolved,
            )
            delegated_spec = spec
            visited.append({
                "step": step_id, "function": step["use"], "outcome": "PREPARED",
            })
            break
        if delegated is None or delegated_spec is None:
            raise PreconditionError("RELAY_CONTROL_ROUTE_DID_NOT_PREPARE_OPERATION")
        frozen = {
            "capability": delegated.capability,
            "target": delegated.target,
            "arguments": delegated.arguments,
            "resources": list(delegated.resources),
            "preconditions": delegated.preconditions,
        }
        return FeatureRequest(
            self.capability, delegated.target,
            {
                "scope_id": scope_id, "purpose": purpose, "route": route_name,
                "settings_sha256": revision, "prepared_step": step_id,
                "declared_effect": delegated_spec["effect"],
                "trace": visited, "delegated": frozen,
            }, delegated.resources,
            {
                "delegated_capability": delegated.capability,
                "settings_sha256": revision,
                "single_operation_step": True,
            },
        )

    def execute(self, request: FeatureRequest) -> FeatureResult:
        frozen = request.arguments["delegated"]
        capability = str(frozen["capability"])
        feature = self.features.get(capability)
        if feature is None or capability == self.capability:
            raise PreconditionError("RELAY_CONTROL_HANDLER_UNAVAILABLE:" + capability)
        delegated = FeatureRequest(
            capability=capability, target=str(frozen["target"]),
            arguments=dict(frozen["arguments"]),
            resources=tuple(str(item) for item in frozen["resources"]),
            preconditions=dict(frozen["preconditions"]),
            operation_id=request.operation_id,
        )
        result = feature.execute(delegated)
        if not isinstance(result, FeatureResult):
            raise TypeError("RELAY_CONTROL_HANDLER_RESULT_INVALID")
        # Preserve the delegated feature's established evidence keys at the
        # top level so existing result/recovery inspection remains compatible.
        evidence = {
            **result.evidence,
            "configured_flow": True,
            "scope_id": request.arguments["scope_id"],
            "purpose": request.arguments["purpose"],
            "route": request.arguments["route"],
            "prepared_step": request.arguments["prepared_step"],
            "settings_sha256": request.arguments["settings_sha256"],
            "delegated_capability": capability,
            "delegated_outcome": result.outcome.value,
            "delegated_evidence": result.evidence,
        }
        return replace(result, evidence=evidence)
