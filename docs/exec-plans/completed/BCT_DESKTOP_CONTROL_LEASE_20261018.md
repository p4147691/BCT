# BCT Desktop control lease and emergency stop — 2026-10-18

Status: `complete`

## Delivered boundary

VTL's interactive-session Agent now owns one in-memory control lease with a
2–120 second TTL, exact work-derived owner and lease-ID fencing, session or
HWND/PID/process-start target binding, automatic expiry and a latched emergency
stop. Emergency stop immediately clears the lease; reset requires the exact
stop generation.

BCT exposes the Agent protocol as authenticated MCP capabilities
`desktop_control_lease` and `desktop_emergency_stop`. Emergency stop has an
independent BCT resource so it remains dispatchable while a normal control
claim is unresolved. Post-write transport ambiguity remains UNKNOWN and is not
retried; confirmed Agent rejection is FAILED and releases its claim.

This slice does not inject mouse, keyboard or clipboard input, change focus,
launch programs, mutate windows, install a Scheduled Task or configure
automatic logon.

## Verification and rollout

- VTL PR #8 merged as `83b95d4efc9f5b0b7f0a0a186db6e3611b1ff48c`.
  Exact merged-main validation and local sync both passed.
- BCT PR #189 merged as `0c09f86c567cb4ee93500c220700423e906b0383`.
  The exact PR head passed the complete Windows CI workflow; its Git tree is
  identical to the merge commit tree.
- Local BCT focused tests passed 18/18 and the full regression passed 728/728.
- The exact merged VTL Agent was restarted in interactive Session 1 as version
  1.1.0. Exact merged BCT main deployed with outcome APPLIED, Generation 113
  and 26 MCP tools.
- Live authenticated MCP acceptance proved initial clean state, competing-owner
  rejection, two-second expiry, wrong-owner renewal rejection, owner renewal,
  emergency lease revocation, blocked acquisition while stopped,
  wrong-generation reset rejection, exact reset, final acquisition and release.
- Final live state was clean: no active lease and emergency stop inactive.

The default Manager prompt test was also isolated from the operator-editable
live relay note. UTF-8/UTF-8 BOM/UTF-16/UTF-32/CP949 relay-note coverage remains
in the full suite.

## Next slice

Build the first lease-gated mutation primitive behind this completed boundary.
Input injection, focus/window mutation and process launch must each require the
exact active lease and check the emergency latch immediately before effect.
