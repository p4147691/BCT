# Bounded verification and round-trip reduction

Status: COMPLETE / LIVE_ACCEPTED / HOSTED_CONNECTOR_E2E_ACCEPTED.

Deferred independent bottlenecks: https://github.com/p4147691/BCT/issues/82 .
PR: https://github.com/p4147691/BCT/pull/81 .

## Scope

Finish the short/medium-term latency roadmap: bounded verification, server-side CI wait,
durable result retrieval, and compact status. A general autonomous local workflow engine,
automatic merge/deploy recipes, new event infrastructure, and hosted transport replacement
remain outside this increment. GitHub Issues is the existing follow-up mechanism; do not
create a second improvement ledger.

## Contract

- `verify` accepts 1..8 steps with unique `id`, `capability`, and `arguments`.
- Allowed children: `read` (metadata evidence only), `test` (existing unittest/py_compile),
  `github_pr_status` (exact head and required checks). Work and authenticated principal
  must allow verify and every child action; policy is checked again before every step.
- All children are prepared before dispatch and all existing child resources are claimed
  atomically under one durable operation. No nested recipes, shells, merges, or deployments.
- Fail-fast on FAIL, TIMEOUT, pending CI, stale SHA, or authorization change. UNKNOWN keeps
  claims and never retries. Earlier completed step evidence survives a later failure.
- Sum of configured test timeouts and CI wait windows is at most 600 seconds. Individual
  GitHub API calls retain their existing 30-second timeout; an in-flight read can finish
  after the wait window. File reads retain their existing per-read and batch limits.
- MCP dispatch uses the existing one-shot worker. Closing/reopening a client connection
  does not restart execution. `bct_operation_get(wait_seconds=0..25)` only reads the receipt.
- Durable evidence contains step outcomes, file hashes/metadata, test summary, CI checks,
  and measured timings. File bodies and test stdout/stderr are not saved by verification.
  Use bounded `bct_read` for content; no implied output cache or source snapshot guarantee.
- `github_pr_status(wait_seconds=0..300)` checks internally at five-second intervals and
  stops on ready/failure/closed/deadline. Exact head is checked around each check snapshot.
  Newest same-name check ID wins; a historical success cannot hide a newer failure.
- Existing receipt reuse is the cache for immutable operation results. Live health, CI,
  permissions, and deployment preconditions are never cached as authorization evidence.
- `bct_status` defaults to five recent rows per history category; `compact=false` preserves
  the full previous view. Current health and unresolved claims remain visible.

## Acceptance evidence

- Local full regression: 128 PASS before the last focused refinement. Final focused
  verification suite: 9 PASS. Authenticated MCP disconnect/reconnect, duplicate and cached
  catalogue alias acceptance: PASS. Compile and diff checks: PASS.
- Final Windows PR CI run `38499116087`: 129 PASS in 111.713 seconds; overall job 2m38s.
- PR #81 merged as `0502d783f7fdd8d6fd7003eb95e9c3bc354a5097`; main CI `38499382225`
  passed. Deployment `bounded-verification-deploy-01` finished APPLIED with manifest
  `418655ab3a14656abda01c91eb55b3fc2e60242b19eca7bbf85d633b6caa56c4`.
- LIVE direct MCP: seven separate read/test operations and one verification plan plus
  receipt. All six hashes matched; compile PASS; disconnect/reconnect and duplicate
  evidence preserved. `bounded-direct-e2e-01-combined` finished APPLIED.
- Direct loopback timings: separate 503.211 ms, combined 859.676 ms. Worker startup and
  reconnect cost more locally; the benefit is fewer hosted round trips, not faster file IO.
- Hosted BCT Control connector: `bounded-hosted-combined-01` and `-02` both finished
  APPLIED with six matching file hashes and compile PASS. Existing cached `bct_test`
  tool routes `operation=verify` to the same verification capability and permissions.
- First sample sums tool-call boundaries: separate 7,755 ms versus combined 2,161 ms.
  There was an additional orchestration gap between exec cells; the combined wall span
  was 12,254 ms, so this sample is not a whole-agent latency comparison.
- Reverse-order contiguous sample in one execution: combined 2,097 ms versus separate
  7,692 ms. Calls reduced from seven to two; the measured tool-sequence time fell about
  72.7%. Two small samples are evidence of this path, not a latency guarantee or model
  reasoning-time measurement.
- Compact status was 8,545 bytes versus 65,494 bytes for full history in the LIVE sample;
  current state and unresolved claims remain present. Standalone background exact-head
  CI wait returned READY for merged PR #81; pending-to-ready and stale-head behavior
  have deterministic regression coverage.
- Reproducible driver: `scripts/verify_mcp_acceptance.py`. Local acceptance summaries are
  under `D:\BCT\data\acceptance\bounded-*-e2e-*.json`; no token/body/stdout is recorded.

The final documentation-only closeout follows normal CI and exact-main deployment;
use current HEAD/current.json/health equality and durable receipts for final state.

## Rollback

Deploy a previously accepted exact SHA using the normal deployment contract. Keep all
receipts and claims. Historical verify receipts remain readable without rerunning them.
Do not restart a RUNNING/UNKNOWN operation after rollback or worker loss.
