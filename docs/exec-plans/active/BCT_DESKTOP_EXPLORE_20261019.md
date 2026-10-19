# BCT current-session process and path discovery — 2026-10-19

Status: implementation, CI, rollout, and LIVE acceptance pending.

## Boundary

Add one authenticated read-only `desktop_explore` capability with `processes`
and `paths` operations.  Process results come only from the exact interactive
Session Agent and connect PID/process birth/executable identity to visible
windows on the current virtual desktop.  Path results identify the logged-in
user's known folders and ready drives.

The capability does not read files, walk directories, mutate processes, or
require a control Lease.  Callers compose a discovered path with the existing
work-root-scoped `read` capability.  This preserves the existing filesystem
scope and reparse-point protections instead of inventing a parallel path
authorization model.

## Gates

1. Focused integration/feature/MCP tests and compileall.
2. VTL Agent 1.6 exact-head CI, merge, runtime sync, and live rollout.
3. BCT exact-head CI, merge, and exact-main deployment.
4. Authenticated LIVE `processes`/`paths` plus one bounded `read`
   directory-tree composition.  Final desktop control state must remain free
   of Lease and emergency stop.
