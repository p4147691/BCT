# BCT batch read and round-trip reduction

Status: `COMPLETE / LIVE_ACCEPTED / CHATGPT_E2E_ACCEPTED`.

## Goal

Reduce ChatGPT-to-BCT round trips for related read-only inspection while preserving the existing
work scope, operation digest, resource claim, receipt, and UNKNOWN no-retry contracts.

## Delivered scope

- Added a bounded `operation: "batch"` mode to the existing `bct_read` capability.
- Validates every item before starting the operation and claims all item resources atomically.
- Reads file content and calculates its SHA-256 from the same bytes.
- Returns per-item observation evidence without persisting file content in SQLite.
- Preserves the existing `file` and `directory_tree` request and response contracts.
- Documents the shared rule: after safety conditions are fixed, combine related reads inside one
  BCT call instead of paying repeated external round trips.

## Bounds

- At most 20 items per batch.
- At most 512 KiB per file and 1 MiB of file content per batch.
- At most 2,000 requested directory entries across a batch.
- Nested batches and duplicate item IDs or targets are rejected.

## Acceptance evidence

- Focused development-flow tests: 11 PASS.
- Authenticated Streamable HTTP MCP integration: PASS, including one mixed file/tree batch.
- Full Python regression: 111 PASS in 109.220 seconds.
- `compileall` and `git diff --check`: PASS.
- Local disposable benchmark over five small files: five individual operations totalled
  157.844 ms; one batch operation took 41.698 ms. This isolates local operation overhead and is
  not an estimate of the external ChatGPT round trip.
- PR #72 passed `BCT CI/test` and merged to `main` as
  `212623809a5cff60efa5543b90d531ed7512b90f`.
- The exact merge SHA was deployed to Core. Deployment manifest:
  `26fe6b2f7f08bddf18035816baaf5c393b7be287cfb94fc2505dc87827d2bd85`.
- LIVE direct-MCP verification read five real repository files in one batch. All five SHA-256
  values matched separate reads; the separate calls totalled 165 ms and the batch took 41 ms.
- Hosted ChatGPT verification used work `bct-batch-read-chatgpt-e2e-20261014-01` and exactly one
  batch read operation `bct-batch-read-chatgpt-e2e-op-01`. The durable receipt is
  `FINISHED / APPLIED`, status `COMPLETE`, 5/5 OK, 27,751 bytes, zero failures. ChatGPT reported
  4.930 seconds for the batch tool call and returned `BCT_BATCH_CHATGPT_E2E_OK`.

The local and hosted timings measure different paths and must not be subtracted from each other.
The hosted path confirms that bundling five reads into one operation is functional; it does not
claim that every ChatGPT response completes in 4.930 seconds.

## Follow-up observation

The production tunnel process forwarded the ChatGPT commands successfully, but `runtimes status`
reported `healthy=false` and `runtime_state=starting` because its health URL file was absent. The
BCT tunnel supervisor therefore kept attempting a reconnect and logged
`BCT_TUNNEL_CONNECT_FAILED` while the existing dispatcher remained usable. This did not invalidate
the batch-read acceptance, but the supervisor readiness predicate should be reconciled separately;
do not restart or replace the working tunnel merely because this status field is stale.
