# BCT deploy shutdown reconciliation — 2026-10-14

Status: `COMPLETE / LIVE_ACCEPTED`.

## Verified incident

Deploying exact `main` while the tunnel held a persistent Streamable HTTP connection caused the authenticated shutdown endpoint to close its listener without allowing the Uvicorn process to exit within the controller's 10-second verification window. The deployment operation `bct-mcp-latency-closeout-live-deploy-01` therefore ended `FINISHED / UNKNOWN` with `DEPLOYMENT_ROLLBACK_UNVERIFIED`, and its deployment/service claims correctly remained unresolved.

The service was recovered without replaying the UNKNOWN operation: the official tunnel runtime stop command released the persistent connection, the Core supervisor restored the exact current release, and the tunnel supervisor re-established a ready connection.

## Correction

- Uvicorn graceful shutdown is bounded to five seconds, inside the controller's ten-second exit-proof window.
- Deploy reconciliation uses a separate resource and releases an exact original UNKNOWN claim only after verifying the immutable release manifest, `current.json`, the exact failed rollback receipt file, running service identity, release SHA, and manifest SHA.
- Receipt matching uses file identity so equivalent Windows short/long path spellings cannot create false mismatches.
- Original operation history, operation-ID idempotency, UNKNOWN no-retry, exact-SHA deployment, and atomic claim release remain unchanged.

## Verification

- Local focused deployment/service suite: 11 tests passed.
- Local full suite: 116 tests passed; changed Python files compiled; diff check passed.
- The negative reconciliation test kept the original claim unresolved when receipt evidence was altered.
- PR #76 passed Windows CI after a Windows short/long path regression was corrected, then merged as `aeccdd175eabee2d834cc20feed3295a480bd958`.
- Main CI run `38493017422` passed.
- Reconciliation operation `bct-mcp-latency-closeout-live-reconcile-02` finished `APPLIED` against the exact running release without replaying the original deployment effect; the original historical UNKNOWN receipt was not rewritten.
- Exact-main deployment `bct-deploy-shutdown-reconcile-live-deploy-01` finished `APPLIED` and installed `aeccdd175eabee2d834cc20feed3295a480bd958`.
- An initial restart operation finished `APPLIED`, but a later exact deployment proved that the five-second request timeout alone did not bound FastMCP lifespan shutdown. That second operation also remained UNKNOWN and was reconciled without replay after exact LIVE recovery.
- PR #79 added the required `force_exit` fence. With its release live and the persistent tunnel connected, `bct-deploy-force-exit-live-restart-02` finished `APPLIED`; the same tunnel returned to `healthy/ready`, and `bct-mcp-latency-final-local-read-02` returned the expected `pyproject.toml` SHA-256.
- The earlier one-call Hosted ChatGPT E2E remains recorded in `BCT_MCP_TUNNEL_LATENCY_20261014.md`; no extra browser message was sent merely to repeat an already accepted representational effect.

## Rollback

The code rollback is the ordinary exact-SHA deployment of a reviewed earlier `main` release. Do not manually clear claims or rewrite the historical UNKNOWN operation. If reconciliation evidence is insufficient, the claim must remain unresolved for review.

## Preserved invariants

Reconciliation is not a retry mode and does not call staging, current-pointer write, stop, start, or restart. It has its own resource key so the resolver can be recorded while the original deployment and service claims remain fenced. The coordinator requires the same work owner, exact original operation ID, target profile, terminal UNKNOWN outcome, and rollback receipt file identity before execution. The feature then proves that the receipt is `ROLLBACK_FAILED`, the current immutable release has the expected complete file set and hashes, and the owned service is running that exact release and manifest. Only `Store.finish_operation()` releases the original claims in the same transaction that records the resolver result and `OPERATION_RECONCILED` event.

The original receipt and deployment failure remain audit evidence. A missing file, changed manifest, stopped or different service, wrong work, wrong target, non-UNKNOWN outcome, or already released claim fails closed. Operators must fix or inspect the external state and run a new exact resolver operation; they must not reuse the original deployment operation ID or edit SQLite state directly.

## Lifespan follow-up

The final shutdown mechanism and LIVE proof are recorded in
`docs/exec-plans/completed/BCT_DEPLOY_FORCE_EXIT_20261014.md`. The request-drain timeout and deploy
reconciliation remain necessary; `force_exit` complements them by preventing an unbounded MCP
application lifespan shutdown after the bounded drain phase.
