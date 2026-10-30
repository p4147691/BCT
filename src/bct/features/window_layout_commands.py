"""Validated, effect-free command preparation for existing BCT and RCC tools.

Only a BCT Work/Operation can execute returned commands. These helpers never
send, click, acquire leases, or modify an UNKNOWN receipt.
"""
from __future__ import annotations
import re
from typing import Any

_HEX = re.compile(r"^[a-f0-9]{32}$")
_UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")

def plan_window_state_action(lease_id: str, action: str) -> tuple[str, dict[str, str]]:
    if not isinstance(lease_id, str) or not _HEX.fullmatch(lease_id):
        raise ValueError("exact window lease required")
    if action not in {"minimize", "restore", "maximize"}:
        raise ValueError("unsupported window action")
    return "desktop_window_manage", {"lease_id": lease_id, "operation": action}

def plan_tab_move(*, instance_id: str, session_id: str, tab_id: int,
                  window_id: int, target_window_id: int, index: int,
                  conversation_key: str, observed: dict[str, Any],
                  allow_generating: bool = False) -> tuple[str, dict[str, Any]]:
    if not all(isinstance(x, str) and _HEX.fullmatch(x) for x in (instance_id, session_id)):
        raise ValueError("invalid RCC instance or session")
    if any(type(v) is not int or v <= 0 for v in (tab_id, window_id, target_window_id)):
        raise ValueError("invalid tab/window ID")
    if type(index) is not int or index < -1:
        raise ValueError("invalid tab index")
    if not isinstance(conversation_key, str) or not _UUID.fullmatch(conversation_key):
        raise ValueError("exact conversation identity required")
    if (observed.get("tab_id") != tab_id
            or observed.get("window_id") != window_id
            or observed.get("conversation_key") != conversation_key):
        raise ValueError("observed tab identity changed")
    if observed.get("generating") and not allow_generating:
        raise ValueError("generating conversation protected")
    return "relay_browser", {
        "command": "move-tab", "instance_id": instance_id, "session_id": session_id,
        "tab_id": tab_id, "window_id": window_id,
        "target_window_id": target_window_id, "index": index,
        "conversation_key": conversation_key,
    }


def execute_verified_once(*, operation_id: str, capability: str, arguments: dict,
                          invoke, readback, verify) -> dict:
    """One bounded BCT Operation through an injected authorized gateway.

    invoke(capability, operation_id, arguments) MUST be the actual Work-scoped
    BCT gateway; no internal privilege or retry is implemented here.
    readback and verify are independent observations supplied by the caller.
    """
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id):
        raise ValueError("exact operation id required")
    if capability not in {"relay_browser", "desktop_window_manage"}:
        raise ValueError("capability not delegated")
    receipt = invoke(capability, operation_id, dict(arguments))
    if not isinstance(receipt, dict) or receipt.get("operation_id") != operation_id:
        return {"operation_id": operation_id, "diagnosis": "RECEIPT_MISMATCH", "outcome": "UNKNOWN", "retry": False}
    if receipt.get("outcome") != "APPLIED" or receipt.get("state") != "FINISHED":
        return {"operation_id": operation_id, "diagnosis": "OPERATION_NOT_PROVEN", "outcome": "UNKNOWN", "retry": False}
    try:
        observed = readback()
        accepted = verify(observed)
    except Exception:
        accepted = False
    return {"operation_id": operation_id, "diagnosis": "VERIFIED" if accepted is True else "READBACK_UNCERTAIN",
            "outcome": "APPLIED" if accepted is True else "UNKNOWN", "retry": False}


def make_bct_operation_invoke(*, operations, principal, work_id: str, approval_ref=None):
    """Bind the existing authorized BCT Operations gateway, not a new executor.

    The caller supplies its authenticated principal and existing Work.  The BCT
    store enforces capability, resource claim, and desktop lease constraints.
    """
    if not isinstance(work_id, str) or not work_id.strip():
        raise ValueError("existing Work id required")
    if operations is None or not callable(getattr(operations, "run", None)):
        raise ValueError("BCT Operations gateway required")
    if principal is None:
        raise ValueError("authenticated principal required")

    def invoke(capability: str, operation_id: str, arguments: dict) -> dict:
        if capability not in {"relay_browser", "desktop_window_manage"}:
            raise ValueError("unsupported delegated capability")
        result = operations.run(
            principal=principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=dict(arguments), approval_ref=approval_ref,
        )
        return result.as_dict()
    return invoke


def execute_bct_verified_once(*, operations, principal, work_id: str,
                              operation_id: str, capability: str, arguments: dict,
                              readback, verify, approval_ref=None) -> dict:
    """Exactly one authorized effect and independent post-effect observation."""
    invoke = make_bct_operation_invoke(
        operations=operations, principal=principal, work_id=work_id,
        approval_ref=approval_ref,
    )
    return execute_verified_once(
        operation_id=operation_id, capability=capability, arguments=arguments,
        invoke=invoke, readback=readback, verify=verify,
    )
