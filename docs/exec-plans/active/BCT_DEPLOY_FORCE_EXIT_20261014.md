# BCT deploy force-exit follow-up — 2026-10-14

Status: IMPLEMENTING

## New verified evidence

PR #76's five-second `timeout_graceful_shutdown` correctly cancelled the persistent Streamable HTTP request, but Uvicorn then entered the FastMCP application lifespan shutdown and remained there. Uvicorn's graceful timeout bounds active request tasks only; it does not bound `lifespan.shutdown()`.

The exact closeout deployment `bct-deploy-shutdown-reconcile-closeout-live-deploy-01` therefore ended UNKNOWN without being retried. After the official tunnel stop released the session, the old process exited, the Core supervisor started the already activated exact release, and reconciliation operation `bct-deploy-shutdown-reconcile-closeout-reconcile-02` verified that LIVE state and atomically released the claims.

## Minimal correction

The authenticated shutdown route will set both Uvicorn `should_exit` and `force_exit`. Uvicorn still closes listeners, asks connections to shut down, and waits up to the configured five-second request-drain timeout. `force_exit` only skips the otherwise unbounded application lifespan shutdown after that drain window.

No deployment retry, DB edit, tunnel-client replacement, safety relaxation, or automatic claim release is permitted.

## Acceptance

- Unit regression proves the shutdown request sets both flags and Uvicorn skips lifespan shutdown.
- Focused and full suites plus Windows CI pass.
- Exact main deploy succeeds while the tunnel remains connected; no manual tunnel stop is used for this acceptance.
- Core exact SHA/manifest, tunnel ready state, and MCP read are verified.
- The prior completed incident record is corrected with the final evidence before closeout.
