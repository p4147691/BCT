"""Optional one-Manager/one-Worker Task Message envelope."""
from __future__ import annotations

import hashlib


def prepare_task_message_instruction(
    instruction: str,
    *,
    acceptance: str,
    bb_rule: str,
    manager_return_rule: str,
    max_rounds: int,
) -> dict[str, object]:
    """Build the A-authored task envelope without choosing B's next route."""
    values = {
        "instruction": instruction,
        "acceptance": acceptance,
        "bb_rule": bb_rule,
        "manager_return_rule": manager_return_rule,
    }
    for name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"TASK_MESSAGE_{name.upper()}_REQUIRED")
    # Zero means "continue while there is real progress".  It is the normal
    # policy for an ordinary Chain Recipe delivery; a positive value is an explicit
    # user/Manager budget, not a hidden completion condition.
    if type(max_rounds) is not int or not 0 <= max_rounds <= 12:
        raise ValueError("TASK_MESSAGE_MAX_ROUNDS_INVALID")
    if max_rounds:
        continuation_policy = (
            f"이 Task Message는 Worker 응답을 최대 {max_rounds}회까지 처리합니다. "
            "완료·정체·위험이면 즉시 Manager에게 반환하고, 남은 안전한 작은 실행이 "
            "있을 때만 SELF를 선택하세요. 반복 한도에 도달하면 BCT가 새 실행을 "
            "만들지 않고 현재 결과를 Manager에게 반환합니다."
        )
    else:
        continuation_policy = (
            "이 Task Message는 고정 횟수로 종료하지 않습니다. 실제 진전이 있고 "
            "다음 안전한 작은 실행이 분명할 때만 SELF를 선택하세요. 같은 실패의 "
            "반복·정체·위험·완료·Manager 판단 필요가 생기면 즉시 Manager에게 반환하세요."
        )
    text = (
        "BCT Task Message\n\n"
        "작업\n"
        f"{instruction.strip()}\n\n"
        "완료 기준\n"
        f"{acceptance.strip()}\n\n"
        "작은 다음 실행(BB)을 선택하는 기준\n"
        f"{bb_rule.strip()}\n\n"
        "Manager에게 반환(BA)하는 기준\n"
        f"{manager_return_rule.strip()}\n\n"
        + continuation_policy
    )
    if len(text) > 11000:
        raise ValueError("TASK_MESSAGE_INSTRUCTION_TOO_LONG")
    return {
        "instruction": text,
        "instruction_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "max_rounds": max_rounds,
    }
