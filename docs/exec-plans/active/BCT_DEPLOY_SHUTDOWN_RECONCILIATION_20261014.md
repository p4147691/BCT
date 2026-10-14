# BCT deploy shutdown reconciliation — 2026-10-14

Status: IMPLEMENTING

## Verified incident

Deploying exact `main` while the tunnel held a persistent Streamable HTTP connection caused the authenticated shutdown endpoint to close its listener without allowing the Uvicorn process to exit within the controller's 10-second verification window. The deploy therefore ended `FINISHED / UNKNOWN` with `DEPLOYMENT_ROLLBACK_UNVERIFIED`, and its deployment/service claims correctly remained unresolved.

The service was recovered without replaying the UNKNOWN operation: the official tunnel runtime stop command released the persistent connection, the Core supervisor restored the exact current release, and the tunnel supervisor re-established a ready connection.

## Minimal correction

- Bound Uvicorn graceful shutdown to five seconds, inside the controller's ten-second exit-proof window.
- Add a deploy reconciliation operation that is separate from deployment resources and only releases the exact original UNKNOWN claims after verifying the immutable release manifest, `current.json`, failed rollback receipt, running service identity, release SHA, and manifest SHA.
- Preserve original operation history, operation-ID idempotency, UNKNOWN no-retry, exact-SHA deployment, and atomic claim release.

## Acceptance

- Focused and full unit tests pass.
- A mismatched LIVE state cannot reconcile and keeps the original claim unresolved.
- The exact production UNKNOWN receipt is reconciled without repeating its deployment effect.
- A later exact-main deployment exits and restarts Core despite the persistent tunnel connection.
- Core health, tunnel readiness, exact source/LIVE SHA, and a final MCP E2E read are verified.
