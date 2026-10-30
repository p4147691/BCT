"""Pure deterministic layout planning. No desktop effects."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError("invalid rectangle")

def plan_grid(area: Rect, ids: list[str], *, columns: int = 2, rows: int | None = None, gap: int = 0, min_width: int = 1, min_height: int = 1) -> dict[str, Rect]:
    if not ids or any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("unique window IDs required")
    if columns < 1 or gap < 0 or min_width < 1 or min_height < 1:
        raise ValueError("invalid grid parameters")
    rows = rows if rows is not None else (len(ids) + columns - 1) // columns
    if rows < 1 or rows * columns < len(ids):
        raise ValueError("insufficient slots")
    aw, ah = area.width - gap * (columns - 1), area.height - gap * (rows - 1)
    if aw < columns * min_width or ah < rows * min_height:
        raise ValueError("work area too small")
    widths = [aw // columns + int(i < aw % columns) for i in range(columns)]
    heights = [ah // rows + int(i < ah % rows) for i in range(rows)]
    output = {}
    n, y = 0, area.y
    for height in heights:
        x = area.x
        for width in widths:
            if n < len(ids):
                output[ids[n]] = Rect(x, y, width, height)
                n += 1
            x += width + gap
        y += height + gap
    return output
