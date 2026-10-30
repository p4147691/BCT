"""Legacy RCC receipt interpretation only; never starts a message send."""
from __future__ import annotations


def legacy_send_effect_state(command: str, result: dict, state: str) -> str:
    """Preserve historical generic-send effectState interpretation."""
    if command == "send":
        effect = str(result.get("effectState") or "").upper()
        if effect:
            return effect
    return state


def legacy_send_ack_verified(command: str, result: dict, state: str) -> bool:
    """Classify a historical generic-send host ACK without executing it."""
    if command != "send" or result.get("type") != "host:ack":
        return True
    return result.get("submitted") is True and state == "SUBMITTED"