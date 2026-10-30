"""Side-effect-free multi-monitor allocation using per-monitor work areas."""
from __future__ import annotations
from .window_layout import Rect, plan_grid

def plan_monitors(work_areas: dict[str, Rect], assignments: dict[str, list[str]],
                  *, columns: dict[str, int] | None = None,
                  gap: int = 0, min_width: int = 100,
                  min_height: int = 80) -> dict[str, Rect]:
    """Reject absent monitors, duplicate windows, and unsupported coordinates."""
    if not assignments or not work_areas:
        raise ValueError("monitor selection required")
    if set(assignments) - set(work_areas):
        raise ValueError("unknown monitor")
    if columns is not None and set(columns) - set(assignments):
        raise ValueError("unexpected monitor column override")
    all_ids = [identity for ids in assignments.values() for identity in ids]
    if not all_ids or len(all_ids) != len(set(all_ids)):
        raise ValueError("duplicate or empty assignments")
    out: dict[str, Rect] = {}
    for monitor, ids in assignments.items():
        if not ids:
            raise ValueError("empty monitor assignment")
        rects = plan_grid(work_areas[monitor], ids, columns=(columns or {}).get(monitor, 2),
                          gap=gap, min_width=min_width, min_height=min_height)
        for identity, rect in rects.items():
            if not (-(2**31) <= rect.x < 2**31 and -(2**31) <= rect.y < 2**31
                    and 100 <= rect.width <= 7680 and 80 <= rect.height <= 4320):
                raise ValueError("desktop_window_manage coordinate limit")
            out[identity] = rect
    return out
