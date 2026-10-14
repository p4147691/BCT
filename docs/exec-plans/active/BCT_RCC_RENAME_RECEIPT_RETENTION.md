# BCT RCC Rename Receipt Retention

Status: IMPLEMENTATION_READY / NO_LIVE_ACTION

## Verified fact

RCC previously stored completed `rename-conversation` effects only in the
generic `operations` object.  That object retains the newest 100 records and
silently removes older entries.  The historical operation
`rcc-localbridge-rename-tab594833023-20261015-02` is no longer in that cache,
so PR #116's authenticated, owner-scoped `inspect-rename-receipt` correctly
returned `receipt_found=false`.  An open tab proves neither that the requested
title was applied nor that it was not applied.

## Historical policy (receipt missing)

`UNKNOWN` plus a legacy broad claim remains **BLOCKED** when its rename receipt
is absent.  It must not be automatically narrowed, released, retried, or
declared `NOT_APPLIED` from a current tab observation.  The only safe current
actions are owner-scoped read-only inspection and an evidence-preserving
handoff.  A future remediation needs new, independently sufficient evidence
(for example a signed durable receipt captured elsewhere); it must use the
canonical reconciliation path and cannot infer evidence from this change.

This policy applies specifically to the historical broad claim.  New renames
already use exact conversation claims, so a future missing receipt cannot
quarantine an entire RCC instance; it still fences its own uncertain target.

## Forward retention contract

Before a `rename-conversation` reaches the UI, RCC reserves a full
terminal-shaped record in `chrome.storage.local` key `renameReceiptsV1`; a
capacity failure is therefore confirmed before dispatch.  On confirmed UI
success, the fixed-size record becomes terminal and is written alongside the
bounded generic cache.  A service-worker restart while the reservation is
non-terminal is `UNKNOWN` and blocks duplicate dispatch; it is never treated
as success or returned by `rename-receipt` as reconciliation evidence.
`rename-receipt` reads that ledger first and supports pre-ledger receipts from
the legacy cache only as a compatibility fallback.  Duplicate rename lookup
also reads the ledger first, so eviction from the 100-record generic cache
cannot re-dispatch the same operation.

The ledger is intentionally never automatically pruned.  A capacity or storage
write failure makes the command outcome unconfirmed rather than deleting or
inventing evidence.  A future retention/acknowledgement protocol may remove a
record only after BCT has independently recorded a terminal outcome; it must
be authenticated, exact-operation scoped, tested for crash ordering, and must
not touch historical receipt-missing UNKNOWN claims.

## Acceptance

- Store a rename receipt, then complete more than 100 unrelated operations.
- Verify the generic cache may evict the rename while `renameReceiptsV1`
  retains the exact proof.
- Verify the pre-dispatch reservation cannot be read as success and prevents a
  duplicate rename after a service-worker restart.
- Verify a same-ID/same-fingerprint duplicate is answered from the ledger and
  a different fingerprint is rejected.
- Preserve the existing owner, digest, tab and conversation fences in Core;
  this extension change does not alter an existing operation or claim.

## Delivery boundary

This plan authorizes source and isolated tests only.  It does not authorize
RCC reload, Chrome modification, Core deployment, historical claim mutation,
or Issue #111 E2E.  Before any activation, verify exact source SHA, payload
hash, install path and a controlled new-target test under separate approval.
