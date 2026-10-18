# BCT desktop exact-window inventory and activation — 2026-10-19

Status: `complete`

## Delivered boundary

Authenticated MCP now exposes:

- `desktop_window_list`: bounded read-only enumeration of visible titled
  top-level windows on the current virtual desktop with exact fingerprints; and
- `desktop_window_activate`: activation only of the non-hidden, non-minimized
  window bound to the calling work's exact active `window` lease.

BCT derives the owner from the work and durably fences activation.  VTL
revalidates lease owner/ID, emergency-stop state, HWND, PID, process start,
Session ID and virtual-desktop ID immediately before the effect.  Terminal
rejection is FAILED; transport ambiguity or postcondition mismatch is UNKNOWN
and is never automatically retried.  Launch, restore, move, resize and close
remain outside this slice.

## Verification and rollout

- Focused desktop/MCP/module tests passed 25/25; full local BCT regression
  passed 735/735.
- VTL's two-window current-session smoke passed inventory, exact activation,
  wrong-owner rejection, input after activation and emergency-stop fencing.
- VTL PR #12 passed CI and merged as
  `aa72627f6dad2c79dbc310351e364b0a2e66a302`; Agent 1.3 runs from that exact
  merged source in interactive Session 1.
- BCT PR #195 passed its 12m29s Windows CI and merged as
  `90c963d6f05a552a367529eae03aacfaa3e00e1c`.
- A concurrent already-reviewed claim-diagnostics change was present in the
  final merge, so the combined exact-main push CI was required and passed run
  `39141512756` in 11m1s before deployment.
- Deployment operation `bct-window-control-20261019-01-deploy` finished
  `APPLIED`.  LIVE Generation 117 reported READY at the exact merge SHA and
  advertised 29 MCP tools including both new capabilities.
- The first live activation operation itself finished `APPLIED`; its harness
  rejected a later, non-atomic external foreground observation and cleaned the
  remaining lease through generation-fenced emergency stop/reset without
  replaying the activation.
- The corrected live acceptance used Agent evidence at the effect boundary and
  actual follow-up input observation.  It passed two-window inventory,
  peer-to-target activation, wrong-owner rejection, Korean Unicode input,
  emergency-stop blocking/reset and final no-lease/no-stop state.

## Next boundary

Add bounded program launch with exact process birth and launch-to-window
identity binding.  Restore/move/resize should remain separately scoped.
