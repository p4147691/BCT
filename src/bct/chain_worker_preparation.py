"""Validated input and deterministic identities for Chain Worker preparation."""
from __future__ import annotations

import hashlib
import re
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,60}")
_INSTANCE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


def validate_worker_preparation(value: object) -> dict[str, Any]:
    """Validate A's explicit request without selecting or inventing a node."""
    if not isinstance(value, dict) or set(value) != {
        "preparation_id", "command", "instance_id", "window_id",
        "instruction", "display_name", "scope_name", "role_tags", "arrange",
    }:
        raise ValueError("CHAIN_WORKER_PREPARATION_INVALID")
    preparation_id = str(value.get("preparation_id") or "").strip()
    command = str(value.get("command") or "").strip().lower()
    instance_id = str(value.get("instance_id") or "").strip()
    window_id = value.get("window_id")
    instruction = str(value.get("instruction") or "")
    display_name = str(value.get("display_name") or "").strip()
    scope_name = str(value.get("scope_name") or "").strip()
    role_tags = value.get("role_tags")
    arrangement = value.get("arrange")
    if not _ID.fullmatch(preparation_id):
        raise ValueError("CHAIN_WORKER_PREPARATION_ID_INVALID")
    if command not in {"create-chat-tab", "create-chat-window"}:
        raise ValueError("CHAIN_WORKER_PREPARATION_COMMAND_INVALID")
    if not _INSTANCE.fullmatch(instance_id):
        raise ValueError("CHAIN_WORKER_PREPARATION_INSTANCE_INVALID")
    if type(window_id) is not int or window_id < 0:
        raise ValueError("CHAIN_WORKER_PREPARATION_WINDOW_INVALID")
    if command == "create-chat-tab" and window_id <= 0:
        raise ValueError("CHAIN_WORKER_PREPARATION_WINDOW_REQUIRED")
    if command == "create-chat-window" and window_id != 0:
        raise ValueError("CHAIN_WORKER_PREPARATION_WINDOW_FORBIDDEN")
    if not instruction.strip() or len(instruction) > 6000:
        raise ValueError("CHAIN_WORKER_PREPARATION_INSTRUCTION_INVALID")
    if not display_name or len(display_name) > 120 or not scope_name or len(scope_name) > 200:
        raise ValueError("CHAIN_WORKER_PREPARATION_METADATA_INVALID")
    if (not isinstance(role_tags, list) or not role_tags or len(role_tags) > 16
            or any(not isinstance(role, str) or not role.strip() or len(role) > 80
                   for role in role_tags)):
        raise ValueError("CHAIN_WORKER_PREPARATION_ROLES_INVALID")
    normalized_roles = sorted({role.strip() for role in role_tags}, key=str.casefold)
    folded = {role.casefold() for role in normalized_roles}
    if "worker" not in folded or folded & {"manager", "supervisor"}:
        raise ValueError("CHAIN_WORKER_PREPARATION_ROLE_CONFLICT")
    if arrangement is not None:
        if (not isinstance(arrangement, dict)
                or set(arrangement) != {"target_window_id", "index"}
                or type(arrangement.get("target_window_id")) is not int
                or arrangement["target_window_id"] <= 0
                or type(arrangement.get("index")) is not int
                or arrangement["index"] < -1):
            raise ValueError("CHAIN_WORKER_PREPARATION_ARRANGE_INVALID")
        arrangement = dict(arrangement)
    return {
        "preparation_id": preparation_id, "command": command,
        "instance_id": instance_id, "window_id": window_id,
        "instruction": instruction, "display_name": display_name,
        "scope_name": scope_name, "role_tags": normalized_roles,
        "arrange": arrangement,
    }


def worker_preparation_operation_id(
    *, direction_id: str, preparation_id: str, stage: str,
) -> str:
    """Return a stable bounded Operation ID for restart-safe stage replay."""
    if stage not in {"create", "arrange", "send", "watch", "register"}:
        raise ValueError("CHAIN_WORKER_PREPARATION_STAGE_INVALID")
    digest = hashlib.sha256(
        f"{direction_id}:{preparation_id}".encode("utf-8")
    ).hexdigest()[:20]
    return f"worker-{digest}-{stage}"
