# BCT desktop exact-window inventory and activation — 2026-10-19

Status: `delivery in progress`

## Intended boundary

Expose two authenticated MCP capabilities over the VTL-owned current-session
Agent:

- `desktop_window_list`: bounded read-only enumeration of visible titled
  top-level windows on the current virtual desktop, with exact process/window
  fingerprints; and
- `desktop_window_activate`: foreground only the non-hidden, non-minimized
  window already bound to the calling work's active exact `window` lease.

No launch, restore, move, resize, close, Scheduled Task or automatic-logon
behavior is permitted in this slice.

## Protected effects

BCT derives the owner from the exact work and durably fences activation.  VTL
revalidates lease owner/ID, emergency-stop state, HWND, PID, process start,
Session ID and virtual-desktop ID immediately before the effect.  A terminal
rejection is FAILED.  A transport ambiguity or postcondition mismatch is
UNKNOWN and must not be retried automatically.

## Acceptance

- Focused desktop/MCP/module tests and the full BCT regression pass with the
  worktree `src` explicitly first on `PYTHONPATH`.
- VTL's two-window current-session smoke proves inventory, exact activation,
  wrong-owner rejection, input after activation and emergency-stop fencing.
- Exact PR heads pass CI and merge.
- Exact merged BCT main deploys READY and advertises both new MCP tools.
- Live authenticated acceptance repeats list → exact lease → activation → input
  → emergency stop/reset and ends with no lease or emergency latch.
