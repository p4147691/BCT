# BCT bounded desktop program launch — 2026-10-19

Status: `active`

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

1. Compile Agent 1.4 and run its interactive smoke including Unicode argv,
   exact PID/window binding, activation/input, wrong-owner fencing and final
   emergency-stop/reset cleanup.
2. Run focused BCT desktop/MCP tests and one full local regression.
3. Merge VTL first, deploy the exact merged Agent, then merge/deploy BCT.
4. Reuse tested Git trees and skip only redundant post-merge CI whose exact
   tree equals the already-passed PR head tree.
5. Run authenticated live E2E and leave no Lease, emergency latch, probe
   process or temporary evidence behind.
