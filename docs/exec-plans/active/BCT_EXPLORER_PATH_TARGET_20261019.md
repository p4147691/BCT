# BCT Explorer folder-path targeting — 2026-10-19

Status: IMPLEMENTING.

## Boundary

Extend the existing `desktop_application_target` tool rather than adding a new
control capability. Explorer `list` and `bind` accept an optional existing
absolute `folder_path`. The Desktop Session Agent resolves Shell location
metadata to exact current-session/current-virtual-desktop HWND inventory.
Chrome behavior is unchanged.

The list operation remains read-only. Bind fails closed on zero, multiple, or
truncated candidates, then the existing Agent revalidates the full window
fingerprint while acquiring the Lease. No Explorer navigation, creation, close,
file mutation, or path guessing is part of the product operation.

## Acceptance

- Focused desktop-session and MCP contract tests pass locally.
- VTL Agent 1.7 current-session smoke passes from the exact reviewed source.
- A disposable unique folder Explorer window is listed, bound, and released by
  exact folder path through authenticated MCP LIVE.
- Only the disposable test window is closed and final control state has no
  Lease or emergency-stop latch.
- PR CI, merge, exact-main deployment, runtime alignment, and handoff updates
  are complete.
