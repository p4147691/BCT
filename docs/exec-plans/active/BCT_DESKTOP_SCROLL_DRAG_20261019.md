# BCT desktop scroll and drag

Status: IMPLEMENTED / FOCUSED TEST PASS / PR AND LIVE PENDING.

## Goal and ownership

Expose the VTL Desktop Session Agent's bounded wheel scrolling and left dragging
through the authenticated `desktop_input` capability. VTL owns Windows input;
BCT owns validation, work/claim fencing, durable receipts and UNKNOWN semantics.

## Contract

- `scroll`: exact leased foreground window, bounded x/y, and a non-zero wheel
  delta divisible by 120 in the inclusive range -1200..1200.
- `drag`: exact leased foreground window, distinct start/end x/y, left button
  only, and 2..32 interpolation steps.
- Existing Lease owner/ID, process-birth, Session/current-desktop,
  emergency-stop and no-retry-on-UNKNOWN rules remain unchanged.
- Explicit UTF-8 transport remains independent of the Windows system-locale
  UTF-8 checkbox.

## Verification

- PASS: 44 focused desktop-session tests, including valid dispatch and invalid
  scroll/drag bounds.
- PENDING: complete suite/catalogue, PR exact-head CI and merge.
- PENDING: exact-main Core deploy, VTL Agent 2.1 rollout, authenticated MCP
  observation against a disposable probe, Lease release, and inactive
  emergency-stop final state.
