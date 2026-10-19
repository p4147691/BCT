# BCT bounded desktop window management — 2026-10-19

Status: COMPLETE / LIVE ACCEPTED.

## Boundary

Add authenticated `desktop_window_manage` for `restore`, `minimize`,
`maximize`, and `move_resize`.  Every effect requires the calling work's exact
active Window Lease.  BCT derives the owner from the work, shares the existing
desktop-control claim, and never accepts close through this capability.

VTL revalidates emergency-stop state, owner/Lease ID, HWND, PID, process start,
Session ID and virtual-desktop ID immediately before the effect.  Invalid or
changed targets fail before mutation.  An attempted effect without a proven
postcondition is UNKNOWN and is not retried.

## Final evidence

- BCT focused desktop/MCP/core/layout tests pass 44/44 with the worktree source
  explicitly selected instead of the host's unrelated editable checkout.
- Python compileall passes.
- VTL Agent 1.5 Session 1 smoke passes all four operations plus activation,
  input, launch, owner fencing and emergency-stop cleanup.
- VTL PR #25 passed CI and merged as
  `fb0e140027cecddd8d999220d8644f31dc63c332`; exact-main validation and runtime
  sync both passed.
- The live Session 1 Agent is 1.5.0 and runs from that immutable VTL release.
  The pre-rollout control status proved no active Lease and no emergency stop.
- BCT PR #208 passed its adaptive preflight, four core shards and browser-bridge
  gate, then merged as `172c404b78a3874ae7f2e5b75da11abcacd1dbcf`.
  The merge tree is byte-identical to the tested PR head.  Exact-main CI also
  passed.
- The durable `bct_deploy` operation deployed that exact SHA.  Health is READY,
  the MCP catalogue contains 32 tools, and `desktop_window_manage` is present.
- A disposable window launched through BCT was found by its Korean title and
  exact HWND/PID.  Durable BCT receipts prove `move_resize`, `minimize`,
  `restore`, `maximize`, second `restore`, activation and input all APPLIED.
  The final control status proves no Lease and no emergency stop; the probe
  process and its two temporary artifacts were removed.

## Validation harness lessons

The first acceptance wrapper incorrectly expected `programLaunch.process.pid`;
the contract returns `programLaunch.pid`.  It stopped after the already-applied
launch, so recovery used the durable receipt instead of relaunching.  A second
wrapper treated the probe's atomic JSON replacement as a terminal read error;
on Windows that read can transiently raise `PermissionError`.  Again, the
already-applied operation receipts were reconciled without repeating effects.
Future wrappers must tolerate transient sharing failures while reading the
probe state and must parse the published result shape.

## Deferred boundary

Window close remains deliberately unsupported because it can discard user
data.  Virtual-desktop moves and higher-level Chrome/Explorer workflows are
separate capabilities.
