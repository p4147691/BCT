# BCT Desktop control lease and emergency stop — 2026-10-18

Status: `implementation in progress`

## Exact scope

VTL extends its existing per-user Desktop Session Agent with one in-memory
control lease, exact target fingerprint, automatic TTL expiry and a latched
emergency stop.  BCT adds durable operation receipts and authenticated MCP
capabilities for lease status/acquire/renew/release, emergency stop and
generation-fenced reset.

Emergency stop uses a resource separate from normal control operations so it
remains dispatchable if a normal control claim is unresolved.  Mutation
transport loss remains UNKNOWN and is never retried automatically.  Agent
terminal rejection is a confirmed failure and releases its BCT claim.

Out of scope: mouse/keyboard/clipboard injection, focus, program launch, window
mutation, Chrome/Explorer control, Scheduled Task installation and auto-logon.

## Acceptance gates

1. VTL parse and isolated Agent smoke prove acquisition, conflict, expiry,
   renewal, stop, blocked acquisition, wrong-generation reset, exact reset and
   release without input.
2. BCT focused tests prove validation, owner derivation, claim separation and
   UNKNOWN handling.
3. One BCT full local regression, exact-head PR CI and repository merges.
4. Restart the manually owned Agent from exact merged VTL source, deploy exact
   merged BCT main, then repeat the full state transition sequence through live
   authenticated MCP.
5. Leave the live Agent with no active lease and emergency stop inactive.
