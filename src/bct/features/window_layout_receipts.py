"""Side-effect-free readback classification for an existing window operation.

This is not an executor: the BCT Work/Operation/Lease gateway is authoritative.
UNKNOWN never triggers a retry, and the original receipt is never rewritten.
"""
from __future__ import annotations

def classify_window_readback(expected: dict, observed: dict | None, *,
                             same_process: bool, operation_finished: bool) -> str:
    """Return APPLIED, NOT_APPLIED, or UNKNOWN from exact post-effect evidence.

    NOT_APPLIED is not inferred from timeout or missing state.
    """
    if not operation_finished or not same_process or observed is None:
        return "UNKNOWN"
    keys = ("x", "y", "width", "height")
    if any(type(expected.get(k)) is not int or type(observed.get(k)) is not int for k in keys):
        return "UNKNOWN"
    if all(observed[k] == expected[k] for k in keys):
        return "APPLIED"
    # A mismatched final state does not prove the effect never happened.
    return "UNKNOWN"

def classify_tab_readback(*, expected_tab_id: int, expected_window_id: int,
                          expected_index: int, expected_conversation_key: str,
                          observed: dict | None, same_session: bool,
                          operation_finished: bool) -> str:
    if not operation_finished or not same_session or observed is None:
        return "UNKNOWN"
    if (observed.get("tab_id") == expected_tab_id
            and observed.get("window_id") == expected_window_id
            and observed.get("tab_index") == expected_index
            and observed.get("conversation_key") == expected_conversation_key):
        return "APPLIED"
    return "UNKNOWN"
