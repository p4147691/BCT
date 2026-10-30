"""Pure read-only UNKNOWN diagnosis; never mutates original operation evidence."""
from __future__ import annotations

def diagnose_unknown(original: dict, before: dict | None, after: dict | None,
                     *, fingerprint_keys: tuple[str, ...], effect_keys: tuple[str, ...]) -> dict:
    if not isinstance(original, dict) or not original.get("operation_id"):
        raise ValueError("original operation receipt required")
    if not fingerprint_keys or not effect_keys or set(fingerprint_keys) & set(effect_keys):
        raise ValueError("invalid identity/effect keys")
    result = {"original_operation_id": original["operation_id"], "original_outcome": original.get("outcome"),
              "diagnosis": "INSUFFICIENT_EVIDENCE", "replay_allowed": False, "original_preserved": True}
    if original.get("outcome") != "UNKNOWN":
        result["diagnosis"] = "NOT_AN_UNKNOWN"
        return result
    if not isinstance(before, dict) or not isinstance(after, dict):
        return result
    if any(key not in before or key not in after or before[key] != after[key] for key in fingerprint_keys):
        result["diagnosis"] = "IDENTITY_CHANGED"
        return result
    if any(key not in before or key not in after for key in effect_keys):
        return result
    if all(before[key] == after[key] for key in effect_keys):
        result["diagnosis"] = "NO_OBSERVED_CHANGE_NOT_PROOF_OF_NO_EFFECT"
    else:
        result["diagnosis"] = "STATE_CHANGED_CAUSALITY_UNPROVEN"
    return result
