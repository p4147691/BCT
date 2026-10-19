# BCT bounded desktop window management — 2026-10-19

Status: BCT implementation complete; PR, BCT rollout, and end-to-end acceptance pending.

## Boundary

Add authenticated `desktop_window_manage` for `restore`, `minimize`,
`maximize`, and `move_resize`.  Every effect requires the calling work's exact
active Window Lease.  BCT derives the owner from the work, shares the existing
desktop-control claim, and never accepts close through this capability.

VTL revalidates emergency-stop state, owner/Lease ID, HWND, PID, process start,
Session ID and virtual-desktop ID immediately before the effect.  Invalid or
changed targets fail before mutation.  An attempted effect without a proven
postcondition is UNKNOWN and is not retried.

## Evidence so far

- BCT focused desktop/MCP/core/layout tests pass 44/44 with the worktree source
  explicitly selected instead of the host's unrelated editable checkout.
- Python compileall passes.
- VTL Agent 1.5 Session 1 smoke passes all four operations plus activation,
  input, launch, owner fencing and emergency-stop cleanup.
- VTL PR #25 passed CI and merged as
  `fb0e140027cecddd8d999220d8644f31dc63c332`; exact-main validation and runtime
  sync both passed.
- The live Session 1 Agent is now 1.5.0, PID 5732, running from that immutable
  VTL release.  The pre-rollout control status proved no active Lease and no
  emergency stop.

## Remaining gates

1. Run BCT exact-head CI and merge.
2. Deploy exact BCT main and verify the new MCP catalogue entry.
3. Run one disposable-window LIVE acceptance and clean its Lease/process.
