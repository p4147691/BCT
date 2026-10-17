# BCT Schema 2 Work allowlist (superseded)

This rollout design is preserved as history but is no longer the active
collaboration contract.  Requiring every fresh Work ID in deployed static
configuration created the repeated approval/deploy bottleneck that the final
normalization removes.  See
`BCT_TRUSTED_COLLABORATION_NORMALIZATION_20261017.md`.

## Purpose

Schema 2 remains globally disabled by default and is additionally limited to
explicit Work IDs. This is a rollout safety gate, not an authority grant.
Current Principal, Work ownership, Policy, epoch, lease, attachment, and
dispatcher fences remain authoritative.

## Contract

- `manager_wake_receipt_v2_enabled` defaults to `false`.
- `manager_wake_receipt_v2_allowed_work_ids` defaults to an empty list.
- A new Wake uses Schema 2 only when the global gate is true and its exact
  current Work ID is present. Otherwise it keeps the Schema 1 contract.
- Invalid configuration, an empty runtime allowlist, a removed Work ID, or a
  mismatched Work ID fails closed for every existing Schema 2 processing path.
- The same in-memory, startup-validated allowlist gates Manager polling and
  lease recovery, decision consumption, Worker outbox recovery, Manager wake
  delivery, and the final pre-write fence for RCC pipe sends.
- Stored Wake schema and receipt mode are never rewritten when configuration
  changes. A no-longer-allowed Schema 2 record remains persisted but cannot be
  processed by a restarted Core.
- Existing Schema 1, Issue #111 receipts, UNKNOWN no-resend, Claim, and
  `consumed_at` contracts are unchanged.

## Verification

Focused tests cover default OFF, global ON with an empty/mismatched allowlist,
invalid types and IDs, Core restart, allowlist removal, stale Work fencing,
Manager Poller and decision denial, Dispatcher denial, and both Worker and
Manager final pipe-write fences. The existing PR A/B/C recovery, replay,
takeover, UNKNOWN, attachment, Policy, and lease regressions remain in scope.

## Operational hold

This source change does not authorize Schema 2 activation, LIVE deployment,
Core restart, RCC/Chrome traffic, or reuse of existing UNKNOWN/Claim/Issue #111
records. A new dedicated Work and separate rollout approval are still required.
