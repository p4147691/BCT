# BCT desktop scroll and drag

Status: COMPLETE — MAIN/LIVE EXACT / AUTHENTICATED MCP PASS.

## Goal and contract

The authenticated `desktop_input` capability exposes VTL Agent wheel scrolling
and left dragging. `scroll` requires a non-zero 120-unit delta in -1200..1200.
`drag` requires distinct endpoints, left button only and 2..32 steps. Existing
exact Window Lease, foreground, path occlusion, process-birth, Session/current
desktop, emergency-stop and no-retry-on-UNKNOWN rules remain in force. Explicit
UTF-8 transport does not depend on the Windows system-locale UTF-8 checkbox.

## Final verification

- 44 focused desktop-session tests passed. BCT PR #224 then passed preflight,
  four parallel core shards and browser-bridge CI and merged as
  `b154234accd1ae5aaccf32ae57ca79a2044df90b`.
- VTL PR #42 merged as `26bb2028391ba5937d709a335f0b35f085517e85`;
  its full current-session disposable probe observed scroll and drag. Persistent
  Agent 2.1.0 runs from that immutable release.
- Durable deployment `desktop-scroll-drag-deploy-b154234a` finished APPLIED at
  generation 139. Health was READY/OK with matching source/current/release SHA.
- Authenticated BCT MCP acquired one exact disposable-probe Window Lease,
  activated it, applied a -120 scroll and an eight-step left drag, and the probe
  observed the wheel and one completed drag. A distinct +120 diagnostic proved
  one requested wheel event produced exactly +120 observed change.
- The disposable process/files were removed. Final control status has no Lease
  and an inactive emergency stop. No existing Chrome process was closed.
