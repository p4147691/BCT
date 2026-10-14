# BCT Durable Recipe V1

Status: COMPLETE / LIVE_ACCEPTED.

## Delivered

- `local-python-validation@1` and `pr-readiness@1` server-owned recipes.
- Existing sequential fail-fast execution; no DAG or automatic resume.
- Immutable step ID/order/capability/request digest persisted before child dispatch.
- `PENDING/RUNNING/FINISHED/SKIPPED` step journal exposed by `bct_operation_get`.
- Completed child evidence persisted independently of the worker lifetime.
- Existing operation ID idempotency, policy scope, atomic claims, UNKNOWN no-retry and
  exact-head CI checks preserved.

Recipes do not accept arbitrary YAML, loops, nested recipes, writes, Git mutations,
merge or deployment. A crashed in-flight step remains unresolved; V1 does not infer an
external effect or automatically replay it.

## Acceptance evidence

- Implementation PR: `#84`; merge commit and accepted LIVE SHA
  `f652ff91d1479e78ad8d7c91fdb03ede1627190c`.
- Exact feature head CI: run `38504104663`, job `115657504845`, 135 tests PASS and
  compileall PASS. Independent design review reported no blocker.
- Deployment operation `durable-recipe-v1-deploy-f652ff91`: `FINISHED/APPLIED`;
  generation 66, Core and MCP ready.
- Direct success operation `durable-recipe-v1-live-success-f652ff91`:
  `FINISHED/APPLIED`, both journal steps `FINISHED/APPLIED`.
- Direct bounded failure `durable-recipe-v1-live-failfast-f652ff91`:
  expected test step `FINISHED/FAILED`, following read `SKIPPED/NOT_APPLIED`.
- Hosted success operation `durable-recipe-v1-hosted-success2-f652ff91`:
  `FINISHED/APPLIED`, repeat receipt matched, changed input under the same operation ID
  was rejected with `OPERATION_ID_REQUEST_MISMATCH`.
- Hosted bounded failure `durable-recipe-v1-hosted-failfast-f652ff91` preserved the same
  fail-fast journal contract. No new UNKNOWN or unresolved claim was created.

The first Hosted success attempt was rejected during preparation with
`RECIPE_ARGUMENTS_INVALID` and created no operation or claim. A new operation ID with the
exact four-key recipe envelope completed successfully; the rejected payload was not replayed.

## Deferred

- Manual resume policy and feature-level repeatability contracts.
- Read-only DAG scheduling.
- AI-generated plan proposals.
- Tunnel-client v0.0.16 measurement (GitHub issue #82).
- Monitor stale attachment reconciliation and locate/focus UI for C-Nodes.

