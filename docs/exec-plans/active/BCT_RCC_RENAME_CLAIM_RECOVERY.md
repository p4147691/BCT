# BCT RCC Rename Claim Recovery

Status: OPERATOR_QUARANTINED / NO_RECONCILIATION

## Latest verified live state (2026-10-15)

- PR #119 added the exceptional, audited operator-quarantine path for a
  historical rename whose terminal RCC receipt has already been evicted.  Its
  exact-head CI passed, it merged as `86ea3a2b9351f1aa22fbf36ed327aafec624ef55`,
  and that SHA is LIVE (Core generation 89).
- The original owner reconstructed the canonical rename request and matched
  its stored SHA-256 request digest.  A fresh `inspect-rename-receipt` then
  again proved the exact tab/conversation OPEN while `receipt=null` and
  `receiptState=MISSING`.
- The canonical quarantine operation atomically changed only the original
  legacy broad claim to
  `rcc-instance:6174664e1c1b4e6db1d4729c841db3c9:rename:594833023:6acf6b7c-3624-83e8-ac15-edf282278501`.
  It recorded `RCC_RENAME_CLAIM_OPERATOR_QUARANTINED`; the original operation
  remains `FINISHED/UNKNOWN` with its original error.  This is containment,
  not a conclusion that the historical rename applied or failed.
- Total unresolved claims remain 27.  No rename was resent, deleted, released,
  or directly edited.

- PR #115 (scoped rename claims and reconciliation) and PR #116 (owner-scoped,
  read-only receipt inspection before digest reconstruction) are merged.
- Core release `7f67d126de917808896e06d7a24d774a8643d5f4` is LIVE and healthy
  (generation 87).  The installed RCC payload was updated to the matching
  `rename-receipt` implementation and Chrome was explicitly reloaded.
- The original work owner ran exactly one `inspect-rename-receipt` operation
  against `rcc-localbridge-rename-tab594833023-20261015-02`.  It confirmed the
  exact instance, tab `594833023`, and conversation
  `6acf6b7c-3624-83e8-ac15-edf282278501` are OPEN, but returned
  `receipt_found=false`.
- No historical RCC `operations` receipt remains from which the original
  session/title fingerprint can be proven.  The current title alone is not
  proof of either application or non-application.
- Result: `BLOCKED`.  The original operation remains `FINISHED/UNKNOWN`; its
  legacy broad `rcc-instance:6174664e1c1b4e6db1d4729c841db3c9` claim remains
  unresolved.  The total unresolved-claim count remains 27.  No reconciliation,
  reclassification, resend, RCC reload, or Issue #111 E2E occurred.

## Problem

An UNKNOWN `rename-conversation` operation currently retains the broad resource
claim `rcc-instance:<instance_id>`.  A fresh durable-orchestration `node-sync`
also claims that exact instance-wide resource.  Consequently, one unproven
cosmetic rename blocks an unrelated manager-worker-manager E2E before any new
assignment or browser delivery starts.

This is not an acceptable recovery boundary.  UNKNOWN must prevent duplicate
rename effects; it must not quarantine unrelated conversations or the whole RCC
instance solely because their operations share a transport process.

## Verified cause

- `src/bct/features/rcc.py` derives `rcc-instance:<instance_id>` for every
  mutating RCC command, including `rename-conversation`.
- `src/bct/features/orchestration.py` intentionally claims the same resource
  for `node-sync`, which can alter registered bindings across an instance.
- BCT has fenced `recover-node-sync`, but no equivalent inspection and
  reconciliation path for an uncertain conversation rename.
- The observed blocker is operation
  `rcc-localbridge-rename-tab594833023-20261015-02`, work
  `BCT-RCC-LOCALBRIDGE-TITLE-RENAME-20261015`, with the unresolved resource
  `rcc-instance:6174664e1c1b4e6db1d4729c841db3c9`.

## Required implementation

1. Give `rename-conversation` a canonical resource key scoped to its exact
   `instance_id`, `tab_id`, and `conversation_key`.  Do not reduce claims for
   commands that really mutate instance-wide state.
2. Add an authenticated, read-first rename reconciliation operation.  It must
   observe the exact tab/conversation identity and current title before making
   a terminal decision; it must not resend the rename.
3. If the observed title exactly proves the original requested effect, record
   `APPLIED`.  If it exactly proves no effect, record `NOT_APPLIED`.  If the
   identity, title, or observation is ambiguous, preserve `UNKNOWN` and the
   narrow claim.
4. Provide a fenced migration/reconciliation path for legacy broad rename
   claims.  It may narrow or release the old claim only after the original
   operation, exact target identity, and external state are verified in one
   transaction.  No direct DB edits, blind release, takeover, or resend.
5. Verify that a rename UNKNOWN on one conversation does not block node-sync
   or a fresh E2E for a different, unclaimed target.  It must still block a
   duplicate rename of its own exact target.

## Required tests and acceptance

- Unit tests for canonical claim keys: same target conflicts; distinct tabs or
  conversations do not conflict; genuinely instance-wide commands remain
  fenced.
- Reconciliation tests: confirmed applied, confirmed not-applied, missing or
  mismatched conversation identity, ambiguous title, lost response, and
  duplicate reconciliation invocation.
- Legacy broad-claim tests: no release on incomplete evidence; atomic
  reclassification only on exact evidence; historical unrelated UNKNOWN claims
  unchanged.
- Full suite, compile, diff check, exact-head CI, exact-SHA deployment, then a
  fresh manager-worker-manager E2E on a new target.  The E2E is not evidence of
  this fix until it records one durable worker result, one wake, and one
  independently authorized next bounded task.

## Non-negotiable guards

- Do not resend `rcc-localbridge-rename-tab594833023-20261015-02`.
- Do not directly delete, release, take over, or edit the existing UNKNOWN
  operation, its claim, or `BCT-ISSUE111-LIVE-20261015` ACTIVE work.
- Do not alter existing RCC tabs, conversations, bindings, drafts, or Chrome
  state while diagnosing.
- Do not claim E2E success from polling, a status read, or a broad-lock bypass.

## Handoff order

First inspect the original durable receipt and exact RCC state read-only.  Then
implement the scoped key and reconciliation in an isolated worktree, prove the
guards above locally and in CI, and deploy only the exact tested SHA.  Resume
Issue #111 E2E only after the stale broad fence is safely reconciled or
reclassified by that canonical path.
