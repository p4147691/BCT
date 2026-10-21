# BCT Monitor thumbnail badge collision

## Objective

Keep every open ChatGPT Chrome window's BCT node badge readable when two
projected native windows overlap in one desktop thumbnail.

## Contract

- Keep the existing exact `conversation -> Chrome window_id -> HWND` mapping.
- Reuse the single semantic thumbnail overlay; do not alter capture images.
- Place badges deterministically in the first free corner: top-left,
  top-right, bottom-left, then bottom-right.
- Use the projected native window rectangle and rendered badge size for
  collision checks. Do not poll or add another refresh loop.
- Preserve one badge and one highlight layer per physical HWND.
- If all four corners are occupied, choose the least-colliding corner and
  expose that fact only in renderer diagnostics; never attach the label to a
  guessed window.

## Verification

- Focused overlay test covers two exact-overlap Chrome windows and repeat
  rendering without duplicated nodes or anchor drift.
- Existing Monitor structure, thumbnail, minimized badge, node interaction,
  backpressure, and deployment checks remain green.
- LIVE acceptance requires exact source/install hashes, same-ID reload, and a
  visible non-overlapping badge result for the currently overlapping windows.

## Status

`ISOLATED_VERIFIED / LIVE_NOT_APPLIED`

- Focused overlay collision/re-render check: PASS
- Thumbnail labels, minimized badges, node interaction, HWND projection,
  backpressure, shell, deployment reload, capture and thumbnail service checks:
  PASS
- `tests.test_monitor_runtime`: 10 PASS
- JavaScript syntax and `git diff --check`: PASS
