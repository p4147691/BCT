"""Validation and scheduling facts for Manager-declared derived Chain work.

This module deliberately does not infer a problem from prose, select a Worker,
create a tab, or send a message.  A Manager declares the classification; this
module keeps that declaration safe to store and tells the Chain delivery recipe
which declared targets are immediately independent.
"""
from __future__ import annotations

import re
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")
_KINDS = frozenset({"SELF", "INDEPENDENT", "BLOCKED", "RISK", "ASK_USER"})


def _text(value: object, *, code: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise ValueError(code)
    return text


def validate_derived_tasks(value: object, *, target_keys: set[str]) -> list[dict[str, Any]]:
    """Validate a declared derived-task graph without interpreting its prose.

    ``INDEPENDENT`` means the target may be dispatched in this Direction.
    Other kinds remain durable Manager evidence only.  Dependencies must be
    resolved in a later Manager Direction; this function never guesses that a
    sibling's external effect completed.
    """
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("CHAIN_DERIVED_TASKS_INVALID")
    tasks: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    target_owners: set[str] = set()
    mutable_owners: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "task_id", "classification", "summary", "depends_on",
            "target_conversation_key", "mutable_scopes",
        }:
            raise ValueError("CHAIN_DERIVED_TASK_INVALID")
        task_id = str(item.get("task_id") or "").strip()
        if not _ID.fullmatch(task_id) or task_id in identifiers:
            raise ValueError("CHAIN_DERIVED_TASK_ID_INVALID")
        identifiers.add(task_id)
        classification = str(item.get("classification") or "").strip().upper()
        if classification not in _KINDS:
            raise ValueError("CHAIN_DERIVED_TASK_CLASSIFICATION_INVALID")
        summary = _text(item.get("summary"), code="CHAIN_DERIVED_TASK_SUMMARY_INVALID", limit=4000)
        dependencies = item.get("depends_on")
        if not isinstance(dependencies, list) or len(dependencies) > 16:
            raise ValueError("CHAIN_DERIVED_TASK_DEPENDENCIES_INVALID")
        depends_on = sorted({str(value or "").strip() for value in dependencies})
        if (not all(_ID.fullmatch(value) for value in depends_on)
                or task_id in depends_on or len(depends_on) != len(dependencies)):
            raise ValueError("CHAIN_DERIVED_TASK_DEPENDENCIES_INVALID")
        mutable = item.get("mutable_scopes")
        if not isinstance(mutable, list) or len(mutable) > 32:
            raise ValueError("CHAIN_DERIVED_TASK_MUTABLE_SCOPES_INVALID")
        mutable_scopes = sorted({_text(scope, code="CHAIN_DERIVED_TASK_SCOPE_INVALID", limit=300)
                                for scope in mutable})
        if len(mutable_scopes) != len(mutable):
            raise ValueError("CHAIN_DERIVED_TASK_MUTABLE_SCOPES_INVALID")
        target = str(item.get("target_conversation_key") or "").strip().lower()
        if classification == "INDEPENDENT":
            if target not in target_keys or not _UUID.fullmatch(target):
                raise ValueError("CHAIN_DERIVED_TASK_TARGET_INVALID")
            if target in target_owners:
                raise ValueError("CHAIN_DERIVED_TASK_TARGET_CONFLICT")
            target_owners.add(target)
            for scope in mutable_scopes:
                owner = mutable_owners.setdefault(scope, task_id)
                if owner != task_id:
                    raise ValueError("CHAIN_DERIVED_TASK_MUTABLE_SCOPE_CONFLICT")
        elif target:
            raise ValueError("CHAIN_DERIVED_TASK_TARGET_FORBIDDEN")
        tasks.append({
            "task_id": task_id,
            "classification": classification,
            "summary": summary,
            "depends_on": depends_on,
            "target_conversation_key": target,
            "mutable_scopes": mutable_scopes,
        })
    known = {task["task_id"] for task in tasks}
    if any(dependency not in known for task in tasks for dependency in task["depends_on"]):
        raise ValueError("CHAIN_DERIVED_TASK_DEPENDENCY_NOT_FOUND")
    edges = {task["task_id"]: task["depends_on"] for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError("CHAIN_DERIVED_TASK_DEPENDENCY_CYCLE")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in edges[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)
    for identifier in sorted(edges):
        visit(identifier)
    return tasks


def dispatch_plan(*, tasks: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Return immediate target keys and durable non-dispatch reasons.

    With no declared derived tasks, this preserves the existing behavior: every
    declared target is an immediately dispatchable target.
    """
    if not tasks:
        return {"ready_target_keys": {str(target["conversation_key"]) for target in targets},
                "deferred": [], "classification": "LEGACY_ALL_TARGETS"}
    by_target = {task["target_conversation_key"]: task for task in tasks
                 if task["classification"] == "INDEPENDENT"}
    ready = {key for key, task in by_target.items() if not task["depends_on"]}
    deferred = []
    for task in tasks:
        if task["classification"] == "INDEPENDENT" and task["depends_on"]:
            reason = "DEPENDENCIES_PENDING"
        elif task["classification"] == "INDEPENDENT":
            continue
        else:
            reason = task["classification"]
        deferred.append({"task_id": task["task_id"], "classification": task["classification"],
                         "reason": reason, "depends_on": list(task["depends_on"])})
    unclassified = [target for target in targets if target["conversation_key"] not in by_target]
    for target in unclassified:
        deferred.append({"task_id": "", "classification": "UNCLASSIFIED_TARGET",
                         "reason": "MANAGER_CLASSIFICATION_REQUIRED",
                         "target_conversation_key": target["conversation_key"], "depends_on": []})
    return {"ready_target_keys": ready, "deferred": deferred,
            "classification": "MANAGER_DECLARED"}
