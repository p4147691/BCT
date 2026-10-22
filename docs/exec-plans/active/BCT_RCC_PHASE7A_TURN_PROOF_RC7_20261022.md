# Phase 7A RCC exact user-turn proof — RC7 isolated candidate

State: ISOLATED_TESTED / NOT_LIVE_ACCEPTED / NO_RESEND

## Observations
N13 Manager UUID `6ad7f5b6-c834-83e8-9c00-ff70bab4204d` and
N14 Worker UUID `6ad7ff62-fa64-83ee-a485-1138f1538e53` are exact RCC endpoints.

Delivery `p7a.manager-observe.live.20261022.n13n14.01` ended
`NEEDS_REVIEW` with `RELAY_EDITOR_TEXT_MISMATCH`. Browser evidence after
failure showed an unsubmitted multi-paragraph draft; user subsequently
cleared it. Its original effect and receipt are preserved.

Different one-line Delivery `p7a.manager-observe.live.20261022.n13n14.singleline02`
ended `NEEDS_REVIEW` with `RELAY_EXACT_USER_TURN_NOT_CONFIRMED`.
Browser read-only context independently showed exactly one user turn and a
completed Worker reply. **That UI evidence does not override the terminal
BCT/RCC UNKNOWN ledger state.** No identical prompt should be resent.

## Bounded source change
ChatGPT can publish an exact, stable user *semantic unit key* before the
enclosing `data-turn-key` / `conversation-turn-*` wrapper exists. The
content script now admits such a unit only if it has an explicit keyed user
role, is not already represented in an indexed wrapper, and has a stable
identity. Existing exact normalized user text, baseline exclusion and
unique-new-turn checks still gate route acceptance. Unkeyed/missing and
duplicate ambiguous evidence remains rejected.

This is a conservative compatibility candidate, not a proven explanation
of the live DOM. It does not relax the multiline composer fence, replay
UNKNOWN effects, or authorize delivery-return of a terminal NEEDS_REVIEW.

RC7 names `2026-10-22-rcc-semantic-turn-proof-v2`, with an inventory of
52 payload files. The rollback inventory is the already installed RC6
(Phase 7A Manager Observation) payload, **not** the older RC5.

## Remaining evidence requirements
- Exact-head CI success and no other in-flight BCT/RCC/Chrome change.
- Complete backup, candidate payload verification and one same-ID reload.
- On the exact existing Worker, use supported *read-only* recovery to prove
  original relay ID, exact conversation UUID, request hash, distinct user
  turn, and completed assistant reply before any state reconciliation.
- No new submission while the original effect remains UNKNOWN; never
  overwrite the two historical receipts.
- Manager-return and delivery-manager-status must pass fresh LIVE E2E
  without relaxing the effect/claim fences.
