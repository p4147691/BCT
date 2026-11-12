"""Pure validation and record preparation for the project-plan ledger.

Preparation performs no persistence or capability execution. The caller sends
the prepared arguments through the existing authorized project_context gateway.
"""
from __future__ import annotations

from typing import Any


def prepare_project_plan(
    *, work_id: str, plan_id: str, project: str, objective: str,
    acceptance: str, steps: list[dict[str, Any]], author: str,
    expected_revision: int = 0, discretion: str = "normal",
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", plan_id):
        return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_ID_INVALID"}
    if not project.strip() or not objective.strip() or not acceptance.strip():
        return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_REQUIRED_FIELDS"}
    if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
        return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_STEPS_INVALID"}
    if discretion not in {"limited", "normal", "extended"}:
        return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_DISCRETION_INVALID"}
    checked = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict) or not {"instruction", "acceptance"} <= step.keys():
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_STEP_INVALID"}
        instruction = step["instruction"]
        criterion = step["acceptance"]
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 4000 or not isinstance(criterion, str) or not criterion.strip() or len(criterion) > 4000:
            return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_STEP_INVALID"}
        checked.append({"text": f"{idx + 1}/{len(steps)}: {instruction} | 완료: {criterion}", "evidence": []})
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_REVISION_INVALID"}
    assumptions = assumptions or []
    if not isinstance(assumptions, list) or len(assumptions) > 30 or any(not isinstance(x, str) or len(x) > 2000 for x in assumptions):
        return {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_ASSUMPTIONS_INVALID"}
    record = {
        "title": "Run plan " + plan_id, "goal": objective,
        "scope_note": "Project: " + project + "; discretion: " + discretion,
        "summary": acceptance, "links": [{"type": "bct_work", "id": work_id}],
        "items": checked,
        "decisions": [{"text": "재량: " + discretion, "evidence": []}],
        "next_actions": [{"text": "가정: " + x, "evidence": []} for x in assumptions],
        "checkpoints": {"external": {"plan_id": plan_id, "project": project, "stage": "PLANNED"}},
    }
    return {
        "status": "READY",
        "arguments": {
            "operation": "central-save", "project": "run-plan-" + plan_id.lower(),
            "record": record, "author": author, "expected_revision": expected_revision,
        },
    }
