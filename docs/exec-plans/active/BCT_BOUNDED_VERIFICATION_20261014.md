# Bounded verification and round-trip reduction

Status: IMPLEMENTING; LIVE acceptance pending.

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

## Acceptance plan

Focused adversarial tests; full Python regression; authenticated isolated MCP disconnect/
reconnect and duplicate request; Windows PR/main CI; exact-SHA Core deploy; fresh LIVE MCP
verify/receipt retrieval and CI wait; compare equivalent separate and combined observations.
Report direct and hosted transport measurements separately. No guaranteed speedup ratio.

## Rollback

Deploy a previously accepted exact SHA using the normal deployment contract. Keep all
receipts and claims. Historical verify receipts remain readable without rerunning them.
Do not restart a RUNNING/UNKNOWN operation after rollback or worker loss.
