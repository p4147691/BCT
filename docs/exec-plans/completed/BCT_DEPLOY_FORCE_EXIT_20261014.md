# BCT deploy force-exit follow-up — 2026-10-14

Status: `COMPLETE / LIVE_ACCEPTED`.

## Verified follow-up

PR #76's five-second `timeout_graceful_shutdown` correctly cancelled the persistent Streamable HTTP request, but Uvicorn then entered the FastMCP application lifespan shutdown and remained there. Uvicorn's graceful timeout bounds active request tasks only; it does not bound `lifespan.shutdown()`.

The exact closeout deployment `bct-deploy-shutdown-reconcile-closeout-live-deploy-01` therefore ended UNKNOWN without being retried. After the official tunnel stop released the session, the old process exited, the Core supervisor started the already activated exact release, and reconciliation operation `bct-deploy-shutdown-reconcile-closeout-reconcile-02` verified that LIVE state and atomically released the claims.

## Final correction

The authenticated shutdown route now sets both Uvicorn `should_exit` and `force_exit`. Uvicorn still closes listeners, asks connections to shut down, and waits up to the configured five-second request-drain timeout. `force_exit` skips only the otherwise unbounded application lifespan shutdown after that drain window.

No deployment retry, DB edit, tunnel-client replacement, safety relaxation, or automatic claim release was used.

## Acceptance

- Regression coverage proves the shutdown request sets both flags and Uvicorn skips lifespan shutdown.
- Focused deployment/service suite: 11 tests passed; full suite: 116 tests passed; compile and diff checks passed.
- PR #79 passed Windows CI run `38494897550`, merged as `84a65e9dd0c85f0441e024f002f717ddccbcb0cb`, and main CI run `38495142459` passed.
- Because the prior release did not yet contain `force_exit`, the bootstrap deployment of `84a65e9dd0c85f0441e024f002f717ddccbcb0cb` intentionally used one official tunnel stop and finished `APPLIED` as `bct-deploy-force-exit-bootstrap-live-deploy-01`.
- After that release was live, the tunnel was connected and `ready` while `bct-deploy-force-exit-live-restart-02` restarted Core. The operation finished `APPLIED` with a new exact process identity and the same release/manifest; no tunnel stop was used for this acceptance.
- The same tunnel process returned to `healthy=true`, `ready=true`, `runtime_state=ready`, `stale=false` after the Core restart.
- Post-restart MCP read `bct-mcp-latency-final-local-read-02` finished `APPLIED` and returned the expected `pyproject.toml` SHA-256.

## Safety and rollback

Both UNKNOWN deployment records remain immutable audit evidence and were released only by distinct reconciliation operations after exact LIVE verification. Rollback is an ordinary reviewed exact-SHA deployment. A missing or mismatched receipt, manifest, current pointer, service identity, release, or original operation keeps the claim unresolved and requires review.

## Shutdown contract

The controller's proof boundary remains exact process exit plus endpoint absence. It never treats an accepted HTTP shutdown response, a closed listener, or a cancelled request task as sufficient proof by itself. The server-side sequence is now: authenticate the loopback control request, set the normal exit flag and the lifespan skip flag, close listeners, request connection shutdown, wait at most five seconds for active requests, cancel any remainder, skip application lifespan shutdown, and let the owned process exit. The controller still waits independently for the exact PID to disappear before it writes a stopped receipt or starts a replacement process.

This change is intentionally narrower than killing the process from the controller. It preserves Uvicorn's bounded request-drain behavior and exact process verification while removing the one phase that the installed FastMCP stack could leave unbounded. A service that does not exit still produces UNKNOWN; no forced OS process termination, second shutdown request, automatic deployment replay, or optimistic receipt rewrite is introduced.
