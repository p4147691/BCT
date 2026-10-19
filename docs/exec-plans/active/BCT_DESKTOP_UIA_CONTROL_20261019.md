# BCT generic desktop UI Automation control

Status: active

## Progress

- Authenticated list/action MCP capabilities, policy, typed Agent validation,
  redacted durable evidence and failure semantics are implemented.
- The list and all five semantic actions passed authenticated LIVE MCP once.
  A subsequent activation UNKNOWN exposed that an expired Lease does not by
  itself retire the durable interactive-session Claim.
- `desktop_window_activate_reconcile` now verifies the exact original Lease
  digest and UNKNOWN code, stable current Agent observations, clear control
  state, and absence of the exact retired target before releasing only that
  Claim while preserving the original UNKNOWN receipt.
- BCT full regression passes: 803 tests.
- Pending: reconcile PR/required CI, exact-main Core deploy, reconcile the one
  known test Claim, then repeat the authenticated LIVE canary on VTL Agent 2.3.2.

## Goal

Expose the VTL-owned generic UI Automation capability through authenticated BCT
MCP so ChatGPT/Codex can inspect and operate normal Windows application controls
without guessing screen coordinates.

## BCT ownership

- Add `desktop_uia_elements_list` as a read-only exact-HWND observation.
- Add `desktop_uia_element_action` as a Window-Lease mutation for `invoke`,
  `set_value`, `toggle`, `select`, `expand` and `collapse`.
- Validate bounded schemas, opaque element IDs and exact window/Lease identity.
- Keep raw control names only in the first direct list output. Durable evidence
  stores counts, truncation, role/pattern summaries and a canonical metadata
  digest. Field values are never requested or persisted. Set text is represented
  only by Unicode scalar count, UTF-8 byte count and SHA-256.
- Map helper pre-invocation failures to confirmed failure with released claims;
  transport loss, foreground change, Lease loss after invocation, or an
  unproved postcondition remains UNKNOWN with its claim retained.
- Keep the default policy and MCP catalogue synchronized with the implementation.

## Non-goals

No RCC/Chrome extension change, Core deployment while another deployment Work
owns that resource, window close, force kill, unrestricted UI tree dump,
credential-field extraction, arbitrary shell, automatic login or new scheduler.

## Delivery and acceptance

1. Implement against the exact VTL command contract with focused unit tests.
2. Run BCT desktop/MCP/policy tests, compileall and diff check locally.
3. Use VTL direct validation where it can replace repeated GitHub runs.
4. Push one coherent BCT candidate, run required CI once, merge exact head.
5. After the RCC rollforward Work has finished and no conflicting deploy claim
   exists, deploy exact BCT main and install exact VTL main.
6. Run one disposable WinForms LIVE canary through authenticated MCP: list,
   semantic actions, postconditions, wrong-owner/emergency rejection, duplicate
   receipt, foreground/process preservation and cleanup.
7. Finish with null Lease, inactive emergency stop and source/runtime/main SHA
   equality. Move both plans to `completed/` only after LIVE acceptance.
