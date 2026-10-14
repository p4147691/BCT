# BCT Durable Recipe V1

Status: IMPLEMENTATION_IN_PROGRESS.

## Goal

Extend the accepted bounded `verify` path with two server-owned versioned recipes and a
durable per-step SQLite journal. Preserve operation ID idempotency, work/policy scope,
atomic resource claims, UNKNOWN no-retry, exact-head CI checks and exact-SHA deployment.

## Scope

- `local-python-validation@1` and `pr-readiness@1` only.
- Existing sequential fail-fast execution; no DAG or automatic resume.
- Persist immutable step ID/order/capability/request digest before dispatch.
- Persist terminal child evidence and mark unvisited steps `SKIPPED`.
- Expose the journal through the existing operation receipt endpoint.
- Keep arbitrary YAML, loops, nested recipes, writes, Git mutations, merge and deploy out.

## Safety boundary

A completed checkpoint may be reported but does not authorize current state or a later
mutation. An in-flight step after process loss remains unresolved. V1 performs no generic
reconciliation and never replays UNKNOWN work. Capability-specific reconciliation is a
separate future increment.

## Acceptance

- Focused verification/Core/MCP regression.
- Full unit suite and compileall.
- Independent design review of schema, transitions, claim behavior and compatibility.
- PR CI on the exact head.
- Exact-main deployment and one fixed-recipe LIVE E2E with receipt reconnect.
- A bounded failure E2E proving `SKIPPED` without replaying any external effect.

## Deferred

- Manual resume policy and feature-level repeatability contracts.
- Read-only DAG scheduling.
- AI-generated plan proposals.
- Tunnel-client v0.0.16 measurement (GitHub issue #82).
- Monitor stale attachment reconciliation and locate/focus UI for C-Nodes.
