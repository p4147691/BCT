"""Plan-only adapter to existing BCT desktop_window_manage Operation arguments.

No input injection, no lease acquisition, no mutations. A caller must resolve
identity, acquire a window lease per target, submit each separate BCT Operation
and independently verify the resulting geometry.
"""
from __future__ import annotations
import re
from .window_layout import Rect, plan_grid

LEASE_RE = re.compile(r"^[0-9a-f]{32}$")

def plan_window_operations(work_area: Rect, window_lease_ids: dict[str, str],
                           *, columns: int = 2, rows: int | None = None,
                           gap: int = 0, min_width: int = 100,
                           min_height: int = 80) -> dict[str, dict[str, int | str]]:
    """Create exact existing desktop_window_manage move_resize arguments."""
    if not window_lease_ids or any(not LEASE_RE.fullmatch(v or "") for v in window_lease_ids.values()):
        raise ValueError("exact active lease IDs required")
    slots = plan_grid(work_area, list(window_lease_ids), columns=columns,
                      rows=rows, gap=gap, min_width=min_width, min_height=min_height)
    result = {}
    for hwnd, rect in slots.items():
        if not (-(2**31) <= rect.x < 2**31 and -(2**31) <= rect.y < 2**31
                and 100 <= rect.width <= 7680 and 80 <= rect.height <= 4320):
            raise ValueError("rectangle outside existing desktop_window_manage contract")
        result[hwnd] = dict(lease_id=window_lease_ids[hwnd], operation="move_resize",
                            x=rect.x, y=rect.y, width=rect.width, height=rect.height)
    return result
