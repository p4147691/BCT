# BCT current-session process and path discovery — 2026-10-19

Status: COMPLETE / LIVE ACCEPTED.

## Boundary

Add one authenticated read-only `desktop_explore` capability with `processes`
and `paths` operations. Process results come only from the exact interactive
Session Agent and connect PID/process birth/executable identity to visible
windows on the current virtual desktop. Path results identify the logged-in
user's known folders and ready drives.

The capability does not read files, walk directories, mutate processes, or
require a control Lease. Callers compose a discovered path with the existing
work-root-scoped `read` capability. This preserves the existing filesystem
scope and reparse-point protections instead of inventing a parallel path
authorization model.

## Final evidence

- Focused desktop/MCP/core/layout tests passed 47/47, along with compileall.
- VTL PR #27 merged as `7f2f1b440b68f6f06998f8d89f10fcb4f15fba5f`.
  Its exact-main validation and immutable runtime sync passed, and the live
  Session 1 Agent 1.6.0 runs from that exact release.
- BCT PR #210 passed adaptive CI and merged as
  `d05e344bc71b52b120618651a12ea95415b627e1`. That exact SHA was deployed as
  generation 126 and reported READY. The independent merged-main CI run
  `39187791816` also passed scope, preflight, all four core shards, and the
  browser-bridge Windows E2E gate.
- Authenticated LIVE MCP exposed 33 tools including `bct_desktop_explore`.
  Process discovery returned a current-Session Chrome process connected to
  its current-desktop windows. Path discovery returned six existing known
  folders and ready C:, D:, and E: drives.
- The same Work composed the discovered context with bounded `bct_read`
  `directory_tree` on `D:\BCT\source`; existing work-scope and reparse
  protections remained authoritative.
- Final control state had no Lease and emergency stop was false.
