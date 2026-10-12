from __future__ import annotations

import ipaddress
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = {
    "task_type": {
        "type": "choice",
        "instructions": "Classify the requested work by its dominant effect.",
        "criteria": {
            "READ": "Inspect, list, search, compare, or report without changing state.",
            "WRITE": "Create, edit, patch, rename, or otherwise change project/user data.",
            "SYSTEM": "Start, stop, restart, reconfigure, or change runtime or host state.",
        },
    },
    "executor": {
        "type": "choice",
        "instructions": "Recommend the smallest capable execution boundary.",
        "criteria": {
            "BCT": "A bounded structured BCT capability can complete the operation deterministically.",
            "CODEX": "Cross-file implementation, debugging, migration, or substantial reasoning is needed.",
            "RCC": "The operation must interact with an existing browser or ChatGPT web session.",
            "NONE": "No executor should run because the request is informational or already complete.",
        },
    },
    "failure_cause": {
        "type": "choice",
        "instructions": "Classify the most likely failure family from the supplied evidence.",
        "criteria": {
            "INPUT": "Required input is missing, malformed, stale, or contradictory.",
            "AUTHORITY": "Authentication, permission, ownership, or approval is the proven blocker.",
            "CONFLICT": "Concurrent work, a lease, dirty paths, or state ownership conflicts.",
            "TRANSPORT": "A connection, timeout, response loss, endpoint, or session transport failed.",
            "EXECUTION": "The selected tool or process ran and failed with a confirmed execution error.",
            "NONE": "No failure is present in the stated facts.",
            "UNKNOWN": "The evidence is insufficient to distinguish the cause.",
        },
    },
    "next_action": {
        "type": "choice",
        "instructions": "Recommend one safe next action.",
        "criteria": {
            "RETRY": "Retry once because the operation is idempotent and a concrete transient condition changed.",
            "RECHECK": "Collect or refresh exact evidence before deciding whether to execute again.",
            "STOP": "Do not repeat the operation because it is unsafe, stale, duplicate, or already applied.",
            "ESCALATE": "A user or higher-authority decision is genuinely required.",
            "NOOP": "No further action is required.",
        },
    },
}


def _loopback_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("DECISION_ENDPOINT_INVALID")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise ValueError("DECISION_ENDPOINT_NOT_LOOPBACK") from exc
    if not address.is_loopback or not parsed.port:
        raise ValueError("DECISION_ENDPOINT_NOT_LOOPBACK")
    return f"http://{parsed.hostname}:{parsed.port}"


class DecisionClient:
    def __init__(self, endpoint_file: str | Path, *, timeout_s: float = 1.0):
        self.endpoint_file = Path(endpoint_file)
        self.timeout_s = max(0.05, min(float(timeout_s), 30.0))

    def endpoint(self) -> dict[str, Any]:
        value = json.loads(self.endpoint_file.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("DECISION_ENDPOINT_RECORD_INVALID")
        result = dict(value)
        result["base_url"] = _loopback_url(str(value.get("base_url") or ""))
        return result

    def _json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint = self.endpoint()
        data = None if body is None else json.dumps(
            body, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint["base_url"] + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("DECISION_RESPONSE_INVALID")
        return payload

    def status(self) -> dict[str, Any]:
        endpoint = self.endpoint()
        health = self._json("GET", "/health")
        loaded = health.get("loaded")
        model_name = str(endpoint.get("model_name") or "")
        ready = str(health.get("status") or "").casefold() in {"ok", "ready"}
        if isinstance(loaded, list) and model_name:
            ready = ready and model_name in loaded
        return {
            "ready": ready,
            "endpoint": endpoint["base_url"],
            "model_name": model_name,
            "model_sha256": str(endpoint.get("model_sha256") or ""),
            "mode": str(endpoint.get("mode") or "recommend_shadow"),
            "owner": str(endpoint.get("owner") or "external"),
            "health": health,
        }

    def recommend(self, structured_input: dict[str, Any], questions: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint = self.endpoint()
        body: dict[str, Any] = {
            "state": structured_input,
            "questions": questions or DEFAULT_QUESTIONS,
            "independent": True,
        }
        model_name = str(endpoint.get("model_name") or "")
        if model_name:
            body["model"] = model_name
        payload = self._json("POST", "/v1/systemone", body)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("DECISION_ANSWERS_MISSING")
        return {
            "model": payload.get("model") or model_name,
            "answers": {
                name: {
                    "choice": answer.get("choice"),
                    "confidence": answer.get("confidence"),
                    "certainty": answer.get("certainty"),
                    "probabilities": answer.get("probabilities"),
                }
                for name, answer in answers.items()
                if isinstance(answer, dict)
            },
            "usage": payload.get("usage"),
            "advisory_only": True,
        }
