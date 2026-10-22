# BCT Phase 7B — Manager continuation preview (isolated)

Status: ISOLATED_SOURCE / FOCUSED_TESTS_PASS / LIVE_NOT_APPLIED

## Boundary
Phase 6 accepted the thin Manager → Worker → Manager relay on one delivery ID.
Phase 7A added `delivery-manager-status` to **observe** the next Manager answer on
the exact returned turn. Phase 7B is deliberately **read-only preview** and
does not yet perform a new dispatch, Manager takeover or autonomous scheduling.

Public operation: `bct_orchestrate(operation="project-run-next-preview")`
with `run_id`, `delivery_id`, `instance_id`, optional `timeout_s`.
It reads the exact `RETURNED` delivery belonging to the same Work, verifies the
READY Project Run and its active current Manager session, and calls RCC
`delivery-manager-status` without performing a submit. While the Manager is
generating it returns `pending=true`. The normalized preview has
`mutated=false`; no execution right is inferred from the Manager answer.

A Manager decision must be only one JSON object wrapped in exactly these markers:
`[BCT_DELIVERY_NEXT_V1]` and `[/BCT_DELIVERY_NEXT_V1]`.

Schema-1 fields: `schema`, `run_id`, `parent_delivery_id`,
`parent_result_sha256`, `kind`, `summary`, `successor`.
`kind=COMPLETE` demands a null successor. `kind=CONTINUE` demands exactly
`worker_conversation_key`, `instruction`, `acceptance`; it never accepts an
`actions` field or arbitrary tool permissions.

The parse is fail-closed for duplicate keys, extra keys, invalid identities,
incorrect parent Worker result hash, Manager response drift, incorrect Work,
inactive Manager session, manager-as-worker, or Worker outside the run's active
Conversation Network membership. A proposed next delivery ID is deterministic
from (run ID, parent delivery ID, Manager response SHA-256); preview creates no
new ledger row. Actual future dispatch must be a separate bounded authority
gate and explicit ledger `delivery-start` operation.

## Verification and cutover
Focused Phase 7B and existing Project Run, RCC Delivery, module deployment
inventory and architecture tests: 43 PASS; source baseline regressions:
14 PASS; compile: PASS. Existing long orchestration suite timed out after
240 seconds and must not be reported PASS. GitHub PR exact-head CI must verify
this scope before main integration. Phase 7B preview requires Phase 7A's
RCC 1.0.29 to be live before any real Manager read E2E.

N22 Subtitle-AUTO local testing is unrelated and must be preserved.
No Core restart, RCC reload, Chrome action, or live relay is authorized in
this Phase 7B isolated development Work.
