# BCT tunnel-client v0.0.16 cutover

Status: `V0.0.16 LIVE / HOSTED READ MEASURED / UNKNOWN RECONCILIATION ACTIVE`.

## Goal and boundary

Upgrade the single production `act-control` tunnel from exact v0.0.14 to official v0.0.16 so
`resp_timing` can split the hosted path more precisely. Preserve the current Scheduled Task and
Supervisor recovery contract, keep W3C trace forwarding disabled, and provide an MCP/RCC-independent
rollback to the exact v0.0.14 binary. No PC reboot, logoff, Chrome restart, or new periodic poller is
part of this work.

This closeout Work is the only LIVE owner for the tunnel transition. Parallel work may inspect or
prepare artifacts but may not change the tunnel, its pointer, Supervisor, or Task. The cutover script
is an executor of this ownership, not another owner.

## Design

The Supervisor reads `D:\BCT\runtime\tunnel-client-current.json` as strict UTF-8 and accepts only
schema `BCT_TUNNEL_CLIENT_POINTER_V1`, a path below `D:\TOOLS\OpenAI\tunnel-client`, and an exact
SHA-256 match. With no pointer it retains the verified v0.0.14 fallback. It explicitly writes
`mcp.forward_trace_context=false` so the new timing feature does not forward upstream trace context.

`invoke_bct_tunnel_cutover.ps1` is a bounded local one-shot with three modes:

- `Inspect`: read-only proof of exact binaries, one old tunnel, one Supervisor, Task identity, and
  absence of a stop fence.
- `FixtureTest`: offline fail-closed truth-table proof with no operational effects.
- `Cutover`: install v0.0.16 side by side, stop the Supervisor through its existing flag, take the
  shared mutex, stop the old runtime, publish the pointer atomically, restart the existing Task once,
  and verify exact executable, MCP target, health, and readiness. Any failure selects and verifies
  v0.0.14 and emits a rollback receipt.

## Acceptance order

1. Focused source tests and fixture/Inspect pass from the worktree's own `src` import path.
2. One PR reaches exact-head required CI and merges; do not debug repeated candidates in Actions.
3. Deploy exact main so runtime receives the new Supervisor and cutover one-shot.
4. Re-run read-only Inspect, then run Cutover once from the local host outside the tunnel transport.
5. Verify Scheduled Task, one Supervisor, one exact v0.0.16 process, `/healthz`, `/readyz`, Core READY,
   and tunnel status. Roll back automatically on any failed gate.
6. Issue one unique Hosted read canary and correlate Hosted duration, tunnel `resp_timing`, local MCP
   timing, result upload, and any unobserved residual. Do not replay a mutation for measurement.

## Evidence so far

- Exact v0.0.16 binary SHA-256:
  `4226bb74a72388147882881f29f79801b95e285d731a138071812e3aa6766571`.
- Exact rollback v0.0.14 binary SHA-256:
  `fcc85a69ec0ad82518e4f8964f60c45e31787957782a0fc9c1b0c44e82d61b9b`.
- FixtureTest: eight gates PASS, operational effects false.
- Read-only Inspect: exact old tunnel and one Supervisor observed; cutover ready.
- Focused Python tests: 25 PASS from this worktree's `src`.
- PR #234 merged as `8afc6b50e2996d1f9e9f2478fe408f4ab40885e2`; deployment
  follow-up PR #235 merged as `d28891146a0343606e716169b5e573f206825dc4`.
- Core LIVE is exact `d28891146a0343606e716169b5e573f206825dc4`, generation 147,
  and READY/OK. The Scheduled Task runs one Supervisor and exact tunnel-client v0.0.16
  SHA `4226bb74a72388147882881f29f79801b95e285d731a138071812e3aa6766571`.
- Hosted read canary finished APPLIED. BCT-local stages measured authorization 2.485 ms,
  claim reservation 7.207 ms, read 0.341 ms, receipt persistence 6.464 ms, handler
  23.010 ms, and ASGI 29.703 ms. Exact hosted queue/handback timing is not yet projected
  into the operator receipt even though v0.0.16 emits `resp_timing` upstream.

## Remaining adjacent work

RCC PR #226 is installed and reloaded, and a visible ChatGPT canary response succeeded. Its RCC
result receipt nevertheless remains `pending`, so result-persistence reconciliation is not closed.
The tunnel timing acceptance is complete. A bounded common effect-stage journal and an exact
read-only UNKNOWN reconciliation capability are now being added. The nine legacy `read`,
`system_inspect`, and `github_pr_status` Claims go first; their original UNKNOWN receipts remain.
Then classify execute, relay, and orchestration. Never clear a mutating claim merely because it is
old and never resend an UNKNOWN mutation without downstream proof.
