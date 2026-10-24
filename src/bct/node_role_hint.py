"""Format non-authoritative BCT node role notes for compact UI display.

Role labels and thinking preferences are advisory text, not execution privileges.
"""
from __future__ import annotations

from collections.abc import Iterable


def format_node_role_hint(
    desktop: str,
    role_tags: Iterable[str],
    reasoning_preference: str | None = None,
    max_chars: int = 72,
) -> str:
    """Render desktop, up to six unique roles, and optional preferred reasoning.

    Does not infer or claim the model's actual current reasoning setting.
    """
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 8:
        raise ValueError("max_chars must be an integer >= 8")
    name = desktop.strip() if isinstance(desktop, str) else ""
    fields = [name or "D?"]
    unique: set[str] = set()
    for value in role_tags:
        if not isinstance(value, str):
            continue
        tag = value.strip()
        if not tag or tag.casefold() in unique:
            continue
        unique.add(tag.casefold())
        fields.append(tag)
        if len(unique) == 6:
            break
    if isinstance(reasoning_preference, str) and reasoning_preference.strip():
        fields.append("선호: " + reasoning_preference.strip())
    label = " · ".join(fields)
    return label if len(label) <= max_chars else label[: max_chars - 1] + "…"
