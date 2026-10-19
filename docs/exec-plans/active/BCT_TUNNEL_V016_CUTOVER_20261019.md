# BCT tunnel-client v0.0.16 cutover

Status: `V0.0.16 LIVE / HOSTED READ MEASURED / LEGACY UNKNOWN CLASSIFIED`.

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
- A second visible ChatGPT `bct_status(compact=true)` canary on the current LIVE release
  `b4663866417230d90347d2a295150d7a1a589b61` correlated the ChatGPT turn timestamps,
  tunnel metric deltas, temporary DEBUG event timestamps, and BCT `MCP_TIMING` for one exact
  successful `tools/call`. The 13,570 ms whole turn split into 8,196 ms before the Hosted
  command was enqueued, 781 ms from control-plane enqueue through response acceptance, and
  4,593 ms after the tool result until the final answer completed. The 781 ms tunnel envelope
  split into 241 ms enqueue-to-poll wait, 184.205 ms local MCP HTTP, about 4.064 ms dispatcher
  glue, and 351.731 ms response POST. BCT ASGI for the same call was 183.009 ms. An adjacent
  Monitor snapshot split its 161.438 ms into store 11.627 ms, process sessions 1.255 ms, RCC
  discovery 0.845 ms, and RCC state 147.710 ms; this adjacent snapshot is diagnostic context,
  not falsely labelled as the exact canary's internal subspan.
- The production tunnel stayed running throughout the second canary. Runtime log level changed
  from INFO to DEBUG only for the bounded observation window and was verified back at INFO;
  raw HTTP logging stayed disabled. No Core, Supervisor, tunnel, RCC, Worker, or Manager restart
  occurred.
- Optimisation priority follows the measured size and ownership of each segment: first reduce
  ChatGPT/model pre-tool and post-tool work with shorter deterministic prompts and compact results;
  next reduce the roughly 148 ms RCC state lookup for compact status; then assess the 352 ms
  control-plane upload and 241 ms hosted queue as tunnel/platform boundaries. BCT authorization,
  Claim, receipt, or execution changes are not justified by this status canary.

## UNKNOWN reconciliation result

The common effect-stage journal and bounded `claim_reconcile` capability are LIVE. Evidence-based
cleanup released nine read-only Claims, four execute Claims whose exact FileNotFound receipt proves
CreateProcess never started, two broad relay Claims after durable continuity observations, and one
orchestration operation whose recovery receipt proves `external_effect_excluded=true`. Original
UNKNOWN receipts remain unchanged.

Twenty-two exact-resource Claims remain: one fast-exit execute, one exact historical RCC rename,
and twenty orchestration attachment/session Claims whose worker message may have been submitted.
Seven exact RCC result lookups now return `OPERATION_NOT_FOUND`; absence after retention expiry does
not prove non-delivery. These Claims therefore remain protected with no replay. They are scoped to
their exact historical process path, tab/conversation, attachment, or session/assignment and do not
justify stopping unrelated work.

Monitor exposes shared-resource versus exact-resource Claim counts and compares the canonical RCC
`background.js` SHA-256 with the installed payload SHA-256. This replaces build
label inference with exact byte comparison. A mismatch is a deployment gate and diagnostic signal;
it does not trigger an automatic reload or replay.
