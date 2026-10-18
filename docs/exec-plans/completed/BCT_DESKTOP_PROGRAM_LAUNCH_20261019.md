# BCT bounded desktop program launch — 2026-10-19

Status: `complete`

## Boundary

Add authenticated `desktop_program_launch` using an active Session Lease.
Accept one existing absolute non-reparse `.exe`, a bounded argument array,
an existing working directory and a bounded window wait.  Do not invoke a
shell.  Record the new PID/process birth/Session identity and upgrade the same
Lease only when that exact PID owns a visible top-level window on the current
virtual desktop.

Execution may already have happened when transport or post-start validation
becomes ambiguous, so those failures are UNKNOWN and are never retried.
No exact new-PID window is an APPLIED unbound launch, not a failed launch.
Emergency stop remains independently callable while the Agent waits; other
operations on the Lease are fenced by an in-progress transition.

Chrome singleton/process reuse, restore, move, resize, close, arbitrary shell
commands, auto-login and Scheduled Task recovery are outside this slice.

## Verification and rollout

- Agent 1.4 compiled and passed the interactive smoke including exact
  PID/window binding, activation, Korean Unicode input, wrong-owner fencing and
  final emergency-stop/reset cleanup.  VTL PR #14 passed validation and merged
  as `ce31d4baa1316f1b7b605a2486b1c006c143738f` before the Agent rollout.
- Focused BCT desktop/MCP tests passed 20/20.  The single full local regression
  passed 743/743 in 380.684 seconds.
- BCT PR #197 passed Windows CI run `39164413348` in 11m48s and merged as
  `c2f799922ef2c2a56b1102dcfa288d24239aaa94`.  Its final main Git tree was
  exactly the tested PR-head tree, so redundant main run `39165338761` was
  cancelled rather than repeating the same 743-test suite.
- Authenticated deployment operation
  `bct-desktop-program-launch-deploy-20261019` finished APPLIED.  LIVE
  Generation 119 is READY at the exact merge SHA and advertises 30 MCP tools,
  including `bct_desktop_program_launch`.
- Authenticated MCP LIVE acceptance passed Session Lease acquisition, exact
  program birth and `WINDOW_BOUND`, PID/HWND agreement, exact activation,
  Korean Unicode input observation, different-work rejection, emergency-stop
  fencing/reset and final no-lease/no-stop state.  The probe process, temporary
  directory and disposable test script were removed.
